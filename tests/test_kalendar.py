"""Testy vlastního kalendáře plánu.

Jádro rozbalování se testuje v `test_planovac.py`; tady jde o to, že
entita kalendáře opravdu vrací rozbalené výskyty a že událost založená
z panelu Kalendář dojde až do plánu — včetně pravidla opakování, které
akce `calendar.create_event` neumí.
"""

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta

import pytest

KOREN = pathlib.Path(__file__).parent.parent


@pytest.fixture(scope="module")
def kalendar():
    sys.path.insert(0, str(KOREN / "tests" / "stub_ha"))
    sys.path.insert(0, str(KOREN / "custom_components"))
    import importlib

    m = importlib.import_module("napohodu.calendar")
    yield m
    for jmeno in list(sys.modules):
        if jmeno.startswith(("napohodu", "homeassistant")):
            del sys.modules[jmeno]
    sys.path.remove(str(KOREN / "tests" / "stub_ha"))
    sys.path.remove(str(KOREN / "custom_components"))


class Koordinator:
    """Jen to z koordinátoru, co kalendář potřebuje."""

    def __init__(self, zaznamy=None):
        self.zaznamy = zaznamy or []
        self.zapsane = []
        self.smazane = []

    # CoordinatorEntity si bere data a čas poslední aktualizace
    data = None
    last_update_success = True

    def async_add_listener(self, *_a, **_k):
        return lambda: None

    def plan_zaznamy(self):
        return self.zaznamy

    def plan_z_nazvu(self, nazev):
        return ("obsazeno", "Ložnice", None, None) if "Ložnice" in nazev \
            else ("nikdo", None, None, None)

    def plan_skupiny(self):
        return {}

    async def plan_zapis(self, z):
        self.zapsane.append(z)

    async def plan_smaz(self, uid):
        self.smazane.append(uid)


class Zapis:
    entry_id = "x"


def _entita(kalendar, koordinator):
    e = kalendar.KalendarPlanu(koordinator, Zapis())
    return e


def test_opakovana_udalost_se_vraci_rozbalena(kalendar):
    """Jeden záznam s pravidlem by panel ani jádro nepoznaly."""
    k = Koordinator([{"uid": "a", "druh": "obsazeno", "mistnost": "Ložnice",
                      "od": datetime(2026, 10, 20, 8, 0),
                      "do": datetime(2026, 10, 20, 15, 0),
                      "rrule": "FREQ=WEEKLY;COUNT=3"}])
    e = _entita(kalendar, k)
    v = asyncio.run(e.async_get_events(None, datetime(2026, 10, 1),
                                       datetime(2026, 12, 1)))
    assert [u.start.day for u in v] == [20, 27, 3]
    assert v[0].summary == "Ložnice: je tu někdo"
    assert all(u.uid == "a" for u in v)


def test_zalozeni_z_panelu_si_pamatuje_opakovani(kalendar):
    """Právě proto se to vede přes entitu a ne přes akci."""
    k = Koordinator()
    e = _entita(kalendar, k)
    od = datetime(2026, 10, 20, 8, 0)
    asyncio.run(e.async_create_event(
        dtstart=od, dtend=od + timedelta(hours=7),
        summary="Ložnice: je tu někdo", rrule="FREQ=WEEKLY;COUNT=3"))
    z, = k.zapsane
    assert (z["druh"], z["mistnost"]) == ("obsazeno", "Ložnice")
    assert z["rrule"] == "FREQ=WEEKLY;COUNT=3"
    assert z["od"] == od and z["uid"]


def test_mazani_bere_celou_radu(kalendar):
    """Výjimky z opakování nevedeme, takže maže celou řadu."""
    k = Koordinator()
    e = _entita(kalendar, k)
    asyncio.run(e.async_delete_event("a", recurrence_id="a-2",
                                     recurrence_range="THISANDFUTURE"))
    assert k.smazane == ["a"]
