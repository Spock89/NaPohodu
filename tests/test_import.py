"""Ověří, že se balíček dá naimportovat tak, jak to udělá Home Assistant.

Testy jádra chyby v propojení nechytnou, protože jádro Home Assistant
nepotřebuje. Tenhle test podstrčí náhradní Home Assistant a zkusí každý
modul skutečně naimportovat — odhalí překlepy, chybějící konstanty
i syntaktické chyby v částech, které se jinak nespustí.
"""

import importlib
import pathlib
import sys

import pytest

KOREN = pathlib.Path(__file__).parent.parent
MODULY = [
    "const", "core", "slunce", "pritomnost", "prumery", "sousedstvi",
    "sekvence", "arbiter", "vykon", "entity", "coordinator", "config_flow",
    "services", "sensor", "binary_sensor", "number", "switch", "button",
]


@pytest.fixture(scope="module", autouse=True)
def nahradni_ha():
    sys.path.insert(0, str(KOREN / "tests" / "stub_ha"))
    sys.path.insert(0, str(KOREN / "custom_components"))
    yield
    for m in list(sys.modules):
        if m.startswith(("napohodu", "homeassistant")):
            del sys.modules[m]


@pytest.mark.parametrize("modul", MODULY)
def test_modul_jde_naimportovat(modul):
    importlib.import_module(f"napohodu.{modul}")


def test_vitr_blokuje_podle_dvou_prahu(nahradni_ha):
    """Koordinátor se dá zavolat, ne jen naimportovat.

    Chyby jako „get() se třemi argumenty" se projeví až za běhu, proto
    se ta funkce zkusí na několika hodnotách.
    """
    import importlib

    ko = importlib.import_module("napohodu.coordinator")
    c = importlib.import_module("napohodu.const")

    class Falesny:
        vitr_blokuje = False
        _vitr = ko.NaPohoduCoordinator._vitr

    f = Falesny()
    g = {c.CONF_VITR_PRAH: 7.0, c.CONF_NARAZ_PRAH: 11.0, c.CONF_VITR_KLID: 5.0}

    assert f._vitr(g, vitr=3.0, naraz=4.0) is False      # klid
    assert f._vitr(g, vitr=8.0, naraz=8.0) is True       # průměr přes práh
    assert f._vitr(g, vitr=6.0, naraz=6.0) is True       # drží, hystereze
    assert f._vitr(g, vitr=2.0, naraz=2.0) is False      # povolilo
    assert f._vitr(g, vitr=3.0, naraz=12.0) is True      # náraz přes práh
    assert f._vitr({}, vitr=20.0, naraz=20.0) is True    # výchozí hodnoty
