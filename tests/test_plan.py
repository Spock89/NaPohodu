"""Testy plánu obsazenosti."""

from plan import Udalost, konci_do, popis, predvetrat, slouc

HODINA = 3600.0
TED = 100000.0


def test_slouc_staci_jeden_zdroj():
    """Kalendář i rozvrh můžou běžet oba; stačí jeden, aby to platilo."""
    u = slouc([Udalost(bezi=False, od_s=TED + HODINA),
               Udalost(bezi=True, do_s=TED + 2 * HODINA)])
    assert u.bezi and u.do_s == TED + 2 * HODINA


def test_slouc_bere_pozdejsi_konec():
    """Jinak by útlum skončil podle toho, který zdroj skončí první."""
    u = slouc([Udalost(bezi=True, do_s=TED + HODINA),
               Udalost(bezi=True, do_s=TED + 5 * HODINA)])
    assert u.do_s == TED + 5 * HODINA


def test_slouc_bez_znameho_konce_nelze_planovat():
    """Když u jednoho běžícího konec neznáme, neumíme říct, kdy to
    skončí — a vymyslet si ho by znamenalo nahřívat naslepo."""
    u = slouc([Udalost(bezi=True, do_s=TED + HODINA),
               Udalost(bezi=True, do_s=None)])
    assert u.bezi and u.do_s is None


def test_slouc_ceka_na_nejblizsi_zacatek():
    u = slouc([Udalost(od_s=TED + 5 * HODINA), Udalost(od_s=TED + HODINA)])
    assert not u.bezi and u.od_s == TED + HODINA


def test_slouc_bez_zdroju():
    assert slouc([]) == Udalost()


def test_predvetrani_jen_v_predstihu():
    vic = Udalost(od_s=TED + 30 * 60)
    assert predvetrat(vic, TED, 60) is True      # začne za půl hodiny
    assert predvetrat(vic, TED, 15) is False     # ještě je brzy
    assert predvetrat(vic, TED, 0) is False      # nula vypíná


def test_predvetrani_neplati_kdyz_uz_bezi():
    """Při běžící návštěvě se větrá podle CO2, ne podle předstihu."""
    assert predvetrat(Udalost(bezi=True), TED, 60) is False
    assert predvetrat(Udalost(), TED, 60) is False   # nic se nechystá


def test_navrat_ukonci_utlum_s_predstihem():
    """Náběh musí začít dřív, než se lidi vrátí."""
    nikdo = Udalost(bezi=True, do_s=TED + 40 * 60)
    assert konci_do(nikdo, TED, 60) is True
    assert konci_do(nikdo, TED, 30) is False
    # bez známého konce se neplánuje a útlum platí dál
    assert konci_do(Udalost(bezi=True), TED, 60) is False


def test_popis_rika_co_plati_a_dokdy():
    assert popis(Udalost(bezi=True, do_s=TED + 2 * HODINA),
                 Udalost(), TED).startswith("nikdo doma, ještě 120 min")
    assert "víc lidí za 30 min" in popis(
        Udalost(), Udalost(od_s=TED + 30 * 60), TED)
    # bez plánu nic, ať se řádek v kartě schová
    assert popis(Udalost(), Udalost(), TED) is None


def test_popis_nehlasi_udalosti_z_pristiho_tydne():
    """Zajímá nás, co se chystá dnes, ne co je za pět dní."""
    assert popis(Udalost(), Udalost(od_s=TED + 100 * HODINA), TED) is None
