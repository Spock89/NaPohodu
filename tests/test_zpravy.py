"""Testy hlášení."""

from zpravy import VYCHOZI, DRUHY, Hlasic


def test_prazdny_vyber_nepusti_nic():
    h = Hlasic(())
    assert h.zprava("vitr", "Kuchyně", 1000, prumer=15, naraz=15) is None


def test_posila_se_jen_zaskrtnute():
    h = Hlasic(("vitr",))
    assert h.zprava("vitr", "Kuchyně", 1000, prumer=15, naraz=15)
    assert h.zprava("vetrani", "Kuchyně", 1000, duvod="CO2 900") is None


def test_vychozi_vyber_obsahuje_ochranu():
    assert "vitr" in VYCHOZI and "dest" in VYCHOZI and "souhrn" in VYCHOZI
    assert "vetrani" not in VYCHOZI      # první dny ano, pak otravuje


def test_kazdy_druh_ma_text():
    h = Hlasic(DRUHY)
    for i, druh in enumerate(DRUHY):
        t = h.zprava(druh, "Kuchyně", i * 100000,
                     prumer=12, naraz=12, dest=1.0, co2=1300,
                     duvod="CO2 900", text="pohon mlčí", dnes={})
        assert t, druh


def test_stejna_zprava_se_neopakuje():
    """Automatika, která upozorňuje pořád, se přestane číst."""
    h = Hlasic(VYCHOZI)
    assert h.zprava("vitr", "Kuchyně", 1000, prumer=15, naraz=15)
    assert h.zprava("vitr", "Kuchyně", 1100, prumer=15, naraz=15) is None
    assert h.zprava("vitr", "Kuchyně", 1000 + 31 * 60, prumer=15, naraz=15)


def test_ruzne_druhy_se_neblokuji():
    h = Hlasic(VYCHOZI)
    assert h.zprava("vitr", "Kuchyně", 1000, prumer=15, naraz=15)
    assert h.zprava("dest", "Kuchyně", 1000, dest=2.0)


def test_text_obsahuje_mistnost_i_cislo():
    h = Hlasic(VYCHOZI)
    t = h.zprava("vitr", "Ložnice", 1000, naraz=14, prumer=8,
                 co_prekrocilo="nárazy",
                 prahy={"prumer": 9, "naraz": 11, "povoli_pod": 5})
    assert "Ložnice" in t and "14" in t and "11" in t


def test_zprava_o_vetru_uvadi_vsechna_cisla():
    """Ať se z jedné zprávy pozná, co se stalo a proti jakým prahům."""
    h = Hlasic(VYCHOZI)
    t = h.zprava("vitr", "Kuchyně", 1000, prumer=10.2, naraz=3.1,
                 co_prekrocilo="průměr",
                 prahy={"prumer": 9, "naraz": 11, "povoli_pod": 5})
    assert "10.2" in t and "3.1" in t
    assert "9" in t and "11" in t and "5" in t


def test_zprava_o_vetru_pri_hysterezi():
    h = Hlasic(VYCHOZI)
    t = h.zprava("vitr", "Kuchyně", 1000, prumer=6.0, naraz=7.0,
                 co_prekrocilo="hystereze",
                 prahy={"prumer": 9, "naraz": 11, "povoli_pod": 5})
    assert "neklesl" in t


def test_zprava_o_vetru_bez_podrobnosti_nespadne():
    h = Hlasic(VYCHOZI)
    assert h.zprava("vitr", "Kuchyně", 1000)


def test_souhrn_shrne_den():
    h = Hlasic(VYCHOZI)
    t = h.zprava("souhrn", "Kuchyně", 1000,
                 dnes={"pohyby": 4, "otevreno_min": 95, "co2_max": 1180,
                       "nejnizsi_teplota": 19.4})
    assert "4x" in t and "95" in t and "1180" in t


def test_neznamy_druh_nespadne():
    h = Hlasic(DRUHY)
    assert h.zprava("cosi", "Kuchyně", 1000) is None
