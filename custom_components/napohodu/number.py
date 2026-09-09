"""Posuvníky na ladění. To, co bylo v Node-REDu konstantou v kódu."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (NumberEntity, NumberMode,
                                             RestoreNumber)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (CONF_CO2_NOC, CONF_CO2_NOC_KRIZE, CONF_CO2_OTEVRIT, CONF_CO2_ZAVRIT, CONF_KOMFORT_ODSTUP,
                    CONF_NOC_MIN, CONF_ODCHYLKA, CONF_PRIORITA, CONF_UTLUM,
                    DOMAIN,
                    PODENTITA_MISTNOST, PODENTITA_ZONA)
from .entity import NaPohoduEntity


@dataclass(frozen=True)
class Posuvnik:
    klic: str
    min: float
    max: float
    krok: float
    jednotka: str | None
    vychozi: float
    ikona: str


MISTNOST = [
    Posuvnik(CONF_ODCHYLKA, -3, 3, 0.5, UnitOfTemperature.CELSIUS, 0.0,
             "mdi:thermometer-plus"),
    Posuvnik(CONF_NOC_MIN, 14, 24, 0.5, UnitOfTemperature.CELSIUS, 18.0,
             "mdi:weather-night"),
    Posuvnik(CONF_KOMFORT_ODSTUP, 1, 15, 0.5, UnitOfTemperature.CELSIUS, 4.0,
             "mdi:window-open"),
    Posuvnik(CONF_UTLUM, 5, 20, 0.5, UnitOfTemperature.CELSIUS, 16.0,
             "mdi:radiator-off"),
    Posuvnik(CONF_PRIORITA, 0, 10, 1, None, 5.0, "mdi:scale-balance"),
]

ZONA = [
    Posuvnik(CONF_CO2_OTEVRIT, 500, 2000, 25, "ppm", 800.0, "mdi:molecule-co2"),
    Posuvnik(CONF_CO2_ZAVRIT, 400, 1500, 25, "ppm", 700.0, "mdi:molecule-co2"),
    Posuvnik(CONF_CO2_NOC, 600, 2000, 25, "ppm", 1000.0, "mdi:weather-night"),
    Posuvnik(CONF_CO2_NOC_KRIZE, 800, 2500, 25, "ppm", 1250.0,
             "mdi:weather-night-partly-cloudy"),
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = hass.data[DOMAIN][entry.entry_id]
    for pod in entry.subentries.values():
        if pod.subentry_type == PODENTITA_MISTNOST:
            sada = MISTNOST
        elif pod.subentry_type == PODENTITA_ZONA:
            sada = ZONA
        else:
            continue
        pridat([NaPohoduNumber(k, pod, p) for p in sada],
               config_subentry_id=pod.subentry_id)


class NaPohoduNumber(NaPohoduEntity, RestoreNumber, NumberEntity):
    """Hodnota přežije restart. Výchozí bere z konfigurace místnosti."""

    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, k, pod, p: Posuvnik) -> None:
        super().__init__(k, pod, p.klic)
        self._p = p
        self._attr_native_min_value = p.min
        self._attr_native_max_value = p.max
        self._attr_native_step = p.krok
        self._attr_native_unit_of_measurement = p.jednotka
        self._attr_icon = p.ikona
        self._hodnota = float(pod.data.get(p.klic, p.vychozi))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        ulozene = await self.async_get_last_number_data()
        if ulozene and ulozene.native_value is not None:
            self._hodnota = float(ulozene.native_value)
        self.coordinator.hodnoty[(self.pod_id, self._p.klic)] = self._hodnota

    @property
    def native_value(self) -> float:
        return self._hodnota

    async def async_set_native_value(self, value: float) -> None:
        self._hodnota = value
        self.coordinator.hodnoty[(self.pod_id, self._p.klic)] = value
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
