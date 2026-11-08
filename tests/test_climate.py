"""Termostat místnosti: navenek climate, uvnitř odchylka od cíle.

Cíl si integrace počítá sama a místnost ho posouvá jen odchylkou.
Termostatová karta ale umí mluvit jen o absolutní teplotě, takže
překlad mezi obojím je celá tahle platforma — a právě v něm se dá
rozbít to, proč integrace vznikla.
"""

import asyncio
import pathlib
import sys

import pytest

KOREN = pathlib.Path(__file__).parent.parent


@pytest.fixture(scope="module")
def cl():
    import importlib

    sys.path.insert(0, str(KOREN / "tests" / "stub_ha"))
    sys.path.insert(0, str(KOREN / "custom_components"))
    m = importlib.import_module("napohodu.climate")
    yield m
    for jmeno in list(sys.modules):
        if jmeno.startswith(("napohodu", "homeassistant")):
            del sys.modules[jmeno]
    sys.path.remove(str(KOREN / "custom_components"))
    sys.path.remove(str(KOREN / "tests" / "stub_ha"))


class _M:
    def __init__(self, zaklad=21.0, odchylka=0.0, teplota=20.0,
                 plan_cil=None, povel=None):
        self.cil_zaklad = zaklad
        self.cil = round(zaklad + odchylka, 1) if plan_cil is None \
            else plan_cil
        self.teplota = teplota
        self.plan_cil = plan_cil
        self.povel_topeni = povel
        self.nazev = "Obývák"


class _K:
    def __init__(self, m, odchylka=0.0, topeni=1.0):
        self.mistnosti = {"id": m}
        self.hodnoty = {("id", "odchylka"): odchylka,
                        ("id", "ovladat_topeni"): topeni}
        self.obnoveno = False

    def hodnota(self, pod_id, klic, vychozi):
        return self.hodnoty.get((pod_id, klic), vychozi)

    def async_update_listeners(self):
        pass

    async def async_request_refresh(self):
        self.obnoveno = True


def _termostat(cl, m, **kw):
    e = cl.TermostatMistnosti.__new__(cl.TermostatMistnosti)
    e.coordinator = _K(m, **kw)
    e.pod_id = "id"
    e.async_write_ha_state = lambda: None
    return e


def test_cil_je_zaklad_plus_odchylka(cl):
    e = _termostat(cl, _M(zaklad=21.0, odchylka=0.5), odchylka=0.5)
    assert e.target_temperature == 21.5
    assert e.current_temperature == 20.0
    # kolečko se dá otočit jen tam, kam dosáhne odchylka
    assert e.min_temp == 18.0 and e.max_temp == 24.0


def test_nastaveni_teploty_se_prepocita_na_odchylku(cl):
    """Jádro věci: nastavuje se posun, ne teplota.

    Kdyby se ukládala absolutní hodnota, přestal by cíl sledovat
    venkovní průměr — a to je celé, proč integrace vznikla.
    """
    e = _termostat(cl, _M(zaklad=21.0))
    asyncio.run(e.async_set_temperature(temperature=22.0))
    assert e.coordinator.hodnoty[("id", "odchylka")] == 1.0
    assert e.coordinator.obnoveno


def test_odchylka_se_drzi_mrizky_posuvniku(cl):
    """Hodnota mimo krok posuvníku by se v nastavení ukázala tam,
    kam posuvníkem nejde dojet."""
    e = _termostat(cl, _M(zaklad=21.37))
    asyncio.run(e.async_set_temperature(temperature=22.0))
    assert e.coordinator.hodnoty[("id", "odchylka")] == 0.5


def test_dal_nez_mez_to_nepusti(cl):
    e = _termostat(cl, _M(zaklad=21.0))
    asyncio.run(e.async_set_temperature(temperature=40.0))
    assert e.coordinator.hodnoty[("id", "odchylka")] == 3.0
    asyncio.run(e.async_set_temperature(temperature=0.0))
    assert e.coordinator.hodnoty[("id", "odchylka")] == -3.0


def test_naplanovany_cil_se_neda_prebit_tise(cl):
    """Plán cíl přebíjí, takže uložená odchylka by nic neudělala.

    Mlčky to spolknout je horší než to říct: kolečko by se na kartě
    vrátilo zpátky a vypadalo by to, že termostat nefunguje.
    """
    from homeassistant.exceptions import ServiceValidationError

    e = _termostat(cl, _M(zaklad=21.0, plan_cil=18.0))
    assert e.target_temperature == 18.0
    with pytest.raises(ServiceValidationError) as chyba:
        asyncio.run(e.async_set_temperature(temperature=22.0))
    assert "18.0" in str(chyba.value)
    # a nic se nezměnilo
    assert e.coordinator.hodnoty[("id", "odchylka")] == 0.0


def test_vypnuti_sedi_na_prepinaci_topeni(cl):
    """OFF vypne zápis do hlavic, ne okna a stínění."""
    from homeassistant.components.climate import HVACAction, HVACMode

    e = _termostat(cl, _M(povel=22.0))
    assert e.hvac_mode is HVACMode.HEAT
    asyncio.run(e.async_set_hvac_mode(HVACMode.OFF))
    assert e.coordinator.hodnoty[("id", "ovladat_topeni")] == 0.0
    assert e.hvac_mode is HVACMode.OFF
    assert e.hvac_action is HVACAction.OFF
    # okna ani stínění tím nezhasla
    assert ("id", "ovladat") not in e.coordinator.hodnoty
    assert ("id", "ovladat_stineni") not in e.coordinator.hodnoty


def test_topi_se_podle_povelu_ne_podle_cile(cl):
    """Útlum i otevřené okno stahují povel pod cíl. Podle cíle by
    karta tvrdila, že se topí, i když se netopí schválně."""
    from homeassistant.components.climate import HVACAction

    topi = _termostat(cl, _M(teplota=20.0, povel=22.0))
    assert topi.hvac_action is HVACAction.HEATING
    # cíl pořád 21, ale hlavicím jde útlum na 16
    utlumeno = _termostat(cl, _M(teplota=20.0, povel=16.0))
    assert utlumeno.hvac_action is HVACAction.IDLE
    # dokud se nic neposlalo, netvrdíme nic
    nevime = _termostat(cl, _M(teplota=20.0, povel=None))
    assert nevime.hvac_action is HVACAction.IDLE
