"""Přepínač, kterým se zóně povolí sahat na okno.

Ve výchozím stavu vypnutý. Do té doby integrace jen počítá a ukazuje,
co by udělala, což je bezpečnější způsob, jak ji poprvé nasadit.
"""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, PODENTITA_ZONA
from .entity import NaPohoduEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = hass.data[DOMAIN][entry.entry_id]
    for pod in entry.subentries.values():
        if pod.subentry_type == PODENTITA_ZONA:
            pridat([OvladatOkno(k, pod), OvladatStineni(k, pod)],
                   config_subentry_id=pod.subentry_id)


class NaPohoduPrepinac(NaPohoduEntity, SwitchEntity, RestoreEntity):
    """Povolení sahat na pohon. Ve výchozím stavu vypnuté."""

    _attr_entity_category = EntityCategory.CONFIG
    _klic_hodnoty = "ovladat"

    def __init__(self, k, pod, klic):
        super().__init__(k, pod, klic)
        self._zap = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        posledni = await self.async_get_last_state()
        if posledni is not None:
            self._zap = posledni.state == "on"
        self.coordinator.hodnoty[
            (self.pod_id, self._klic_hodnoty)] = float(self._zap)

    @property
    def is_on(self) -> bool:
        return self._zap

    async def async_turn_on(self, **kwargs) -> None:
        await self._nastav(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._nastav(False)

    async def _nastav(self, hodnota: bool) -> None:
        self._zap = hodnota
        self.coordinator.hodnoty[
            (self.pod_id, self._klic_hodnoty)] = float(hodnota)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class OvladatOkno(NaPohoduPrepinac):
    _attr_icon = "mdi:window-shutter-auto"
    _klic_hodnoty = "ovladat"

    def __init__(self, k, pod):
        super().__init__(k, pod, "ovladat_okno")


class OvladatStineni(NaPohoduPrepinac):
    _attr_icon = "mdi:blinds-horizontal"
    _klic_hodnoty = "ovladat_stineni"

    def __init__(self, k, pod):
        super().__init__(k, pod, "ovladat_stineni")
