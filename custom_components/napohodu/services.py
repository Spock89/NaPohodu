"""Služby pro ladění a ovládání žaluzií.

Tester je udělaný jako služba, protože Nástroje pro vývojáře ukážou
odpověď rovnou pod formulářem. Vyzkoušíš posloupnost, vidíš polohu před
a po, a když sedí, uložíš ji jedním dalším voláním pod jménem.
"""

from __future__ import annotations

import asyncio
import logging
import time

import voluptuous as vol

from homeassistant.core import (HomeAssistant, ServiceCall, ServiceResponse,
                                SupportsResponse)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store

from . import sekvence as sq
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ULOZISTE = f"{DOMAIN}.stavy_stineni"

ATR_ZALUZIE = "zaluzie"
ATR_SEKVENCE = "sekvence"
ATR_NAZEV = "nazev"
ATR_TIMEOUT = "timeout_polohy_s"

SCHEMA_TEST = vol.Schema({
    vol.Required(ATR_ZALUZIE): cv.entity_id,
    vol.Required(ATR_SEKVENCE): cv.string,
    vol.Optional(ATR_TIMEOUT, default=30): vol.Coerce(float),
})
SCHEMA_ULOZ = vol.Schema({
    vol.Required(ATR_ZALUZIE): cv.entity_id,
    vol.Required(ATR_NAZEV): cv.string,
    vol.Required(ATR_SEKVENCE): cv.string,
})
SCHEMA_NASTAV = vol.Schema({
    vol.Required(ATR_ZALUZIE): cv.entity_id,
    vol.Required(ATR_NAZEV): cv.string,
})
SCHEMA_SEZNAM = vol.Schema({vol.Optional(ATR_ZALUZIE): cv.entity_id})
SCHEMA_SMAZ = SCHEMA_NASTAV


class OvladacHA:
    """Vykonává kroky přes služby cover. Jedna žaluzie, jedno vlákno."""

    def __init__(self, hass: HomeAssistant, entita: str) -> None:
        self.hass = hass
        self.entita = entita

    async def poloha(self) -> float | None:
        st = self.hass.states.get(self.entita)
        if st is None:
            return None
        hodnota = st.attributes.get("current_position")
        if hodnota is None:
            # pohony bez procent hlásí aspoň otevřeno a zavřeno
            if st.state == "open":
                return 100.0
            if st.state == "closed":
                return 0.0
            return None
        try:
            return float(hodnota)
        except (TypeError, ValueError):
            return None

    async def _sluzba(self, sluzba: str, data: dict | None = None) -> None:
        await self.hass.services.async_call(
            "cover", sluzba, {"entity_id": self.entita, **(data or {})},
            blocking=True,
        )

    async def nastav_polohu(self, hodnota: float) -> None:
        await self._sluzba("set_cover_position", {"position": hodnota})

    async def nastav_tilt(self, hodnota: float) -> None:
        await self._sluzba("set_cover_tilt_position",
                           {"tilt_position": hodnota})

    async def stop(self) -> None:
        await self._sluzba("stop_cover")

    async def cekej(self, sekund: float) -> None:
        await asyncio.sleep(sekund)

    def cas(self) -> float:
        return time.monotonic()


class Stavy:
    """Uložené pojmenované stavy. Klíč je entita žaluzie."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store = Store(hass, 1, ULOZISTE)
        self._data: dict[str, dict[str, str]] = {}

    async def nacti(self) -> None:
        self._data = await self._store.async_load() or {}

    def pro(self, zaluzie: str) -> dict[str, str]:
        return dict(self._data.get(zaluzie, {}))

    def vse(self) -> dict[str, dict[str, str]]:
        return {k: dict(v) for k, v in self._data.items()}

    async def uloz(self, zaluzie: str, nazev: str, zapis: str) -> None:
        self._data.setdefault(zaluzie, {})[nazev] = zapis
        await self._store.async_save(self._data)

    async def nahrad(self, zaluzie: str, stavy: dict[str, str]) -> None:
        if stavy:
            self._data[zaluzie] = dict(stavy)
        else:
            self._data.pop(zaluzie, None)
        await self._store.async_save(self._data)

    async def smaz(self, zaluzie: str, nazev: str) -> bool:
        if nazev not in self._data.get(zaluzie, {}):
            return False
        del self._data[zaluzie][nazev]
        if not self._data[zaluzie]:
            del self._data[zaluzie]
        await self._store.async_save(self._data)
        return True


def _stavy(hass: HomeAssistant) -> "Stavy":
    return hass.data.setdefault(DOMAIN, {})["stavy_stineni"]


async def proved_sekvenci(hass: HomeAssistant, entita: str, zapis: str,
                          timeout_s: float = 30.0) -> dict:
    """Provede posloupnost. Volá se ze služby i z testeru v nastavení."""
    try:
        kroky = sq.preved(zapis)
    except sq.ChybaSekvence as e:
        return {"povedlo_se": False, "chyba": str(e), "sekvence": zapis}

    if hass.states.get(entita) is None:
        return {"povedlo_se": False, "chyba": f"Entita {entita} neexistuje."}

    zamky = hass.data.setdefault(DOMAIN, {}).setdefault("zamky_zaluzii", {})
    zamek = zamky.setdefault(entita, asyncio.Lock())
    async with zamek:
        vysledek = await sq.spust(kroky, OvladacHA(hass, entita), timeout_s)

    out = vysledek.jako_slovnik()
    out["sekvence"] = sq.zpet(kroky)
    out["odhad_s"] = sq.doba_s(kroky)
    return out


def nacti_stavy(hass: HomeAssistant, entita: str) -> dict:
    """Uložené stavy jedné žaluzie. Prázdné, když ještě žádné nejsou."""
    stavy = hass.data.get(DOMAIN, {}).get("stavy_stineni")
    return stavy.pro(entita) if stavy else {}


async def proved_stav_stineni(hass: HomeAssistant, entita: str,
                              nazev: str) -> dict:
    """Provede uložený pojmenovaný stav."""
    stavy = hass.data.get(DOMAIN, {}).get("stavy_stineni")
    if stavy is None:
        return {"povedlo_se": False, "chyba": "Stavy nejsou načtené."}
    ulozene = stavy.pro(entita)
    if nazev not in ulozene:
        return {"povedlo_se": False,
                "chyba": f"Stav {nazev!r} pro {entita} není uložený.",
                "dostupne": sorted(ulozene)}
    return await proved_sekvenci(hass, entita, ulozene[nazev], 30.0)


async def uloz_hromadne(hass: HomeAssistant, entita: str,
                        text: str) -> dict:
    """Nahradí všechny stavy jedné žaluzie tím, co je v textu."""
    try:
        stavy = sq.z_textu(text)
    except sq.ChybaSekvence as e:
        return {"povedlo_se": False, "chyba": str(e)}
    await _stavy(hass).nahrad(entita, stavy)
    return {"povedlo_se": True, "pocet": len(stavy)}


async def uloz_stav_stineni(hass: HomeAssistant, entita: str, nazev: str,
                            zapis: str) -> dict:
    try:
        kroky = sq.preved(zapis)
    except sq.ChybaSekvence as e:
        return {"povedlo_se": False, "chyba": str(e)}
    await _stavy(hass).uloz(entita, nazev, sq.zpet(kroky))
    return {"povedlo_se": True, "nazev": nazev, "sekvence": sq.zpet(kroky)}


async def zaregistruj(hass: HomeAssistant) -> None:
    """Zaregistruje služby. Volá se jednou při prvním nastavení."""
    if hass.services.has_service(DOMAIN, "test_sekvence"):
        return

    stavy = Stavy(hass)
    await stavy.nacti()
    hass.data.setdefault(DOMAIN, {})["stavy_stineni"] = stavy

    async def _proved(entita: str, zapis: str, timeout: float) -> dict:
        return await proved_sekvenci(hass, entita, zapis, timeout)

    async def test_sekvence(call: ServiceCall) -> ServiceResponse:
        vysledek = await _proved(call.data[ATR_ZALUZIE],
                                 call.data[ATR_SEKVENCE],
                                 call.data[ATR_TIMEOUT])
        if vysledek.get("povedlo_se"):
            vysledek["napoveda"] = (
                "Pokud poloha sedí, ulož ji službou Uložit stav stínění "
                "se stejnou posloupností.")
        return vysledek

    async def uloz_stav(call: ServiceCall) -> ServiceResponse:
        return await uloz_stav_stineni(
            hass, call.data[ATR_ZALUZIE], call.data[ATR_NAZEV],
            call.data[ATR_SEKVENCE])

    async def nastav_stineni(call: ServiceCall) -> ServiceResponse:
        return await proved_stav_stineni(
            hass, call.data[ATR_ZALUZIE], call.data[ATR_NAZEV])

    async def seznam_stavu(call: ServiceCall) -> ServiceResponse:
        entita = call.data.get(ATR_ZALUZIE)
        return {"stavy": stavy.pro(entita) if entita else stavy.vse()}

    async def smaz_stav(call: ServiceCall) -> ServiceResponse:
        smazano = await stavy.smaz(call.data[ATR_ZALUZIE], call.data[ATR_NAZEV])
        return {"povedlo_se": smazano}

    # OPTIONAL, ne ONLY: služba jde zavolat i ze skriptu, kde odpověď
    # nikoho nezajímá. ONLY vynucuje response_variable u každého volání.
    for jmeno, funkce, schema in (
        ("test_sekvence", test_sekvence, SCHEMA_TEST),
        ("uloz_stav", uloz_stav, SCHEMA_ULOZ),
        ("nastav_stineni", nastav_stineni, SCHEMA_NASTAV),
        ("seznam_stavu", seznam_stavu, SCHEMA_SEZNAM),
        ("smaz_stav", smaz_stav, SCHEMA_SMAZ),
    ):
        hass.services.async_register(
            DOMAIN, jmeno, funkce, schema=schema,
            supports_response=SupportsResponse.OPTIONAL,
        )
