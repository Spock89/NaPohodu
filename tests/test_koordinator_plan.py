"""Testy plánovacích metod koordinátoru.

Testy jádra koordinátor nepotřebují a import jen ověří, že se modul
naimportuje — propojení mezi plánem, rozbalováním opakování a pamětí
tak zůstávalo nekontrolované. Právě tam vznikla chyba, kdy seznam
`self._plan` zastínil metodu `_plan()` a nastavení integrace spadlo na
„'list' object is not callable".

Koordinátor se tu nezakládá celý — vyžadoval by běžící Home Assistant.
Vyrobí se prázdná instance a doplní se jen to, co tyhle metody čtou.
"""

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta

import pytest

KOREN = pathlib.Path(__file__).parent.parent


@pytest.fixture(scope="module")
def koord():
    sys.path.insert(0, str(KOREN / "tests" / "stub_ha"))
    sys.path.insert(0, str(KOREN / "custom_components"))
    import importlib

    m = importlib.import_module("napohodu.coordinator")
    yield m
    for jmeno in list(sys.modules):
        if jmeno.startswith(("napohodu", "homeassistant")):
            del sys.modules[jmeno]
    sys.path.remove(str(KOREN / "tests" / "stub_ha"))
    sys.path.remove(str(KOREN / "custom_components"))


class Podentita:
    def __init__(self, typ, nazev, data=None):
        self.subentry_type = typ
        self.subentry_id = nazev
        self.title = nazev
        self.data = data or {}


class Zapis2:
    """Konfigurační záznam s podentitami, které plán potřebuje."""

    entry_id = "x"

    def __init__(self, podentity=()):
        self.subentries = {p.subentry_id: p for p in podentity}


class Uloziste:
    def __init__(self):
        self.ulozeno = None

    async def async_save(self, data):
        self.ulozeno = data

    async def async_load(self):
        return self.ulozeno


def _instance(koord, zaznamy=None, podentity=()):
    """Prázdná instance s tím minimem, co plán čte."""
    k = object.__new__(koord.NaPohoduCoordinator)
    k.entry = Zapis2(podentity)
    k._vlastni_plan = list(zaznamy or [])
    k._uloziste_planu = Uloziste()
    k.plan_vysledek = ""
    k.plan_opakovani = "jednou"
    return k


def _ted(koord):
    return koord.dt_util.now()


def test_bezici_udalost_vlastniho_planu(koord):
    """Tahle cesta se volá při každém načtení — a spadla."""
    ted = _ted(koord)
    k = _instance(koord, [{"uid": "a", "druh": "obsazeno",
                           "mistnost": "Ložnice",
                           "od": ted - timedelta(hours=1),
                           "do": ted + timedelta(hours=1),
                           "rrule": None}])
    u = k.plan_vlastni("obsazeno", "Ložnice", 1000.0)
    assert u.bezi and 3540 < u.do_s - 1000 <= 3600
    # jiná místnost ani jiný druh se nesmí chytit
    assert not k.plan_vlastni("obsazeno", "Kuchyně", 1000.0).bezi
    assert not k.plan_vlastni("prazdno", "Ložnice", 1000.0).bezi


def test_opakovana_udalost_plati_i_priste(koord):
    """Bez rozbalení by platil jen první výskyt."""
    ted = _ted(koord)
    zacatek = (ted - timedelta(days=7)).replace(microsecond=0)
    k = _instance(koord, [{"uid": "a", "druh": "nikdo", "mistnost": None,
                           "od": zacatek - timedelta(hours=1),
                           "do": zacatek + timedelta(hours=1),
                           "rrule": "FREQ=WEEKLY"}])
    u = k.plan_vlastni("nikdo", None, 1000.0)
    assert u.bezi


def test_naplanovana_cilova_teplota(koord):
    ted = _ted(koord)
    k = _instance(koord, [{"uid": "a", "druh": "cil", "mistnost": "Ložnice",
                           "cil": 22.5,
                           "od": ted - timedelta(minutes=10),
                           "do": ted + timedelta(hours=2), "rrule": None}])
    assert k.plan_cil_mistnosti("Ložnice") == 22.5
    assert k.plan_cil_mistnosti("Kuchyně") is None


def test_ulozeni_a_nacteni_prezije_restart(koord):
    """Časy jdou do úložiště textem, musí se vrátit jako datum."""
    ted = _ted(koord).replace(microsecond=0)
    k = _instance(koord)
    asyncio.run(k._uloziste_planu.async_save(
        [{"uid": "a", "druh": "nikdo", "mistnost": None,
          "od": ted.isoformat(), "do": (ted + timedelta(hours=1)).isoformat(),
          "rrule": "FREQ=WEEKLY;COUNT=3"}]))
    asyncio.run(k._nacti_plan())
    z, = k.plan_zaznamy()
    assert isinstance(z["od"], datetime) and z["rrule"] == "FREQ=WEEKLY;COUNT=3"


def test_nazev_z_panelu_se_precte_zpatky(koord):
    """Ručně založená událost se pozná z názvu, který píšeme my."""
    k = _instance(koord, podentity=[
        Podentita("skupina", "1. patro",
                  {"skupina_mistnosti": ["Ložnice"]})])
    assert k.plan_z_nazvu("NaPohodu: nikdo doma") == ("nikdo", None, None,
                                                      None)
    assert k.plan_z_nazvu("Ložnice: je tu někdo") == ("obsazeno", "Ložnice",
                                                      None, None)
    assert k.plan_z_nazvu("Ložnice: cíl 22,5 °C") == ("cil", "Ložnice", None,
                                                      22.5)
    # jméno před dvojtečkou, které je skupina, se pozná jako skupina
    assert k.plan_z_nazvu("1. patro: zavřená okna") == ("zavreno", None,
                                                        "1. patro", None)
    # a složený povel se nesmí poznat jen jako jeho první polovina
    assert k.plan_z_nazvu(
        "Ložnice: nikdo tu nebude, zavřená okna")[0] == "prazdno_zavreno"
    assert k.plan_z_nazvu("dovolená")[0] == "nerozumim"


def test_skupina_platí_pro_sve_mistnosti(koord):
    """Jedna událost na celé patro místo pěti na místnosti."""
    ted = _ted(koord)
    skupina = Podentita("skupina", "1. patro",
                        {"skupina_mistnosti": ["Ložnice", "Dětská"]})
    k = _instance(koord, [{"uid": "a", "druh": "prazdno_zavreno",
                           "mistnost": None, "skupina": "1. patro",
                           "clenove": ["Ložnice"],
                           "od": ted - timedelta(hours=1),
                           "do": ted + timedelta(hours=1), "rrule": None}],
                  [skupina])
    # složený povel nese obojí a platí na oba členy
    assert k.plan_vlastni("prazdno", "Dětská", 1000.0).bezi
    assert k.plan_vlastni("zavreno", "Dětská", 1000.0).bezi
    assert not k.plan_vlastni("prazdno", "Kuchyně", 1000.0).bezi


def test_prazdno_samo_okno_nezavira(koord):
    """Utlumená ložnice nesmí ochromit větrání zbytku bytu."""
    ted = _ted(koord)
    k = _instance(koord, [{"uid": "a", "druh": "prazdno",
                           "mistnost": "Ložnice",
                           "od": ted - timedelta(hours=1),
                           "do": ted + timedelta(hours=1), "rrule": None}])
    assert k.plan_vlastni("prazdno", "Ložnice", 1000.0).bezi
    assert not k.plan_vlastni("zavreno", "Ložnice", 1000.0).bezi
