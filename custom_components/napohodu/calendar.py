"""Vlastní kalendář plánu.

Zakládat kalendář ručně a hlídat, který znamená co, je zbytečná past.
Integrace si proto vyrobí vlastní — `calendar.napohodu_plan` — a sama
ví, co která událost znamená: význam je v uloženém záznamu, ne
v názvu, takže ho nejde pokazit překlepem.

Ukazuje se v panelu Kalendář jako každý jiný, takže se do něj dá
přidávat a mazat i odtud. A protože se tam události zakládají přes
rozhraní entity, ne přes akci `calendar.create_event`, **funguje
i opakování** — akce pole pro opakování nemá, kdežto entita ano.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from homeassistant.components.calendar import (CalendarEntity, CalendarEvent,
                                               CalendarEntityFeature)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import planovac as pz
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

try:      # dateutil je v Home Assistantu běžně k dispozici
    from dateutil.rrule import rrulestr
except ImportError:      # pragma: no cover - bez něj se jen neopakuje
    rrulestr = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = hass.data[DOMAIN][entry.entry_id]
    pridat([KalendarPlanu(k, entry)])


class KalendarPlanu(CoordinatorEntity, CalendarEntity):
    """Plán obsazenosti jako kalendář."""

    _attr_has_entity_name = True
    _attr_translation_key = "plan"
    _attr_icon = "mdi:calendar-account"
    _attr_supported_features = (CalendarEntityFeature.CREATE_EVENT
                                | CalendarEntityFeature.DELETE_EVENT)

    def __init__(self, k, entry: ConfigEntry) -> None:
        super().__init__(k)
        self._attr_unique_id = f"{entry.entry_id}_plan"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="NaPohodu", manufacturer="NaPohodu", model="Byt")

    @property
    def event(self) -> CalendarEvent | None:
        """Co platí teď, jinak co bude nejblíž."""
        ted = dt_util.now()
        vse = self._udalosti(ted - timedelta(days=1), ted + timedelta(days=30))
        bezici = [u for u in vse if u.start <= ted < u.end]
        if bezici:
            return bezici[0]
        budouci = [u for u in vse if u.start > ted]
        return min(budouci, key=lambda u: u.start) if budouci else None

    async def async_get_events(self, hass: HomeAssistant, start: datetime,
                               end: datetime) -> list[CalendarEvent]:
        return self._udalosti(start, end)

    def _udalosti(self, od: datetime, do: datetime) -> list[CalendarEvent]:
        """Záznamy rozložené na jednotlivé výskyty.

        Opakovaná událost se musí vrátit rozbalená; jeden záznam
        s pravidlem by panel ani jádro nepoznaly.
        """
        out = []
        for z in self.coordinator.plan_zaznamy():
            for a, b in pz.rozbal(z, od, do, rrulestr):
                out.append(CalendarEvent(
                    start=a, end=b, uid=z["uid"],
                    summary=pz.nazev(z["druh"], z.get("mistnost"),
                                     z.get("cil")),
                    description=z.get("popis") or ""))
        return sorted(out, key=lambda u: u.start)

    async def async_create_event(self, **kw) -> None:
        """Událost z panelu Kalendář.

        Panel posílá i pravidlo opakování, takže odtud jde založit
        i opakovanou událost. Význam se čte z názvu, protože nic
        jiného panel nenabízí — co nerozumíme, zůstane uložené
        a v kartě se objeví jako nepochopená položka.
        """
        zacatek = kw.get("dtstart") or kw.get("start")
        konec = kw.get("dtend") or kw.get("end")
        druh, mistnost, cil = self.coordinator.plan_z_nazvu(
            kw.get("summary") or "")
        await self.coordinator.plan_zapis({
            "uid": uuid.uuid4().hex,
            "druh": druh, "mistnost": mistnost, "cil": cil,
            "od": zacatek, "do": konec,
            "rrule": kw.get("rrule"),
            "popis": kw.get("description") or "",
            "nazev_rucne": kw.get("summary") or "",
        })
        self.async_update_event_listeners()

    async def async_delete_event(self, uid: str, recurrence_id=None,
                                 recurrence_range=None) -> None:
        """Maže se celá řada.

        Vyndat z opakování jediný výskyt by znamenalo vést seznam
        výjimek a to je na plán obsazenosti zbytečná složitost —
        jednodušší je řadu smazat a založit znovu.
        """
        await self.coordinator.plan_smaz(uid)
        self.async_update_event_listeners()
