"""Výběr pojmenovaného stavu pro každou žaluzii.

Tlačítka podle rolí umí jen to, co má místnost přiřazené. Tady se dá
žaluzii poslat do kteréhokoli jejího uloženého stavu přímo z Home
Assistanta — z karty, z automatizace nebo z hlasového asistenta.
"""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import planovac as pz
from .const import CONF_ZALUZIE, DOMAIN, PODENTITA_MISTNOST
from .entity import NaPohoduEntity
from .services import nacti_stavy, proved_stav_stineni

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = hass.data[DOMAIN][entry.entry_id]
    for pod in entry.subentries.values():
        if pod.subentry_type != PODENTITA_MISTNOST:
            continue
        vybery = [StavZaluzie(k, pod, z, i)
                  for i, z in enumerate(pod.data.get(CONF_ZALUZIE) or [])]
        if vybery:
            pridat(vybery, config_subentry_id=pod.subentry_id)
    pridat([CoNaplanovat(k, entry), JakCasto(k, entry)])


class StavZaluzie(NaPohoduEntity, SelectEntity):
    """Pošle žaluzii do vybraného uloženého stavu."""

    _attr_icon = "mdi:blinds-horizontal"

    def __init__(self, k, pod, zaluzie: str, poradi: int) -> None:
        super().__init__(k, pod, "stav_zaluzie")
        self._zaluzie = zaluzie
        # translation_key je pro všechny stejný, jméno i identifikátor
        # musí nést konkrétní žaluzii
        self._attr_unique_id = f"{pod.subentry_id}_stav_{zaluzie}"
        self._attr_translation_placeholders = {"cislo": str(poradi + 1)}

    @property
    def options(self) -> list[str]:
        return sorted(nacti_stavy(self.hass, self._zaluzie)) or ["žádný stav"]

    @property
    def current_option(self) -> str | None:
        """Poslední stav, do kterého jsme žaluzii poslali."""
        vyk = self.coordinator.vykonavaci.get(self.pod_id)
        if vyk is None:
            return None
        nazev = vyk.stav.posledni_stineni.get(self._zaluzie)
        return nazev if nazev in self.options else None

    @property
    def extra_state_attributes(self) -> dict:
        return {"zaluzie": self._zaluzie}

    async def async_select_option(self, option: str) -> None:
        if option not in nacti_stavy(self.hass, self._zaluzie):
            _LOGGER.warning("NaPohodu: %s nemá stav %s",
                            self._zaluzie, option)
            return
        vysledek = await proved_stav_stineni(self.hass, self._zaluzie, option)
        vyk = self.coordinator.vykonavaci.get(self.pod_id)
        if vyk is not None and vysledek.get("povedlo_se"):
            # ruční volba se bere jako nastavený stav, ať ji automatika
            # hned nepřepíše a karta ukazuje pravdu
            vyk.stav.posledni_stineni[self._zaluzie] = option
            poloha = vysledek.get("poloha_po")
            if poloha is not None:
                vyk.stav.stineni_poloha[self._zaluzie] = float(poloha)
                vyk.stav.poloha_predbezna.add(self._zaluzie)
        self.async_write_ha_state()


class CoNaplanovat(CoordinatorEntity, RestoreEntity, SelectEntity):
    """Co založí tlačítko Naplánovat.

    Nabídka vzniká z nastavení: je v ní jen to, co má kam zapsat.
    Volba bez přiřazeného kalendáře by skončila chybou až po stisku.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-plus"
    _attr_translation_key = "co_naplanovat"

    def __init__(self, k, entry) -> None:
        super().__init__(k)
        self._volba: str | None = None
        self._attr_unique_id = f"{entry.entry_id}_co_naplanovat"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="NaPohodu", manufacturer="NaPohodu", model="Byt")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        posledni = await self.async_get_last_state()
        if posledni is not None and posledni.state in self.options:
            self._volba = posledni.state
            self.coordinator.plan_volba = self._volba

    @property
    def options(self) -> list[str]:
        volby = [v.popis for v in self.coordinator.nabidka_planu()]
        return volby or ["není kam zapisovat"]

    @property
    def current_option(self) -> str | None:
        return self._volba if self._volba in self.options else None

    @property
    def extra_state_attributes(self) -> dict:
        # Výsledek posledního stisku. Tlačítko sám o sobě nic neukáže
        # a bez téhle zpětné vazby člověk neví, jestli se událost
        # založila, nebo proč ne.
        return {"posledni_vysledek": self.coordinator.plan_vysledek}

    async def async_select_option(self, option: str) -> None:
        self._volba = option
        self.coordinator.plan_volba = option
        self.async_write_ha_state()


class JakCasto(CoordinatorEntity, RestoreEntity, SelectEntity):
    """Jak často se má naplánovaná událost opakovat.

    Opakování neumí akce `calendar.create_event`, ale entita kalendáře
    ano — a vlastní kalendář integrace je právě entita, takže sem to
    projde.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:repeat"
    _attr_translation_key = "jak_casto"

    def __init__(self, k, entry) -> None:
        super().__init__(k)
        self._attr_unique_id = f"{entry.entry_id}_jak_casto"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="NaPohodu", manufacturer="NaPohodu", model="Byt")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        posledni = await self.async_get_last_state()
        if posledni is not None and posledni.state in self.options:
            self.coordinator.plan_opakovani = posledni.state

    @property
    def options(self) -> list[str]:
        return list(pz.OPAKOVANI)

    @property
    def current_option(self) -> str | None:
        return self.coordinator.plan_opakovani

    async def async_select_option(self, option: str) -> None:
        self.coordinator.plan_opakovani = option
        self.async_write_ha_state()
