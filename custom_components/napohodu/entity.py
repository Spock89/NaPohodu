"""Společný základ entit. Každá místnost i zóna je vlastní zařízení,
takže je karta integrace přehledná a dá se rozkliknout."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PODENTITA_KLIMA, PODENTITA_ZONA

if TYPE_CHECKING:
    from .coordinator import NaPohoduCoordinator, VysledekMistnosti
    from .coordinator import VysledekZony


# Koordinátor je v typu schválně: `self.coordinator` je pak NaPohodu
# koordinátor, ne obecný DataUpdateCoordinator, takže se překlep ve
# jméně atributu pozná při kontrole typů, ne až za běhu u uživatele.
class NaPohoduEntity(CoordinatorEntity["NaPohoduCoordinator"]):
    _attr_has_entity_name = True

    # Posuvník pro celý byt visí na hlavním zařízení integrace, takže
    # podentitu nemá. Všechny ostatní entity ji mají vždycky.
    pod: ConfigSubentry | None = None

    def __init__(self, koordinator: "NaPohoduCoordinator",
                 pod: ConfigSubentry, klic: str) -> None:
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
    def pod_data(self) -> Mapping[str, Any]:
        """Nastavení podentity, nebo prázdno u entity celého bytu."""
        return self.pod.data if self.pod is not None else {}

    @property
    def zona(self) -> "VysledekZony | None":
        return self.coordinator.zony.get(self.pod_id)

    @property
    def mistnost(self) -> "VysledekMistnosti | None":
        return self.coordinator.mistnosti.get(self.pod_id)
