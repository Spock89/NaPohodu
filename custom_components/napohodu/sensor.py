"""Textový stav zóny a cílová teplota místnosti."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PODENTITA_MISTNOST, PODENTITA_ZONA
from .entity import NaPohoduEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = hass.data[DOMAIN][entry.entry_id]
    for pod in entry.subentries.values():
        if pod.subentry_type == PODENTITA_ZONA:
            pridat([StavZony(k, pod)], config_subentry_id=pod.subentry_id)
        elif pod.subentry_type == PODENTITA_MISTNOST:
            pridat([CilMistnosti(k, pod), SlunceMistnosti(k, pod)],
                   config_subentry_id=pod.subentry_id)
    pridat([Prumer(k, entry, "prumer_tyden", "tyden"),
            Prumer(k, entry, "prumer_tri_dny", "tri_dny")])


class StavZony(NaPohoduEntity, SensorEntity):
    """Co zóna dělá a proč. Totéž, co bylo v Node-REDu pod uzlem."""

    _attr_icon = "mdi:window-open-variant"

    def __init__(self, k, pod):
        super().__init__(k, pod, "stav")

    @property
    def native_value(self) -> str | None:
        z = self.zona
        if z is None or z.rozhodnuti is None:
            return None
        return z.rozhodnuti.duvod[:255]

    @property
    def extra_state_attributes(self) -> dict:
        z = self.zona
        return z.atributy if z else {}


class CilMistnosti(NaPohoduEntity, SensorEntity):
    """Cíl pro tuhle místnost, tedy adaptivní teplota plus odchylka."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, k, pod):
        super().__init__(k, pod, "cil")

    @property
    def native_value(self):
        m = self.mistnost
        return m.cil if m else None

    @property
    def extra_state_attributes(self) -> dict:
        m = self.mistnost
        return m.atributy if m else {}


class SlunceMistnosti(NaPohoduEntity, SensorEntity):
    """Kolik slunce právě dopadá na okna místnosti."""

    _attr_native_unit_of_measurement = "W/m²"
    _attr_icon = "mdi:weather-sunny"

    def __init__(self, k, pod):
        super().__init__(k, pod, "slunce")

    @property
    def native_value(self):
        m = self.mistnost
        return m.slunce if m else None

    @property
    def extra_state_attributes(self) -> dict:
        m = self.mistnost
        if not m:
            return {}
        return {k: v for k, v in m.atributy.items()
                if k in ("stineni", "stineni_stav")}


class Prumer(CoordinatorEntity, SensorEntity):
    """Klouzavé průměry venkovní teploty, které si integrace počítá sama."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, koordinator, entry, klic: str, pole: str) -> None:
        super().__init__(koordinator)
        self._pole = pole
        self._attr_translation_key = klic
        self._attr_unique_id = f"{entry.entry_id}_{klic}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="NaPohodu", manufacturer="NaPohodu", model="Společné",
        )

    @property
    def native_value(self):
        return getattr(self.coordinator.prumery, self._pole, None)
