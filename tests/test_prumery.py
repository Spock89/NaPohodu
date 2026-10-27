"""Testy klouzavých průměrů."""

import math

from prumery import TAU_TRI_DNY_H, TAU_TYDEN_H, Prumery

H = 3600.0


def test_prvni_mereni_nastavi_oba():
    p = Prumery()
    p.aktualizuj(12.0, 0)
    assert p.tyden == p.tri_dny == 12.0


def test_tridenni_reaguje_rychleji():
    """Po ochlazení se třídenní průměr přiblíží dřív než týdenní."""
    p = Prumery()
    p.aktualizuj(20.0, 0)
    for h in range(1, 49):
        p.aktualizuj(5.0, h * H)
    assert p.tri_dny < p.tyden
    assert 5.0 < p.tri_dny < 20.0


def test_ustali_se_na_konstantni_teplote():
    p = Prumery()
    p.aktualizuj(20.0, 0)
    for h in range(1, 24 * 30):
        p.aktualizuj(8.0, h * H)
    assert abs(p.tyden - 8.0) < 0.2
    assert abs(p.tri_dny - 8.0) < 0.05


def test_dlouhy_vypadek_zacne_znovu():
    p = Prumery()
    p.aktualizuj(20.0, 0)
    p.aktualizuj(2.0, 30 * 24 * H)
    assert p.tyden == p.tri_dny == 2.0


def test_krok_zpet_v_case_nic_nezmeni():
    p = Prumery()
    p.aktualizuj(20.0, 100 * H)
    p.aktualizuj(5.0, 50 * H)
    assert p.tyden == 20.0


def test_vaha_odpovida_case():
    """Za jeden časový úsek tau se rozdíl zmenší zhruba na třetinu."""
    p = Prumery()
    p.aktualizuj(0.0, 0)
    p.aktualizuj(10.0, TAU_TRI_DNY_H * H)
    ocekavane = 10.0 * (1 - math.exp(-1))
    assert abs(p.tri_dny - ocekavane) < 0.01


def test_prezije_ulozeni():
    p = Prumery()
    p.aktualizuj(14.0, 0)
    p.aktualizuj(9.0, 24 * H)
    q = Prumery.ze_slovniku(p.jako_slovnik())
    assert q.tyden == p.tyden and q.tri_dny == p.tri_dny


def test_prazdny_slovnik_da_cisty_stav():
    q = Prumery.ze_slovniku(None)
    assert q.tyden is None


def test_mlady_prumer_se_nenese_z_prvniho_cteni():
    """Exponenciální průměr se nasazuje z jediného prvního čtení.

    Kdo integraci spustí v babím létě, nesl by si dvacet stupňů
    v průměru i do listopadu — a cíl s ním, protože křivka z průměru
    počítá. Dokud je mladý, platí obyčejný průměr všeho naměřeného.
    """
    p = Prumery()
    p.aktualizuj(20.0, 0.0)                 # teplý den při zapnutí
    for h in range(1, 3 * 24):              # pak dva dny zimy
        p.aktualizuj(8.0, h * 3600.0)

    cas = 3 * 24 * 3600.0
    assert not p.usazeny(cas)
    # exponenciální si teplo pořád nese, obyčejný průměr už ne
    assert p.tyden > 15.0
    pouzit = p.tyden_pouzitelny(cas)
    assert pouzit < 12.0, pouzit
    # a je to opravdu obyčejný průměr naměřeného
    assert abs(pouzit - p.soucet / p.doba_h) < 0.01


def test_usazeny_prumer_uz_plati_sam():
    """Po třech časových konstantách se přechází na exponenciální: ten
    na rozdíl od obyčejného zapomíná, takže po měsíci provozu nemluví
    pořád o létě."""
    p = Prumery()
    p.aktualizuj(20.0, 0.0)
    for h in range(1, 22 * 24):
        p.aktualizuj(8.0, h * 3600.0)

    cas = 22 * 24 * 3600.0
    assert p.usazeny(cas)
    assert p.tyden_pouzitelny(cas) == p.tyden
    # přechod není poznat: obě čísla už jsou u sebe
    assert abs(p.tyden - p.soucet / p.doba_h) < 0.6


def test_prechod_bez_skoku():
    """Kdyby se přepínalo po jedné konstantě, cíl by v sedmý den
    o stupeň poskočil zpátky nahoru — přesně tomu se tu předchází."""
    p = Prumery()
    minuly, nejvetsi = None, 0.0
    for h in range(40 * 24):
        p.aktualizuj(20.0 if h < 24 else 8.0, h * 3600.0)
        v = p.tyden_pouzitelny(h * 3600.0)
        cil = round(min(max(0.33 * v + 18.8, 20.0), 27.0), 1)
        if minuly is not None:
            nejvetsi = max(nejvetsi, abs(cil - minuly))
        minuly = cil
    assert nejvetsi <= 0.3, f"skok {nejvetsi} °C"


def test_zapomenuti_nasadi_znovu():
    """Jediná cesta, jak průměru říct, že se nasadil vedle."""
    p = Prumery()
    p.aktualizuj(20.0, 0.0)
    p.aktualizuj(20.0, 3600.0)
    assert p.tyden == 20.0

    p.zapomen()
    assert p.tyden is None and p.zaseto_s is None and p.doba_h == 0.0
    p.aktualizuj(8.0, 7200.0)
    assert p.tyden == 8.0 and p.tyden_pouzitelny(7200.0) == 8.0


def test_ulozeni_si_pamatuje_odkdy_se_uci():
    """Bez toho by se po restartu mladý průměr tvářil jako usazený."""
    p = Prumery()
    p.aktualizuj(20.0, 0.0)
    for h in range(1, 48):
        p.aktualizuj(8.0, h * 3600.0)

    zpet = Prumery.ze_slovniku(p.jako_slovnik())
    cas = 48 * 3600.0
    assert zpet.zaseto_s == p.zaseto_s
    assert not zpet.usazeny(cas)
    assert abs(zpet.tyden_pouzitelny(cas) - p.tyden_pouzitelny(cas)) < 0.01

    # starší zápis bez té značky se bere za usazený, ne za čerstvý
    stary = Prumery.ze_slovniku(
        {"tyden": 12.0, "tri_dny": 11.0, "cas_s": 0.0})
    assert stary.tyden_pouzitelny(99 * 86400.0) == 12.0
