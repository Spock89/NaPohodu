"""Náběhová křivka: za jak dlouho se místnost nahřeje o kolik."""

import pytest

from naber import DOST_VZORKU, Mereni, Naber, prihradka


def test_prihradky_podle_venku():
    assert prihradka(-18.0) == 0
    assert prihradka(0.0) == 4
    assert prihradka(18.0) == 7
    # mimo rozsah se nespadne, jen se přilepí ke kraji
    assert prihradka(-40.0) == 0
    assert prihradka(40.0) == 7


def test_bez_dat_netvrdi_nic():
    """Hádat rychlost z ničeho by znamenalo plánovat příchod podle
    výmyslu. Volající pak sáhne po pevném předstihu."""
    n = Naber()
    assert n.rychlost(0.0) is None
    assert n.predstih_s(2.0, 0.0, strop_s=4 * 3600) is None
    assert n.naucene() == 0


def test_nauci_se_a_spocita_predstih():
    n = Naber()
    for _ in range(DOST_VZORKU):
        assert n.zapis(1.0, t_out=0.0)
    assert n.rychlost(0.0) == pytest.approx(1.0)
    # dva stupně při jednom za hodinu jsou dvě hodiny
    assert n.predstih_s(2.0, 0.0, strop_s=8 * 3600) == pytest.approx(7200)


def test_strop_drzi_pomalou_mistnost():
    """Bez stropu by jedna pomalá místnost začala topit od rána."""
    n = Naber()
    for _ in range(DOST_VZORKU):
        n.zapis(0.25, t_out=-15.0)
    assert n.predstih_s(3.0, -15.0, strop_s=4 * 3600) == 4 * 3600


def test_nesmysly_se_zahazuji():
    """Naměřit se dá leccos, ale nahřívání to být nemusí: pod dolní
    mezí je to šum čidla, nad horní otevřené okno nebo slunce."""
    n = Naber()
    assert not n.zapis(0.05, t_out=0.0)
    assert not n.zapis(20.0, t_out=0.0)
    assert n.rychlost(0.0) is None


def test_jeden_vzorek_nestaci():
    """Jeden může být náhoda — třeba se topilo do pokoje plného lidí."""
    n = Naber()
    n.zapis(1.0, t_out=0.0)
    assert n.rychlost(0.0) is None


def test_sousedni_prihradka_kdyz_vlastni_nic_nevi():
    """Pět stupňů vedle je pořád blíž pravdě než pevné číslo, které
    o venku neví nic."""
    n = Naber()
    for _ in range(DOST_VZORKU):
        n.zapis(0.8, t_out=-12.0)
    assert n.rychlost(-12.0) == pytest.approx(0.8)
    assert n.rychlost(-3.0) == pytest.approx(0.8)
    # a bere se ta bližší z obou stran
    for _ in range(DOST_VZORKU):
        n.zapis(2.0, t_out=12.0)
    assert n.rychlost(8.0) == pytest.approx(2.0)


def test_prumer_se_uci_a_pak_ustali():
    """Pokoj po výměně oken se chová jinak a modul se má přizpůsobit,
    ale jeden divný den nesmí přepsat celou zimu."""
    n = Naber()
    for _ in range(10):
        n.zapis(1.0, t_out=0.0)
    pred = n.rychlost(0.0)
    n.zapis(3.0, t_out=0.0)
    po = n.rychlost(0.0)
    assert pred < po < 2.0


def test_ulozeni_a_nacteni():
    n = Naber()
    for _ in range(DOST_VZORKU):
        n.zapis(1.4, t_out=5.0)
    zpet = Naber.nacti(n.uloz())
    assert zpet.rychlost(5.0) == pytest.approx(n.rychlost(5.0))


def test_pokazeny_zaznam_nezabrani_startu():
    """Spadnout kvůli uložené hodnotě by znamenalo, že integrace
    nenastartuje — kvůli něčemu, co se dá naměřit znovu."""
    for spatne in (None, {}, {"rychlosti": "ne"},
                   {"rychlosti": [1.0], "vzorky": [1]},
                   {"rychlosti": ["a"] * 8, "vzorky": [1] * 8}):
        assert Naber.nacti(spatne).naucene() == 0


def test_mereni_zahodi_kratke_useky():
    """Za minutu přibude setina stupně, což je pod rozlišením čidla."""
    m = Mereni(od_s=0.0, od_t=20.0, t_out=0.0)
    assert m.vyhodnot(cas_s=300, t_in=20.1) is None     # krátké
    assert m.vyhodnot(cas_s=3600, t_in=20.1) is None    # malý rozdíl
    assert m.vyhodnot(cas_s=3600, t_in=21.0) == pytest.approx(1.0)
