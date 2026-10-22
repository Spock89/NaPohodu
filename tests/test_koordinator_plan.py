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


# ------------------------------------------------------------ scény

def test_scena_pres_plan_vlastni(koord):
    """Scéna se do zbytku integrace promítne jako běžné druhy plánu.

    Nikde jinde se pak o scénách nemusí vědět: útlum, zavřená okna
    i cílová teplota se čtou stejnými dotazy jako dřív.
    """
    from napohodu import const as c

    ted = _ted(koord)
    scena = Podentita(
        c.PODENTITA_SCENA, "Home Office",
        {c.CONF_NAZEV: "Home Office",
         c.CONF_SCENA_OD: "00:00", c.CONF_SCENA_DO: "23:59",
         c.CONF_SCENA_PRAZDNO: ["Ložnice"],
         c.CONF_SCENA_ZAVRENO: ["Ložnice"],
         c.PREFIX_SCENA_CIL + "dilna": 22.0})
    den = ted.replace(hour=0, minute=0, second=0, microsecond=0)
    k = _instance(koord, [{
        "uid": "u1", "druh": "scena", "scena": "Home Office",
        "celodenni": True, "okno": ["00:00", "23:59"],
        "opis": {"prazdno": [], "zavreno": [], "cil": {}},
        "od": den, "do": den + timedelta(days=1), "rrule": None,
    }], podentity=(scena,
                   Podentita(c.PODENTITA_MISTNOST, "Dílna"),
                   Podentita(c.PODENTITA_MISTNOST, "Ložnice")))

    assert k.sceny()["Home Office"]["cil"] == {"Dílna": 22.0}

    # ložnice: prázdno i zavřená okna, dílna nic z toho
    assert k.plan_vlastni("prazdno", "Ložnice", 0.0).bezi is True
    assert k.plan_vlastni("zavreno", "Ložnice", 0.0).bezi is True
    assert k.plan_vlastni("prazdno", "Dílna", 0.0).bezi is False

    # dílna má cíl, ložnice ne
    assert k.plan_cil_mistnosti("Dílna") == 22.0
    assert k.plan_cil_mistnosti("Ložnice") is None


def test_smazana_scena_jede_podle_opisu(koord):
    """Smazaná scéna nesmí shodit dny, které jsou podle ní zadané."""
    from napohodu import const as c

    ted = _ted(koord)
    den = ted.replace(hour=0, minute=0, second=0, microsecond=0)
    k = _instance(koord, [{
        "uid": "u1", "druh": "scena", "scena": "uz_neexistuje",
        "celodenni": True, "okno": ["00:00", "23:59"],
        "opis": {"prazdno": ["Ložnice"], "zavreno": [], "cil":
                 {"Dílna": 21.0}},
        "od": den, "do": den + timedelta(days=1), "rrule": None,
    }], podentity=(Podentita(c.PODENTITA_MISTNOST, "Dílna"),))

    assert k.plan_vlastni("prazdno", "Ložnice", 0.0).bezi is True
    assert k.plan_cil_mistnosti("Dílna") == 21.0


def test_konkretnejsi_cil_prebije_scenu(koord):
    """Když platí scéna i cíl zadaný té místnosti, vyhraje ten cíl."""
    from napohodu import const as c

    ted = _ted(koord)
    den = ted.replace(hour=0, minute=0, second=0, microsecond=0)
    spolecne = dict(celodenni=True, okno=["00:00", "23:59"],
                    od=den, do=den + timedelta(days=1), rrule=None)
    scena = Podentita(
        c.PODENTITA_SCENA, "Home Office",
        {c.CONF_NAZEV: "Home Office",
         c.PREFIX_SCENA_CIL + "dilna": 22.0})
    k = _instance(koord, [
        {"uid": "s", "druh": "scena", "scena": "Home Office",
         "opis": {"prazdno": [], "zavreno": [], "cil": {}}, **spolecne},
        {"uid": "c", "druh": "cil", "mistnost": "Dílna", "cil": 19.5,
         "od": ted - timedelta(hours=1), "do": ted + timedelta(hours=1),
         "rrule": None},
    ], podentity=(scena, Podentita(c.PODENTITA_MISTNOST, "Dílna")))

    assert k.plan_cil_mistnosti("Dílna") == 19.5

    # bez toho konkrétního cíle platí scéna
    k._vlastni_plan = k._vlastni_plan[:1]
    assert k.plan_cil_mistnosti("Dílna") == 22.0


def test_scena_jen_s_cilem_neni_potichu(koord):
    """Scéna, která nastaví jen teplotu, musí být poznat.

    Zprávy se staví z dopadu, ne ze záznamu. Dokud mezi dopady nebyla
    naplánovaná teplota, proběhla taková scéna úplně potichu.
    """
    poslano = []

    k = object.__new__(koord.NaPohoduCoordinator)
    k.plan_nikdo = koord.pl.Udalost()
    k.plan_vic = koord.pl.Udalost()
    k._plan_zpravy_prvni = False
    k._plan_bezelo = {}
    k._plan_chyby = set()
    k._vlastni_plan = []
    k.entry = Zapis2(())
    k.mistnosti = {"x": koord.VysledekMistnosti(nazev="Dílna",
                                                plan_cil=22.0)}

    async def posli(g, druh, kdo, cas_s, **kw):
        poslano.append((kdo, kw))

    k._posli = posli
    asyncio.run(k._plan_zpravy({}, 1000.0))
    assert poslano and poslano[0][0] == "Dílna"
    assert "cíl 22,0 °C" in poslano[0][1]["co"]

    # podruhé se totéž neopakuje
    poslano.clear()
    asyncio.run(k._plan_zpravy({}, 1060.0))
    assert poslano == []

    # a konec plánu se ohlásí
    k.mistnosti["x"].plan_cil = None
    asyncio.run(k._plan_zpravy({}, 1120.0))
    assert poslano and poslano[0][1].get("konec") is True
