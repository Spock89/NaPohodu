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
    "sekvence", "vykon", "entity", "coordinator", "config_flow",
    "services", "sensor", "binary_sensor", "number", "switch", "button",
    "karty", "zpravy", "klima",
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


# ------------------------------------------------- zakládání entit

class FalesnaPodentita:
    def __init__(self, typ, nazev, data=None):
        self.subentry_type = typ
        self.subentry_id = f"id_{nazev}"
        self.title = nazev
        self.data = data or {}


class FalesnyEntry:
    def __init__(self, podentity):
        self.entry_id = "entry"
        self.data = {}
        self.options = {}
        self.subentries = {p.subentry_id: p for p in podentity}


def _entity_platformy(modul, podentity):
    """Spustí zakládání entit a vrátí, co vzniklo."""
    import asyncio
    import importlib

    m = importlib.import_module(f"napohodu.{modul}")
    const = importlib.import_module("napohodu.const")
    entry = FalesnyEntry(podentity)

    class FalesnyHass:
        data = {const.DOMAIN: {"entry": object()}}

    vznikle = []

    def pridat(seznam, config_subentry_id=None):
        vznikle.extend(seznam)

    asyncio.run(m.async_setup_entry(FalesnyHass(), entry, pridat))
    return vznikle


def _klice(entity):
    return sorted(e._attr_translation_key for e in entity)


def test_mistnost_dostane_vsechny_prepinace(nahradni_ha):
    """Přepínače ovládání jsou entity, ne konfigurace. Když jeden chybí,
    uživatel nemá čím automatiku povolit."""
    import importlib
    const = importlib.import_module("napohodu.const")
    pod = FalesnaPodentita(const.PODENTITA_MISTNOST, "Kuchyne")
    assert _klice(_entity_platformy("switch", [pod])) == [
        "ovladat_okno", "ovladat_stineni", "ovladat_topeni"]


def test_klima_dostane_svuj_prepinac(nahradni_ha):
    import importlib
    const = importlib.import_module("napohodu.const")
    pod = FalesnaPodentita(const.PODENTITA_KLIMA, "Klima")
    assert _klice(_entity_platformy("switch", [pod])) == ["ovladat_klimu"]


def test_mistnost_dostane_tlacitka(nahradni_ha):
    import importlib
    const = importlib.import_module("napohodu.const")
    pod = FalesnaPodentita(const.PODENTITA_MISTNOST, "Kuchyne")
    klice = _klice(_entity_platformy("button", [pod]))
    assert "srovnat_okno" in klice and "srovnat_stineni" in klice


def test_tlacitka_stineni_jen_pro_prirazene_role(nahradni_ha):
    """Tlačítko, které nic nedělá, by jen zaplevelilo kartu."""
    import importlib
    const = importlib.import_module("napohodu.const")
    bez = FalesnaPodentita(const.PODENTITA_MISTNOST, "Kuchyne")
    assert "zastinit" not in _klice(_entity_platformy("button", [bez]))

    s = FalesnaPodentita(const.PODENTITA_MISTNOST, "Obyvak", {
        const.CONF_STINENI_MAPA: {"cover.o1|zastinit": "zastíněno",
                                  "cover.o1|soukromi": "dolů"}})
    klice = _klice(_entity_platformy("button", [s]))
    assert "zastinit" in klice and "soukromi" in klice
    assert "odstinit" not in klice


def test_mistnost_dostane_senzory(nahradni_ha):
    import importlib
    const = importlib.import_module("napohodu.const")
    pod = FalesnaPodentita(const.PODENTITA_MISTNOST, "Kuchyne")
    klice = _klice(_entity_platformy("sensor", [pod]))
    for k in ("stav", "cil", "slunce"):
        assert k in klice


def test_oblast_dostane_sdileny_vzduch(nahradni_ha):
    import importlib
    const = importlib.import_module("napohodu.const")
    pod = FalesnaPodentita(const.PODENTITA_ZONA, "Oblast")
    assert "stav_oblasti" in _klice(_entity_platformy("sensor", [pod]))


# ------------------------------------------------- jednotky větru

class FalesnyStav:
    def __init__(self, state, jednotka=None):
        self.state = state
        self.attributes = {"unit_of_measurement": jednotka} if jednotka else {}


def _rychlost(state, jednotka):
    """Zavolá převod bez celého koordinátoru."""
    import importlib
    ko = importlib.import_module("napohodu.coordinator")

    class Falesny:
        NA_MS = ko.NaPohoduCoordinator.NA_MS
        _rychlost = ko.NaPohoduCoordinator._rychlost

        def _stav(self, eid):
            return FalesnyStav(state, jednotka)

    return Falesny()._rychlost("sensor.vitr")


def test_metry_za_sekundu_se_neprepocitavaji(nahradni_ha):
    assert abs(_rychlost("7.0", "m/s") - 7.0) < 0.01


def test_kilometry_za_hodinu_se_prepoctou(nahradni_ha):
    """Ecowitt hlásí km/h, ale prahy jsou v m/s. Bez převodu by 7,2 km/h
    přeteklo práh 7 m/s, což je vánek proti čerstvému větru."""
    assert abs(_rychlost("7.2", "km/h") - 2.0) < 0.05


def test_mile_a_uzly(nahradni_ha):
    assert abs(_rychlost("10", "mph") - 4.47) < 0.05
    assert abs(_rychlost("10", "kn") - 5.14) < 0.05


def test_neznama_jednotka_se_bere_jako_ms(nahradni_ha):
    assert _rychlost("5", "beaufort") == 5.0


def test_chybejici_jednotka_se_bere_jako_ms(nahradni_ha):
    assert _rychlost("5", None) == 5.0


def test_nesmyslna_hodnota_da_nahradu(nahradni_ha):
    assert _rychlost("unavailable", "km/h") == 0.0


# ------------------------------------- atributy nezávislé na vybavení

def test_vlhkost_se_ukazuje_i_bez_odtahu(nahradni_ha):
    """Hodnotu, kterou známe, má být vidět — i když není čím odsávat."""
    import asyncio
    import importlib

    ko = importlib.import_module("napohodu.coordinator")
    c = importlib.import_module("napohodu.const")

    class FalesnyStavRH:
        state = "43.5"
        attributes: dict = {}

    class Mistnost:
        obsazeno = True
        atributy: dict = {}

    class Falesny:
        _cislo = ko.NaPohoduCoordinator._cislo
        _stav = staticmethod(lambda eid: FalesnyStavRH() if eid else None)
        _pomocnici_krok = ko.NaPohoduCoordinator._pomocnici_krok
        vykonavaci: dict = {}
        hass = None

    k = Falesny()
    m = Mistnost()
    m.atributy = {}
    d = {c.CONF_RH_VNITRNI: "sensor.vlhkost"}      # žádný odtah, žádný zvlhčovač
    asyncio.run(k._pomocnici_krok(_Pod(), d, m, {"pm25": 0, "pm10": 0}))
    assert m.atributy["vlhkost"] == 43.5


class _Pod:
    subentry_id = "id"
    title = "Kuchyne"
