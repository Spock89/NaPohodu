"""Vymazání pole v nastavení se musí udržet.

Do průměru za deset dní se dostalo cizí čidlo. Vymazat ho nešlo:
po uložení bylo zpátky ve formuláři a integrace podle něj dál
počítala cílovou teplotu.

Příčina je v tom, jak formuláře Home Assistantu vracejí výsledek —
prázdné pole se ve výsledku neobjeví vůbec. Starý kód nové hodnoty
jen přisypával k starým, takže vymazaný klíč zůstal po starém.
"""

import asyncio

import pytest


@pytest.fixture(scope="module")
def cf():
    import importlib
    import pathlib
    import sys

    koren = pathlib.Path(__file__).parent.parent
    sys.path.insert(0, str(koren / "tests" / "stub_ha"))
    sys.path.insert(0, str(koren / "custom_components"))
    m = importlib.import_module("napohodu.config_flow")
    c = importlib.import_module("napohodu.const")
    yield m, c
    for jmeno in list(sys.modules):
        if jmeno.startswith(("napohodu", "homeassistant")):
            del sys.modules[jmeno]
    sys.path.remove(str(koren / "custom_components"))
    sys.path.remove(str(koren / "tests" / "stub_ha"))


class _Zapis:
    def __init__(self, data, options):
        self.data = dict(data)
        self.options = dict(options)


class _Spravce:
    """Zaznamenává, co se do zápisu uložilo."""

    def __init__(self):
        self.zapsano = []

    def async_update_entry(self, zapis, data=None, options=None):
        if data is not None:
            zapis.data = dict(data)
        if options is not None:
            zapis.options = dict(options)
        self.zapsano.append((dict(zapis.data), dict(zapis.options)))
        return True


class _Hass:
    def __init__(self):
        self.config_entries = _Spravce()


def test_poskladej_zahodi_vymazane_pole(cf):
    m, c = cf
    stare = {"a": "sensor.stary", "b": 3, "jine": "zustane"}
    import voluptuous as vol

    schema = vol.Schema({vol.Optional("a"): str, vol.Optional("b"): int})
    nove = m._poskladej(stare, schema, {"b": 5})
    assert "a" not in nove, "pole vymazané ve formuláři musí zmizet"
    assert nove["b"] == 5
    assert nove["jine"] == "zustane", "na co se krok neptal, zůstává"


def test_vymazani_prumeru_se_udrzi(cf):
    """Hodnota byla v data, uložení psalo jen do options — a protože
    se nastavení čte jako data překrytá options, vracela se zpátky."""
    m, c = cf

    zapis = _Zapis({c.CONF_T_VENKU: "sensor.venku",
                    c.CONF_T_PRUMER: "sensor.spatny"}, {})
    tok = m.NaPohoduOptionsFlow()
    tok.hass = _Hass()
    tok.config_entry = zapis
    tok.async_create_entry = lambda **kw: {"data": kw.get("data")}

    # formulář odeslaný s vymazaným polem průměru: klíč v něm není
    vysledek = asyncio.run(tok.async_step_nastaveni(
        {c.CONF_T_VENKU: "sensor.venku"}))

    assert c.CONF_T_PRUMER not in vysledek["data"]
    # a hlavně: ani v jednom z míst, odkud se nastavení skládá
    slozene = {**zapis.data, **zapis.options}
    assert c.CONF_T_PRUMER not in slozene, slozene
    assert slozene[c.CONF_T_VENKU] == "sensor.venku"


def test_vymazani_pole_mistnosti_se_udrzi(cf):
    """Úprava místnosti skládá jeden formulář ze čtyř kroků a stejně
    tak si vymazané pole přepisovala starou hodnotou."""
    m, c = cf

    tok = m.MistnostSubentryFlow()
    tok._data = {c.CONF_NAZEV: "Kuchyně",
                 c.CONF_TEPLOTY: ["sensor.t"],
                 c.CONF_CO2: ["sensor.co2_cizi"],
                 c.CONF_STINENI_MAPA: {"x": {"vychozi": "y"}}}
    tok._ostatni_mistnosti = lambda: []
    schema = (m._schema_mistnost()
              .extend(m._schema_chovani([]).schema)
              .extend(m.SCHEMA_PRITOMNOST.schema)
              .extend(m.SCHEMA_INDICIE.schema))
    nove = m._poskladej(tok._data, schema,
                        {c.CONF_NAZEV: "Kuchyně",
                         c.CONF_TEPLOTY: ["sensor.t"]})

    assert c.CONF_CO2 not in nove, "vymazané čidlo CO2 musí zmizet"
    # mapa stínění se v tomhle formuláři nevyplňuje, ať nezmizí s ním
    assert nove[c.CONF_STINENI_MAPA] == {"x": {"vychozi": "y"}}


def test_formular_mistnosti_se_ptá_jen_na_to_co_tam_je(cf):
    """Proklikat se desítkami polí, ze kterých polovina nic nedělá,
    je nepřehledné. Chování zařízení, které v místnosti není, se
    neukazuje — pole pro přiřazení toho zařízení ale zůstává jinde,
    v základním kroku, takže jde přidat vždycky.
    """
    m, c = cf

    def pole(data):
        return {str(k.schema) for k
                in m._schema_chovani([], data).schema}

    holá = pole({})
    vse = pole({c.CONF_OKNA: ["cover.o"], c.CONF_ZALUZIE: ["cover.z"],
                c.CONF_ZVLHCOVAC: ["switch.v"], c.CONF_CISTICKA: ["fan.c"],
                c.CONF_CLIMATE: ["climate.h"]})
    assert len(holá) < len(vse) / 2, (len(holá), len(vse))

    # čeho se to týká
    assert c.CONF_STINENI_PREDSTIH in vse and c.CONF_STINENI_PREDSTIH not in holá
    assert c.CONF_RH_MIN in vse and c.CONF_RH_MIN not in holá
    assert c.CONF_UTLUM in vse and c.CONF_UTLUM not in holá
    assert c.CONF_PROJEZD_M in vse and c.CONF_PROJEZD_M not in holá
    assert c.CONF_PRACH_DOSAH in vse and c.CONF_PRACH_DOSAH not in holá

    # Odchylka od cíle zůstává vždycky: posouvá cílovou teplotu,
    # ať se v místnosti větrá nebo ne.
    assert c.CONF_ODCHYLKA in holá

    # Prahy CO2 a pásmo kolem cíle patří i místnosti bez vlastního
    # okna, pokud je v oblasti — tam si jimi říká sousedovi o vyvětrání.
    v_zone = {str(k.schema) for k
              in m._schema_chovani([], {}, v_zone=True).schema}
    for klic in (c.CONF_CO2_OTEVRIT, c.CONF_MEZ_DOLNI, c.CONF_MEZ_HORNI):
        assert klic in v_zone, klic
        assert klic not in holá, klic

    # jednotlivě: žaluzie zapnou jen stínění, ne zvlhčovač
    jen_zaluzie = pole({c.CONF_ZALUZIE: ["cover.z"]})
    assert c.CONF_STINENI_PREDSTIH in jen_zaluzie
    assert c.CONF_RH_MIN not in jen_zaluzie


def test_spolecne_nastaveni_schova_jen_to_co_nema_druhy_zdroj(cf):
    """Schovat pole podle prázdného výběru entity smí jen tam, kde
    ta entita je jediný zdroj.

    Vítr jiný zdroj nemá: bez čidla se o větru nedozvíme nic.
    Příchody ale chodí i z vlastního kalendáře integrace, kam se
    události přidávají z dashboardu — tedy dlouho potom, co se
    integrace nastavovala. Prázdné pole pro cizí kalendář neznamená,
    že žádné příchody nejsou, takže předvětrání musí zůstat.
    """
    m, c = cf

    def pole(data):
        return {str(k.schema) for k in m._global_pro(data).schema}

    bez = pole({})
    assert c.CONF_VITR_PRAH not in bez
    assert c.CONF_NARAZ_PRAH not in bez
    assert c.CONF_PREDVETRAT in bez, "příchody chodí i z vlastního plánu"

    # čidlo samotné zůstává, jinak by nebylo jak ho přidat
    assert c.CONF_VITR in bez and c.CONF_PLAN_VIC in bez

    s_vetrem = pole({c.CONF_VITR: "sensor.v"})
    assert c.CONF_VITR_PRAH in s_vetrem
    assert c.CONF_VITR_KLID in s_vetrem
