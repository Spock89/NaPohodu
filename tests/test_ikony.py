"""Ikony žijí v icons.json, ne v kódu — a musí tam být všechny.

Chybějící záznam se nijak neohlásí: entita prostě dostane výchozí
ikonu svého oboru a nikdo si toho nevšimne, dokud se nepodívá na
dashboard. Proto se tu obě strany porovnávají: co vzniká, musí mít
ikonu, a co je v icons.json, musí někomu patřit.
"""

import asyncio
import importlib
import json
import pathlib
import sys

import pytest

KOREN = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(KOREN / "tests"))

PLATFORMY = ("sensor", "binary_sensor", "switch", "number", "select",
             "button", "datetime", "calendar", "climate")

# Entity, které svou ikonu mít nemají: jejich obor ji určuje podle
# `device_class` (okno, obsazenost, teplota) a vlastní ikona by ten
# rozumný výchozí stav jen přepsala.
BEZ_IKONY = {
    ("binary_sensor", "obsazeno"), ("binary_sensor", "okno"),
    ("binary_sensor", "okno_otevreno"),
    ("sensor", "cil"), ("sensor", "prumer_tyden"),
    ("sensor", "prumer_tri_dny"),
}


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


def _vznikle(ha):
    """Překladové klíče všeho, co se v plné instalaci založí."""
    import test_cyklus as tc

    c = importlib.import_module("napohodu.const")
    podentity = list(tc._instalace(c))
    podentity.append(tc.Podentita(c.PODENTITA_KLIMA, "Split", {
        c.CONF_KLIMA_ENTITA: "climate.split",
        c.CONF_KLIMA_POKOJE: ["id_Obývák"]}))
    stavy = dict(tc._stavy())
    stavy["climate.split"] = tc.Stav("off", {"temperature": 24.0})
    stavy["sensor.vitr"] = tc.Stav("3.0", {"unit_of_measurement": "m/s"})
    k, hass = tc._koordinator(
        ha, c, podentity, stavy,
        {c.CONF_T_VENKU: "sensor.venku", c.CONF_DOMA: "binary_sensor.doma",
         c.CONF_VITR: "sensor.vitr"})
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())
    hass.data = {c.DOMAIN: {k.entry.entry_id: k}}

    vse: set[tuple[str, str]] = set()
    kod: set[tuple[str, str]] = set()
    for jmeno in PLATFORMY:
        modul = importlib.import_module(f"napohodu.{jmeno}")

        def pridat(seznam, **_kw):
            for e in seznam:
                klic = getattr(e, "_attr_translation_key", None)
                if klic:
                    vse.add((jmeno, klic))
                if getattr(e, "_attr_icon", None) or isinstance(
                        getattr(type(e), "icon", None), property):
                    kod.add((jmeno, klic or type(e).__name__))

        asyncio.run(modul.async_setup_entry(hass, k.entry, pridat))

    # Šoupátka a tlačítka stínění, která v téhle instalaci nevzniknou,
    # ikonu potřebují stejně.
    n = importlib.import_module("napohodu.number")
    for p in n.MISTNOST + n.TOPENI + n.CELY_BYT:
        vse.add(("number", p.klic))
    for klic in ("odstinit", "soukromi", "stineni_pryc", "stineni_vychozi"):
        vse.add(("button", klic))
    return vse, kod


def _icons():
    cesta = KOREN / "custom_components" / "napohodu" / "icons.json"
    return json.loads(cesta.read_text())["entity"]


def test_vse_co_vznika_ma_ikonu(ha):
    """Nová entita bez ikony se musí vědomě zapsat do BEZ_IKONY."""
    vse, _ = _vznikle(ha)
    ikony = _icons()
    chybi = {(dom, klic) for dom, klic in vse
             if klic not in ikony.get(dom, {})}
    assert chybi == BEZ_IKONY


def test_v_icons_json_neni_nic_navic(ha):
    """Záznam, kterému nic nepatří, zůstane po přejmenování klíče."""
    vse, _ = _vznikle(ha)
    ikony = _icons()
    navic = {(dom, klic) for dom in ikony for klic in ikony[dom]
             if (dom, klic) not in vse}
    assert navic == set()


def test_v_kodu_zustavaji_jen_dve_vyjimky(ha):
    """Ikona v kódu smí zůstat jen tam, kde ji icons.json neumí.

    Kalendář scény se jmenuje scénou, takže překladový klíč nemá a
    nemá se čeho chytit. Dlaždice dne si ikonu počítá ze stavu
    zaškrtnutí a z toho, jestli je rozdělaná změna — to je logika,
    ne tabulka.
    """
    _, kod = _vznikle(ha)
    assert kod == {("calendar", "KalendarSceny"), ("switch", "DenSceny")}


def test_ikony_jsou_platny_mdi_nazev():
    """Překlep v názvu se pozná jako chybějící ikona na dashboardu."""
    for dom, klice in _icons().items():
        for klic, zapis in klice.items():
            assert set(zapis) == {"default"}, (dom, klic)
            assert zapis["default"].startswith("mdi:"), (dom, klic)
            assert zapis["default"] == zapis["default"].strip().lower()
