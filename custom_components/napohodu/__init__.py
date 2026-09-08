"""Integrace NaPohodu — udržuje v místnostech teplotu a kvalitní vzduch."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PODENTITA_MISTNOST, PODENTITA_ZONA
from .coordinator import PohodaCoordinator
from .services import zaregistruj

_LOGGER = logging.getLogger(__name__)

PLATFORMY: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await zaregistruj(hass)

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
