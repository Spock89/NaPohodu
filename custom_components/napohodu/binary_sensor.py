"""Okno pro topení a stav větrání."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (BinarySensorDeviceClass,
                                                    BinarySensorEntity)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, PODENTITA_MISTNOST, PODENTITA_ZONA
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .entity import NaPohoduEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = hass.data[DOMAIN][entry.entry_id]
    for pod in entry.subentries.values():
        if pod.subentry_type == PODENTITA_MISTNOST:
            pridat([OknoOtevreno(k, pod), Obsazeno(k, pod), Klid(k, pod)],
                   config_subentry_id=pod.subentry_id)
        elif pod.subentry_type == PODENTITA_ZONA:
            pridat([VetraSe(k, pod)], config_subentry_id=pod.subentry_id)
    pridat([TopnaSezona(k, entry)])


class OknoOtevreno(NaPohoduEntity, BinarySensorEntity):
    """Vstup pro Better Thermostat. Nikdy nesmí být nedostupný, jinak
    se s ním stane nedostupným i celý termostat."""

    _attr_device_class = BinarySensorDeviceClass.WINDOW
    _attr_available = True

    def __init__(self, k, pod):
        super().__init__(k, pod, "okno_otevreno")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        m = self.mistnost
        return bool(m and m.okno_otevreno)


class Obsazeno(NaPohoduEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, k, pod):
        super().__init__(k, pod, "obsazeno")

    @property
    def is_on(self) -> bool:
        m = self.mistnost
        return bool(m and m.obsazeno)

    @property
    def extra_state_attributes(self) -> dict:
        m = self.mistnost
        return {"indicie": m.atributy.get("indicie", [])} if m else {}


class Klid(NaPohoduEntity, BinarySensorEntity):
    _attr_icon = "mdi:sleep"

    def __init__(self, k, pod):
        super().__init__(k, pod, "klid")

    @property
    def is_on(self) -> bool:
        m = self.mistnost
        return bool(m and m.klid)


class VetraSe(NaPohoduEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.OPENING

    def __init__(self, k, pod):
        super().__init__(k, pod, "vetra_se")

    @property
    def is_on(self) -> bool:
        z = self.zona
        return bool(z and z.otevreno)


class TopnaSezona(CoordinatorEntity, BinarySensorEntity):
    """Zapnuto znamená topnou sezónu. Mimo ni se topí klimatizací,
    v sezóně radiátory — ať se ty dva zdroje nepřetahují."""

    _attr_has_entity_name = True
    _attr_translation_key = "topna_sezona"
    _attr_icon = "mdi:radiator"

    def __init__(self, koordinator, entry) -> None:
        super().__init__(koordinator)
        self._attr_unique_id = f"{entry.entry_id}_topna_sezona"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="NaPohodu",
            manufacturer="NaPohodu",
            model="Společné",
        )

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.topna_sezona)
