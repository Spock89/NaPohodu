"""Posuvníky na ladění. To, co bylo v Node-REDu konstantou v kódu."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (NumberEntity, NumberMode,
                                             RestoreNumber)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (CONF_NARAZOVE_ODSTUP, CONF_NEJDRIV_ZNOVU,
                    CONF_ZMENA_PODMINEK,
                    CONF_CO2_NOC, CONF_CO2_NOC_KRIZE, CONF_CO2_OTEVRIT, CONF_CO2_ZAVRIT,
                    CONF_DENNI_HYSTEREZE, CONF_CHLAZENI_MIN_VENKU, CONF_MIN_DRZENI, CONF_NOC_MIN, CONF_NOC_UTLUM,
                    CONF_PM_CISTO, CONF_PM_SPATNE, CONF_RUCNI_KLID, CONF_RH_MAX, CONF_RH_MIN,
                    CONF_TLOUSTKA,
                    CONF_ODCHYLKA, CONF_UTLUM,
                    DOMAIN,
                    PODENTITA_MISTNOST)
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


# Globální hodnoty nepatří místnosti, ale celému bytu. Jsou to pořád
# čísla, takže si zaslouží posuvník stejně jako ta místnostní.
CELY_BYT = [
    Posuvnik(CONF_NARAZOVE_ODSTUP, 2, 30, 0.5, UnitOfTemperature.CELSIUS,
             15.0, "mdi:weather-windy"),
    Posuvnik(CONF_ZMENA_PODMINEK, 0, 10, 0.5, UnitOfTemperature.CELSIUS,
             2.0, "mdi:thermometer-chevron-up"),
    Posuvnik(CONF_NEJDRIV_ZNOVU, 5, 240, 5, "min", 60.0,
             "mdi:timer-sand"),
]

MISTNOST = [
    Posuvnik(CONF_ODCHYLKA, -3, 3, 0.5, UnitOfTemperature.CELSIUS, 0.0,
             "mdi:thermometer-plus"),
    Posuvnik(CONF_NOC_UTLUM, 0, 4, 0.5, UnitOfTemperature.CELSIUS, 0.0,
             "mdi:weather-night-partly-cloudy"),
    Posuvnik(CONF_CHLAZENI_MIN_VENKU, -20, 10, 0.5,
             UnitOfTemperature.CELSIUS, 7.0, "mdi:snowflake-alert"),
    Posuvnik(CONF_MIN_DRZENI, 1, 120, 1, "min", 20.0, "mdi:timer-lock"),
    Posuvnik(CONF_RUCNI_KLID, 0, 240, 5, "min", 30.0, "mdi:hand-back-right"),
    Posuvnik(CONF_PM_SPATNE, 10, 100, 1, "µg/m³", 35.0, "mdi:blur"),
    Posuvnik(CONF_PM_CISTO, 5, 60, 1, "µg/m³", 20.0, "mdi:blur-off"),
    Posuvnik(CONF_RH_MIN, 20, 55, 1, PERCENTAGE, 38.0,
             "mdi:water-percent"),
    Posuvnik(CONF_RH_MAX, 40, 80, 1, PERCENTAGE, 60.0,
             "mdi:water-percent-alert"),
    Posuvnik(CONF_TLOUSTKA, 0, 7, 0.5, UnitOfTemperature.CELSIUS, 1.0,
             "mdi:sine-wave"),
    Posuvnik(CONF_NOC_MIN, 14, 24, 0.5, UnitOfTemperature.CELSIUS, 18.0,
             "mdi:weather-night"),
    Posuvnik(CONF_UTLUM, 5, 20, 0.5, UnitOfTemperature.CELSIUS, 16.0,
             "mdi:radiator-off"),
    Posuvnik(CONF_DENNI_HYSTEREZE, 0.5, 6, 0.5, UnitOfTemperature.CELSIUS,
             1.5, "mdi:thermometer-chevron-down"),
    Posuvnik(CONF_CO2_OTEVRIT, 500, 2000, 25, "ppm", 800.0, "mdi:molecule-co2"),
    Posuvnik(CONF_CO2_ZAVRIT, 400, 1500, 25, "ppm", 700.0, "mdi:molecule-co2"),
    Posuvnik(CONF_CO2_NOC, 600, 2000, 25, "ppm", 1000.0, "mdi:weather-night"),
    Posuvnik(CONF_CO2_NOC_KRIZE, 800, 2500, 25, "ppm", 1250.0,
             "mdi:weather-night-partly-cloudy"),
]




async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = hass.data[DOMAIN][entry.entry_id]
    pridat([NaPohoduNumber(k, None, p, entry) for p in CELY_BYT])
    for pod in entry.subentries.values():
        if pod.subentry_type != PODENTITA_MISTNOST:
            continue          # prahy vzduchu patří místnosti, ta se rozhoduje
        sada = MISTNOST
        pridat([NaPohoduNumber(k, pod, p) for p in sada],
               config_subentry_id=pod.subentry_id)


class NaPohoduNumber(NaPohoduEntity, RestoreNumber, NumberEntity):
    """Šoupátko a pole ve formuláři ukazují tutéž hodnotu.

    Jediné, kde hodnota doopravdy žije, je koordinátor. Šoupátko do něj
    zapisuje a zároveň z něj čte, takže když někdo změní pole v nastavení
    místnosti, šoupátko se posune taky. Dvě místa pro tutéž hodnotu jsou
    past: člověk pak neví, co platí.
    """

    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, k, pod, p: Posuvnik, entry=None) -> None:
        if pod is None:
            # Posuvník pro celý byt visí na hlavním zařízení integrace.
            CoordinatorEntity.__init__(self, k)
            self.pod = None
            self.pod_id = entry.entry_id
            self._attr_translation_key = p.klic
            self._attr_unique_id = f"{entry.entry_id}_{p.klic}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, entry.entry_id)},
                name="NaPohodu", manufacturer="NaPohodu", model="Byt")
            data = {**entry.data, **entry.options}
        else:
            super().__init__(k, pod, p.klic)
            data = pod.data
        self._p = p
        self._attr_native_min_value = p.min
        self._attr_native_max_value = p.max
        self._attr_native_step = p.krok
        self._attr_native_unit_of_measurement = p.jednotka
        self._attr_icon = p.ikona
        self._vychozi = float(data.get(p.klic, p.vychozi))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        klic = (self.pod_id, self._p.klic)
        hodnota = self._vychozi
        ulozene = await self.async_get_last_number_data()
        if ulozene and ulozene.native_value is not None:
            hodnota = float(ulozene.native_value)
        # Formulář vyhrává, když ho člověk právě přepsal — je to výslovný
        # pokyn, kdežto uložená hodnota šoupátka je jen minulý stav.
        if self.coordinator.prepsano_formularem(klic):
            hodnota = self._vychozi
        self.coordinator.hodnoty[klic] = hodnota

    @property
    def native_value(self) -> float:
        return self.coordinator.hodnoty.get(
            (self.pod_id, self._p.klic), self._vychozi)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.hodnoty[(self.pod_id, self._p.klic)] = value
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
