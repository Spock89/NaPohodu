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


@pytest.fixture(autouse=True)
def cista_poznamka(migrace):
    """Každý test začíná bez poznámky o srovnání."""
    from homeassistant.helpers.storage import Store

    Store._data.clear()
    yield
    Store._data.clear()


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


def _pokoje(*jmena):
    return Zapis([Podentita("mistnost", j, {}) for j in jmena])


def test_prejmenuje_jen_drivejsi_jmena(migrace):
    """Vlastní jméno, které si někdo nastavil sám, zůstane."""
    m, reg = migrace
    r = reg.Registr([
        reg.RegistrZapis("number.napohodu_loznice_odchylka_teploty",
                         "loznice_odchylka"),
        reg.RegistrZapis("number.napohodu_loznice_nocni_utlum_topeni",
                         "loznice_noc_posun"),
        reg.RegistrZapis("number.napohodu_loznice_moje_vlastni_jmeno",
                         "loznice_mez_dolni"),
        # dnešní jméno se nesmí přepsat na nic jiného
        reg.RegistrZapis("number.napohodu_kuchyne_moje_odchylka_teploty",
                         "kuchyne_odchylka"),
        # jiná doména se netýká posuvníků
        reg.RegistrZapis("sensor.napohodu_loznice_odchylka_teploty", "x"),
    ])
    asyncio.run(m.srovnej(Hass(r), _pokoje("loznice", "kuchyne")))
    assert r.prejmenovane == [
        ("number.napohodu_loznice_odchylka_teploty",
         "number.napohodu_loznice_moje_odchylka_teploty"),
        ("number.napohodu_loznice_nocni_utlum_topeni",
         "number.napohodu_loznice_v_noci_posun_cilove_teploty"),
    ]
    # šoupátko s vlastním jménem a cizí doména zůstaly
    assert "number.napohodu_loznice_moje_vlastni_jmeno" not in r.smazane
    assert "sensor.napohodu_loznice_odchylka_teploty" not in r.smazane


def test_zbytek_po_zrusenem_nastaveni_se_smaze(migrace):
    """Hlásí se jako nedostupný, ručně smazat nejde a blokuje jméno
    tomu živému. Přesně tahle dvojice zbyla po přejmenování pásma."""
    m, reg = migrace
    r = reg.Registr([
        # zbytek: klíč nastavení už neexistuje
        reg.RegistrZapis("number.napohodu_obyvak_ve_dne_smi_klesnout_pod_cil_o",
                         "obyvak_denni_hystereze"),
        # živé šoupátko pod dnešním jménem
        reg.RegistrZapis(
            "number.napohodu_obyvak_ve_dne_otevrit_pri_odchylce_od_cile_o",
            "obyvak_hyst_den_otevrit"),
    ])
    asyncio.run(m.srovnej(Hass(r), _pokoje("obyvak")))
    assert r.smazane == [
        "number.napohodu_obyvak_ve_dne_smi_klesnout_pod_cil_o"]
    # to živé zůstalo a nepřejmenovalo se
    assert r.prejmenovane == []
    assert r.async_get(
        "number.napohodu_obyvak_ve_dne_otevrit_pri_odchylce_od_cile_o")


def test_zive_soupatko_se_nesmaze(migrace):
    """Jediná chyba tady by znamenala, že člověk přijde o nastavení."""
    m, reg = migrace
    import importlib
    cisla = importlib.import_module("napohodu.number")
    zive = [reg.RegistrZapis(f"number.napohodu_loznice_{i}",
                             f"loznice_{p.klic}")
            for i, p in enumerate(cisla.MISTNOST)]
    zive += [reg.RegistrZapis(f"number.napohodu_byt_{i}", f"x_{p.klic}")
             for i, p in enumerate(cisla.CELY_BYT)]
    r = reg.Registr(zive)
    entry = _pokoje("loznice")
    entry.entry_id = "x"
    asyncio.run(m.srovnej(Hass(r), entry))
    assert r.smazane == []


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


def test_srovnava_se_jen_jednou(migrace):
    """Integrace se načítá znovu při každé změně nastavení. Bez
    poznámky by stejné hlášení chodilo pokaždé — a hlášení, které
    chodí pořád, se přestane číst."""
    m, reg = migrace
    r = reg.Registr([
        reg.RegistrZapis("number.napohodu_loznice_odchylka_teploty",
                         "loznice_odchylka")])
    hass = Hass(r)
    entry = _pokoje("loznice", "kuchyne")
    asyncio.run(m.srovnej(hass, entry))
    # druhé načtení už do registru vůbec nesahá
    r.zapisy.append(
        reg.RegistrZapis("number.napohodu_kuchyne_odchylka_teploty",
                         "kuchyne_odchylka"))
    asyncio.run(m.srovnej(hass, entry))
    assert len(r.prejmenovane) == 1


def test_poznamka_se_zapise_drive_nez_prace(migrace):
    """Změna, kterou srovnání udělá, může spustit další načtení.
    Kdyby se poznámka psala až nakonec, mohlo by se celé kolo
    opakovat pořád dokola a log by zaplavilo jedno hlášení."""
    m, reg = migrace
    from homeassistant.helpers.storage import Store

    r = reg.Registr([reg.RegistrZapis("number.napohodu_loznice_zbytek",
                                      "loznice_zruseno")])
    porad = []

    class Hlidane(Hass):
        pass

    hass = Hlidane(r)
    puvodni = Store.async_save

    async def zaznam(self, data):
        porad.append(("poznámka", dict(data)))
        return await puvodni(self, data)

    Store.async_save = zaznam
    try:
        asyncio.run(m.srovnej(hass, _pokoje("loznice")))
    finally:
        Store.async_save = puvodni
    assert porad and porad[0][1] == {"srovnano": True}
    # a práce se přesto udělala
    assert r.smazane == ["number.napohodu_loznice_zbytek"]


def test_sluzba_spusti_srovnani_znovu(migrace):
    """Když se při instalaci něco nepovedlo, musí jít zkusit to znovu
    bez mazání poznámky ručně v souborech."""
    m, reg = migrace
    r = reg.Registr([reg.RegistrZapis("number.napohodu_loznice_zbytek",
                                      "loznice_zruseno")])
    hass = Hass(r)
    entry = _pokoje("loznice")
    asyncio.run(m.srovnej(hass, entry))
    # po poznámce už srovnej nic nedělá, ale znovu() ano
    r.zapisy.append(reg.RegistrZapis("number.napohodu_kuchyne_zbytek",
                                     "kuchyne_zruseno"))
    asyncio.run(m.srovnej(hass, entry))
    assert len(r.smazane) == 1
    asyncio.run(m.znovu(hass, entry))
    assert len(r.smazane) == 2
