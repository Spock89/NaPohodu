"""Testy jednorázového srovnání starší konfigurace.

Migrace běží jednou při načtení integrace a mění registr entit
i uložená data. Spoléhá na ni karta i rozhodování — po srovnání už
nikdo dřívější jména nezkouší — takže jediná chyba tady znamená, že
řádek z dashboardu zmizí nebo že místnost přijde o žaluzie.
"""

import asyncio
import pathlib
import sys

import pytest

KOREN = pathlib.Path(__file__).parent.parent


@pytest.fixture(scope="module")
def migrace():
    sys.path.insert(0, str(KOREN / "tests" / "stub_ha"))
    sys.path.insert(0, str(KOREN / "custom_components"))
    import importlib

    m = importlib.import_module("napohodu.migrace")
    reg = importlib.import_module("homeassistant.helpers.entity_registry")
    yield m, reg
    for jmeno in list(sys.modules):
        if jmeno.startswith(("napohodu", "homeassistant")):
            del sys.modules[jmeno]
    sys.path.remove(str(KOREN / "tests" / "stub_ha"))
    sys.path.remove(str(KOREN / "custom_components"))


class Podentita:
    def __init__(self, typ, nazev, data):
        self.subentry_type = typ
        self.subentry_id = nazev
        self.title = nazev
        self.data = data


class Zaznamy:
    def __init__(self, podentity=()):
        self.zmeny = []

    def async_update_subentry(self, entry, pod, data=None):
        self.zmeny.append((pod.subentry_id, data))
        pod.data = data


class Zapis:
    entry_id = "x"

    def __init__(self, podentity=()):
        self.subentries = {p.subentry_id: p for p in podentity}


class Hass:
    def __init__(self, registr, podentity=()):
        self.registr = registr
        self.config_entries = Zaznamy()


def test_prejmenuje_jen_drivejsi_jmena(migrace):
    """Vlastní jméno, které si někdo nastavil sám, zůstane."""
    m, reg = migrace
    r = reg.Registr([
        reg.RegistrZapis("number.napohodu_loznice_odchylka_teploty"),
        reg.RegistrZapis("number.napohodu_loznice_nocni_utlum_topeni"),
        reg.RegistrZapis("number.napohodu_loznice_moje_vlastni_jmeno"),
        # dnešní jméno se nesmí přepsat na nic jiného
        reg.RegistrZapis("number.napohodu_kuchyne_moje_odchylka_teploty"),
        # jiná doména se netýká posuvníků
        reg.RegistrZapis("sensor.napohodu_loznice_odchylka_teploty"),
    ])
    entry = Zapis()
    asyncio.run(m.srovnej(Hass(r), entry))
    assert r.prejmenovane == [
        ("number.napohodu_loznice_odchylka_teploty",
         "number.napohodu_loznice_moje_odchylka_teploty"),
        ("number.napohodu_loznice_nocni_utlum_topeni",
         "number.napohodu_loznice_v_noci_posun_cilove_teploty"),
    ]


def test_obsazene_jmeno_se_preskoci(migrace):
    """Dvě entity na jeden identifikátor nejdou a hádat příponu by
    vedlo k další podivnosti — radši se o tom jen ozve."""
    m, reg = migrace
    r = reg.Registr([
        reg.RegistrZapis("number.napohodu_loznice_odchylka_teploty"),
        reg.RegistrZapis("number.napohodu_loznice_moje_odchylka_teploty"),
    ])
    asyncio.run(m.srovnej(Hass(r), Zapis()))
    assert r.prejmenovane == []


def test_zaluzie_se_prepisou_do_dnesniho_klice(migrace):
    m, _ = migrace
    pod = Podentita("mistnost", "Ložnice",
                    {"zaluzie_zony": ["cover.a"], "nazev": "Ložnice"})
    entry = Zapis([pod])
    hass = Hass(m.er.async_get(None))
    asyncio.run(m.srovnej(hass, entry))
    assert pod.data["zaluzie"] == ["cover.a"]
    assert "zaluzie_zony" not in pod.data


def test_vyplneny_dnesni_klic_se_neprepisuje(migrace):
    """Kdo má obojí, má pravdu v tom dnešním."""
    m, _ = migrace
    pod = Podentita("mistnost", "Ložnice",
                    {"zaluzie_zony": ["cover.stare"],
                     "zaluzie": ["cover.nove"]})
    hass = Hass(m.er.async_get(None))
    asyncio.run(m.srovnej(hass, Zapis([pod])))
    assert pod.data["zaluzie"] == ["cover.nove"]


def test_srovnani_jde_spustit_opakovane(migrace):
    """Načtení integrace se opakuje při každé změně nastavení."""
    m, reg = migrace
    r = reg.Registr([
        reg.RegistrZapis("number.napohodu_loznice_odchylka_teploty")])
    hass = Hass(r)
    entry = Zapis()
    asyncio.run(m.srovnej(hass, entry))
    asyncio.run(m.srovnej(hass, entry))
    assert len(r.prejmenovane) == 1
