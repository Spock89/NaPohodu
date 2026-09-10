"""Textový stav zóny a cílová teplota místnosti."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (DOMAIN, PODENTITA_KLIMA, PODENTITA_MISTNOST,
                    PODENTITA_ZONA)
from .entity import NaPohoduEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = hass.data[DOMAIN][entry.entry_id]
    for pod in entry.subentries.values():
        if pod.subentry_type == PODENTITA_ZONA:
            pridat([StavOblasti(k, pod)], config_subentry_id=pod.subentry_id)
        elif pod.subentry_type == PODENTITA_KLIMA:
            pridat([StavKlimy(k, pod)], config_subentry_id=pod.subentry_id)
        elif pod.subentry_type == PODENTITA_MISTNOST:
            pridat([StavMistnosti(k, pod), CilMistnosti(k, pod),
                    SlunceMistnosti(k, pod)],
                   config_subentry_id=pod.subentry_id)
    pridat([Prumer(k, entry, "prumer_tyden", "tyden"),
            Prumer(k, entry, "prumer_tri_dny", "tri_dny")])


class StavMistnosti(NaPohoduEntity, SensorEntity):
    """Co se v místnosti děje s okny a proč."""

    _attr_icon = "mdi:window-open-variant"

    def __init__(self, k, pod):
        super().__init__(k, pod, "stav")

    @property
    def native_value(self) -> str | None:
        m = self.mistnost
        if m is None or m.rozhodnuti is None:
            return None
        return m.rozhodnuti.duvod[:255]

    @property
    def extra_state_attributes(self) -> dict:
        m = self.mistnost
        return m.atributy if m else {}


class StavOblasti(NaPohoduEntity, SensorEntity):
    """Sdílený vzduch oblasti. Sama nic neovládá."""

    _attr_icon = "mdi:home-group"

    def __init__(self, k, pod):
        super().__init__(k, pod, "stav_oblasti")

    @property
    def native_value(self) -> str | None:
        z = self.zona
        if z is None:
            return None
        return f"CO2 {z.atributy.get('co2', 0):.0f}"

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
    """Klouzavý průměr venkovní teploty.

    Ukazuje tu hodnotu, se kterou se opravdu počítá. Když je v nastavení
    vlastní statistický senzor, ukáže jeho hodnotu — jinak by entita
    tvrdila něco jiného, než podle čeho se rozhoduje.
    """

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
        hodnota, _ = self.coordinator.pouzity.get(self._pole, (None, ""))
        if hodnota is None:
            return getattr(self.coordinator.prumery, self._pole, None)
        return round(hodnota, 2)

    @property
    def extra_state_attributes(self) -> dict:
        hodnota, zdroj = self.coordinator.pouzity.get(self._pole, (None, ""))
        vlastni = getattr(self.coordinator.prumery, self._pole, None)
        return {
            "zdroj": {"cidlo": "vlastní čidlo",
                      "pocitano": "počítá integrace",
                      "nahrada": "náhrada, chybí data"}.get(zdroj, zdroj),
            "vlastni_vypocet": None if vlastni is None else round(vlastni, 2),
        }


class StavKlimy(NaPohoduEntity, SensorEntity):
    """Co sdílená klimatizace dělá a podle koho."""

    _attr_icon = "mdi:air-conditioner"

    def __init__(self, k, pod):
        super().__init__(k, pod, "stav_klimy")

    @property
    def native_value(self) -> str | None:
        d = self.coordinator.klimy.get(self.pod_id)
        if not d:
            return None
        cil = f" na {d['cil']} °C" if d.get("cil") is not None else ""
        return f"{d['stav']}{cil}"

    @property
    def extra_state_attributes(self) -> dict:
        return self.coordinator.klimy.get(self.pod_id) or {}
