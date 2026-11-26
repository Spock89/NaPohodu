"""Opravy: co se hlásí, kdy to zmizí a kdy se to nesmí hlásit vůbec.

Hláška, která nezmizí po spravení, je horší než žádná — člověk pak
přestane věřit i těm ostatním. Proto se tu zkouší oba konce: že
položka vznikne, a hlavně že se sama zruší.
"""

import importlib
import pathlib
import sys

import pytest

KOREN = pathlib.Path(__file__).parent.parent


@pytest.fixture
def op():
    sys.path.insert(0, str(KOREN / "tests" / "stub_ha"))
    sys.path.insert(0, str(KOREN / "custom_components"))
    yield importlib.import_module("napohodu.opravy")
    for jmeno in list(sys.modules):
        if jmeno.startswith(("napohodu", "homeassistant")):
            del sys.modules[jmeno]
    sys.path.remove(str(KOREN / "custom_components"))
    sys.path.remove(str(KOREN / "tests" / "stub_ha"))


class _Hass:
    pass


class _Pod:
    def __init__(self, title, data, pod_id="m1"):
        self.title, self.data = title, data
        self.subentry_id = pod_id
        self.subentry_type = "mistnost"


class _Zapis:
    def __init__(self, podentity=(), data=None):
        self.entry_id = "zapis"
        self.data = data or {}
        self.options = {}
        self.subentries = {p.subentry_id: p for p in podentity}


def _opravy(op, hass=None):
    return op.Opravy(hass or _Hass(), "zapis")


def _zalozene(hass):
    return sorted(i for _, i in getattr(hass, "opravy_registr", {}))


def test_entity_v_nastaveni_najde_i_klice(op):
    """Přiřazení stínění má entity v klíčích, ne v hodnotách — právě
    na to se při prvním pokusu zapomnělo."""
    nalez = op.entity_v_nastaveni({
        "okna": ["cover.okno", "cover.druhe"],
        "teplota": "sensor.t",
        "stineni_mapa": {"cover.zaluzie": {"zastinit": "dolu"}},
        "projezd": 30.0,
        "nazev": "Obývák",
        # Text s tečkou, který entita není: desetinné číslo jako řetězec
        # ani věta se takhle vypadat nesmí.
        "poznamka": "21.5 stupně",
    })
    assert nalez == {"cover.okno", "cover.druhe", "sensor.t",
                     "cover.zaluzie"}


def test_chybejici_entita_az_po_trech_cyklech(op):
    """Při startu se integrace načítají postupně. Hlásit hned by
    znamenalo hlásit vždycky po restartu."""
    hass = _Hass()
    o = _opravy(op, hass)
    zapis = _Zapis([_Pod("Dílna", {"teplota": "sensor.zmizela"})])

    for _ in range(op.NEZ_SE_OHLASI - 1):
        o.zacni()
        o.zkontroluj(zapis, lambda e: False)
        o.hotovo()
        assert _zalozene(hass) == []

    o.zacni()
    o.zkontroluj(zapis, lambda e: False)
    o.hotovo()
    assert _zalozene(hass) == ["chybi_sensor.zmizela"]
    zaznam = hass.opravy_registr[("napohodu", "chybi_sensor.zmizela")]
    assert zaznam["translation_key"] == "chybi"
    assert zaznam["translation_placeholders"] == {
        "entita": "sensor.zmizela", "kde": "Dílna"}
    assert zaznam["is_fixable"] is False

    # Entita se vrátila: položka musí zmizet sama.
    o.zacni()
    o.zkontroluj(zapis, lambda e: True)
    o.hotovo()
    assert _zalozene(hass) == []

    # A po dalším smazání se počítá znovu od začátku, ne hned.
    o.zacni()
    o.zkontroluj(zapis, lambda e: False)
    o.hotovo()
    assert _zalozene(hass) == []


def test_entita_v_registru_se_nehlasi(op):
    """Nedostupná entita existuje. Hlásit ji je planý poplach."""
    hass = _Hass()
    o = _opravy(op, hass)
    zapis = _Zapis([_Pod("Ložnice", {"zaluzie": ["cover.je"]})])
    for _ in range(5):
        o.zacni()
        o.zkontroluj(zapis, lambda e: True)
        o.hotovo()
    assert _zalozene(hass) == []


def test_smycka_se_hlasi_a_sama_zmizi(op):
    """Vlastní entita přiřazená jako hlavice. Do protokolu se to píše
    jednou, do Oprav každý cyklus — jinak by položka hned zmizela."""
    hass = _Hass()
    o = _opravy(op, hass)
    zapis = _Zapis()

    for _ in range(3):
        o.zacni()
        o.nahlas("smycka", "climate.napohodu_termostat",
                 entita="climate.napohodu_termostat", kde="Obývák",
                 co="hlavice")
        o.zkontroluj(zapis, lambda e: True)
        o.hotovo()
    assert _zalozene(hass) == ["smycka_climate.napohodu_termostat"]
    zaznam = hass.opravy_registr[
        ("napohodu", "smycka_climate.napohodu_termostat")]
    assert zaznam["severity"] == "error"

    # Přiřazení se spravilo: cyklus bez hlášení položku zruší.
    o.zacni()
    o.zkontroluj(zapis, lambda e: True)
    o.hotovo()
    assert _zalozene(hass) == []


def test_dve_chybejici_cidla_jsou_dve_polozky(op):
    """Jedna položka na všechno by neřekla, co přenastavit."""
    hass = _Hass()
    o = _opravy(op, hass)
    zapis = _Zapis([_Pod("Dílna", {"a": "sensor.jedna", "b": "sensor.dva"})])
    for _ in range(op.NEZ_SE_OHLASI):
        o.zacni()
        o.zkontroluj(zapis, lambda e: False)
        o.hotovo()
    assert _zalozene(hass) == ["chybi_sensor.dva", "chybi_sensor.jedna"]


def test_jednotka_se_hlasi_dokud_cidlo_je_v_nastaveni(op):
    """Jednotka se kontroluje jednou, ale hlásit se musí pořád."""
    hass = _Hass()
    o = _opravy(op, hass)
    zapis = _Zapis(data={"t_venku": "sensor.venku"})
    o.jednotka("sensor.venku", "teplota", "°F", "°C")

    for _ in range(3):
        o.zacni()
        o.zkontroluj(zapis, lambda e: True)
        o.hotovo()
    assert _zalozene(hass) == ["jednotka_sensor.venku"]
    assert hass.opravy_registr[("napohodu", "jednotka_sensor.venku")][
        "translation_placeholders"] == {
            "entita": "sensor.venku", "popis": "teplota",
            "jednotka": "°F", "ocekavane": "°C"}

    # Čidlo se z nastavení odebralo: hláška o něm nemá co dělat.
    o.zacni()
    o.zkontroluj(_Zapis(), lambda e: True)
    o.hotovo()
    assert _zalozene(hass) == []


def test_preklady_maji_vsechny_hlasky(op):
    """Chybějící překlad se v Opravách pozná jako prázdná položka."""
    import json

    for jazyk in ("cs", "en"):
        cesta = (KOREN / "custom_components" / "napohodu" / "translations"
                 / f"{jazyk}.json")
        issues = json.loads(cesta.read_text())["issues"]
        assert set(issues) == set(op.ZAVAZNOST)
        for druh, text in issues.items():
            assert text["title"] and text["description"], druh


def test_zastupne_texty_v_prekladu_odpovidaji_hlasenym(op):
    """Zástupný text, který se nedoplní, zůstane v hlášce jako {kde}."""
    import json
    import re

    hlasene = {
        "smycka": {"entita", "kde", "co"},
        "chybi": {"entita", "kde"},
        # Společné nastavení nemá jméno místnosti, kam poslat — cesta
        # k němu je jiná, takže má vlastní hlášku i vlastní návod.
        "chybi_byt": {"entita"},
        "jednotka": {"entita", "popis", "jednotka", "ocekavane"},
    }
    for jazyk in ("cs", "en"):
        cesta = (KOREN / "custom_components" / "napohodu" / "translations"
                 / f"{jazyk}.json")
        issues = json.loads(cesta.read_text())["issues"]
        for druh, text in issues.items():
            pouzite = set(re.findall(r"\{(\w+)\}",
                                     text["title"] + text["description"]))
            assert pouzite <= hlasene[druh], (jazyk, druh, pouzite)


def test_spolecne_nastaveni_ma_vlastni_hlasku(op):
    """Návod pro místnost posílá na „Upravit" u podentity. Ve
    společném nastavení se tam nedá dojít, takže by lhal."""
    hass = _Hass()
    o = _opravy(op, hass)
    zapis = _Zapis(data={"t_prumer": "sensor.zmizela"})

    for _ in range(op.NEZ_SE_OHLASI):
        o.zacni()
        o.zkontroluj(zapis, lambda e: False)
        o.hotovo()

    assert _zalozene(hass) == ["chybi_byt_sensor.zmizela"]
    zaznam = hass.opravy_registr[("napohodu", "chybi_byt_sensor.zmizela")]
    assert zaznam["translation_key"] == "chybi_byt"
    # Jméno místnosti tu nemá co dělat.
    assert zaznam["translation_placeholders"] == {"entita": "sensor.zmizela"}
