"""Tlačítka na srovnání do žádané polohy.

Integrace si pamatuje, co naposledy poslala, a stejný povel neopakuje.
Po ručním přestavení nebo po restartu se proto může stát, že skutečnost
neodpovídá tomu, co automatika chce. Tlačítko tu paměť zahodí a povely
se pošlou znovu.

Ovládání to neobchází: kde je přepínač vypnutý, se nic nestane.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PODENTITA_MISTNOST, PODENTITA_ZONA
from .entity import NaPohoduEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = hass.data[DOMAIN][entry.entry_id]
    for pod in entry.subentries.values():
        if pod.subentry_type == PODENTITA_ZONA:
            pridat([Srovnat(k, pod, "srovnat_okno")],
                   config_subentry_id=pod.subentry_id)
        elif pod.subentry_type == PODENTITA_MISTNOST:
            pridat([Srovnat(k, pod, "srovnat_stineni")],
                   config_subentry_id=pod.subentry_id)
    pridat([SrovnatVse(k, entry)])


class Srovnat(NaPohoduEntity, ButtonEntity):
    """Srovná jednu místnost nebo zónu."""

    _attr_icon = "mdi:sync"

    async def async_press(self) -> None:
        self.coordinator.srovnej(self.pod_id)
        await self.coordinator.async_request_refresh()


class SrovnatVse(CoordinatorEntity, ButtonEntity):
    """Srovná všechno naráz. Hodí se po restartu."""

    _attr_has_entity_name = True
    _attr_translation_key = "srovnat_vse"
    _attr_icon = "mdi:sync-circle"

    def __init__(self, koordinator, entry) -> None:
        super().__init__(koordinator)
        self._attr_unique_id = f"{entry.entry_id}_srovnat_vse"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="NaPohodu", manufacturer="NaPohodu", model="Společné",
        )

    async def async_press(self) -> None:
        self.coordinator.srovnej()
        await self.coordinator.async_request_refresh()
