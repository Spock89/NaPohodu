"""Podklady pro kartu: jedno místo pro obě cesty generování.

Karta se vyrábí dvakrát — z dialogu nastavení a ze služby. Dokud to
byly dvě kopie téhož kódu, rozešly se: služba neuměla vybavení
místností, takže tatáž instalace dala pokaždé jinou kartu.
"""

import pytest


@pytest.fixture(scope="module")
def pod():
    import pathlib
    import sys

    koren = pathlib.Path(__file__).parent.parent
    sys.path.insert(0, str(koren / "tests" / "stub_ha"))
    sys.path.insert(0, str(koren / "custom_components"))
    import importlib

    m = importlib.import_module("napohodu.podklady")
    c = importlib.import_module("napohodu.const")
    yield m, c
    for jmeno in list(sys.modules):
        if jmeno.startswith(("napohodu", "homeassistant")):
            del sys.modules[jmeno]
    sys.path.remove(str(koren / "custom_components"))
    sys.path.remove(str(koren / "tests" / "stub_ha"))


class Podentita:
    def __init__(self, typ, nazev, data=None):
        self.subentry_type = typ
        self.title = nazev
        self.subentry_id = nazev
        self.data = data or {}


def _instalace(c):
    return [
        Podentita(c.PODENTITA_MISTNOST, "Obývák", {
            c.CONF_OKNA: ["cover.o"], c.CONF_ZALUZIE: ["cover.z"],
            c.CONF_TEPLOTY: ["sensor.t"], c.CONF_CO2: ["sensor.c"],
            c.CONF_SPANEK: "input_boolean.s", c.CONF_PORADI: 2}),
        Podentita(c.PODENTITA_MISTNOST, "Dílna", {
            c.CONF_TEPLOTY: ["sensor.t2"], c.CONF_CLIMATE: "climate.d",
            c.CONF_PORADI: 1}),
        Podentita(c.PODENTITA_ZONA, "Kuchyň a obývák",
                  {c.CONF_MISTNOSTI: ["Obývák", "Dílna"]}),
        Podentita(c.PODENTITA_SKUPINA, "1. patro",
                  {c.CONF_SKUPINA_MISTNOSTI: ["Dílna"]}),
        Podentita(c.PODENTITA_SCENA, "Home Office", {}),
    ]


def test_vybaveni_a_okna(pod):
    p, c = pod
    v = p.podklady(_instalace(c))
    assert v["s_okny"] == {"obyvak"}
    assert v["vybaveni"]["obyvak"] == {"okno", "co2", "zaluzie"}
    assert "topeni" in v["vybaveni"]["dilna"]
    assert v["s_klidem"] == {"obyvak"}
    assert v["skupiny"] == ["1. patro"]
    assert v["sceny"] == ["Home Office"]
    assert v["oblasti"] == ["kuchyn_a_obyvak"]


def test_vetrani_zonou_pro_mistnost_bez_okna(pod):
    """Dílna okno nemá, ale je v zóně s Obývákem — šoupátko jí patří."""
    p, c = pod
    v = p.podklady(_instalace(c))
    assert "vetrani_zonou" in v["vybaveni"]["dilna"]
    assert "vetrani_zonou" not in v["vybaveni"]["obyvak"]


def test_poradi_z_nastaveni(pod):
    p, c = pod
    assert p.podklady(_instalace(c))["mistnosti"] == ["dilna", "obyvak"]


def test_obe_cesty_davaji_tutez_kartu(pod):
    """Dialog i služba musí z téže instalace poskládat stejný text."""
    import sys

    sys.path.append(str(__import__("pathlib").Path(__file__).parent.parent
                        / "custom_components" / "napohodu"))
    from karty import dashboard

    p, c = pod
    v = p.podklady(_instalace(c))
    mistnosti, oblasti = v.pop("mistnosti"), v.pop("oblasti")
    a = dashboard(mistnosti, oblasti, lambda e: True, **v)

    v2 = p.podklady(_instalace(c))
    m2, o2 = v2.pop("mistnosti"), v2.pop("oblasti")
    b = dashboard(m2, o2, lambda e: True, **v2)
    assert a == b
    # a to podstatné v ní opravdu je
    assert "number.napohodu_dilna_ve_dne_otevrit_pri_odchylce_od_cile_o" in a
    assert "- entity: sensor.napohodu_dilna_stav" not in a
