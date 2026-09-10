"""Testy hlášení."""

from zpravy import UROVEN_DULEZITE, UROVEN_NIC, UROVEN_VSE, Hlasic


def test_uroven_nic_nepusti_nic():
    h = Hlasic(UROVEN_NIC)
    assert h.zprava("vitr", "Kuchyně", 1000, naraz=15) is None


def test_dulezite_pusti_ochranu_ne_bezne_vetrani():
    h = Hlasic(UROVEN_DULEZITE)
    assert h.zprava("vitr", "Kuchyně", 1000, naraz=15)
    assert h.zprava("vetrani", "Kuchyně", 1000, duvod="CO2 900") is None


def test_vse_pusti_i_vetrani():
    h = Hlasic(UROVEN_VSE)
    assert h.zprava("vetrani", "Kuchyně", 1000, duvod="CO2 900")


def test_stejna_zprava_se_neopakuje():
    """Automatika, která upozorňuje pořád, se přestane číst."""
    h = Hlasic(UROVEN_DULEZITE)
    assert h.zprava("vitr", "Kuchyně", 1000, naraz=15)
    assert h.zprava("vitr", "Kuchyně", 1100, naraz=15) is None
    assert h.zprava("vitr", "Kuchyně", 1000 + 31 * 60, naraz=15)


def test_ruzne_druhy_se_neblokuji():
    h = Hlasic(UROVEN_DULEZITE)
    assert h.zprava("vitr", "Kuchyně", 1000, naraz=15)
    assert h.zprava("dest", "Kuchyně", 1000, dest=2.0)


def test_text_obsahuje_mistnost_i_cislo():
    h = Hlasic(UROVEN_DULEZITE)
    t = h.zprava("vitr", "Ložnice", 1000, naraz=14)
    assert "Ložnice" in t and "14" in t


def test_souhrn_shrne_den():
    h = Hlasic(UROVEN_DULEZITE)
    t = h.zprava("souhrn", "Kuchyně", 1000,
                 dnes={"pohyby": 4, "otevreno_min": 95, "co2_max": 1180,
                       "nejnizsi_teplota": 19.4})
    assert "4x" in t and "95" in t and "1180" in t


def test_neznamy_druh_nespadne():
    h = Hlasic(UROVEN_VSE)
    assert h.zprava("cosi", "Kuchyně", 1000) is None
