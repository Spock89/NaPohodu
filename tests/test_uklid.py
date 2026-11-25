"""Úklid entit musí krýt přesně to, co platformy zakládají podmíněně.

Seznam druhů v `_uklid` je ruční opis pravidel rozesetých po devíti
platformách. Takový opis zastará potichu: kdo přidá podmíněnou entitu
a na úklid zapomene, nic nerozbije — jen po aktualizaci zůstane
v registru viset entita, kterou nemá kdo smazat, a pozná se to až
v dashboardu u uživatele.

Tenhle test to porovnává sám. Vyrobí dvě místnosti, jednu plně
vybavenou a jednu bez ničeho, nechá všechny platformy založit entity
a z rozdílu obou sad spočítá, co na vybavení závisí. Co v tom rozdílu
je, musí úklid v nevybavené místnosti smazat — a ve vybavené nechat.
"""

import asyncio
import importlib
import pathlib
import sys

import pytest

KOREN = pathlib.Path(__file__).parent.parent

from test_cyklus import Hass, Podentita, Stav, Zapis  # noqa: E402

PLATFORMY = ("sensor", "number", "button", "switch", "binary_sensor",
             "select", "climate", "datetime", "calendar")


@pytest.fixture
def ha():
    sys.path.insert(0, str(KOREN / "tests" / "stub_ha"))
    sys.path.insert(0, str(KOREN / "custom_components"))
    storage = importlib.import_module("homeassistant.helpers.storage")
    storage.Store._data = {}
    yield importlib.import_module("napohodu")
    for jmeno in list(sys.modules):
        if jmeno.startswith(("napohodu", "homeassistant")):
            del sys.modules[jmeno]
    sys.path.remove(str(KOREN / "custom_components"))
    sys.path.remove(str(KOREN / "tests" / "stub_ha"))


def _stavy():
    return {
        "sensor.venku": Stav("6.5", {"unit_of_measurement": "°C"}),
        "sensor.t": Stav("21.5", {"unit_of_measurement": "°C"}),
        "cover.okno": Stav("closed", {"current_position": 0}),
        "cover.zaluzie": Stav("open", {"current_position": 100}),
        "climate.hlavice": Stav("heat", {"temperature": 21.0}),
        "humidifier.zvlhcovac": Stav("on"),
        "fan.cisticka": Stav("on"),
        "binary_sensor.kontakt": Stav("off"),
        "sun.sun": Stav("above_horizon", {"azimuth": 180.0,
                                          "elevation": 25.0}),
    }


def _mistnosti(c):
    plny = Podentita(c.PODENTITA_MISTNOST, "Plny", {
        c.CONF_TEPLOTY: ["sensor.t"],
        c.CONF_OKNA: ["cover.okno"],
        c.CONF_KONTAKT_M: ["binary_sensor.kontakt"],
        c.CONF_ZALUZIE: ["cover.zaluzie"],
        c.CONF_STINENI_MAPA: {"cover.zaluzie": {
            "zastinit": "dolu", "odstinit": "nahoru", "soukromi": "dolu",
            "pryc": "dolu", "vychozi": "nahoru"}},
        c.CONF_ZVLHCOVAC: ["humidifier.zvlhcovac"],
        c.CONF_CISTICKA: ["fan.cisticka"],
        c.CONF_CLIMATE: ["climate.hlavice"]})
    prazdny = Podentita(c.PODENTITA_MISTNOST, "Prazdny",
                        {c.CONF_TEPLOTY: ["sensor.t"]})
    return plny, prazdny


def _zaloz(ha, c, podentity):
    """Nechá všechny platformy založit entity a vrátí jejich identifikátory."""
    from homeassistant.helpers import entity_registry as er

    hass = Hass(_stavy())
    hass.registr = er.Registr()
    entry = Zapis(podentity, {c.CONF_T_VENKU: "sensor.venku"})
    ko = importlib.import_module("napohodu.coordinator")
    k = ko.NaPohoduCoordinator(hass, entry)
    k.hass = hass
    hass.data = {c.DOMAIN: {entry.entry_id: k}}

    identifikatory = []

    def pridat(entity, config_subentry_id=None, **_kw):
        for e in entity:
            identifikatory.append(e._attr_unique_id)

    for jmeno in PLATFORMY:
        modul = importlib.import_module(f"napohodu.{jmeno}")
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            modul.async_setup_entry(hass, entry, pridat))
    return identifikatory


def _pro(identifikatory, pod):
    predpona = f"{pod.subentry_id}_"
    return {i[len(predpona):] for i in identifikatory
            if i.startswith(predpona)}


def test_uklid_kryje_vsechno_podminene(ha):
    """Co vzniká jen s vybavením, musí umět úklid i smazat."""
    c = importlib.import_module("napohodu.const")
    from homeassistant.helpers import entity_registry as er

    plny, prazdny = _mistnosti(c)
    vznikle = _zaloz(ha, c, [plny, prazdny])
    podminene = _pro(vznikle, plny) - _pro(vznikle, prazdny)
    # Kdyby se podmínky z platforem vytratily, test by prošel naprázdno.
    assert len(podminene) >= 40

    # Registr jako po aktualizaci: obě místnosti mají všechno, co kdy
    # vzniklo plně vybavené.
    hass = Hass(_stavy())
    entry = Zapis([plny, prazdny])
    hass.registr = er.Registr([
        er.RegistrZapis(f"switch.{pod.title}_{klic}".lower(),
                        f"{pod.subentry_id}_{klic}",
                        config_entry_id=entry.entry_id)
        for pod in (plny, prazdny)
        for klic in _pro(vznikle, plny)
    ])
    puvodni = {z.entity_id for z in hass.registr.zapisy}

    uklid = importlib.import_module("napohodu")._uklid
    uklid(hass, entry)

    smazane = set(hass.registr.smazane)
    cekane = {f"switch.{prazdny.title}_{klic}".lower()
              for klic in podminene}
    # V nevybavené místnosti zmizí přesně to podmíněné, nic víc.
    assert smazane == cekane
    # Ve vybavené nezmizí nic.
    assert not any(z.startswith(f"switch.{plny.title}".lower())
                   for z in smazane)
    # A nic, co se nemaže, se neztratilo.
    zbyle = {z.entity_id for z in hass.registr.zapisy}
    assert zbyle == puvodni - smazane
