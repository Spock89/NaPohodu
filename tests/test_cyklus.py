"""Jeden celý cyklus koordinátoru proti náhradnímu Home Assistantu.

Všechno ostatní testuje kousky. Tohle testuje propojení: že se celý
cyklus vůbec projde a nespadne. Právě tam vznikly chyby, které se
v jednotlivých modulech nedaly vidět — seznam, který zastínil metodu,
nebo chybějící import v nové větvi.
"""

import asyncio
import datetime
import pathlib
import sys

import pytest

KOREN = pathlib.Path(__file__).parent.parent


@pytest.fixture
def ha():
    sys.path.insert(0, str(KOREN / "tests" / "stub_ha"))
    sys.path.insert(0, str(KOREN / "custom_components"))
    import importlib

    storage = importlib.import_module("homeassistant.helpers.storage")
    storage.Store._data = {}
    yield importlib.import_module("napohodu.coordinator")
    for jmeno in list(sys.modules):
        if jmeno.startswith(("napohodu", "homeassistant")):
            del sys.modules[jmeno]
    sys.path.remove(str(KOREN / "custom_components"))
    sys.path.remove(str(KOREN / "tests" / "stub_ha"))


class Stav:
    def __init__(self, stav, atributy=None):
        self.state = stav
        self.attributes = atributy or {}
        self.last_changed = datetime.datetime.now(datetime.timezone.utc)
        self.last_updated = self.last_changed
        self.entity_id = ""


class Sluzby:
    def __init__(self):
        self.volano = []

    def has_service(self, obor, jmeno):
        return True

    async def async_call(self, obor, jmeno, data=None, **kw):
        self.volano.append((obor, jmeno, data))
        return None


class Stavy:
    def __init__(self, hodnoty):
        self._h = dict(hodnoty)

    def get(self, eid):
        return self._h.get(eid)

    def async_all(self, obor=None):
        return []


class Hass:
    def __init__(self, hodnoty):
        self.states = Stavy(hodnoty)
        self.services = Sluzby()
        self.data = {}
        self.config = type("C", (), {"time_zone": "Europe/Prague"})()

    def async_create_task(self, coro):
        return asyncio.ensure_future(coro)

    async def async_add_executor_job(self, f, *a):
        return f(*a)


class Podentita:
    def __init__(self, typ, nazev, data=None):
        self.subentry_type = typ
        self.subentry_id = f"id_{nazev}"
        self.title = nazev
        self.data = data or {}


class Zapis:
    entry_id = "entry"

    def __init__(self, podentity, data=None):
        self.subentries = {p.subentry_id: p for p in podentity}
        self.data = data or {}
        self.options = {}


def _instalace(c):
    """Byt jako ten skutečný: okno, žaluzie, zóna, skupina i scéna."""
    return [
        Podentita(c.PODENTITA_MISTNOST, "Obývák", {
            c.CONF_OKNA: ["cover.obyvak"],
            c.CONF_ZALUZIE: ["cover.zaluzie"],
            c.CONF_STINENI_MAPA: {"cover.zaluzie": {"zastinit": "dolu"}},
            c.CONF_TEPLOTY: ["sensor.t_obyvak"],
            c.CONF_CO2: ["sensor.co2"],
            c.CONF_PRITOMNOST: "binary_sensor.pohyb",
            c.CONF_CLIMATE: "climate.hlavice"}),
        Podentita(c.PODENTITA_MISTNOST, "Dílna", {
            c.CONF_TEPLOTY: ["sensor.t_dilna"]}),
        Podentita(c.PODENTITA_ZONA, "Kuchyň a obývák",
                  {c.CONF_MISTNOSTI: ["Obývák", "Dílna"]}),
        Podentita(c.PODENTITA_SKUPINA, "1. patro", {
            c.CONF_SKUPINA_MISTNOSTI: ["Dílna"],
            c.CONF_SKUPINA_PRITOMNOST: "binary_sensor.patro"}),
        Podentita(c.PODENTITA_SCENA, "Home Office", {
            c.CONF_NAZEV: "Home Office",
            c.CONF_SCENA_OD: "00:00:00", c.CONF_SCENA_DO: "23:59:00",
            c.CONF_SCENA_PRAZDNO: ["Dílna"],
            c.PREFIX_SCENA_CIL + "obyvak": 22.0}),
    ]


def _stavy():
    return {
        "sensor.t_obyvak": Stav("21.5", {"unit_of_measurement": "°C"}),
        "sensor.t_dilna": Stav("19.0", {"unit_of_measurement": "°C"}),
        "sensor.co2": Stav("640", {"unit_of_measurement": "ppm"}),
        "sensor.venku": Stav("6.5", {"unit_of_measurement": "°C"}),
        "binary_sensor.pohyb": Stav("on"),
        "binary_sensor.patro": Stav("off"),
        "binary_sensor.doma": Stav("on"),
        "cover.obyvak": Stav("closed", {"current_position": 0}),
        "cover.zaluzie": Stav("open", {"current_position": 100,
                                       "current_tilt_position": 50}),
        "climate.hlavice": Stav("heat", {"temperature": 21.0,
                                         "current_temperature": 21.4}),
        "sun.sun": Stav("above_horizon", {"azimuth": 180.0,
                                          "elevation": 25.0}),
    }


def _koordinator(ko, c, podentity=None, stavy=None, data=None):
    hass = Hass(stavy if stavy is not None else _stavy())
    entry = Zapis(podentity if podentity is not None else _instalace(c),
                  data or {c.CONF_T_VENKU: "sensor.venku",
                           c.CONF_DOMA: "binary_sensor.doma"})
    k = ko.NaPohoduCoordinator(hass, entry)
    k.hass = hass
    return k, hass


def test_cely_cyklus_projde(ha):
    """Nic víc, než že se celý cyklus projde a nespadne."""
    ko = ha
    from napohodu import const as c

    k, hass = _koordinator(ko, c)
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())

    assert set(k.mistnosti) == {"id_Obývák", "id_Dílna"}
    obyvak = k.mistnosti["id_Obývák"]
    assert obyvak.rozhodnuti is not None
    assert obyvak.atributy["co2"] == 640.0


def test_cyklus_se_scenou_a_skupinou(ha):
    """Scéna i čidlo patra se projeví tam, kde mají."""
    ko = ha
    from napohodu import const as c

    k, hass = _koordinator(ko, c)
    asyncio.run(k.async_nacti())

    ted = ko.dt_util.now()
    den = ted.replace(hour=0, minute=0, second=0, microsecond=0)
    k._vlastni_plan = [{
        "uid": "u1", "druh": "scena", "scena": "id_Home Office",
        "celodenni": True, "okno": ["00:00:00", "23:59:00"],
        "opis": {"prazdno": [], "zavreno": [], "cil": {}},
        "od": den, "do": den + datetime.timedelta(days=1), "rrule": None}]
    asyncio.run(k._async_update_data())

    # scéna nastavuje cíl obýváku
    assert k.mistnosti["id_Obývák"].cil == 22.0
    # scéna i čidlo patra prohlásí dílnu za prázdnou
    dilna = k.mistnosti["id_Dílna"]
    assert dilna.plan_prazdno is True
    assert dilna.skupina_prazdno == "1. patro"
    assert dilna.obsazeno is False


def test_skupina_neprebije_vlastni_cidlo(ha):
    """Co místnost vidí sama, to jí čidlo patra nepřebije."""
    ko = ha
    from napohodu import const as c

    podentity = _instalace(c)
    # dílna dostane vlastní čidlo pohybu, které někoho vidí
    podentity[1].data[c.CONF_PRITOMNOST] = "binary_sensor.pohyb_dilna"
    podentity[1].data[c.CONF_ZDROJ_OBSAZENOSTI] = "cidlo"
    stavy = _stavy()
    stavy["binary_sensor.pohyb_dilna"] = Stav("on")

    k, hass = _koordinator(ko, c, podentity, stavy)
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())

    dilna = k.mistnosti["id_Dílna"]
    assert dilna.skupina_prazdno is None
    assert dilna.obsazeno is True


def test_obracene_cidlo_pritomnosti(ha):
    """Zapnuto znamená „nikdo doma", když se to zaškrtne."""
    ko = ha
    from napohodu import const as c

    k, hass = _koordinator(
        ko, c, data={c.CONF_T_VENKU: "sensor.venku",
                     c.CONF_DOMA: "binary_sensor.doma",
                     c.CONF_DOMA_OBRACENE: True})
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())
    assert "obráceně" in k.doma_popis
    # prázdný byt přebíjí všechno, takže místnost není obsazená
    assert k.mistnosti["id_Obývák"].obsazeno is False

    # a bez zaškrtnutí je to naopak
    k2, _ = _koordinator(ko, c)
    asyncio.run(k2.async_nacti())
    asyncio.run(k2._async_update_data())
    assert "obráceně" not in k2.doma_popis
    assert k2.mistnosti["id_Obývák"].obsazeno is True


def test_zadost_posle_i_mistnost_s_vypnutym_oknem(ha):
    """Vyvětrat si sama neumí ani místnost, která okno má, ale má
    vypnutý přepínač Ovládat okno — požádá tedy souseda v zóně.

    Dřív to hlídal test, který hledal jméno klíče v kódu. Klíč tam
    byl, jenže špatný: hodnota přepínače se vede pod „ovladat", takže
    se četla výchozí jednička a větev byla mrtvá. Proto se to teď
    zkouší během, ne čtením.
    """
    ko = ha
    from napohodu import const as c

    pod = _instalace(c)
    stavy = _stavy()
    # v obýváku je chladno a venku tepleji, takže by si rád ohřál
    stavy["sensor.t_obyvak"] = Stav("18.0", {"unit_of_measurement": "°C"})
    stavy["sensor.venku"] = Stav("24.0", {"unit_of_measurement": "°C"})

    # se zapnutým ovládáním si pomůže sám a nikoho neprosí
    k, _ = _koordinator(ko, c, pod, stavy)
    k.hodnoty[("id_Obývák", "ovladat")] = 1.0
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())
    asyncio.run(k._async_update_data())
    zona = next(iter(k.zony.values()))
    assert "Obývák" not in (zona.atributy.get("teplo_za") or [])

    # s vypnutým ovládáním o to požádá zónu
    k2, _ = _koordinator(ko, c, pod, stavy)
    k2.hodnoty[("id_Obývák", "ovladat")] = 0.0
    asyncio.run(k2.async_nacti())
    asyncio.run(k2._async_update_data())
    asyncio.run(k2._async_update_data())
    zona2 = next(iter(k2.zony.values()))
    assert "Obývák" in (zona2.atributy.get("teplo_za") or [])
