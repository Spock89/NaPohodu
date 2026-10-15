"""Od kdy do kdy u plánované události.

Dvě pole, která se dají naklikat přímo na dashboardu. Hodnota se
pamatuje přes restart, aby se po něm nezačínalo od prázdna.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN

# Výchozí návrh: dnešek od teď do půlnoci. Nejčastější případ je
# „dneska to bude jinak", takže ať se nemusí klikat zbytečně.
OD_ZA_MIN = 0
DO_ZA_H = 6


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = hass.data[DOMAIN][entry.entry_id]
    pridat([CasPlanu(k, entry, "plan_od", OD_ZA_MIN / 60),
            CasPlanu(k, entry, "plan_do", DO_ZA_H)])


class CasPlanu(CoordinatorEntity, RestoreEntity, DateTimeEntity):
    """Jeden z časů pro tlačítko Naplánovat."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, k, entry: ConfigEntry, klic: str,
                 za_hodin: float) -> None:
        super().__init__(k)
        self._klic = klic
        self._za_hodin = za_hodin
        self._hodnota: datetime | None = None
        self._attr_translation_key = klic
        self._attr_unique_id = f"{entry.entry_id}_{klic}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="NaPohodu", manufacturer="NaPohodu", model="Byt")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        posledni = await self.async_get_last_state()
        if posledni is not None:
            self._hodnota = dt_util.parse_datetime(posledni.state)
        if self._hodnota is None:
            self._hodnota = dt_util.utcnow() + timedelta(
                hours=self._za_hodin)
        self._uloz()

    @property
    def native_value(self) -> datetime | None:
        return self._hodnota

    async def async_set_value(self, value: datetime) -> None:
        self._hodnota = value
        self._uloz()
        self.async_write_ha_state()

    def _uloz(self) -> None:
        """Hodnotu drží koordinátor, odkud si ji tlačítko vezme.

        Hledat entitu podle jména by se rozešlo při prvním
        přejmenování.
        """
        setattr(self.coordinator, self._klic, self._hodnota)
