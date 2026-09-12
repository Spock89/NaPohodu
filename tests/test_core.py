"""Testy rozhodovacího jádra."""

from core import (Akce, Nastaveni, Pamet, Vstup, cil_adaptivni, rozhodni,
                  rosny_bod)

N = Nastaveni()


def krok(v: Vstup, p: Pamet | None = None, **kw):
    # výchozí paměť: minimální držení stavu už uplynulo,
    # ale obnova povelu ještě nenastala
    p = p or Pamet(cas_povelu_s=v.cas_s - N.min_drzeni_s - 60)
    for k, val in kw.items():
        setattr(p, k, val)
    return rozhodni(v, p, N), p


def stary(**kw):
    """Vstup s časem, který nikdy neblokuje minimální držení stavu."""
    return Vstup(cas_s=100000, **kw)


# ---------------------------------------------------------------- pomocné

def test_rosny_bod():
    assert abs(rosny_bod(20, 50) - 9.3) < 0.2
    assert abs(rosny_bod(0, 100) - 0.0) < 0.2
    rosny_bod(20, 0)          # nesmí spadnout


def test_cil_pres_rok():
    assert cil_adaptivni(-5) == 20.0        # zima, oříznuto zdola
    assert cil_adaptivni(20.5) == 25.6
    assert cil_adaptivni(30) == 27.0        # léto, oříznuto shora
    assert cil_adaptivni(20.5, posun=-1) == 24.6


# ---------------------------------------------------------------- priority

def test_vitr_prebiji_i_rucni():
    r, _ = krok(stary(vitr_blokuje=True, vynuceno=True), otevreno=True)
    assert r.akce is Akce.ZAVRIT and "větr" in r.duvod


def test_nepritomnost_zavira():
    r, _ = krok(stary(doma=False, co2=1500), otevreno=True)
    assert r.akce is Akce.ZAVRIT


def test_rucni_otevreni_bez_limitu():
    r, _ = krok(stary(vynuceno=True, t_out=-5))
    assert r.akce is Akce.OTEVRIT and r.limit_s is None


# ---------------------------------------------------------------- vzduch

def test_mrtva_zona_nespousti():
    r, _ = krok(stary(co2=750, cil=25.5, t_out=10))
    assert r.akce is Akce.NIC


def test_rozdelane_vetrani_pokracuje_pod_800():
    """Pulz skončí na 738 – bez tohohle by se do 800 neotevřelo."""
    v = stary(co2=850, cil=25.5, t_out=10)
    r, p = krok(v)
    assert r.akce is Akce.OTEVRIT
    p.otevreno = False
    p.cas_povelu_s = 0
    r2 = rozhodni(stary(co2=738, cil=25.5, t_out=10), p, N)
    assert r2.akce is Akce.OTEVRIT


def test_kvalita_ma_mrtvou_zonu():
    for kv, ocek in [("poor", Akce.OTEVRIT), ("very_poor", Akce.OTEVRIT),
                     ("moderate", Akce.NIC), ("fair", Akce.NIC)]:
        r, _ = krok(stary(co2=750, kvalita=kv, cil=25.5, t_out=10))
        assert r.akce is ocek, f"{kv} -> {r.akce} ({r.duvod})"


def test_kvalita_s_mezerou_i_podtrzitkem():
    a, _ = krok(stary(co2=750, kvalita="very_poor", cil=25.5, t_out=10))
    b, _ = krok(stary(co2=750, kvalita="Very Poor", cil=25.5, t_out=10))
    assert a.akce is b.akce is Akce.OTEVRIT


def test_prach_bez_ventilatoru_ma_vyssi_prah():
    a, _ = krok(stary(co2=600, pm25=45, pm_platny=False, cil=25.5, t_out=10))
    assert a.akce is Akce.NIC, a.duvod
    b, _ = krok(stary(co2=600, pm25=55, pm_platny=False, cil=25.5, t_out=10))
    assert b.akce is Akce.OTEVRIT


def test_zamrzly_prach_neblokuje_zavreni():
    r, _ = krok(stary(co2=500, pm25=45, pm_platny=False, cil=25.5, t_out=10),
                otevreno=True, cas_povelu_s=0)
    assert r.akce is Akce.ZAVRIT


def test_prumer_prachu_se_neuci_bez_ventilatoru():
    _, p = krok(stary(pm25=45, pm_platny=False), pm_prumer=10.0)
    assert p.pm_prumer == 10.0
    _, p2 = krok(stary(pm25=45, pm_platny=True), pm_prumer=10.0)
    assert p2.pm_prumer > 10.0


def test_smog_blokuje_prach_ale_ne_co2():
    r, _ = krok(stary(co2=600, pm25=90, smog=True, cil=25.5, t_out=10))
    assert r.akce is Akce.NIC
    r2, _ = krok(stary(co2=900, pm25=90, smog=True, cil=25.5, t_out=10))
    assert r2.akce is Akce.OTEVRIT


# ---------------------------------------------------------------- teploty

def test_komfort_jen_kdyz_neni_pod_cilem():
    """Reálný případ: 23,9 uvnitř, 19,4 venku, cíl 25,5 – táhne."""
    r, _ = krok(stary(co2=550, t_in=23.9, t_out=19.4, cil=25.5, hodina=20))
    assert r.akce is Akce.NIC, r.duvod


def test_komfort_kdyz_je_venku_stejne_teplo():
    r, _ = krok(stary(co2=550, t_in=25.9, t_out=24.0, cil=25.5, hodina=14))
    assert r.akce is Akce.OTEVRIT
    # popisek má být srozumitelný, ne pojem ze specifikace
    assert "příjemně" in r.duvod


def test_chlazeni_prebiji_nocni_klid():
    r, _ = krok(stary(co2=550, t_in=27, t_out=19, cil=24, hodina=2))
    assert r.akce is Akce.OTEVRIT and "chlaz" in r.duvod


def test_chlazeni_nefunguje_v_mrazu():
    r, _ = krok(stary(co2=550, t_in=22, t_out=-3, cil=20, hodina=2))
    assert r.akce is not Akce.OTEVRIT, r.duvod


def test_pulz_je_delsi_pri_malem_rozdilu():
    a, _ = krok(stary(co2=900, t_in=21, t_out=14.5, cil=25.5))
    b, _ = krok(stary(co2=900, t_in=21, t_out=-5, cil=20))
    assert a.limit_s > b.limit_s


# ---------------------------------------------------------------- noc

def test_noc_otevira_az_od_vyssiho_prahu():
    a, _ = krok(stary(co2=900, t_in=20.3, cil=25.5, hodina=2, spanek=True))
    assert a.akce is Akce.NIC
    b, _ = krok(stary(co2=1100, t_in=20.3, cil=25.5, hodina=2, spanek=True))
    assert b.akce is Akce.OTEVRIT


def test_noc_neotevre_pod_mezi():
    r, _ = krok(stary(co2=1100, t_in=18.5, cil=25.5, hodina=2, spanek=True))
    assert r.akce is Akce.NIC and "jen" in r.duvod


def test_noc_krize_prebiji_mez():
    r, _ = krok(stary(co2=1300, t_in=18.2, cil=25.5, hodina=2, spanek=True))
    assert r.akce is Akce.OTEVRIT and "nouzov" in r.duvod


def test_rano_neotevira_ale_krize_ano():
    a, _ = krok(stary(co2=1100, t_in=20.3, cil=25.5, hodina=7, spanek=True))
    assert a.akce is Akce.NIC and "ruch" in a.duvod
    b, _ = krok(stary(co2=1300, t_in=20.3, cil=25.5, hodina=7, spanek=True))
    assert b.akce is Akce.OTEVRIT


def test_noc_zavira_na_teplotu_ne_na_cisto():
    v = stary(co2=500, t_in=19.5, cil=25.5, hodina=2, spanek=True)
    r, _ = krok(v, otevreno=True, cas_povelu_s=0, noc_mez=18.0)
    assert r.akce is Akce.NIC, r.duvod


# ---------------------------------------------------------------- pohon

def test_projezd_blokuje_opacny_povel():
    p = Pamet(otevreno=True, cas_povelu_s=0)
    r = rozhodni(Vstup(co2=500, cil=25.5, cas_s=30), p, N)
    assert r.akce is Akce.NIC
    # hláška má říct, co se chce a jak dlouho se ještě drží
    assert "zavřít" in r.duvod and "držím" in r.duvod


def test_hlaska_o_cekani_je_srozumitelna():
    p = Pamet(otevreno=False, cas_povelu_s=0)
    r = rozhodni(Vstup(co2=1200, cil=25.5, t_out=10, cas_s=30), p, N)
    assert "chci otevřít" in r.duvod
    assert "min" in r.duvod          # dlouhé čekání v minutách, ne v sekundách


def test_teplota_se_nijak_neupravuje():
    """Dřív se při otevřeném okně dopočítávala korekce. Hodnota pak
    neodpovídala ničemu, co jde ověřit, tak je pryč."""
    for otevreno in (False, True):
        r, _ = krok(stary(t_in=21, t_out=14.5), otevreno=otevreno)
        assert r.t_in_korig == 21
        assert r.korekce == 0


# ---------------------------------------------------------------- odolnost

def test_chybejici_kvalita_neblokuje():
    r, _ = krok(stary(co2=500, kvalita=None, cil=25.5), otevreno=True,
                cas_povelu_s=0)
    assert r.akce is Akce.ZAVRIT


def test_neznama_kvalita_neblokuje():
    r, _ = krok(stary(co2=500, kvalita="unknown", cil=25.5), otevreno=True,
                cas_povelu_s=0)
    assert r.akce is Akce.ZAVRIT


def test_nulova_vlhkost_nespadne():
    r, _ = krok(stary(co2=900, rh_out=0, cil=25.5, t_out=10))
    assert r.akce in (Akce.OTEVRIT, Akce.NIC)


def test_stejna_teplota_uvnitr_i_venku():
    r, _ = krok(stary(co2=900, t_in=21, t_out=21, cil=25.5))
    assert r.limit_s is None or r.limit_s > 0


# ---------------------------------------------------------- min a max čidlo

def test_v_horku_rozhoduje_nejteplejsi_cidlo():
    """Kuchyň 27, ložnice 22, venku 29. Průměr by svedl k větrání,
    ale do přehřáté kuchyně vedro pouštět nechceme."""
    r, _ = krok(stary(co2=550, t_in=22, t_in_max=27, t_out=29, cil=25))
    assert r.akce is not Akce.OTEVRIT, r.duvod


def test_v_zime_rozhoduje_nejchladnejsi_cidlo():
    """Rosný bod hrozí na nejchladnějším místě, ne na nejteplejším."""
    a, _ = krok(stary(co2=900, t_in=18, t_in_max=24, t_out=16, rh_out=95,
                      cil=22))
    b, _ = krok(stary(co2=900, t_in=24, t_in_max=24, t_out=16, rh_out=95,
                      cil=22))
    assert a.rosny_bod == b.rosny_bod
    # obě varianty se rozhodují, jen podle jiného čidla
    assert a.akce in (Akce.OTEVRIT, Akce.NIC)
    assert b.akce in (Akce.OTEVRIT, Akce.NIC)


def test_chlazeni_se_ridi_nejteplejsim():
    r, _ = krok(stary(co2=550, t_in=22, t_in_max=27, t_out=19, cil=24,
                      hodina=2))
    assert r.akce is Akce.OTEVRIT and "chlaz" in r.duvod


def test_bez_druheho_cidla_se_chova_stejne():
    a, _ = krok(stary(co2=550, t_in=26, t_out=29, cil=24))
    b, _ = krok(stary(co2=550, t_in=26, t_in_max=26, t_out=29, cil=24))
    assert a.akce is b.akce and a.duvod == b.duvod


# ---------------------------------------------------------- zástupce

def test_se_zastupcem_se_v_noci_neotevre():
    """Kuchyňské okno větrá za ložnici, ta zůstane zavřená."""
    bez, _ = krok(stary(co2=1100, t_in=20.3, cil=25.5, hodina=2, spanek=True))
    se, _ = krok(stary(co2=1100, t_in=20.3, cil=25.5, hodina=2, spanek=True,
                       zastupce=True))
    assert bez.akce is Akce.OTEVRIT
    assert se.akce is Akce.NIC


def test_krize_prebiji_i_zastupce():
    """Když ani cizí okno nestačí, otevře se."""
    r, _ = krok(stary(co2=1400, t_in=20.3, cil=25.5, hodina=2, spanek=True,
                      zastupce=True))
    assert r.akce is Akce.OTEVRIT


def test_zastupce_zvedne_prah_i_ve_dne():
    """Když za nás větrá soused, sami otevřeme až když to nestačí.
    Jinak by okno v místnosti pod cílem kmitalo sem a tam."""
    bez, _ = krok(stary(co2=900, t_in=21, t_out=10, cil=25.5, hodina=14))
    se, _ = krok(stary(co2=900, t_in=21, t_out=10, cil=25.5, hodina=14,
                       zastupce=True))
    assert bez.akce is Akce.OTEVRIT
    assert se.akce is Akce.NIC


def test_zastupce_neudusi_kdyz_je_hodne_dusno():
    r, _ = krok(stary(co2=1300, t_in=21, t_out=10, cil=25.5, hodina=14,
                      zastupce=True))
    assert r.akce is Akce.OTEVRIT


# ---------------------------------------------------------- déšť a priorita

def test_dest_prebiji_rucni_otevreni():
    """Ochrana bytu stojí nad ručním rozhodnutím, stejně jako vítr."""
    r, _ = krok(stary(dest=2.0, vynuceno=True), otevreno=True)
    assert r.akce is Akce.ZAVRIT and "dešt" in r.duvod


def test_slaby_dest_nezavira():
    r, _ = krok(stary(dest=0.1, co2=900, t_out=10, cil=25.5))
    assert r.akce is Akce.OTEVRIT


def test_vitr_prebiji_i_dest():
    r, _ = krok(stary(dest=2.0, vitr_blokuje=True), otevreno=True)
    assert r.akce is Akce.ZAVRIT and "větr" in r.duvod


def test_priorita_uprostred_odpovida_vychozim():
    from core import Nastaveni, z_priority
    n = Nastaveni()
    den, noc = z_priority(5)
    assert abs(den - n.denni_pokles) < 0.3
    assert abs(noc - n.nocni_pokles) < 0.1


def test_priorita_je_monotonni():
    from core import z_priority
    hodnoty = [z_priority(p) for p in range(11)]
    assert all(a[0] < b[0] for a, b in zip(hodnoty, hodnoty[1:]))
    assert all(a[1] < b[1] for a, b in zip(hodnoty, hodnoty[1:]))


def test_priorita_je_orezana():
    from core import z_priority
    assert z_priority(-5) == z_priority(0)
    assert z_priority(99) == z_priority(10)


def test_vysoka_priorita_vetra_dele():
    from core import Nastaveni, z_priority
    den_nizka, _ = z_priority(1)
    den_vysoka, _ = z_priority(9)
    a, _ = krok(stary(co2=900, t_in=22, t_out=8, cil=25.5),
                p=Pamet(cas_povelu_s=100000 - N.min_drzeni_s - 60))
    assert den_vysoka > den_nizka


# ------------------------------------------------- projezd a rozejití stavu

def test_po_povelu_se_veri_vlastnimu_stavu():
    """Pohon chvíli jede a hlásí starou polohu. Kdyby jádro vidělo
    zavřeno, chtělo by otevřít znovu a naráželo na držení stavu."""
    p = Pamet(otevreno=False, cas_povelu_s=0)
    r = rozhodni(Vstup(co2=1200, cil=25.5, t_out=10, cas_s=100000), p, N)
    assert r.akce is Akce.OTEVRIT
    assert p.otevreno is True           # jádro si povel zapamatuje
    # hned nato se stejné rozhodnutí neopakuje
    r2 = rozhodni(Vstup(co2=1200, cil=25.5, t_out=10, cas_s=100010), p, N)
    assert r2.akce is Akce.NIC


# ---------------------------------------------------------- diagnostika

def test_diagnostika_vyjmenuje_vsechny_prekazky():
    from core import duvody
    v = stary(co2=500, vitr_blokuje=True, dest=2.0, doma=False, cil=25.5)
    d = duvody(v, Pamet(), N)
    assert any("vítr" in x for x in d)
    assert any("déšť" in x for x in d)
    assert any("nikdo doma" in x for x in d)


def test_diagnostika_v_noci_rekne_proc():
    from core import duvody
    v = stary(co2=800, t_in=18.0, cil=25.5, hodina=2, spanek=True)
    d = duvody(v, Pamet(), N)
    assert any("noční" in x for x in d)
    assert any("noční mezí" in x for x in d)


def test_diagnostika_je_prazdna_kdyz_nic_nebrani():
    from core import duvody
    v = stary(co2=1200, t_in=21, t_out=12, cil=25.5, hodina=14)
    assert duvody(v, Pamet(cas_povelu_s=0), N) == []


def test_diagnostika_zminuje_zastupce():
    from core import duvody
    v = stary(co2=900, t_in=21, cil=25.5, hodina=2, spanek=True, zastupce=True)
    assert any("soused" in x for x in duvody(v, Pamet(), N))


# ---------------------------------------------------------- kódy důvodů

def test_kod_odlisi_vitr_od_vyvetrano():
    """„vyvětráno" obsahuje „větr" — rozhodovat se podle textu je past."""
    vitr, _ = krok(stary(vitr_blokuje=True), otevreno=True)
    cisto, _ = krok(stary(co2=500, cil=25.5), otevreno=True, cas_povelu_s=0)
    assert vitr.kod == "vitr"
    assert cisto.kod == "cisto"
    assert "větr" in cisto.duvod        # text mate, kód ne


def test_kody_hlavnich_rozhodnuti():
    dest, _ = krok(stary(dest=2.0), otevreno=True)
    pryc, _ = krok(stary(doma=False), otevreno=True)
    rucni, _ = krok(stary(vynuceno=True))
    assert (dest.kod, pryc.kod, rucni.kod) == ("dest", "pryc", "rucni")


def test_kod_nouzoveho_vetrani():
    r, _ = krok(stary(co2=1400, t_in=20.3, cil=25.5, hodina=2, spanek=True))
    assert r.kod == "noc_krize"


def test_drzeni_stavu_ma_vlastni_kod():
    p = Pamet(otevreno=True, cas_povelu_s=0)
    r = rozhodni(Vstup(co2=500, cil=25.5, cas_s=30), p, N)
    assert r.kod == "drzeni"


# ------------------------------------------------- noční hystereze

def test_po_nocnim_zavreni_se_ceka_na_prohrati():
    """Čidlo v okně po zavření vyskočí. Bez hystereze by se okno
    otevřelo za pár minut znovu a fouká to na hlavu celou noc."""
    p = Pamet(otevreno=True, cas_povelu_s=0,
              noc_mez=18.0, noc_start=21.0)
    # při otevřeném okně se k čidlu přičítá korekce, proto nižší hodnota
    v = stary(co2=1200, t_in=17.0, t_out=10, cil=25.5, hodina=2, spanek=True)
    zavreni = rozhodni(v, p, N)
    assert zavreni.akce is Akce.ZAVRIT
    assert p.noc_zavreno_teplotou is True

    # čidlo vyskočilo na 19.5, ale pokoj prohřátý není
    p.cas_povelu_s = 0
    znovu = rozhodni(stary(co2=1200, t_in=19.5, cil=25.5, hodina=2,
                           spanek=True), p, N)
    assert znovu.akce is Akce.NIC
    assert "prohřátí" in znovu.duvod


def test_po_prohrati_se_otevre():
    p = Pamet(cas_povelu_s=0, noc_zavreno_teplotou=True, noc_start=21.0)
    r = rozhodni(stary(co2=1200, t_in=20.2, cil=25.5, hodina=2, spanek=True),
                 p, N)
    assert r.akce is Akce.OTEVRIT
    assert p.noc_zavreno_teplotou is False


def test_krize_prebiji_i_cekani_na_prohrati():
    p = Pamet(cas_povelu_s=0, noc_zavreno_teplotou=True, noc_start=21.0)
    r = rozhodni(stary(co2=1400, t_in=19.0, cil=25.5, hodina=2, spanek=True),
                 p, N)
    assert r.akce is Akce.OTEVRIT and r.kod == "noc_krize"


def test_otevreni_si_zapamatuje_vychozi_teplotu():
    p = Pamet(cas_povelu_s=0)
    rozhodni(stary(co2=1200, t_in=21.0, cil=25.5, hodina=2, spanek=True), p, N)
    assert p.noc_start == 21.0


# ------------------------------------------- společné nárazové větrání

def test_narazove_zkrati_pulz():
    """V mrazu krátký průvan místo dlouhého větrání jedním oknem."""
    bez, _ = krok(stary(co2=900, t_in=21, t_out=14.5, cil=25.5))
    s, _ = krok(stary(co2=900, t_in=21, t_out=14.5, cil=25.5, narazove=True))
    assert bez.limit_s > s.limit_s
    assert s.limit_s <= N.narazove_strop_s


def test_narazove_prebiji_zastupce():
    """Při nárazovém větrání se otevírá všude — o to právě jde."""
    zastoupeno, _ = krok(stary(co2=900, t_in=21, t_out=5, cil=25.5,
                               zastupce=True))
    narazove, _ = krok(stary(co2=900, t_in=21, t_out=5, cil=25.5,
                             zastupce=True, narazove=True))
    assert zastoupeno.akce is Akce.NIC
    assert narazove.akce is Akce.OTEVRIT


def test_narazove_nepusti_okno_pres_ochranu():
    """Vítr, déšť ani noční mez nárazové větrání nepřebije."""
    vitr, _ = krok(stary(co2=900, narazove=True, vitr_blokuje=True),
                   otevreno=True)
    dest, _ = krok(stary(co2=900, narazove=True, dest=2.0), otevreno=True)
    assert vitr.akce is Akce.ZAVRIT and dest.akce is Akce.ZAVRIT


def test_narazove_v_noci_respektuje_mez():
    r, _ = krok(stary(co2=1100, t_in=18.2, cil=25.5, hodina=2, spanek=True,
                      narazove=True))
    assert r.akce is Akce.NIC and "jen" in r.duvod


def test_narazove_ma_vlastni_spodni_strop():
    """Běžný pulz nikdy nejde pod 30 minut, nárazové ano — o to jde."""
    bezne, _ = krok(stary(co2=900, t_in=21, t_out=-5, cil=20))
    naraz, _ = krok(stary(co2=900, t_in=21, t_out=-5, cil=20, narazove=True))
    assert bezne.limit_s == 30 * 60
    assert naraz.limit_s < 30 * 60


# ------------------------------------- komfort a pokles čidla v okně

def test_komfort_nezavre_hned_po_otevreni():
    """Čidlo v okenním rámu po otevření spadne. Bez měření poklesu by
    komfortní režim skončil do minuty po tom, co začal."""
    p = Pamet(cas_povelu_s=0)
    v = stary(co2=550, t_in=25.0, t_out=24.0, cil=25.0, hodina=14)
    prvni = rozhodni(v, p, N)
    assert prvni.akce is Akce.OTEVRIT
    assert p.komfort_start == 25.0

    # čidlo v okně spadlo na 24.2, ale pokoj se nevychladil
    druhy = rozhodni(Vstup(co2=550, t_in=24.2, t_out=24.0, cil=25.0,
                           hodina=14, cas_s=100200), p, N)
    assert druhy.akce is not Akce.ZAVRIT


def test_komfort_zavre_pri_skutecnem_ochlazeni():
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
              komfort_start=25.0)
    r = rozhodni(stary(co2=550, t_in=23.0, t_out=22.0, cil=25.0, hodina=14),
                 p, N)
    assert r.akce is Akce.ZAVRIT


def test_pri_zavrenem_okne_se_poroznava_s_cilem():
    """Zavřené okno čidlo nezkresluje, takže absolutní porovnání stačí."""
    r, _ = krok(stary(co2=550, t_in=23.9, t_out=19.4, cil=25.5, hodina=20))
    assert r.akce is Akce.NIC


def test_konec_komfortu_zapomene_vychozi_teplotu():
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
              komfort_start=25.0)
    rozhodni(stary(co2=550, t_in=23.0, t_out=22.0, cil=25.0, hodina=14), p, N)
    assert p.komfort_start is None


# ---------------------------------------------- co změnu spustí

def test_ocekavani_pri_otevrenem_vyvetranem():
    """Otevřené okno u vyvětrané místnosti — člověk chce vědět, na co
    se čeká, ne co se stalo."""
    from core import ocekavani
    p = Pamet(otevreno=True, cas_povelu_s=99000, den_mez=20.5, rezim="pulz")
    t = ocekavani(Vstup(co2=640, t_in=22.0, cil=25.5, cas_s=100000), p, N)
    text = " | ".join(t)
    assert "20.5" in text and "vyvětráno" in text
    assert "držím stav" in text


def test_ocekavani_pri_zavrenem_rekne_prah():
    from core import ocekavani
    t = ocekavani(Vstup(co2=720, t_in=22.0, cil=25.5, cas_s=100000),
                  Pamet(cas_povelu_s=0), N)
    assert "800" in " ".join(t) and "720" in " ".join(t)


def test_ocekavani_v_noci_uvadi_i_teplotni_mez():
    from core import ocekavani
    t = " | ".join(ocekavani(
        Vstup(co2=720, t_in=19.0, cil=25.5, hodina=2, spanek=True,
              cas_s=100000), Pamet(cas_povelu_s=0), N))
    assert "1000" in t          # noční práh, ne denní
    assert "19.0" in t


def test_ocekavani_komfortu_bere_pokles_od_otevreni():
    from core import ocekavani
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
              komfort_start=25.0)
    t = " | ".join(ocekavani(
        Vstup(co2=500, t_in=24.4, cil=25.0, cas_s=100000), p, N))
    assert "23.5" in t


# ------------------------------------------------- prach venku

def test_prach_venku_horsi_neotvira():
    """Částice šly do ložnice zvenčí. Větráním se to nespraví — jen by
    se větralo donekonečna a hodnota by rostla."""
    r, _ = krok(stary(co2=500, pm25=9.0, pm_platny=True, pm25_venku=25.0,
                      t_in=21, t_out=10, cil=25.5))
    assert r.akce is not Akce.OTEVRIT


def test_prach_venku_lepsi_otevira():
    r, _ = krok(stary(co2=500, pm25=40.0, pm_platny=True, pm25_venku=8.0,
                      t_in=21, t_out=10, cil=25.5))
    assert r.akce is Akce.OTEVRIT


def test_prach_venku_horsi_nedrzi_okno_otevrene():
    """Otevřené okno se musí zavřít, i když je vnitřní prach vysoký —
    venku je horší, takže čekat nemá cenu."""
    r, _ = krok(stary(co2=500, pm25=40.0, pm_platny=True, pm25_venku=60.0,
                      t_in=21, t_out=10, cil=25.5),
                otevreno=True, cas_povelu_s=0)
    assert r.akce is Akce.ZAVRIT


def test_bez_venkovniho_cidla_se_nic_nemeni():
    r, _ = krok(stary(co2=500, pm25=40.0, pm_platny=True,
                      t_in=21, t_out=10, cil=25.5))
    assert r.akce is Akce.OTEVRIT


def test_ocekavani_rekne_ze_venku_je_horsi():
    from core import ocekavani
    t = " ".join(ocekavani(
        Vstup(co2=500, pm25=9.0, pm25_venku=25.0, pm_platny=True,
              t_in=21, cil=25.5, cas_s=100000), Pamet(cas_povelu_s=0), N))
    assert "nespravím" in t


# ------------------------------- učení bez venkovního čidla na prach

def _vetra(p, pm, cas, co2=1100):
    return rozhodni(Vstup(co2=co2, pm25=pm, pm_platny=True, t_in=21,
                          t_out=10, cil=25.5, cas_s=cas), p, N)


def test_stoupajici_prach_pri_vetrani_se_pozna():
    """Bez venkovního čidla se to pozná z chování: když prach uvnitř
    při otevřeném okně stoupá, tahá se dovnitř."""
    p = Pamet(otevreno=True, cas_povelu_s=0, den_mez=19.0, rezim="pulz")
    _vetra(p, 9.0, 100000)
    assert p.pm_pri_otevreni == 9.0
    _vetra(p, 20.0, 100600)
    assert p.pm_venku_horsi_do_s > 100600


def test_kratke_vetrani_jeste_nestaci():
    """Vzduch se musí promíchat, jinak by poznatek vznikal z šumu."""
    p = Pamet(otevreno=True, cas_povelu_s=0, den_mez=19.0, rezim="pulz")
    _vetra(p, 9.0, 100000)
    _vetra(p, 20.0, 100060)
    assert p.pm_venku_horsi_do_s == 0.0


def test_klesajici_prach_poznatek_nevytvori():
    p = Pamet(otevreno=True, cas_povelu_s=0, den_mez=19.0, rezim="pulz")
    _vetra(p, 30.0, 100000)
    _vetra(p, 12.0, 100600)
    assert p.pm_venku_horsi_do_s == 0.0


def test_poznatek_zabrani_otevreni_kvuli_prachu():
    p = Pamet(cas_povelu_s=0, pm_venku_horsi_do_s=200000)
    r = rozhodni(Vstup(co2=500, pm25=40.0, pm_platny=True, t_in=21,
                       t_out=10, cil=25.5, cas_s=100000), p, N)
    assert r.akce is not Akce.OTEVRIT


def test_poznatek_vyprsi():
    p = Pamet(cas_povelu_s=0, pm_venku_horsi_do_s=100000)
    r = rozhodni(Vstup(co2=500, pm25=40.0, pm_platny=True, t_in=21,
                       t_out=10, cil=25.5, cas_s=100001), p, N)
    assert r.akce is Akce.OTEVRIT


def test_zavreni_zapomene_vychozi_prach():
    p = Pamet(otevreno=True, cas_povelu_s=0, den_mez=19.0, rezim="pulz")
    _vetra(p, 9.0, 100000)
    p.otevreno = False
    _vetra(p, 9.0, 100600, co2=500)
    assert p.pm_pri_otevreni is None


def test_ocekavani_rekne_o_poznatku():
    from core import ocekavani
    p = Pamet(cas_povelu_s=0, pm_venku_horsi_do_s=104000)
    t = " ".join(ocekavani(
        Vstup(co2=500, pm25=40.0, pm_platny=True, t_in=21, cil=25.5,
              cas_s=100000), p, N))
    assert "tahá zvenčí" in t and "min" in t
