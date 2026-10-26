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
from .const import DOMAIN, PODENTITA_SCENA

_LOGGER = logging.getLogger(__name__)

try:      # dateutil je v Home Assistantu běžně k dispozici
    from dateutil.rrule import rrulestr
except ImportError:      # pragma: no cover - bez něj se jen neopakuje
    rrulestr = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = hass.data[DOMAIN][entry.entry_id]
    pridat([KalendarPlanu(k, entry)])
    # Každá scéna má vlastní kalendář. Den se v něm označí kliknutím
    # a nic se nepojmenovává — význam nese kalendář sám, takže
    # odpadá jediná křehká věc ručního zadávání, totiž trefit se
    # do názvu události.
    for pod in entry.subentries.values():
        if pod.subentry_type == PODENTITA_SCENA:
            pridat([KalendarSceny(k, entry, pod)],
                   config_subentry_id=pod.subentry_id)
    # Na kartě je jeden kalendář pro tu scénu, kterou ukazuje
    # rolovátko. S kalendářem ke každé scéně by karta s každou novou
    # narostla a musela by se generovat znovu.
    if any(p.subentry_type == PODENTITA_SCENA
           for p in entry.subentries.values()):
        pridat([KalendarVybraneSceny(k, entry)])


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
            if z.get("druh") == "scena":
                continue      # scéna má vlastní kalendář, tady by jen dublovala
            for a, b in pz.rozbal(z, od, do, rrulestr):
                out.append(CalendarEvent(
                    start=a, end=b, uid=z["uid"],
                    summary=pz.nazev(z["druh"],
                                     z.get("mistnost") or z.get("skupina"),
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
        druh, mistnost, skupina, cil = self.coordinator.plan_z_nazvu(
            kw.get("summary") or "")
        await self.coordinator.plan_zapis({
            "uid": uuid.uuid4().hex,
            "druh": druh, "mistnost": mistnost, "cil": cil,
            "skupina": skupina,
            "clenove": (self.coordinator.plan_skupiny().get(skupina, [])
                        if skupina else None),
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


class KalendarSceny(CoordinatorEntity, CalendarEntity):
    """Dny, kdy platí jedna scéna.

    Událost nenese nic než odkaz na scénu. Co scéna dělá, se čte z ní
    samotné, takže úprava scény se promítne do všech naplánovaných
    dní — přesně proto se zadává jednou a den se jen označí.

    Celodenní událost znamená „použij okno dne té scény". Platit celou
    noc by u home office nedávalo smysl a zadávat pokaždé čas by
    z jednoho kliknutí udělalo formulář.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-star"
    _attr_supported_features = (CalendarEntityFeature.CREATE_EVENT
                                | CalendarEntityFeature.DELETE_EVENT)

    def __init__(self, k, entry: ConfigEntry, pod) -> None:
        super().__init__(k)
        self._pod_id = pod.subentry_id
        # Jméno entity nese zařízení, aby z toho vzniklo
        # `calendar.napohodu_<scéna>` — stejně jako u všech ostatních
        # entit scény, místnosti i zóny.
        self._attr_name = None
        self._attr_unique_id = f"{entry.entry_id}_{pod.subentry_id}_scena"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, pod.subentry_id)},
            name=f"NaPohodu {pod.title}",
            manufacturer="NaPohodu", model="Scéna")

    def _definice(self) -> dict:
        return self.coordinator.sceny().get(self._pod_id) or {}

    def _moje(self) -> list[dict]:
        return [z for z in self.coordinator.plan_zaznamy()
                if z.get("druh") == "scena"
                and z.get("scena") == self._pod_id]

    def _komu(self) -> str | None:
        """Do které scény se zakládá. Potomek si to přepíše."""
        return self._pod_id

    @property
    def event(self) -> CalendarEvent | None:
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
        nazev = self._definice().get("nazev") or "scéna"
        out = []
        for z in self._moje():
            for a, b in pz.rozbal(z, od, do, rrulestr):
                out.append(CalendarEvent(
                    start=a, end=b, uid=z["uid"], summary=nazev,
                    description=z.get("popis") or ""))
        return sorted(out, key=lambda u: u.start)

    async def async_create_event(self, **kw) -> None:
        """Den označený v kalendáři scény.

        Celodenní událost pozná podle toho, že panel pošle datum bez
        času. Okno dne se k záznamu uloží opsané, ne odkazem: rozbalení
        pak nepotřebuje znát scénu a funguje i po jejím smazání.
        """
        zacatek = kw.get("dtstart") or kw.get("start")
        konec = kw.get("dtend") or kw.get("end")
        celodenni = not isinstance(zacatek, datetime)
        if celodenni:
            zacatek = dt_util.start_of_local_day(zacatek)
            konec = dt_util.start_of_local_day(konec)
        d = self._definice()
        await self.coordinator.plan_zapis({
            "uid": uuid.uuid4().hex,
            "druh": "scena",
            "scena": self._komu(),
            "nazev_sceny": d.get("nazev"),
            # Opis pro případ, že scénu smažeš: plán se tím nerozsype,
            # jen zamrzne v podobě, v jaké byl zadán. Stejné pravidlo
            # jako u skupin.
            "opis": {"prazdno": d.get("prazdno") or [],
                     "zavreno": d.get("zavreno") or [],
                     "cil": d.get("cil") or {}},
            "celodenni": celodenni,
            "okno": d.get("okno") or ["07:00", "18:00"],
            "od": zacatek, "do": konec,
            "rrule": kw.get("rrule"),
            "popis": kw.get("description") or d.get("popis") or "",
        })
        self.async_update_event_listeners()

    async def async_delete_event(self, uid: str, recurrence_id=None,
                                 recurrence_range=None) -> None:
        await self.coordinator.plan_smaz(uid)
        self.async_update_event_listeners()


class KalendarVybraneSceny(KalendarSceny):
    """Dny té scény, kterou zrovna ukazuje rolovátko.

    Dědí všechno od kalendáře scény a mění jen jedno: která scéna to
    je. Díky tomu zůstává karta pořád stejná — nová scéna se jen
    objeví v rolovátku.
    """

    _attr_translation_key = "vybrana_scena"

    def __init__(self, k, entry: ConfigEntry) -> None:
        # Základ chce podentitu; tahle entita ale patří bytu, takže se
        # zařízení i jméno přepíšou hned za ním.
        CoordinatorEntity.__init__(self, k)
        self._pod_id = None
        # Jméno nechává na překladu. Přepsat ho na „Scéna: Home
        # Office" by znamenalo, že se jméno — a s ním i identifikátor
        # entity — mění s vybranou scénou. Která to je, stojí
        # v rolovátku hned nad kalendářem.
        self._attr_unique_id = f"{entry.entry_id}_vybrana_scena"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="NaPohodu", manufacturer="NaPohodu", model="Byt")

    @property
    def _scena_id(self) -> str | None:
        return self.coordinator.scena_vybrana()[0]

    def _definice(self) -> dict:
        return self.coordinator.scena_vybrana()[1]

    def _moje(self) -> list[dict]:
        pid = self._scena_id
        if pid is None:
            return []
        return [z for z in self.coordinator.plan_zaznamy()
                if z.get("druh") == "scena" and z.get("scena") == pid]

    def _komu(self) -> str | None:
        return self._scena_id
