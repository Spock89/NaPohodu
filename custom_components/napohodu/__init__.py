"""Integrace NaPohodu — udržuje v místnostech teplotu a kvalitní vzduch."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (CONF_STINENI_PREDSTIH, DOMAIN,
                    PODENTITA_MISTNOST, PODENTITA_ZONA)
from .coordinator import NaPohoduCoordinator
from .services import zaregistruj

_LOGGER = logging.getLogger(__name__)

PLATFORMY: list[Platform] = [
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.CLIMATE,
    Platform.DATETIME,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
]


def _preved(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Dorovná uložené nastavení na to, co umí tahle verze.

    Měnit výchozí hodnotu nestačí: výchozí platí jen pro nově
    zakládanou místnost, kdežto ta stávající má v konfiguraci
    uloženou tu starou a nic by se u ní nezměnilo.

    Předstih stínění: stínilo se o stupeň dřív, než teplota došla na
    cíl. Zrušeno, stíní se až při překročení cíle. Nastavení zůstává,
    kdo chce stínit dřív, nastaví si ho zpátky.
    """
    for pod in list(entry.subentries.values()):
        if pod.subentry_type != PODENTITA_MISTNOST:
            continue
        stary = pod.data.get(CONF_STINENI_PREDSTIH)
        if stary is None or float(stary) == 0.0:
            continue
        hass.config_entries.async_update_subentry(
            entry, pod, data={**pod.data, CONF_STINENI_PREDSTIH: 0.0})
        _LOGGER.info(
            "NaPohodu: %s — předstih stínění %.1f °C zrušen, stíní se "
            "až při překročení cíle", pod.title, float(stary))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await zaregistruj(hass)
    _preved(hass, entry)

    koordinator = NaPohoduCoordinator(hass, entry)
    await koordinator.async_nacti()
    await koordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = koordinator

    mistnosti = sum(1 for p in entry.subentries.values()
                    if p.subentry_type == PODENTITA_MISTNOST)
    zony = sum(1 for p in entry.subentries.values()
               if p.subentry_type == PODENTITA_ZONA)
    _LOGGER.info("NaPohodu: %d místností, %d zón", mistnosti, zony)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMY)
    entry.async_on_unload(entry.add_update_listener(_znovu_nacti))
    return True


async def _znovu_nacti(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Přibyla nebo se změnila místnost či zóna."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMY)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok
