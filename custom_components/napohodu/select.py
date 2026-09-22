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
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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
