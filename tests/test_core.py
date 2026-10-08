"""Testy rozhodovacího jádra."""

from core import (Akce, Nastaveni, Pamet, Vstup, cil_adaptivni, rozhodni,
                  rosny_bod)

N = Nastaveni(narazove_odstup=4.0)


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




def test_drzeni_stavu_ma_vlastni_kod():
    p = Pamet(otevreno=True, cas_povelu_s=0)
    r = rozhodni(Vstup(co2=500, cil=25.5, cas_s=30, t_out=15.0), p, N)
    assert r.kod == "drzeni"


# ------------------------------------------------- noční hystereze









# ------------------------------------------- společné nárazové větrání

def test_narazove_bezi_jako_bezne_ale_zavre_driv():
    """Dřív se pulz zkracoval na pevných deset minut. Teď běží stejně
    dlouho, jen se zavře, jakmile důvod pomine."""
    bez, _ = krok(stary(co2=900, t_in=21, t_out=14.5, cil=25.5))
    s, _ = krok(stary(co2=900, t_in=21, t_out=14.5, cil=25.5, narazove=True))
    assert bez.limit_s == s.limit_s
    assert "nárazově" in s.duvod and "důvod pomine" in s.duvod


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




def test_daleko_od_cile_se_neotvira_pro_pohodu():
    """Za prahem je venku tak jiný vzduch, že „venku je příjemně"
    neplatí ani zdaleka. Platí i při vypnutém nárazovém větrání."""
    from core import Nastaveni as N_
    nast = N_(narazove_odstup=10.0)
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
              komfort_start=21.5)
    r = rozhodni(stary(co2=500, t_in=21.0, t_in_max=21.2, t_out=-5.0,
                       rh_out=50.0, cil=20.0, hodina=14.0), p, nast)
    assert r.akce is Akce.ZAVRIT and "mimo pásmo" in r.duvod


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



def test_ocekavani_pri_zavrenem_rekne_prah():
    from core import ocekavani
    t = ocekavani(Vstup(co2=720, t_in=22.0, cil=25.5, cas_s=100000, t_out=15.0),
                  Pamet(cas_povelu_s=0), N)
    assert "800" in " ".join(t) and "720" in " ".join(t)






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
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz")
    _vetra(p, 9.0, 100000)
    assert p.pm_pri_otevreni == 9.0
    _vetra(p, 20.0, 100600)
    assert p.pm_venku_horsi_do_s > 100600


def test_kratke_vetrani_jeste_nestaci():
    """Vzduch se musí promíchat, jinak by poznatek vznikal z šumu."""
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz")
    _vetra(p, 9.0, 100000)
    _vetra(p, 20.0, 100060)
    assert p.pm_venku_horsi_do_s == 0.0


def test_klesajici_prach_poznatek_nevytvori():
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz")
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
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz")
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



def test_spanek_vedle_nezavre_kuchyni():
    """Kuchyň má klid navázaný na spánek, ale sama se v ní nespí.
    Spánek v obýváku ve stejné oblasti ji nesmí uspat taky."""
    r, _ = krok(stary(co2=1073, t_in=20.6, t_out=8, cil=25.5, hodina=7,
                      spanek=False))
    assert r.akce is Akce.OTEVRIT



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
    assert "4. pulz po sobě" in " ".join(posledni(p, 100000))


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


def test_komfort_potrebuje_prijemno_venku():
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
              komfort_start=21.5)
    # venku 17 při cíli 21 je mimo pásmo, takže pro pohodu se zavře
    r = rozhodni(Vstup(co2=480, t_in=21.0, t_in_max=21.2, t_out=17.0,
                       cil=21.0, hodina=14.0,
                       cas_s=100000), p, N)
    assert r.akce is Akce.ZAVRIT and "mimo pásmo" in r.duvod

    # blíž k cíli se nechá otevřeno
    p2 = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
               komfort_start=21.5)
    r2 = rozhodni(Vstup(co2=480, t_in=21.0, t_in_max=21.2, t_out=19.5,
                        cil=21.0, hodina=14.0,
                        cas_s=100000), p2, N)
    assert r2.akce is not Akce.ZAVRIT




# --------------------- noční větrání má skončit, když je vyvětráno

def test_v_noci_se_zavira_i_po_vyvetrani():
    """Dřív se v noci čekalo jen na pokles teploty. Když bylo venku
    mírně, nepřišel nikdy a okno zůstalo otevřené do rána."""
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="noc")
    r = rozhodni(Vstup(co2=480, t_in=21.0, t_in_max=21.2, t_out=12.0,
                       cil=21.0, hodina=3.0, 
                       cas_s=100000), p, N)
    assert r.akce is Akce.ZAVRIT and "vyvětráno" in r.duvod


def test_v_noci_dusno_vetra_dal():
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="noc")
    r = rozhodni(Vstup(co2=1100, t_in=21.0, t_in_max=21.2, t_out=12.0,
                       cil=21.0, hodina=3.0, 
                       cas_s=100000), p, N)
    assert r.akce is not Akce.ZAVRIT




def test_rucni_zadost_v_noci_vetra_i_po_vyvetrani():
    """Tvůj výslovný pokyn vyvětráno nepřebíjí."""
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="noc")
    r = rozhodni(Vstup(co2=450, t_in=21.0, t_in_max=21.2, t_out=12.0,
                       cil=21.0, hodina=3.0, 
                       vetrat=True, cas_s=100000), p, N)
    assert r.akce is not Akce.ZAVRIT







# --------------------- konflikt mezí s cílovou teplotou











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




def test_pojistka_ve_spanku_prece_zavre():
    """V mrazu se ložnice nesmí vychladit donekonečna."""
    from core import Nastaveni as N_
    nast = N_(mez_dolni=21.0)
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="noc")
    r = rozhodni(stary(co2=1700, t_in=18.9, t_in_max=19.0, t_out=-5.0,
                       cil=22.0, hodina=3.0, spanek=True), p, nast)
    assert r.akce is Akce.ZAVRIT and "kleslo" in r.duvod


def test_bez_spanku_v_nocnich_hodinach_teplota_zavira():
    """Mimo spánek se noční mez drží jako dřív."""
    from core import Nastaveni as N_
    nast = N_(mez_dolni=21.0)
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="noc")
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











# ------------- okno otevřené před spaním se smí zavřít



def test_nad_krizi_vetra_dal():
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="noc")
    r = rozhodni(stary(co2=1400, t_in=21.5, t_in_max=21.7, t_out=12.0,
                       cil=22.0, hodina=23.0, spanek=True), p, N)
    assert r.akce is not Akce.ZAVRIT


def test_ve_spanku_je_pasmo_z_nastavenych_prahu():
    """Otevírá krizový práh, zavírá noční. Obojí si uživatel nastavuje
    a vidí, takže je poznat, v jakém pásmu okno zůstane otevřené."""
    assert N.co2_noc < N.co2_noc_krize      # pásmo musí být neprázdné

    # mezi prahy: otevřené zůstane, zavřené se neotevře
    co2 = (N.co2_noc + N.co2_noc_krize) / 2
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="noc")
    assert rozhodni(stary(co2=co2, t_in=21.5, t_in_max=21.7, t_out=12.0,
                          cil=22.0, hodina=23.0, spanek=True),
                    p, N).akce is not Akce.ZAVRIT

    p2 = Pamet(otevreno=False, cas_povelu_s=0)
    assert rozhodni(stary(co2=co2, t_in=21.5, t_in_max=21.7, t_out=12.0,
                          cil=22.0, hodina=23.0, spanek=True),
                    p2, N).akce is not Akce.OTEVRIT




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
    from core import PM10_NASOBEK, PM_VYHLAZENI
    assert 1.0 < PM10_NASOBEK < 2.0
    assert 0.0 < PM_VYHLAZENI < 1.0




# --------------------- smyčka musí být souměrná

















def test_v_noci_se_zavira_po_vyvetrani_vzdy():
    """Volba zmizela, zavírání po vyvětrání zůstalo."""
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="noc")
    r = rozhodni(stary(co2=480, t_in=21.0, t_in_max=21.2, t_out=12.0,
                       cil=21.0, hodina=3.0), p, N)
    assert r.akce is Akce.ZAVRIT and "vyvětráno" in r.duvod




# --------------------- chlazení dojede na cíl



def test_dve_desetiny_nad_cilem_neni_chlazeni():
    """Jinak by každý pokoj o chlup nad cílem obešel noční pravidlo."""
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
              komfort_start=21.5)
    r = rozhodni(stary(co2=480, t_in=21.0, t_in_max=21.2, t_out=17.0,
                       rh_out=50.0, cil=21.0, hodina=3.0), p, N)
    assert r.akce is Akce.ZAVRIT and "noční hodiny" in r.duvod


# --------------------- kontrola účinku větrání

def test_bez_ucinku_se_zavre():
    """Marně otevřené okno v zimě stojí teplo a nic za to nevrací."""
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz",
              ucinek_od_s=100000 - 1800, ucinek_co2=1100, ucinek_t_in=21.0)
    r = rozhodni(stary(co2=1100, t_in=21.0, t_in_max=21.2, t_out=12.0,
                       cil=22.0, hodina=14.0), p, N)
    assert r.akce is Akce.ZAVRIT and r.kod == "bez_ucinku"
    assert "1100" in r.duvod        # je vidět, z čeho a kam


def test_zlepseni_vetra_dal():
    for co2, t_in in ((900, 21.0), (1100, 21.5)):
        p = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz",
                  ucinek_od_s=100000 - 1800, ucinek_co2=1100,
                  ucinek_t_in=21.0)
        r = rozhodni(stary(co2=co2, t_in=t_in, t_in_max=t_in + 0.2,
                           t_out=12.0, cil=22.0, hodina=14.0), p, N)
        assert r.akce is not Akce.ZAVRIT, (co2, t_in)


def test_zhorseni_zavre_hned_po_dobe():
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz",
              ucinek_od_s=100000 - 1800, ucinek_co2=1100, ucinek_t_in=21.0)
    r = rozhodni(stary(co2=1200, t_in=20.8, t_in_max=21.0, t_out=12.0,
                       cil=22.0, hodina=14.0), p, N)
    assert r.akce is Akce.ZAVRIT and r.kod == "bez_ucinku"


def test_krize_a_rucni_zadost_kontrolu_prebiji():
    """Nad krizovým prahem se větrá, i když to zabírá málo."""
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz",
              ucinek_od_s=100000 - 1800, ucinek_co2=1100, ucinek_t_in=21.0)
    r = rozhodni(stary(co2=1300, t_in=21.0, t_in_max=21.2, t_out=12.0,
                       cil=22.0, hodina=14.0), p, N)
    assert r.kod != "bez_ucinku"

    p2 = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz",
               ucinek_od_s=100000 - 1800, ucinek_co2=1100, ucinek_t_in=21.0)
    r2 = rozhodni(stary(co2=1100, t_in=21.0, t_in_max=21.2, t_out=12.0,
                        cil=22.0, hodina=14.0, vetrat=True), p2, N)
    assert r2.kod != "bez_ucinku"




def test_kontrola_ceka_na_svou_dobu():
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz",
              ucinek_od_s=100000 - 600, ucinek_co2=1100, ucinek_t_in=21.0)
    r = rozhodni(stary(co2=1100, t_in=21.0, t_in_max=21.2, t_out=12.0,
                       cil=22.0, hodina=14.0), p, N)
    assert r.kod != "bez_ucinku"


# --------------------- otevřené okno bez záznamu







# --------------------- ohřev venkovním vzduchem

def test_ohrev_vetranim_ma_vlastni_rezim():
    """Dřív se to jmenovalo „venku je příjemně", takže se nepoznalo,
    že jde o cílené dohánění teploty."""
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(stary(co2=500, t_in=19.0, t_in_max=19.3, t_out=27.0,
                       rh_out=50.0, cil=23.0, hodina=14.0), p, N)
    assert r.akce is Akce.OTEVRIT and "ohřev" in r.duvod
    assert p.ohrivam is True and p.chladi is False


def test_ohrev_dojede_na_horni_hranu():
    p = Pamet(otevreno=True, cas_povelu_s=0, ohrivam=True, rezim="komfort",
              komfort_start=19.0)
    r = rozhodni(stary(co2=500, t_in=23.1, t_in_max=23.3, t_out=28.0,
                       rh_out=50.0, cil=23.0, hodina=14.0), p, N)
    assert r.akce is not Akce.ZAVRIT      # pásmo sahá do 24,5

    p2 = Pamet(otevreno=True, cas_povelu_s=0, ohrivam=True, rezim="komfort",
               komfort_start=19.0)
    r2 = rozhodni(stary(co2=500, t_in=24.5, t_in_max=24.8, t_out=26.0,
                        rh_out=50.0, cil=23.0, hodina=14.0), p2, N)
    assert r2.akce is Akce.ZAVRIT and "dost teplo" in r2.duvod


def test_ohrev_potrebuje_tepleji_venku():
    """Bez teplejšího vzduchu zvenčí není čím ohřívat."""
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(stary(co2=500, t_in=19.0, t_in_max=19.3, t_out=18.0,
                       rh_out=50.0, cil=23.0, hodina=14.0), p, N)
    assert p.ohrivam is False
    assert "ohřev" not in r.duvod




def test_kontrola_ucinku_plati_i_na_ohrev():
    p = Pamet(otevreno=True, cas_povelu_s=0, ohrivam=True, rezim="komfort",
              komfort_start=19.0, ucinek_od_s=100000 - 1800,
              ucinek_co2=500, ucinek_t_in=19.0)
    r = rozhodni(stary(co2=500, t_in=19.0, t_in_max=19.2, t_out=24.5,
                       rh_out=50.0, cil=23.0, hodina=14.0), p, N)
    assert r.kod == "bez_ucinku"


# --------------------- kondenzace na skle

def test_max_vlhkost_klesa_s_mrazem():
    """V mrazu má sklo okolo pěti stupňů a rosný bod ho dohoní dřív,
    než vlhkost dojde na nastavenou mez."""
    from core import max_vlhkost
    v10 = max_vlhkost(22.0, 10.0, 0.2)
    v0 = max_vlhkost(22.0, 0.0, 0.2)
    v15 = max_vlhkost(22.0, -15.0, 0.2)
    assert v10 > v0 > v15
    assert 55 < v15 < 65          # kolem 59 %


def test_horsi_sklo_snese_mene():
    from core import max_vlhkost
    trojsklo = max_vlhkost(22.0, -5.0, 0.08)
    dvojsklo = max_vlhkost(22.0, -5.0, 0.2)
    jednoduche = max_vlhkost(22.0, -5.0, 0.55)
    assert trojsklo > dvojsklo > jednoduche
    assert jednoduche < 45


def test_v_teple_strop_neomezuje():
    """V létě sklo chladné není, takže se vlhkost neřeší."""
    from core import max_vlhkost
    assert max_vlhkost(22.0, 24.0, 0.2) == 100.0


def test_teplota_skla():
    from core import teplota_skla
    assert teplota_skla(22.0, -5.0, 0.0) == 22.0      # ideální okno
    assert teplota_skla(22.0, -5.0, 0.2) == 16.6
    assert teplota_skla(22.0, 22.0, 0.5) == 22.0      # bez rozdílu nic






# --------------------- denní hystereze obemyká cíl







# --------------------- proč se kvůli teplotě neotvírá





def test_zavre_kdyz_vzduch_prestane_pomahat():
    """Chladili jsme a venku se oteplilo — držet okno otevřené pak
    znamená tahat dovnitř, co nechceme."""
    p = Pamet(otevreno=True, cas_povelu_s=0, chladi=True, rezim="komfort",
              komfort_start=24.4)
    r = rozhodni(stary(co2=500, t_in=23.5, t_in_max=23.8, t_out=25.0,
                       rh_out=50.0, cil=22.2, hodina=14.0), p, N)
    assert r.akce is Akce.ZAVRIT and "už nechladí" in r.duvod
    assert p.chladi is False

    p2 = Pamet(otevreno=True, cas_povelu_s=0, ohrivam=True, rezim="komfort",
               komfort_start=19.0)
    r2 = rozhodni(stary(co2=500, t_in=20.0, t_in_max=20.3, t_out=15.0,
                        rh_out=50.0, cil=22.2, hodina=14.0), p2, N)
    assert r2.akce is Akce.ZAVRIT and "už neohřívá" in r2.duvod




def test_kontrola_ucinku_ceka_na_konec_drzeni():
    """Kontrolovat dřív, než se smí zavřít, nemá smysl — zavřít stejně
    nejde, takže se bere ta delší z obou dob."""
    from core import Nastaveni as N_
    nast = N_(min_drzeni_s=21 * 60)

    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz",
              ucinek_od_s=100000 - 15 * 60, ucinek_co2=1100,
              ucinek_t_in=21.0)
    r = rozhodni(stary(co2=1100, t_in=21.0, t_in_max=21.2, t_out=12.0,
                       cil=22.0, hodina=14.0), p, nast)
    assert r.kod != "bez_ucinku"          # 15 min < 21 min držení

    p2 = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz",
               ucinek_od_s=100000 - 22 * 60, ucinek_co2=1100,
               ucinek_t_in=21.0)
    r2 = rozhodni(stary(co2=1100, t_in=21.0, t_in_max=21.2, t_out=12.0,
                        cil=22.0, hodina=14.0), p2, nast)
    assert r2.kod == "bez_ucinku"
    assert "za 21 min" in r2.duvod        # uvedena skutečná doba




def test_pozorovani_zacina_otevrenim():
    """Nové otevření měří od nuly, ne od toho předchozího."""
    p = Pamet(otevreno=False, cas_povelu_s=0, rezim="pulz")
    r = rozhodni(Vstup(co2=1200, t_in=21.0, t_in_max=21.2, t_out=12.0,
                       cil=22.0, hodina=14.0, cas_s=200000), p, N)
    assert r.akce is Akce.OTEVRIT
    assert p.ucinek_od_s == 200000
    assert p.ucinek_co2 == 1200


def test_marne_vetrani_pocita_pokusy():
    """Jinak se za dvacet minut otevře znovu a zjistí se totéž."""
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz",
              ucinek_od_s=100000 - 22 * 60, ucinek_co2=1100,
              ucinek_t_in=21.0, pulzy_za_sebou=2)
    r = rozhodni(stary(co2=1100, t_in=21.0, t_in_max=21.2, t_out=12.0,
                       cil=22.0, hodina=14.0), p, N)
    assert r.kod == "bez_ucinku"
    assert p.pulzy_za_sebou == 3          # pauza se tím zdvojnásobí


def test_jedna_doba_na_vse():
    """Dvě různé doby na jednu věc jen pletly."""
    from core import Nastaveni as N_
    assert not hasattr(N_(), "ucinek_po_s")


# --------------------- čekání na změnu venkovních podmínek

def test_po_marnem_pokusu_ceka_na_zmenu_venku():
    """Čas je jen zástupná veličina — skutečný důvod, proč to nešlo,
    bylo venku."""
    from core import Nastaveni as N_
    nast = N_(zmena_podminek=2.0, nejdriv_znovu_s=3600)

    def zkus(cas, t_out, co2=500):
        p = Pamet(otevreno=False, cas_povelu_s=0, marne_od_s=100000,
                  marne_t_out=20.0)
        return rozhodni(Vstup(co2=co2, t_in=24.5, t_in_max=24.8,
                              t_out=t_out, rh_out=50.0,
                              cil=22.0, hodina=14.0, cas_s=cas), p, nast)

    # venku se nic nezměnilo → čeká se
    assert zkus(100000 + 600, 20.0).akce is not Akce.OTEVRIT
    assert zkus(100000 + 1800, 20.0).akce is not Akce.OTEVRIT

    # ochladilo se o dva stupně → zkusí hned, nečeká na hodinu
    assert zkus(100000 + 600, 18.0).akce is Akce.OTEVRIT

    # a po hodině se zkusí tak jako tak
    assert zkus(100000 + 4200, 20.0).akce is Akce.OTEVRIT

    # krize CO2 to obejde vždycky
    assert zkus(100000 + 600, 20.0, co2=1400).akce is Akce.OTEVRIT


def test_cas_je_strop_ne_dalsi_podminka():
    """Když se ochladí dřív, zkusí se dřív — čas jen hlídá, aby se
    nečekalo věčně."""
    from core import Nastaveni as N_
    nast = N_(zmena_podminek=2.0, nejdriv_znovu_s=3600)
    p = Pamet(otevreno=False, cas_povelu_s=0, marne_od_s=100000,
              marne_t_out=20.0)
    r = rozhodni(Vstup(co2=500, t_in=24.5, t_in_max=24.8, t_out=15.0,
                       rh_out=50.0, cil=22.0, hodina=14.0,
                       cas_s=100000 + 600), p, nast)
    assert r.akce is Akce.OTEVRIT


def test_marny_pokus_si_pamatuje_podminky():
    p = Pamet(otevreno=True, cas_povelu_s=0, chladi=True, rezim="komfort",
              komfort_start=25.0, ucinek_od_s=100000 - 22 * 60,
              ucinek_co2=500, ucinek_t_in=24.0)
    r = rozhodni(Vstup(co2=500, t_in=24.5, t_in_max=24.8, t_out=20.0,
                       rh_out=50.0, cil=22.0, hodina=14.0,
                       cas_s=100000), p, N)
    assert r.kod == "bez_ucinku"
    assert p.marne_t_out == 20.0


def test_hlaska_rozlisi_zhorseni():
    """Nehýbe se to je něco jiného než zhoršuje se to."""
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz",
              ucinek_od_s=100000 - 1800, ucinek_co2=1100, ucinek_t_in=21.0)
    r = rozhodni(stary(co2=1200, t_in=20.8, t_in_max=21.0, t_out=12.0,
                       cil=22.0, hodina=14.0), p, N)
    assert "zhoršuje se to" in r.duvod

    p2 = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz",
               ucinek_od_s=100000 - 1800, ucinek_co2=1100,
               ucinek_t_in=21.0)
    r2 = rozhodni(stary(co2=1100, t_in=21.0, t_in_max=21.2, t_out=12.0,
                        cil=22.0, hodina=14.0), p2, N)
    assert "nehýbe se to" in r2.duvod


# --------------------- nárazový režim na obě strany

def test_narazovy_rezim_plati_soumerne():
    """V mrazu i v horku je venku tak jiný vzduch, že se otevírá jen
    z důvodu, ne pro pohodu."""
    from core import Nastaveni as N_
    nast = N_(narazove_odstup=15.0)      # cíl 22 → mimo 7 až 37

    def zkus(t_out, rh=50.0):
        p = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
                  komfort_start=21.5)
        return rozhodni(stary(co2=500, t_in=21.5, t_in_max=21.7,
                              t_out=t_out, rh_out=rh, cil=22.0,
                              hodina=14.0), p, nast)

    # venku 10 je pod cílem, takže otevřením se k cíli nepřiblížíme —
    # zavírá se, ale z jiného důvodu než kvůli nárazovému režimu
    assert "nárazov" not in zkus(10.0).duvod
    assert "mimo pásmo" in zkus(5.0).duvod     # mráz
    # v horku: suchý vzduch, ať do toho nemluví rosný bod
    assert "mimo pásmo" in zkus(40.0, rh=10.0).duvod


def test_narazovy_pulz_zavre_hned_po_splneni():
    """Nečeká se na dojetí cyklu, zavře se, jakmile důvod pomine."""
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(stary(co2=900, t_in=21.0, t_in_max=21.2, t_out=14.5,
                       cil=25.5, narazove=True), p, N)
    assert r.akce is Akce.OTEVRIT
    assert "zavřu, jakmile důvod pomine" in r.duvod


def test_narazove_zavira_bez_cekani_na_drzeni():
    """Bez tohohle by nárazové větrání nedělalo nic jiného než běžné —
    povel zavřít by se o dobu držení zdržel."""
    from core import Nastaveni as N_
    nast = N_(narazove_odstup=4.0, min_drzeni_s=21 * 60)

    def zkus(narazove):
        p = Pamet(otevreno=True, cas_povelu_s=100000 - 300, rezim="pulz",
                  vetra_se=True)
        return rozhodni(Vstup(co2=500, t_in=21.0, t_in_max=21.2,
                              t_out=5.0, rh_out=50.0, cil=22.0,
                              hodina=14.0, narazove=narazove,
                              cas_s=100000), p, nast)

    assert zkus(False).akce is Akce.NIC          # drží stav
    assert zkus(True).akce is Akce.ZAVRIT        # zavře hned




# --------------------- venkovní vzduch na správné straně cíle

def test_neotevira_kdyz_je_venku_na_spatne_strane():
    """Cíl 21,9, v pokoji 22,7, venku 22,5: otevřením se k cíli
    nepřiblížíme, jen se zastavíme o kus výš."""
    from core import Nastaveni as N_
    nast = N_(hyst_den_otevrit=1.5)

    # nad pásmem: vzduch nedosáhne k doběhu, takže se zavře
    for t_max in (24.5, 26.0):
        p = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
                  komfort_start=22.0)
        r = rozhodni(stary(co2=500, t_in=22.7, t_in_max=t_max, t_out=22.5,
                           rh_out=50.0, cil=21.9, hodina=14.0), p, nast)
        assert r.akce is Akce.ZAVRIT, t_max
        assert "nestačí" in r.duvod
        assert p.chladi is False


def test_chlazeni_v_horku_zustava_mozne():
    """Cíl se v létě sám zvedá, takže se tím chlazení neblokuje."""
    from core import Nastaveni as N_
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(stary(co2=500, t_in=26.5, t_in_max=27.5, t_out=21.0,
                       rh_out=50.0, cil=25.5, hodina=14.0), p,
                 N_(hyst_den_otevrit=1.5))
    assert r.akce is Akce.OTEVRIT and p.chladi is True


def test_ohrev_nepusti_vedro_do_prehrate_mistnosti():
    """Kuchyň 27, ložnice 22, venku 29. Nejchladnější čidlo volá po
    teple, ale do přehřáté kuchyně ho pouštět nechceme."""
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(stary(co2=550, t_in=22, t_in_max=27, t_out=29,
                       rh_out=50.0, cil=25, hodina=14.0), p, N)
    assert r.akce is not Akce.OTEVRIT
    assert p.ohrivam is False


def test_co2_vetra_i_kdyz_venku_nepomuze():
    """Dusno přebíjí teplotu — jinak by se v zimě nevyvětralo nikdy."""
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(stary(co2=1200, t_in=21.5, t_in_max=21.7, t_out=10.0,
                       rh_out=50.0, cil=22.0, hodina=14.0), p, N)
    assert r.akce is Akce.OTEVRIT and "CO2" in r.duvod


def test_po_marnem_pokusu_ceka_i_vetrani_kvuli_co2():
    """Dřív prošlo větrání kvůli CO2 a za dvacet minut se zkusilo
    totéž, co minule nezabralo."""
    from core import Nastaveni as N_
    nast = N_(zmena_podminek=2.0, nejdriv_znovu_s=3600)

    def zkus(cas_min, t_out=20.0, co2=900, vetrat=False):
        p = Pamet(otevreno=False, cas_povelu_s=0, marne_od_s=100000,
                  marne_t_out=20.0)
        return rozhodni(Vstup(co2=co2, t_in=21.5, t_in_max=21.7,
                              t_out=t_out, rh_out=50.0, cil=22.0,
                              hodina=14.0, vetrat=vetrat,
                              cas_s=100000 + cas_min * 60), p, nast)

    assert zkus(22).akce is not Akce.OTEVRIT      # čeká se
    assert zkus(65).akce is Akce.OTEVRIT          # strop vypršel
    assert zkus(22, t_out=18.0).akce is Akce.OTEVRIT   # venku se změnilo
    assert zkus(22, co2=1400).akce is Akce.OTEVRIT     # krize
    assert zkus(22, vetrat=True).akce is Akce.OTEVRIT  # ruční žádost


def test_nula_vypne_jen_cekani_na_podminky():
    """Dřív nula vypnula celou bránu a zbyla jen doba držení polohy,
    takže se zkoušelo každých dvacet minut."""
    from core import Nastaveni as N_
    nast = N_(zmena_podminek=0.0, nejdriv_znovu_s=3600,
              min_drzeni_s=21 * 60)

    def zkus(cas_min, t_out=19.0):
        p = Pamet(otevreno=False, cas_povelu_s=0, marne_od_s=100000,
                  marne_t_out=20.0)
        return rozhodni(Vstup(co2=500, t_in=25.0, t_in_max=25.5,
                              t_out=t_out, rh_out=50.0, cil=22.0,
                              hodina=14.0,
                              cas_s=100000 + cas_min * 60), p, nast)

    assert zkus(22).akce is not Akce.OTEVRIT      # strop platí dál
    assert zkus(45).akce is not Akce.OTEVRIT
    assert zkus(65, t_out=15.0).akce is Akce.OTEVRIT   # až po stropu

    # a se změnou podmínek vypnutou se na ni nečeká
    assert "na změnu venku" not in zkus(22).duvod
    assert "ještě" in zkus(22).duvod


# --------------- vzduch musí dosáhnout tam, kam větrání dojede





def test_zmena_venku_plati_jen_spravnym_smerem():
    """Chlazení zachrání jen chladnější vzduch, ohřev jen teplejší.
    Opačný posun situaci nezlepší, jen ji otočí."""
    from core import Nastaveni as N_
    nast = N_(zmena_podminek=2.0, nejdriv_znovu_s=3600)

    def zkus(smer, t_out):
        p = Pamet(otevreno=False, cas_povelu_s=0, marne_od_s=100000,
                  marne_t_out=20.0, marne_smer=smer)
        return rozhodni(Vstup(co2=500, t_in=25.0, t_in_max=25.5,
                              t_out=t_out, rh_out=50.0, cil=22.0,
                              hodina=14.0, cas_s=100000 + 1200), p, nast)

    # po marném chlazení pomůže jen ochlazení
    assert zkus("chlazeni", 15.0).akce is Akce.OTEVRIT
    assert zkus("chlazeni", 22.0).akce is not Akce.OTEVRIT








def test_pri_rucnim_zasahu_se_neslibuje_nic_dalsiho():
    """Automatika do okna nemluví, takže řádky o zavírání by slibovaly
    něco, co se nestane."""
    from core import ocekavani
    p = Pamet(otevreno=True, cas_povelu_s=99000, rucni_do_s=100000 + 29 * 60,
              rezim="pulz", vetra_se=True)
    v = Vstup(co2=542, t_in=19.7, t_in_max=19.9, t_out=12.0, cil=21.0,
              hodina=14.0, cas_s=100000)
    radky = ocekavani(v, p, N)

    assert len(radky) == 2
    assert "sáhl jsi na okno" in radky[0]
    assert "nouzovém větrání" in radky[1]
    assert not any("zavřu při poklesu" in x for x in radky)
    assert not any("držím stav" in x for x in radky)


# ============ pásmo kolem cíle a absolutní pojistky ============

def test_pasmo_otevira_na_odchylce_a_zavira_za_cilem():
    """Otevře se při odchylce od cíle, dojede na protější stranu —
    a obojí má vlastní číslo, takže pásmo může být nesouměrné."""
    from core import Nastaveni as N_
    nast = N_(hyst_den_otevrit=2.5, hyst_den_zavrit=1.0)
    # cíl 22 → chladit od 24,5, dojet na 21,0

    p = Pamet(cas_povelu_s=0)
    rozhodni(stary(co2=500, t_in=24.0, t_in_max=24.2, t_out=18.0,
                   rh_out=50.0, cil=22.0, hodina=14.0), p, nast)
    assert p.chladi is False          # ještě pod horní hranou

    p2 = Pamet(cas_povelu_s=0)
    r2 = rozhodni(stary(co2=500, t_in=24.4, t_in_max=24.6, t_out=18.0,
                        rh_out=50.0, cil=22.0, hodina=14.0), p2, nast)
    assert r2.akce is Akce.OTEVRIT and p2.chladi is True

    # dojede pod cíl, až na 21,0
    p3 = Pamet(otevreno=True, cas_povelu_s=0, chladi=True, rezim="komfort",
               komfort_start=24.6)
    r3 = rozhodni(stary(co2=500, t_in=21.3, t_in_max=21.5, t_out=18.0,
                        rh_out=50.0, cil=22.0, hodina=14.0), p3, nast)
    assert r3.akce is not Akce.ZAVRIT

    p4 = Pamet(otevreno=True, cas_povelu_s=0, chladi=True, rezim="komfort",
               komfort_start=24.6)
    r4 = rozhodni(stary(co2=500, t_in=20.8, t_in_max=20.9, t_out=18.0,
                        rh_out=50.0, cil=22.0, hodina=14.0), p4, nast)
    assert r4.akce is Akce.ZAVRIT


def test_pasmo_muze_byt_nesoumerne():
    """Zavírací hodnota smí být nula: pak se dojede přesně na cíl."""
    from core import Nastaveni as N_
    nast = N_(hyst_den_otevrit=3.0, hyst_den_zavrit=0.0)
    p = Pamet(otevreno=True, cas_povelu_s=0, chladi=True, rezim="komfort",
              komfort_start=25.5)
    r = rozhodni(stary(co2=500, t_in=22.1, t_in_max=22.3, t_out=18.0,
                       rh_out=50.0, cil=22.0, hodina=14.0), p, nast)
    assert r.akce is not Akce.ZAVRIT      # ještě nad cílem

    p2 = Pamet(otevreno=True, cas_povelu_s=0, chladi=True, rezim="komfort",
               komfort_start=25.5)
    r2 = rozhodni(stary(co2=500, t_in=21.8, t_in_max=21.9, t_out=18.0,
                        rh_out=50.0, cil=22.0, hodina=14.0), p2, nast)
    assert r2.akce is Akce.ZAVRIT


def test_noc_ma_vlastni_pasmo():
    """V noci se obvykle nastavuje širší pásmo, aby okno nejezdilo."""
    from core import Nastaveni as N_
    nast = N_(hyst_den_otevrit=1.0, hyst_noc_otevrit=4.0)

    # ve dne by se při 23,2 už chladilo
    p = Pamet(cas_povelu_s=0)
    rozhodni(stary(co2=500, t_in=23.0, t_in_max=23.2, t_out=18.0,
                   rh_out=50.0, cil=22.0, hodina=14.0), p, nast)
    assert p.chladi is True

    # v noci je hrana na 26,0, takže se nechladí
    p2 = Pamet(cas_povelu_s=0)
    rozhodni(stary(co2=500, t_in=23.0, t_in_max=23.2, t_out=18.0,
                   rh_out=50.0, cil=22.0, hodina=2.0), p2, nast)
    assert p2.chladi is False


def test_pojistka_zavre_at_je_duvod_jakykoli():
    """Větrání kvůli CO2 čeká na vyvětrání; o prochladnutí se stará
    pojistka, ne hrana pásma."""
    from core import Nastaveni as N_
    nast = N_(mez_dolni=18.0)
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz", vetra_se=True)
    r = rozhodni(stary(co2=1200, t_in=17.8, t_in_max=18.0, t_out=5.0,
                       rh_out=50.0, cil=21.0, hodina=14.0), p, nast)
    assert r.akce is Akce.ZAVRIT and r.kod == "pojistka"
    assert "17.8" in r.duvod


def test_pojistka_proti_prehrati():
    from core import Nastaveni as N_
    nast = N_(mez_horni=27.0)
    p = Pamet(otevreno=True, cas_povelu_s=0)
    r = rozhodni(stary(co2=500, t_in=26.5, t_in_max=27.5, t_out=31.0,
                       rh_out=30.0, cil=25.5, hodina=14.0), p, nast)
    assert r.akce is Akce.ZAVRIT and r.kod == "pojistka"


def test_pojistka_nezavre_okno_ktere_pomaha():
    """Zavřít okno, které zrovna chladí přehřátý pokoj, by bylo proti
    smyslu — pojistka chrání před větráním, ne před teplotou."""
    from core import Nastaveni as N_
    nast = N_(mez_horni=27.0, hyst_den_otevrit=1.5)
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(stary(co2=500, t_in=26.5, t_in_max=27.5, t_out=21.0,
                       rh_out=50.0, cil=25.5, hodina=14.0), p, nast)
    assert r.akce is Akce.OTEVRIT and p.chladi is True


def test_pojistku_obejde_jen_rucni_zadost():
    from core import Nastaveni as N_
    nast = N_(mez_dolni=18.0)
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz", vetra_se=True)
    r = rozhodni(stary(co2=1400, t_in=17.0, t_in_max=17.2, t_out=5.0,
                       rh_out=50.0, cil=21.0, hodina=14.0, vetrat=True),
                 p, nast)
    assert r.akce is not Akce.ZAVRIT


def test_vetrani_kvuli_co2_ceka_na_vyvetrani():
    """Dřív se zavíralo na dolní hraně i s dusnem a hned se otevíralo
    znovu."""
    from core import Nastaveni as N_
    nast = N_(mez_dolni=15.0, hyst_den_zavrit=1.0)
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="pulz", vetra_se=True)
    r = rozhodni(stary(co2=1200, t_in=19.5, t_in_max=19.7, t_out=5.0,
                       rh_out=50.0, cil=21.0, hodina=14.0), p, nast)
    assert r.akce is not Akce.ZAVRIT
    assert "větrá se" in r.duvod


def test_pro_pohodu_se_da_vypnout():
    """Vypnutím se okno bude otevírat jen z důvodu."""
    from core import Nastaveni as N_
    nast = N_(pro_pohodu=False)
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="komfort",
              komfort_start=21.8)
    r = rozhodni(stary(co2=500, t_in=21.8, t_in_max=22.0, t_out=20.5,
                       rh_out=50.0, cil=22.0, hodina=14.0), p, nast)
    assert r.akce is Akce.ZAVRIT
    assert "pro pohodu se neotvírá" in r.duvod

    # zapnuté to otevře
    p2 = Pamet(cas_povelu_s=0)
    r2 = rozhodni(stary(co2=500, t_in=21.8, t_in_max=22.0, t_out=20.5,
                        rh_out=50.0, cil=22.0, hodina=14.0), p2, N_())
    assert r2.akce is Akce.OTEVRIT


def test_stupnice_ukaze_pasmo_i_pojistky():
    """U každé hrany je napsané, které nastavení ji určuje."""
    from core import pasmo_text
    t = "\n".join(pasmo_text(22.0, 23.0, 2.5, 1.0, 18.0, 27.0,
                             otevreno=False, t_max=23.2))
    assert "pojistka „nepřehřát nad“" in t
    assert "pojistka „nevychladit pod“" in t
    assert "„ve dne otevřít“" in t
    assert "„ve dne zavřít“" in t
    assert "cíl" in t


def test_stupnice_v_noci_mluvi_o_nocnim_pasmu():
    from core import pasmo_text
    t = "\n".join(pasmo_text(22.0, 21.0, 4.0, 1.5, 18.0, 27.0,
                             otevreno=False, noc=True, t_max=21.2))
    assert "„v noci otevřít“" in t and "„v noci zavřít“" in t


# ============ doplněné pokrytí nového modelu ============

def test_ohrev_dojede_nad_cil():
    """Zrcadlově k chlazení: ohřev končí nad cílem, ne na něm."""
    from core import Nastaveni as N_
    nast = N_(hyst_den_otevrit=2.5, hyst_den_zavrit=1.0)
    # cíl 22 → ohřívat od 19,5, dojet na 23,0, venku aspoň 25,0 + rezerva

    p = Pamet(cas_povelu_s=0)
    r = rozhodni(stary(co2=500, t_in=19.2, t_in_max=19.4, t_out=25.5,
                       rh_out=50.0, cil=22.0, hodina=14.0), p, nast)
    assert r.akce is Akce.OTEVRIT and p.ohrivam is True

    p2 = Pamet(otevreno=True, cas_povelu_s=0, ohrivam=True,
               rezim="komfort", komfort_start=19.4)
    r2 = rozhodni(stary(co2=500, t_in=22.5, t_in_max=22.7, t_out=25.5,
                        rh_out=50.0, cil=22.0, hodina=14.0), p2, nast)
    assert r2.akce is not Akce.ZAVRIT      # ještě pod horní hranou

    p3 = Pamet(otevreno=True, cas_povelu_s=0, ohrivam=True,
               rezim="komfort", komfort_start=19.4)
    r3 = rozhodni(stary(co2=500, t_in=23.2, t_in_max=23.4, t_out=25.5,
                        rh_out=50.0, cil=22.0, hodina=14.0), p3, nast)
    assert r3.akce is Akce.ZAVRIT


def test_ve_spanku_rozhoduje_jen_co2():
    """Teplota okno ve spánku neotvírá ani nezavírá; drží ji pojistky."""
    from core import Nastaveni as N_
    nast = N_(mez_dolni=16.0, co2_noc_krize=1250.0, co2_zavrit=700.0)

    # běžné dusno neotevře
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(stary(co2=1100, t_in=21.0, t_in_max=21.2, t_out=10.0,
                       cil=21.0, hodina=3.0, spanek=True), p, nast)
    assert r.akce is not Akce.OTEVRIT

    # krize ano
    p2 = Pamet(cas_povelu_s=0)
    r2 = rozhodni(stary(co2=1400, t_in=21.0, t_in_max=21.2, t_out=10.0,
                        cil=21.0, hodina=3.0, spanek=True), p2, nast)
    assert r2.akce is Akce.OTEVRIT

    # a zavře se po vyvětrání, ne na nočním prahu
    p3 = Pamet(otevreno=True, cas_povelu_s=0, rezim="noc", vetra_se=True)
    r3 = rozhodni(stary(co2=900, t_in=20.0, t_in_max=20.2, t_out=10.0,
                        cil=21.0, hodina=3.0, spanek=True), p3, nast)
    assert r3.akce is not Akce.ZAVRIT

    p4 = Pamet(otevreno=True, cas_povelu_s=0, rezim="noc", vetra_se=True)
    r4 = rozhodni(stary(co2=650, t_in=20.0, t_in_max=20.2, t_out=10.0,
                        cil=21.0, hodina=3.0, spanek=True), p4, nast)
    assert r4.akce is Akce.ZAVRIT and "vyvětráno" in r4.duvod


def test_v_noci_bez_spanku_otevira_nocni_prah():
    from core import Nastaveni as N_
    nast = N_(co2_noc=1000.0, mez_dolni=16.0)
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(stary(co2=1100, t_in=21.0, t_in_max=21.2, t_out=10.0,
                       cil=21.0, hodina=3.0), p, nast)
    assert r.akce is Akce.OTEVRIT

    p2 = Pamet(cas_povelu_s=0)
    r2 = rozhodni(stary(co2=900, t_in=21.0, t_in_max=21.2, t_out=10.0,
                        cil=21.0, hodina=3.0), p2, nast)
    assert r2.akce is not Akce.OTEVRIT


def test_pojistka_plati_i_ve_spanku():
    """Jedna hodnota bez výjimky — dřív se ve spánku zavíralo jinde."""
    from core import Nastaveni as N_
    nast = N_(mez_dolni=18.0)
    p = Pamet(otevreno=True, cas_povelu_s=0, rezim="noc", vetra_se=True)
    r = rozhodni(stary(co2=1400, t_in=17.5, t_in_max=17.7, t_out=2.0,
                       cil=21.0, hodina=3.0, spanek=True), p, nast)
    assert r.akce is Akce.ZAVRIT and r.kod == "pojistka"


def test_pojistka_nebrani_ohrevu_zdola():
    """Pod spodní mezí při teplejším venku je otevření to, co pomůže."""
    from core import Nastaveni as N_
    nast = N_(mez_dolni=18.0)
    p = Pamet(cas_povelu_s=0)
    r = rozhodni(stary(co2=500, t_in=17.0, t_in_max=17.2, t_out=25.0,
                       rh_out=40.0, cil=21.0, hodina=14.0), p, nast)
    assert r.akce is Akce.OTEVRIT and p.ohrivam is True


def test_stupnice_jmenuje_soupatka():
    """Bez toho se v pěti číslech kolem cíle nikdo nevyzná."""
    from core import pasmo_jen_stupnice, pasmo_text
    radky = pasmo_jen_stupnice(pasmo_text(
        22.0, 23.0, 2.5, 1.0, 18.0, 27.0, otevreno=False, t_max=23.2))
    t = "\n".join(radky)
    assert "„ve dne otevřít“" in t and "„ve dne zavřít“" in t
    assert "pojistka „nepřehřát nad“" in t
    assert "pojistka „nevychladit pod“" in t
    # a pořád se to vejde do řádku
    for radek in radky:
        assert len(radek) <= 45, radek


def test_narazovy_rezim_nebrani_teplotnimu_vetrani():
    """Zakazuje jen otevírání pro pohodu, takže mezi překážky
    teplotního větrání nepatří."""
    from core import Nastaveni as N_, proc_neotevira
    nast = N_(narazove_odstup=6.0)
    v = Vstup(co2=641, t_in=23.2, t_in_max=23.4, t_out=12.0, rh_out=50.0,
              cil=22.2, cas_s=1)
    assert proc_neotevira(v, nast, 23.2, 23.4) == ""


def test_vzduch_musi_byt_za_dojezdem():
    """Bez rezervy se cyklus doplazí k hraně a nikdy ji nepřejde,
    takže větrání dojezd nedokončí a jen vystydne."""
    from core import Nastaveni as N_
    nast = N_(hyst_den_otevrit=2.5, hyst_den_zavrit=1.0,
              rezerva_venku=2.0)
    # cíl 22 → dojezd 21,0 → venku musí být pod 19,0

    def chladi(t_out):
        p = Pamet(cas_povelu_s=0)
        rozhodni(stary(co2=500, t_in=24.4, t_in_max=24.8, t_out=t_out,
                       rh_out=50.0, cil=22.0, hodina=14.0), p, nast)
        return p.chladi

    assert chladi(20.0) is False      # pod dojezdem, ale bez rezervy
    assert chladi(19.5) is False
    assert chladi(18.5) is True

    # bez rezervy stačí být pod dojezdem
    bez = N_(hyst_den_otevrit=2.5, hyst_den_zavrit=1.0, rezerva_venku=0.0)
    p = Pamet(cas_povelu_s=0)
    rozhodni(stary(co2=500, t_in=24.4, t_in_max=24.8, t_out=20.5,
                   rh_out=50.0, cil=22.0, hodina=14.0), p, bez)
    assert p.chladi is True


def test_rezerva_plati_i_pro_ohrev():
    from core import Nastaveni as N_
    nast = N_(hyst_den_otevrit=2.5, hyst_den_zavrit=1.0,
              rezerva_venku=2.0)
    # cíl 22 → dojezd 23,0 → venku musí být nad 25,0

    def ohriva(t_out):
        p = Pamet(cas_povelu_s=0)
        rozhodni(stary(co2=500, t_in=19.2, t_in_max=19.4, t_out=t_out,
                       rh_out=40.0, cil=22.0, hodina=14.0), p, nast)
        return p.ohrivam

    assert ohriva(24.0) is False
    assert ohriva(25.5) is True
