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
