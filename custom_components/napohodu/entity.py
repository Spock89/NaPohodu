"""Společný základ entit. Každá místnost i zóna je vlastní zařízení,
takže je karta integrace přehledná a dá se rozkliknout."""

from __future__ import annotations

from homeassistant.config_entries import ConfigSubentry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PODENTITA_KLIMA, PODENTITA_ZONA


class NaPohoduEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, koordinator, pod: ConfigSubentry, klic: str) -> None:
        super().__init__(koordinator)
        self.pod = pod
        self.pod_id = pod.subentry_id
        self._attr_translation_key = klic
        self._attr_unique_id = f"{pod.subentry_id}_{klic}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, pod.subentry_id)},
            name=f"NaPohodu {pod.title}",
            manufacturer="NaPohodu",
            model={PODENTITA_ZONA: "Oblast",
                   PODENTITA_KLIMA: "Klimatizace"}.get(
                       pod.subentry_type, "Místnost"),
        )

    @property
    def zona(self):
        return self.coordinator.zony.get(self.pod_id)

    @property
    def mistnost(self):
        return self.coordinator.mistnosti.get(self.pod_id)
