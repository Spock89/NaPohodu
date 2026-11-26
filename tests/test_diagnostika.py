"""Diagnostický export: musí být použitelný a nesmí nic prozradit.

Export má smysl jen tehdy, když v něm je to, kvůli čemu se stahuje —
tedy nastavení i to, jak se z něj rozhodlo. A protože ho člověk může
poslat do veřejného vlákna, nesmí v něm být nic, co tam nepatří.
"""

import asyncio
import importlib
import json
import pathlib
import sys

import pytest

KOREN = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(KOREN / "tests"))


@pytest.fixture
def ha():
    sys.path.insert(0, str(KOREN / "tests" / "stub_ha"))
    sys.path.insert(0, str(KOREN / "custom_components"))
    storage = importlib.import_module("homeassistant.helpers.storage")
    storage.Store._data = {}
    yield importlib.import_module("napohodu.coordinator")
    for jmeno in list(sys.modules):
        if jmeno.startswith(("napohodu", "homeassistant")):
            del sys.modules[jmeno]
    sys.path.remove(str(KOREN / "custom_components"))
    sys.path.remove(str(KOREN / "tests" / "stub_ha"))


def _hotovy(ha):
    """Koordinátor po jednom projitém cyklu, jako v běžícím bytě."""
    from test_cyklus import _koordinator
    from napohodu import const as c

    k, hass = _koordinator(ha, c)
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())
    hass.data = {c.DOMAIN: {k.entry.entry_id: k}}
    return k, hass, c


def test_export_obsahuje_nastaveni_i_rozhodnuti(ha):
    dg = importlib.import_module("napohodu.diagnostics")
    k, hass, c = _hotovy(ha)

    out = asyncio.run(dg.async_get_config_entry_diagnostics(hass, k.entry))

    # Nastavení i podentity, ať je vidět, z čeho se vycházelo.
    assert out["nastaveni"]["spolecne"][c.CONF_T_VENKU] == "sensor.venku"
    nazvy = {p["nazev"] for p in out["nastaveni"]["podentity"]}
    assert {"Obývák", "Dílna"} <= nazvy

    # A výsledek: právě ten se z fotky obrazovky nedá přečíst.
    obyvak = out["mistnosti"]["id_Obývák"]
    assert obyvak["nazev"] == "Obývák"
    assert obyvak["atributy"]["co2"] == 640.0
    assert obyvak["rozhodnuti"] is not None
    assert "pamet" in out["koordinator"]
    assert "naber" in out["koordinator"]

    # Celé to musí jít do JSON, jinak export v Home Assistantu spadne.
    json.dumps(out)


def test_export_necedi_tajne_hodnoty(ha):
    """NaPohodu dnes žádné tajnosti nemá. Cedník je pro ty příští."""
    dg = importlib.import_module("napohodu.diagnostics")
    k, hass, c = _hotovy(ha)
    k.entry.data = {**k.entry.data, "latitude": 50.08,
                    "muj_token": "abcdef", "okna": ["cover.okno"]}

    out = asyncio.run(dg.async_get_config_entry_diagnostics(hass, k.entry))
    spolecne = out["nastaveni"]["spolecne"]

    assert spolecne["latitude"] == dg.SKRYTO
    assert spolecne["muj_token"] == dg.SKRYTO
    assert spolecne["okna"] == ["cover.okno"]


def test_export_funguje_i_kdyz_se_integrace_nenacetla(ha):
    """Právě tehdy je nejpotřebnější — nesmí spadnout."""
    dg = importlib.import_module("napohodu.diagnostics")
    k, hass, c = _hotovy(ha)
    # Nenačtený zápis koordinátor nenese.
    hass.data = {}
    k.entry.runtime_data = None

    out = asyncio.run(dg.async_get_config_entry_diagnostics(hass, k.entry))
    assert out["koordinator"] == "nenačtený"
    assert out["nastaveni"]["spolecne"][c.CONF_T_VENKU] == "sensor.venku"
