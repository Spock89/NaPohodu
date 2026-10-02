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
    kw.setdefault("t_out", 15.0)     # venku neutrálně, ať to nerozhoduje
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
    a, _ = krok(stary(co2=900, t_in=20.3, cil=25.5, hodina=2))
    assert a.akce is Akce.NIC
    b, _ = krok(stary(co2=1100, t_in=20.3, cil=25.5, hodina=2))
    assert b.akce is Akce.OTEVRIT


def test_noc_neotevre_pod_mezi():
    r, _ = krok(stary(co2=1100, t_in=18.5, cil=25.5, hodina=2))
    assert r.akce is Akce.NIC and "jen" in r.duvod


def test_noc_krize_prebiji_mez():
    r, _ = krok(stary(co2=1300, t_in=18.2, cil=25.5, hodina=2, spanek=True))
    assert r.akce is Akce.OTEVRIT and "nouzov" in r.duvod


def test_rano_neotevira_ale_krize_ano():
    """Ranní ruch potlačí běžné dusno, krize projde. Ve spánku, protože
    po skončení nočních hodin jinak platí denní pravidla."""
    a, _ = krok(stary(co2=1100, t_in=20.3, cil=25.5, hodina=7,
                      spanek=True))
    assert a.akce is Akce.NIC
    b, _ = krok(stary(co2=1300, t_in=20.3, cil=25.5, hodina=7,
                      spanek=True))
    assert b.akce is Akce.OTEVRIT


def test_noc_muze_vetrat_dal_pro_vychlazeni():
    """Volitelně: noční větrání ložnici zároveň chladí na noční mez,
    takže se nezavírá už po vyvětrání."""
    from core import Nastaveni as N_
    nast = N_(noc_zavrit_po_vyvetrani=False)
    p = Pamet(otevreno=True, cas_povelu_s=0, noc_mez=18.0)
    r = rozhodni(Vstup(co2=500, t_in=19.5, t_in_max=19.7, cil=25.5,
                       hodina=2,  cas_s=100000, t_out=15.0), p, nast)
    assert r.akce is Akce.NIC, r.duvod


# ---------------------------------------------------------------- pohon

def test_projezd_blokuje_opacny_povel():
    p = Pamet(otevreno=True, cas_povelu_s=0)
    r = rozhodni(Vstup(co2=500, cil=25.5, cas_s=30, t_out=15.0), p, N)
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
    bez, _ = krok(stary(co2=1100, t_in=20.3, cil=25.5, hodina=2))
    se, _ = krok(stary(co2=1100, t_in=20.3, cil=25.5, hodina=2, 
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
    assert any("nikdo není doma" in x for x in d)


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
    r = rozhodni(Vstup(co2=500, cil=25.5, cas_s=30, t_out=15.0), p, N)
    assert r.kod == "drzeni"


# ------------------------------------------------- noční hystereze

def test_po_nocnim_zavreni_se_ceka_na_prohrati():
    """Čidlo v okně po zavření vyskočí. Bez hystereze by se okno
    otevřelo za pár minut znovu a fouká to na hlavu celou noc."""
    p = Pamet(otevreno=True, cas_povelu_s=0,
              noc_mez=18.0, noc_start=21.0)
    # při otevřeném okně se k čidlu přičítá korekce, proto nižší hodnota
    v = stary(co2=1200, t_in=17.0, t_out=10, cil=25.5, hodina=2)
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
    r = rozhodni(stary(co2=1200, t_in=20.2, cil=25.5, hodina=2),
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
    rozhodni(stary(co2=1200, t_in=21.0, cil=25.5, hodina=2), p, N)
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
    """Nárazové větrání noční mez nepřebíjí. Ve spánku navíc běžné
    dusno okno neotevře vůbec."""
    r, _ = krok(stary(co2=1100, t_in=18.2, cil=25.5, hodina=2, spanek=True,
                      narazove=True))
    assert r.akce is Akce.NIC

    # v nočních hodinách bez spánku rozhoduje noční rezerva
    r2, _ = krok(stary(co2=1100, t_in=18.2, cil=25.5, hodina=2,
                       narazove=True))
    assert r2.akce is Akce.NIC and "jen" in r2.duvod


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


def test_komfort_zavre_na_denni_mezi():
    """Mez se odvozuje od cíle: při cíli 21 a 1,5 pod ním na 19,5."""
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
              komfort_start=21.5)
    r = rozhodni(stary(co2=550, t_in=19.4, t_out=18.0, cil=21.0, hodina=14),
                 p, N)
    assert r.akce is Akce.ZAVRIT


def test_pri_zavrenem_okne_se_poroznava_s_cilem():
    """Zavřené okno čidlo nezkresluje, takže absolutní porovnání stačí."""
    r, _ = krok(stary(co2=550, t_in=23.9, t_out=19.4, cil=25.5, hodina=20))
    assert r.akce is Akce.NIC


def test_konec_komfortu_zapomene_vychozi_teplotu():
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
              komfort_start=25.0)
    rozhodni(stary(co2=550, t_in=19.4, t_out=18.0, cil=21.0, hodina=14), p, N)
    assert p.komfort_start is None


# ---------------------------------------------- co změnu spustí

def test_ocekavani_pri_otevrenem_vyvetranem():
    """Otevřené okno u vyvětrané místnosti — člověk chce vědět, na co
    se čeká, ne co se stalo."""
    from core import ocekavani
    p = Pamet(otevreno=True, cas_povelu_s=99000, den_mez=20.5, rezim="pulz")
    t = ocekavani(Vstup(co2=640, t_in=22.0, cil=25.5, cas_s=100000, t_out=15.0), p, N)
    text = " | ".join(t)
    assert "20.5" in text and "vyvětráno" in text
    assert "držím stav" in text


def test_ocekavani_pri_zavrenem_rekne_prah():
    from core import ocekavani
    t = ocekavani(Vstup(co2=720, t_in=22.0, cil=25.5, cas_s=100000, t_out=15.0),
                  Pamet(cas_povelu_s=0), N)
    assert "800" in " ".join(t) and "720" in " ".join(t)


def test_ocekavani_v_noci_uvadi_i_teplotni_mez():
    from core import ocekavani
    t = " | ".join(ocekavani(
        Vstup(co2=720, t_in=19.0, cil=25.5, hodina=2, spanek=True,
              cas_s=100000, t_out=15.0), Pamet(cas_povelu_s=0), N))
    assert "1000" in t          # noční práh, ne denní
    assert "19.0" in t


def test_ocekavani_komfortu_uvadi_denni_mez():
    """Mez je vždycky 1,5 pod cílem, ať je cíl kdekoli."""
    from core import ocekavani
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
              komfort_start=25.0)
    t = " | ".join(ocekavani(
        Vstup(co2=500, t_in=24.4, cil=25.0, cas_s=100000, t_out=15.0), p, N))
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
              t_in=21, cil=25.5, cas_s=100000, t_out=15.0), Pamet(cas_povelu_s=0), N))
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
              cas_s=100000, t_out=15.0), p, N))
    assert "tahá zvenčí" in t and "min" in t


# ------------------------------- noční klid se místnosti nemusí týkat

def test_kuchyne_bez_klidu_vetra_i_kdyz_se_vedle_spi():
    """Spánek se bere z té místnosti, ne z celé oblasti. Kuchyň, kde se
    nespí, má vlastní klid vypnutý, i když se spí v obýváku vedle."""
    r, _ = krok(stary(co2=1111, t_in=20.6, t_out=10, cil=25.5, hodina=7,
                      spanek=False))
    assert r.akce is Akce.OTEVRIT


def test_mistnost_s_klidem_rano_neotvira():
    r, _ = krok(stary(co2=1111, t_in=20.6, t_out=10, cil=25.5, hodina=7,
                      spanek=True))
    assert r.akce is Akce.NIC





def test_spanek_vedle_nezavre_kuchyni():
    """Kuchyň má klid navázaný na spánek, ale sama se v ní nespí.
    Spánek v obýváku ve stejné oblasti ji nesmí uspat taky."""
    r, _ = krok(stary(co2=1073, t_in=20.6, t_out=8, cil=25.5, hodina=7,
                      spanek=False))
    assert r.akce is Akce.OTEVRIT


def test_kde_se_spi_nocni_rezim_plati():
    """Ve spánku se kvůli běžnému dusnu neotvírá — rámus okna vzbudí
    spolehlivěji než CO2."""
    r, _ = krok(stary(co2=1073, t_in=20.6, t_out=8, cil=25.5, hodina=7,
                      spanek=True))
    assert r.akce is Akce.NIC and "klid" in r.duvod


def test_klid_podle_noci_plati_v_noci_ne_rano():
    """Volba „podle noci" znamená noční hodiny, ne ranní ruch po nich."""
    v_noci, _ = krok(stary(co2=850, t_in=21, t_out=8, cil=25.5, hodina=2,
                           spanek=True))
    rano, _ = krok(stary(co2=850, t_in=21, t_out=8, cil=25.5, hodina=7,
                         spanek=False))
    assert v_noci.akce is Akce.NIC       # noční práh je 1000
    assert rano.akce is Akce.OTEVRIT     # ráno už noc není


def test_spanek_plati_i_mimo_nocni_hodiny():
    """Zapnutý spánek je výslovný pokyn. Musí platit, i když je klid
    navázaný jen na spánek a ne na hodiny."""
    r, _ = krok(stary(co2=1056, t_in=20.6, t_out=8, cil=25.5, hodina=7.97,
                      spanek=True))
    assert r.akce is Akce.NIC and "klid" in r.duvod


def test_spanek_v_poledne_taky_plati():
    r, _ = krok(stary(co2=900, t_in=21, t_out=8, cil=25.5, hodina=13,
                      spanek=True))
    assert "noc" in r.duvod


def test_bez_spanku_a_bez_nocnich_hodin_denni_rezim():
    for hodina in (2, 7.97, 13):
        r, _ = krok(stary(co2=1056, t_in=20.6, t_out=8, cil=25.5,
                          hodina=hodina, spanek=False))
        assert r.akce is Akce.OTEVRIT, hodina


# ------------------------------------- smog a ruční žádost o vyvětrání

def test_smog_zabrani_otevreni_kvuli_prachu():
    r, _ = krok(stary(co2=500, pm25=60.0, pm_platny=True, smog=True,
                      t_in=21, t_out=10, cil=25.5))
    assert r.akce is not Akce.OTEVRIT


def test_bez_smogu_se_kvuli_prachu_otevre():
    r, _ = krok(stary(co2=500, pm25=60.0, pm_platny=True, smog=False,
                      t_in=21, t_out=10, cil=25.5))
    assert r.akce is Akce.OTEVRIT


def test_rucni_zadost_otevre_i_pri_cistem_vzduchu():
    r, _ = krok(stary(co2=450, vetrat=True, t_in=21, t_out=10, cil=25.5))
    assert r.akce is Akce.OTEVRIT


def test_rucni_zadost_nedrzi_okno_pres_vitr():
    """Na rozdíl od vynuceného otevření platí ochrana dál."""
    r, _ = krok(stary(co2=450, vetrat=True, vitr_blokuje=True),
                otevreno=True)
    assert r.akce is Akce.ZAVRIT


def test_rucni_zadost_brani_prohlaseni_za_vyvetrano():
    r, _ = krok(stary(co2=450, vetrat=True, t_in=21, t_out=10, cil=25.5),
                otevreno=True, cas_povelu_s=0)
    assert r.akce is not Akce.ZAVRIT


# ------------------------------------------------- ruční zásah

def test_rucni_zasah_zrusi_rozdelane_vetrani():
    """Automatika se s člověkem nemá přetahovat."""
    from core import rucni_zasah
    p = Pamet(otevreno=True, cas_povelu_s=0, den_mez=20.0, rezim="pulz",
              vetra_se=True)
    rucni_zasah(p, N, 100000, otevreno=False)
    assert p.den_mez is None and p.vetra_se is False
    assert p.rucni_do_s == 100000 + N.rucni_klid_s


def test_po_rucnim_zasahu_se_neotevira():
    p = Pamet(cas_povelu_s=0, rucni_do_s=101000)
    r = rozhodni(Vstup(co2=1400, t_in=21, t_out=10, cil=25.5, cas_s=100000),
                 p, N)
    assert r.akce is Akce.NIC and r.kod == "rucni_zasah"


def test_vitr_prebiji_i_rucni_zasah():
    """Ochrana bytu stojí nad vším."""
    p = Pamet(otevreno=True, cas_povelu_s=0, rucni_do_s=101000)
    r = rozhodni(Vstup(co2=500, vitr_blokuje=True, cas_s=100000, t_out=15.0), p, N)
    assert r.akce is Akce.ZAVRIT and r.kod == "vitr"


def test_dest_prebiji_i_rucni_zasah():
    p = Pamet(otevreno=True, cas_povelu_s=0, rucni_do_s=101000)
    r = rozhodni(Vstup(co2=500, dest=2.0, cas_s=100000, t_out=15.0), p, N)
    assert r.akce is Akce.ZAVRIT and r.kod == "dest"


def test_po_uplynuti_klidu_automatika_pokracuje():
    p = Pamet(cas_povelu_s=0, rucni_do_s=100000)
    r = rozhodni(Vstup(co2=1400, t_in=21, t_out=10, cil=25.5, cas_s=100001),
                 p, N)
    assert r.akce is Akce.OTEVRIT


def test_ocekavani_zminuje_rucni_zasah():
    from core import ocekavani
    p = Pamet(cas_povelu_s=0, rucni_do_s=101200)
    t = " ".join(ocekavani(Vstup(co2=900, t_in=21, cil=25.5, cas_s=100000, t_out=15.0),
                           p, N))
    assert "sáhl jsi na okno" in t


# ------------------------------- couvání a záznam posledního rozhodnutí

def test_uspesne_vyvetrani_zrusi_couvani():
    p = Pamet(otevreno=True, cas_povelu_s=0, pulzy_za_sebou=3)
    r = rozhodni(Vstup(co2=500, t_in=21, t_out=10, cil=25.5, cas_s=100000),
                 p, N)
    assert r.kod == "cisto"
    assert p.pulzy_za_sebou == 0


def test_posledni_rozhodnuti_se_zapamatuje():
    from core import posledni
    p = Pamet(cas_povelu_s=0)
    rozhodni(Vstup(co2=1200, t_in=21, t_out=10, cil=25.5, cas_s=100000), p, N)
    assert p.posledni_akce == "otevřít"
    assert p.posledni_co2 == 1200
    t = " ".join(posledni(p, 100600))
    assert "otevřít" in t and "před 10 min" in t and "1200" in t


def test_bez_rozhodnuti_se_to_prizna():
    from core import posledni
    assert "zatím nic" in " ".join(posledni(Pamet(), 100000))


def test_zaznam_zminuje_opakovana_vetrani():
    from core import posledni
    p = Pamet(posledni_akce="zavřít", posledni_duvod="pulz",
              posledni_kdy_s=100000, pulzy_za_sebou=4)
    assert "4. větrání" in " ".join(posledni(p, 100000))


def test_narazove_zkraceni_je_videt_v_duvodu():
    """Krátký pulz v mírném počasí mate — má být poznat proč."""
    r, _ = krok(stary(co2=911, t_in=21, t_out=15.5, cil=22, narazove=True))
    assert "nárazově" in r.duvod


def test_bez_narazoveho_se_duvod_nemeni():
    r, _ = krok(stary(co2=911, t_in=21, t_out=15.5, cil=22))
    assert "nárazově" not in r.duvod


# ------------------------------------------- zimní přitápění

def test_pritapeni_roste_s_mrazem():
    """Norma je psaná na letní komfort a v zimě se opře o dolní hranici.
    V mrazu ale chladnou stěny a je nám chladněji."""
    from core import zimni_pritapeni
    # výchozí: práh 7 °C, plná hodnota +1,0 °C, náběh 2,5 °C
    assert zimni_pritapeni(10.0) == 0.0          # nad prahem nic
    assert zimni_pritapeni(7.0) == 0.0           # na prahu ještě ne
    assert zimni_pritapeni(6.0) == 0.4
    assert zimni_pritapeni(5.0) == 0.8
    assert zimni_pritapeni(4.5) == 1.0           # plná hodnota


def test_pritapeni_dal_neroste():
    """Hlubší mrazy na tom nic nemění a v našich šířkách jsou vzácné."""
    from core import zimni_pritapeni
    assert zimni_pritapeni(0.0) == 1.0
    assert zimni_pritapeni(-10.0) == 1.0
    assert zimni_pritapeni(-30.0) == 1.0


def test_pritapeni_jde_vypnout():
    from core import zimni_pritapeni
    assert zimni_pritapeni(-20.0, prah=0) == 0.0


def test_pritapeni_se_pricita_az_za_dolni_hranici():
    """Jinak by ho hranice spolkla právě v mrazu, kde má smysl."""
    from core import cil_adaptivni, zimni_pritapeni
    bez = cil_adaptivni(-10.0, 0.0, 20.0, 27.0)
    s_pritopenim = cil_adaptivni(-10.0, 0.0, 20.0, 27.0,
                                 zimni_pritapeni(-10.0))
    assert bez == 20.0
    assert s_pritopenim == 21.0


def test_pritapeni_neprelezne_horni_hranici():
    from core import cil_adaptivni
    assert cil_adaptivni(25.0, 0.0, 20.0, 27.0, 1.5) == 27.0


# ------------------------------------------- útlumy topení

def test_nocni_utlum_klesa_s_predstihem():
    """Skok by se stejně nestihl projevit — hlavice i zdivo jsou pomalé."""
    from core import nocni_utlum
    u = lambda h: nocni_utlum(h, 22.0, 6.5, 1.0)
    assert u(20.0) == 0.0          # daleko před nocí nic
    assert u(21.0) == 0.0          # předstih je hodina
    assert u(21.5) == 0.5          # v půlce náběhu
    assert u(22.0) == 1.0          # začátek noci, plný útlum
    assert u(3.0) == 1.0
    assert u(6.5) == 0.0           # noc skončila, pouštíme


def test_nocni_utlum_pri_spanku_hned():
    """Zapnutý spánek je výslovný pokyn, hodina nerozhoduje."""
    from core import nocni_utlum
    assert nocni_utlum(14.0, 22.0, 6.5, 1.0, spanek=True) == 1.0


def test_nocni_utlum_jde_vypnout():
    from core import nocni_utlum
    for h in (21.5, 23.0, 3.0):
        assert nocni_utlum(h, 22.0, 6.5, 0.0) == 0.0


def test_nocni_utlum_bez_predstihu_skokem():
    from core import nocni_utlum
    assert nocni_utlum(21.5, 22.0, 6.5, 1.0, predstih_min=0) == 0.0
    assert nocni_utlum(22.5, 22.0, 6.5, 1.0, predstih_min=0) == 1.0


def test_pasmo_pres_pulnoc():
    from core import _v_pasmu
    assert _v_pasmu(23.0, 22.0, 6.5) is True
    assert _v_pasmu(2.0, 22.0, 6.5) is True
    assert _v_pasmu(12.0, 22.0, 6.5) is False


# --------------------- komfortní otevření v noci

def test_komfort_v_noci_zavira_i_bez_klidu():
    """Že je venku příjemně, není ve tři ráno důvod nechat okno
    otevřené — tím se probudí dům, ne místnost."""
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
              komfort_start=21.5)
    r = rozhodni(Vstup(co2=480, t_in=21.0, t_in_max=21.2, t_out=17.0,
                       cil=21.0, hodina=3.0,
                       cas_s=100000), p, N)
    assert r.akce is Akce.ZAVRIT and "noční hodiny" in r.duvod


def test_komfort_pres_den_zustava():
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
              komfort_start=21.5)
    r = rozhodni(Vstup(co2=480, t_in=21.0, t_in_max=21.2, t_out=17.0,
                       cil=21.0, hodina=14.0,
                       cas_s=100000), p, N)
    assert r.akce is not Akce.ZAVRIT


def test_chlazeni_v_noci_smi():
    """V létě se kvůli chlazení otevírá právě v noci."""
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
              komfort_start=27.0)
    r = rozhodni(Vstup(co2=480, t_in=26.0, t_in_max=27.5, t_out=19.0,
                       cil=21.0, hodina=3.0,
                       cas_s=100000), p, N)
    assert r.akce is not Akce.ZAVRIT


# --------------------- noční větrání má skončit, když je vyvětráno

def test_v_noci_se_zavira_i_po_vyvetrani():
    """Dřív se v noci čekalo jen na pokles teploty. Když bylo venku
    mírně, nepřišel nikdy a okno zůstalo otevřené do rána."""
    p = Pamet(otevreno=True, cas_povelu_s=0, noc_mez=20.0, rezim="noc")
    r = rozhodni(Vstup(co2=480, t_in=21.0, t_in_max=21.2, t_out=12.0,
                       cil=21.0, hodina=3.0, 
                       cas_s=100000), p, N)
    assert r.akce is Akce.ZAVRIT and "vyvětráno" in r.duvod


def test_v_noci_dusno_vetra_dal():
    p = Pamet(otevreno=True, cas_povelu_s=0, noc_mez=20.0, rezim="noc")
    r = rozhodni(Vstup(co2=1100, t_in=21.0, t_in_max=21.2, t_out=12.0,
                       cil=21.0, hodina=3.0, 
                       cas_s=100000), p, N)
    assert r.akce is not Akce.ZAVRIT


def test_v_noci_pokles_teploty_zavira_dal():
    p = Pamet(otevreno=True, cas_povelu_s=0, noc_mez=20.0, rezim="noc")
    r = rozhodni(Vstup(co2=1100, t_in=19.8, t_in_max=20.0, t_out=12.0,
                       cil=21.0, hodina=3.0, 
                       cas_s=100000), p, N)
    assert r.akce is Akce.ZAVRIT and "kleslo" in r.duvod


def test_rucni_zadost_v_noci_vetra_i_po_vyvetrani():
    """Tvůj výslovný pokyn vyvětráno nepřebíjí."""
    p = Pamet(otevreno=True, cas_povelu_s=0, noc_mez=20.0, rezim="noc")
    r = rozhodni(Vstup(co2=450, t_in=21.0, t_in_max=21.2, t_out=12.0,
                       cil=21.0, hodina=3.0, 
                       vetrat=True, cas_s=100000), p, N)
    assert r.akce is not Akce.ZAVRIT


def test_volba_nocniho_zavirani_ma_oba_smery():
    """Obě chování musí být dosažitelná, ať je zřejmé, co volba dělá."""
    from core import Nastaveni as N_
    vstup = dict(co2=480, t_in=21.0, t_in_max=21.2, t_out=12.0, cil=21.0,
                 hodina=3.0,  cas_s=100000)

    p1 = Pamet(otevreno=True, cas_povelu_s=0, noc_mez=20.0)
    r1 = rozhodni(Vstup(**vstup), p1, N_(noc_zavrit_po_vyvetrani=True))
    assert r1.akce is Akce.ZAVRIT

    p2 = Pamet(otevreno=True, cas_povelu_s=0, noc_mez=20.0)
    r2 = rozhodni(Vstup(**vstup), p2, N_(noc_zavrit_po_vyvetrani=False))
    assert r2.akce is not Akce.ZAVRIT


def test_nocni_mez_je_jedna_a_absolutni():
    """Relativní pokles mez posouval podle toho, jak bylo zrovna teplo,
    takže nebylo poznat, kde okno zavře."""
    from core import Nastaveni as N_
    nast = N_(nocni_min=21.0)

    # otevře se a mez je rovnou ta nastavená, bez ohledu na teplotu
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(Vstup(co2=1100, t_in=23.5, t_in_max=23.7, t_out=12.0,
                       cil=21.0, hodina=2.0, 
                       cas_s=100000), p, nast)
    assert r.akce is Akce.OTEVRIT
    assert p.noc_mez == 21.0

    p2 = Pamet(cas_povelu_s=0)
    rozhodni(Vstup(co2=1100, t_in=22.5, t_in_max=22.6, t_out=12.0,
                   cil=21.0, hodina=2.0, 
                   cas_s=100000), p2, nast)
    assert p2.noc_mez == 21.0        # táž mez, jiná výchozí teplota


def test_nocni_rezerva_neotevira_tesne_nad_mezi():
    """Otevřít stupeň nad mezí by znamenalo zavřít za pár minut."""
    from core import Nastaveni as N_
    nast = N_(nocni_min=21.0)
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(Vstup(co2=1100, t_in=21.9, t_in_max=22.0, t_out=12.0,
                       cil=21.0, hodina=2.0, 
                       cas_s=100000), p, nast)
    assert r.akce is Akce.NIC and "jen" in r.duvod


# --------------------- konflikt mezí s cílovou teplotou

def test_nocni_mez_nad_cilem_se_ohlasi():
    """Noční mez je absolutní, takže se s cílem rozejít může.
    Denní se od cíle odvozuje, tam ten konflikt nastat nemůže."""
    from core import konflikt_mezi
    assert konflikt_mezi(21.0, 1.5, 18.0) == []
    assert "nad cílem" in " ".join(konflikt_mezi(21.0, 1.5, 22.0))
    assert "nerozjede" in " ".join(konflikt_mezi(21.0, 1.5, 20.5))


def test_maly_denni_odstup_se_ohlasi():
    """Pod půl stupně se okno jen otevře a hned zavře."""
    from core import konflikt_mezi
    assert "hned zavře" in " ".join(konflikt_mezi(21.0, 0.2, 18.0))


def test_konflikt_pocita_i_tloustku():
    from core import konflikt_mezi
    assert konflikt_mezi(21.0, 1.5, 19.5, tloustka=1.0) == []
    assert konflikt_mezi(21.0, 1.5, 19.5, tloustka=2.0) != []


def test_denni_mez_sleduje_cil():
    """Mez odvozená od cíle sleduje sezónu sama: v zimě zavře výš,
    v létě níž, a nemusí se nic přenastavovat."""
    from core import Nastaveni as N_
    nast = N_(denni_pod_cil=1.5)
    for cil, ceka in ((21.0, 19.5), (26.0, 24.5)):
        p = Pamet(cas_povelu_s=0)
        rozhodni(Vstup(co2=1200, t_in=cil, t_in_max=cil, t_out=cil - 8,
                       cil=cil, hodina=14.0, cas_s=100000), p, nast)
        assert p.den_mez == ceka, (cil, p.den_mez)


def test_konflikt_pojmenuje_nastaveni_a_radi():
    """Bez názvu nastavení a rady je z hlášky jen „konflikt“ a nikdo
    neví, kam sáhnout."""
    from core import konflikt_mezi
    t = konflikt_mezi(21.0, 1.5, 21.5)[0]
    assert "V noci vychladnout nejvýš na" in t     # jak se to jmenuje
    assert "21.5" in t and "21.0" in t             # obě čísla
    assert "Sniž" in t                             # co s tím

    t2 = konflikt_mezi(21.0, 0.2, 18.0)[0]
    assert "Ve dne smí klesnout pod cíl o" in t2
    assert "Zvyš" in t2

    t3 = konflikt_mezi(21.0, 1.5, 20.5)[0]
    assert "20.0" in t3        # konkrétní hranice, pod kterou jít


# --------------------- bez venkovní teploty se nerozhoduje

def test_bez_venkovni_teploty_se_nic_nedeje():
    """Po restartu čidlo chvíli nehlásí. Dřív se místo něj použila
    vymyšlená patnáctka a na jejím základě se zavíralo okno."""
    p = Pamet(otevreno=True, cas_povelu_s=0)
    r = rozhodni(Vstup(co2=500, t_in=21.0, t_in_max=21.2, cil=21.0,
                       hodina=14.0, t_out=None, cas_s=100000), p, N)
    assert r.akce is not Akce.ZAVRIT
    assert "neznám" in r.duvod


def test_vitr_plati_i_bez_venkovni_teploty():
    """Vítr poškodí pohon bez ohledu na to, kolik je venku stupňů."""
    p = Pamet(otevreno=True, cas_povelu_s=0)
    r = rozhodni(Vstup(co2=500, t_in=21.0, cil=21.0, vitr_blokuje=True,
                       t_out=None, cas_s=100000), p, N)
    assert r.akce is Akce.ZAVRIT


def test_diagnostika_to_rekne():
    from core import duvody
    p = Pamet(cas_povelu_s=0)
    t = duvody(Vstup(co2=500, t_in=21.0, cil=21.0, t_out=None,
                     cas_s=100000), p, N)
    assert "neznám" in " ".join(t)


def test_rosny_bod_bez_vlhkosti_neblokuje():
    """Vymyšlená padesátka umí kondenzaci zatajit i vyrobit."""
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(Vstup(co2=1200, t_in=21.0, t_in_max=21.2, t_out=18.0,
                       rh_out=None, cil=21.0, hodina=14.0,
                       cas_s=100000), p, N)
    assert r.akce is Akce.OTEVRIT      # rosný bod se nepočítá


def test_rosny_bod_s_vlhkosti_se_pocita():
    """Se známou vlhkostí se rosný bod počítá a diagnostika ho uvede.
    CO2 ho přebíjí — dusno je horší než kondenzace."""
    from core import duvody
    p = Pamet(cas_povelu_s=0)
    t = duvody(Vstup(co2=500, t_in=21.0, t_in_max=21.2, t_out=20.5,
                     rh_out=99.0, cil=21.0, hodina=14.0,
                     cas_s=100000), p, N)
    assert any("rosný" in x for x in t)

    # bez vlhkosti se nepočítá vůbec
    t2 = duvody(Vstup(co2=500, t_in=21.0, t_in_max=21.2, t_out=20.5,
                      rh_out=None, cil=21.0, hodina=14.0,
                      cas_s=100000), p, N)
    assert not any("rosný" in x for x in t2)


# ------------- noční hodiny platí všude, klid je jen spánek

def test_nocni_hodiny_plati_i_bez_spanku():
    """Vyšší práh CO2 v noci není věc jedné místnosti. Dřív se dal
    místnosti vypnout a vznikaly tím tři různé „klidy"."""
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(stary(co2=900, t_in=21.0, t_out=12.0, cil=21.0,
                       hodina=2.0, spanek=False), p, N)
    # 900 je nad denním prahem, ale pod nočním
    assert r.akce is not Akce.OTEVRIT
    assert "noc" in r.duvod


def test_spanek_uspi_i_mimo_nocni_hodiny():
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(stary(co2=900, t_in=21.0, t_out=12.0, cil=21.0,
                       hodina=14.0, spanek=True), p, N)
    assert "noc" in r.duvod


def test_pres_den_bez_spanku_plati_denni_prah():
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(stary(co2=900, t_in=21.0, t_in_max=21.2, t_out=12.0,
                       cil=21.0, hodina=14.0, spanek=False), p, N)
    assert r.akce is Akce.OTEVRIT


# --------------------- ve spánku se kvůli teplotě nevětrá

def test_ve_spanku_otvira_jen_krize():
    """Rámus okna vzbudí spolehlivěji než CO2, tak se běžné dusno
    vydrží."""
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(stary(co2=1100, t_in=21.5, t_in_max=21.7, t_out=12.0,
                       cil=22.0, hodina=3.0, spanek=True), p, N)
    assert r.akce is Akce.NIC

    p2 = Pamet(cas_povelu_s=0)
    r2 = rozhodni(stary(co2=1700, t_in=21.5, t_in_max=21.7, t_out=12.0,
                        cil=22.0, hodina=3.0, spanek=True), p2, N)
    assert r2.akce is Akce.OTEVRIT


def test_ve_spanku_teplota_nezavira_hned():
    """Dřív se zavíralo na noční mezi a pokoj se za dvacet minut
    vrátil — za noc z toho bylo dvanáct cyklů."""
    from core import Nastaveni as N_
    nast = N_(nocni_min=21.0, spanek_pojistka=2.0)
    p = Pamet(otevreno=True, cas_povelu_s=0, noc_mez=21.0, rezim="noc")
    r = rozhodni(stary(co2=1700, t_in=20.5, t_in_max=20.7, t_out=12.0,
                       cil=22.0, hodina=3.0, spanek=True), p, nast)
    assert r.akce is not Akce.ZAVRIT


def test_pojistka_ve_spanku_prece_zavre():
    """V mrazu se ložnice nesmí vychladit donekonečna."""
    from core import Nastaveni as N_
    nast = N_(nocni_min=21.0, spanek_pojistka=2.0)
    p = Pamet(otevreno=True, cas_povelu_s=0, noc_mez=21.0, rezim="noc")
    r = rozhodni(stary(co2=1700, t_in=18.9, t_in_max=19.0, t_out=-5.0,
                       cil=22.0, hodina=3.0, spanek=True), p, nast)
    assert r.akce is Akce.ZAVRIT and "kleslo" in r.duvod


def test_bez_spanku_v_nocnich_hodinach_teplota_zavira():
    """Mimo spánek se noční mez drží jako dřív."""
    from core import Nastaveni as N_
    nast = N_(nocni_min=21.0)
    p = Pamet(otevreno=True, cas_povelu_s=0, noc_mez=21.0, rezim="noc")
    r = rozhodni(stary(co2=1100, t_in=20.9, t_in_max=21.0, t_out=12.0,
                       cil=22.0, hodina=3.0), p, nast)
    assert r.akce is Akce.ZAVRIT


def test_zavreni_kvuli_teplote_ma_kod():
    """Podle kódu na něj koordinátor nasadí pauzu, aby okno nelítalo."""
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
              komfort_start=21.5)
    r = rozhodni(stary(co2=550, t_in=19.4, t_in_max=19.6, t_out=18.0,
                       cil=21.0, hodina=14), p, N)
    assert r.akce is Akce.ZAVRIT and r.kod == "teplota"


# --------------------- obrázek hysterezní smyčky

def test_pasmo_ukaze_meze_i_kde_jsme():
    """Nastavit čtyři čísla a pak hádat, co dělají, je k ničemu."""
    from core import pasmo_text
    r = pasmo_text(21.0, 20.8, 1.5, 18.0, 1.0, otevreno=True)
    t = "\n".join(r)
    assert "cíl 21.0" in t
    assert "19.5" in t            # denní mez = cíl - 1,5
    assert "teď otevřeno" in t
    assert "zavřu při poklesu na 19.5" in t


def test_pasmo_po_zavreni_ukaze_na_co_se_ceka():
    from core import pasmo_text
    t = "\n".join(pasmo_text(21.0, 20.1, 1.5, 18.0, 1.0, otevreno=False,
                             zavrela_na=19.5))
    assert "znovu otevřu od 20.5" in t
    # obě hrany, ať je vidět, že smyčka je souměrná
    assert "hřát od 20.5" in t and "chladit od" in t


def test_pasmo_ve_spanku_ukaze_pojistku():
    from core import pasmo_text
    t = "\n".join(pasmo_text(22.0, 20.4, 1.5, 21.0, 1.0, otevreno=True,
                             spanek=True, noc=True, spanek_pojistka=2.0))
    assert "pojistka ve spánku 19.0" in t


def test_pasmo_ma_teplotu_ve_spravnem_poradi():
    """Značka „teď" musí sedět mezi mezemi, jinak je obrázek matoucí."""
    from core import pasmo_text
    r = pasmo_text(21.0, 20.8, 1.5, 18.0, 1.0, otevreno=True)
    cisla = [float(x.split()[0]) for x in r if x[:5].strip()
             and x.split()[0].replace(".", "").isdigit()]
    assert cisla == sorted(cisla, reverse=True)


def test_tloustka_rusi_hysterezi_kdyz_je_nula():
    from core import Nastaveni as N_
    nast = N_(tloustka=0.0)
    p = Pamet(otevreno=False, cas_povelu_s=0, teplota_zavrela_na=19.5)
    r = rozhodni(stary(co2=1200, t_in=19.6, t_in_max=19.8, t_out=12.0,
                       cil=21.0, hodina=14.0), p, nast)
    assert r.akce is Akce.OTEVRIT


# ------------- okno otevřené před spaním se smí zavřít

def test_pred_spanim_otevrene_okno_se_zavre():
    """Ve spánku smí otevřít jen krize, ale zavírat se smělo až po
    vyvětrání — kterého spící člověk nedosáhne, takže okno zůstalo
    otevřené celou noc."""
    p = Pamet(otevreno=True, cas_povelu_s=0, noc_mez=21.0, rezim="noc")
    r = rozhodni(stary(co2=900, t_in=21.5, t_in_max=21.7, t_out=12.0,
                       cil=22.0, hodina=23.0, spanek=True), p, N)
    assert r.akce is Akce.ZAVRIT and "klid" in r.duvod


def test_nad_krizi_vetra_dal():
    p = Pamet(otevreno=True, cas_povelu_s=0, noc_mez=21.0, rezim="noc")
    r = rozhodni(stary(co2=1400, t_in=21.5, t_in_max=21.7, t_out=12.0,
                       cil=22.0, hodina=23.0, spanek=True), p, N)
    assert r.akce is not Akce.ZAVRIT


def test_ve_spanku_je_pasmo_z_nastavenych_prahu():
    """Otevírá krizový práh, zavírá noční. Obojí si uživatel nastavuje
    a vidí, takže je poznat, v jakém pásmu okno zůstane otevřené."""
    assert N.co2_noc < N.co2_noc_krize      # pásmo musí být neprázdné

    # mezi prahy: otevřené zůstane, zavřené se neotevře
    co2 = (N.co2_noc + N.co2_noc_krize) / 2
    p = Pamet(otevreno=True, cas_povelu_s=0, noc_mez=21.0, rezim="noc")
    assert rozhodni(stary(co2=co2, t_in=21.5, t_in_max=21.7, t_out=12.0,
                          cil=22.0, hodina=23.0, spanek=True),
                    p, N).akce is not Akce.ZAVRIT

    p2 = Pamet(otevreno=False, cas_povelu_s=0)
    assert rozhodni(stary(co2=co2, t_in=21.5, t_in_max=21.7, t_out=12.0,
                          cil=22.0, hodina=23.0, spanek=True),
                    p2, N).akce is not Akce.OTEVRIT


def test_ve_spanku_zavira_na_nocnim_prahu():
    """Žádné skryté číslo: zavírá se pod „V noci otevřít nad CO2"."""
    from core import Nastaveni as N_
    nast = N_(co2_noc=1000.0, co2_noc_krize=1250.0, nocni_min=21.0)

    p = Pamet(otevreno=True, cas_povelu_s=0, noc_mez=21.0, rezim="noc")
    r = rozhodni(stary(co2=999, t_in=21.5, t_in_max=21.7, t_out=12.0,
                       cil=22.0, hodina=23.0, spanek=True), p, nast)
    assert r.akce is Akce.ZAVRIT

    p2 = Pamet(otevreno=True, cas_povelu_s=0, noc_mez=21.0, rezim="noc")
    r2 = rozhodni(stary(co2=1001, t_in=21.5, t_in_max=21.7, t_out=12.0,
                        cil=22.0, hodina=23.0, spanek=True), p2, nast)
    assert r2.akce is not Akce.ZAVRIT


def test_pm10_se_odvozuje_z_pm25():
    """Prahy PM10 byly zadrátované, takže se s nastavením PM2.5
    nehýbaly — kdo si zvedl jeden, druhý mu zůstal."""
    from core import PM10_NASOBEK, Nastaveni as N_
    nast = N_(pm_prah=50.0)
    assert nast.pm_prah * PM10_NASOBEK == 70.0

    # a prach se pozná i podle PM10
    p = Pamet(cas_povelu_s=0, pm_prumer=10.0)
    r = rozhodni(stary(co2=500, pm25=10, pm10=80, t_in=21.0, t_in_max=21.2,
                       t_out=18.0, cil=21.0, hodina=14.0,
                       pm_platny=True), p, nast)
    assert "prach" in r.duvod.lower() or r.akce is Akce.OTEVRIT


def test_pojmenovane_konstanty_existuji():
    """Zadrátované číslo nikdo nenajde a nikdo neví, proč tam je."""
    from core import (PM10_NASOBEK, PM_VYHLAZENI, POD_CILEM_REZERVA,
                      RANO_RUCH_DO)
    assert RANO_RUCH_DO == 9.0
    assert POD_CILEM_REZERVA == 0.5
    assert 1.0 < PM10_NASOBEK < 2.0
    assert 0.0 < PM_VYHLAZENI < 1.0


# --------------------- smyčka musí být souměrná

def test_tloustka_plati_i_v_teplem_smeru():
    """Dřív chránila jen chladný směr, takže v letním období lítalo
    okno stejně jako v zimním."""
    from core import Nastaveni as N_
    nast = N_(tloustka=1.0)

    # zavřelo se, když nejteplejší místo spadlo na 24,9
    p = Pamet(otevreno=False, cas_povelu_s=0, tmax_zavrela_na=24.9)
    r = rozhodni(stary(co2=500, t_in=24.8, t_in_max=25.1, t_out=19.0,
                       rh_out=50.0, cil=24.0, hodina=14.0), p, nast)
    assert r.akce is not Akce.OTEVRIT

    p2 = Pamet(otevreno=False, cas_povelu_s=0, tmax_zavrela_na=24.9)
    r2 = rozhodni(stary(co2=500, t_in=25.6, t_in_max=25.9, t_out=19.0,
                        rh_out=50.0, cil=24.0, hodina=14.0), p2, nast)
    assert r2.akce is Akce.OTEVRIT and "chlazení" in r2.duvod


def test_stupnice_v_horku_ukaze_horni_hranu():
    """V létě tvrdila nesmysl — že se zavře při poklesu hluboko pod
    cíl, přestože v chlazení se zavírá hned nad cílem."""
    from core import pasmo_text
    t = "\n".join(pasmo_text(24.0, 25.1, 1.5, 18.0, 1.0, otevreno=True,
                             t_max=25.4))
    assert "chladím nad 25.0" in t
    assert "zavřu, až klesne na 25.0" in t


def test_stupnice_v_chladu_ukaze_dolni_hranu():
    from core import pasmo_text
    t = "\n".join(pasmo_text(21.0, 20.8, 1.5, 18.0, 1.0, otevreno=True,
                             t_max=21.0))
    assert "zavřu při poklesu na 19.5" in t


def test_stupnice_po_letnim_zavreni():
    from core import pasmo_text
    t = "\n".join(pasmo_text(24.0, 24.6, 1.5, 18.0, 1.0, otevreno=False,
                             t_max=25.1, tmax_zavrela_na=24.9))
    assert "chladit znovu od 25.9" in t
