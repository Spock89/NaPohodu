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

from .const import CONF_STINENI_MAPA, DOMAIN, PODENTITA_MISTNOST
from .entity import NaPohoduEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = hass.data[DOMAIN][entry.entry_id]
    for pod in entry.subentries.values():
        if pod.subentry_type == PODENTITA_MISTNOST:
            tlacitka = [Srovnat(k, pod, "srovnat_okno"),
                        Srovnat(k, pod, "srovnat_stineni")]
            # pro každou nakonfigurovanou roli vlastní tlačítko, ať se
            # stínění dá vyvolat rukou bez psaní automatizace
            mapa = pod.data.get(CONF_STINENI_MAPA) or {}
            for role, klic in (("zastinit", "zastinit"),
                               ("odstinit", "odstinit"),
                               ("soukromi", "soukromi"),
                               ("pryc", "stineni_pryc")):
                if any(k2.endswith(f"|{role}") and v for k2, v in mapa.items()):
                    tlacitka.append(Stineni(k, pod, klic, role))
            pridat(tlacitka, config_subentry_id=pod.subentry_id)
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


class Stineni(NaPohoduEntity, ButtonEntity):
    """Vyvolá pojmenovaný stav žaluzií rukou.

    Vzniká jen pro role, které máš u místnosti skutečně přiřazené —
    tlačítko, které nic nedělá, by jen zaplevelilo kartu.
    """

    _attr_icon = "mdi:blinds-horizontal"

    def __init__(self, k, pod, klic: str, role: str) -> None:
        super().__init__(k, pod, klic)
        self._role = role

    async def async_press(self) -> None:
        from . import vykon as vy
        from .const import CONF_STINENI_MAPA

        cile = vy.cile_zaluzii(self._role,
                               self.pod.data.get(CONF_STINENI_MAPA) or {})
        for zaluzie, nazev in cile.items():
            from .services import proved_stav_stineni

            await proved_stav_stineni(self.hass, zaluzie, nazev)
        vyk = self.coordinator.vykonavaci.get(self.pod_id)
        if vyk is not None:
            vyk.stav.posledni_stineni.update(cile)
