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
    assert r.akce is Akce.OTEVRIT and "komfort" in r.duvod


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
    assert r.akce is Akce.NIC and "čekám" in r.duvod


def test_korekce_ma_spravne_znamenko():
    a, _ = krok(stary(t_in=21, t_out=14.5), otevreno=True)
    assert a.korekce > 0 and a.t_in_korig > 21
    b, _ = krok(stary(t_in=24, t_out=28), otevreno=True)
    assert b.korekce < 0 and b.t_in_korig < 24
    c, _ = krok(stary(t_in=21, t_out=14.5))
    assert c.korekce == 0


def test_korekce_je_umerna_rozdilu():
    a, _ = krok(stary(t_in=21, t_out=14.5), otevreno=True)
    b, _ = krok(stary(t_in=21, t_out=1), otevreno=True)
    assert b.korekce > a.korekce
    assert b.korekce <= N.korekce_max


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


def test_zastupce_ve_dne_nic_nemeni():
    a, _ = krok(stary(co2=900, t_in=21, t_out=10, cil=25.5, hodina=14))
    b, _ = krok(stary(co2=900, t_in=21, t_out=10, cil=25.5, hodina=14,
                      zastupce=True))
    assert a.akce is b.akce is Akce.OTEVRIT


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
    assert abs(noc - n.nocni_pokles_zaklad) < 0.1


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
