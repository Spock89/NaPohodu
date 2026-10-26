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
from homeassistant.util import dt as dt_util

from . import vykon as vy
from . import core
from .const import (
    CONF_OKNA, CONF_RUCNI_KLID, CONF_STINENI_MAPA, DOMAIN,
    PODENTITA_MISTNOST, PODENTITA_SCENA,
)
from .services import proved_stav_stineni
from .entity import NaPohoduEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = hass.data[DOMAIN][entry.entry_id]
    for pod in entry.subentries.values():
        if pod.subentry_type == PODENTITA_MISTNOST:
            tlacitka = [Srovnat(k, pod, "srovnat_okno"),
                        Srovnat(k, pod, "srovnat_stineni"),
                        Srovnat(k, pod, "srovnat_topeni")]
            if pod.data.get(CONF_OKNA):
                tlacitka += [Okno(k, pod, "otevrit_okno", True),
                             Okno(k, pod, "zavrit_okno", False)]
            # pro každou nakonfigurovanou roli vlastní tlačítko, ať se
            # stínění dá vyvolat rukou bez psaní automatizace
            mapa = pod.data.get(CONF_STINENI_MAPA) or {}
            for role, klic in (("zastinit", "zastinit"),
                               ("odstinit", "odstinit"),
                               ("soukromi", "soukromi"),
                               ("pryc", "stineni_pryc"),
                               ("vychozi", "stineni_vychozi")):
                # cile_zaluzii umí starý i nový tvar mapy; dřív se tu
                # hledaly klíče „…|role", které novým tvarem zmizely,
                # a tlačítka tiše přestala vznikat
                if vy.cile_zaluzii(role, mapa):
                    tlacitka.append(Stineni(k, pod, klic, role))
            pridat(tlacitka, config_subentry_id=pod.subentry_id)
    tlacitka_bytu = [SrovnatVse(k, entry), VynulovatStavy(k, entry),
                     Naplanovat(k, entry)]
    # Uložení a zahození rozpracovaného výběru dnů. Jen se scénou:
    # bez ní není co ukládat.
    if any(p.subentry_type == PODENTITA_SCENA
           for p in entry.subentries.values()):
        tlacitka_bytu += [UlozitDny(k, entry), ZahoditDny(k, entry)]
    pridat(tlacitka_bytu)


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


class VynulovatStavy(CoordinatorEntity, ButtonEntity):
    """Zapomene vnitřní stavy rozhodování.

    Když se integrace zamotá — drží nedokončené větrání, čeká na změnu
    venku, pamatuje si marný pokus — není jak to rozmotat jinak než
    restartem. Tohle zapomene jen vnitřní stavy; nastavení, posuvníky
    ani naučené průměry se nedotkne.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "vynulovat_stavy"
    _attr_icon = "mdi:restore-alert"

    def __init__(self, koordinator, entry) -> None:
        super().__init__(koordinator)
        self._attr_unique_id = f"{entry.entry_id}_vynulovat_stavy"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="NaPohodu", manufacturer="NaPohodu", model="Společné",
        )

    async def async_press(self) -> None:
        self.coordinator.vynuluj_stavy()
        await self.coordinator.async_request_refresh()


class Stineni(NaPohoduEntity, ButtonEntity):
    """Vyvolá pojmenovaný stav žaluzií rukou.

    Vzniká jen pro role, které máš u místnosti skutečně přiřazené —
    tlačítko, které nic nedělá, by jen zaplevelilo kartu.

    Bere se to stejně jako ruka na ovladači: automatika se pak chvíli
    do žaluzií neplete. Dřív se stisk choval stejně jen omylem — poloha
    se rozešla s tou zapsanou, takže se po dvou minutách vyhodnotil
    jako „někdo ji přestavil". Teď se klid rozbíhá rovnou a poloha se
    převezme z toho, kam žaluzie doopravdy dojede.
    """

    _attr_icon = "mdi:blinds-horizontal"

    def __init__(self, k, pod, klic: str, role: str) -> None:
        super().__init__(k, pod, klic)
        self._role = role

    async def async_press(self) -> None:
        cile = vy.cile_zaluzii(self._role,
                               self.pod.data.get(CONF_STINENI_MAPA) or {})
        for zaluzie, nazev in cile.items():
            await proved_stav_stineni(self.hass, zaluzie, nazev)
        vyk = self.coordinator.vykonavaci.get(self.pod_id)
        if vyk is not None:
            vyk.stav.posledni_stineni.update(cile)
            for zaluzie in cile:
                vyk.stav.stineni_poloha.pop(zaluzie, None)
                vyk.stav.stineni_tilt.pop(zaluzie, None)
                vyk.stav.rozejiti.pop(zaluzie, None)
        self.coordinator.zaluzie_rukou(
            self.pod_id, dt_util.utcnow().timestamp())
        await self.coordinator.async_request_refresh()


class Okno(NaPohoduEntity, ButtonEntity):
    """Otevře nebo zavře okno rukou.

    Bere se to stejně, jako když na okno sáhneš — rozdělané větrání se
    zruší a automatika chvíli nemluví. Jinak by okno hned vrátila tam,
    kde bylo, a stisk tlačítka by vypadal jako porucha.
    """

    def __init__(self, k, pod, klic: str, otevrit: bool) -> None:
        super().__init__(k, pod, klic)
        self._otevrit = otevrit
        self._attr_icon = ("mdi:window-open-variant" if otevrit
                           else "mdi:window-closed-variant")

    async def async_press(self) -> None:
        okna = self.pod.data.get(CONF_OKNA) or []
        if not okna:
            return
        await self.hass.services.async_call(
            "cover", "open_cover" if self._otevrit else "close_cover",
            {"entity_id": okna}, blocking=False)

        pamet = self.coordinator.pameti.get(self.pod_id)
        if pamet is not None:
            # Tatáž hodnota jako v rozhodování: nejdřív šoupátko,
            # teprve pak formulář. Dřív si tlačítko bralo jen formulář,
            # takže odpočet neodpovídal tomu, co bylo na dashboardu.
            klid = self.coordinator.hodnota(
                self.pod_id, CONF_RUCNI_KLID,
                float(self.pod.data.get(CONF_RUCNI_KLID, 30))) * 60
            core.rucni_zasah(pamet, None, dt_util.utcnow().timestamp(),
                             self._otevrit, klid_s=klid)


class Naplanovat(CoordinatorEntity, ButtonEntity):
    """Založí událost plánu podle toho, co je navolené vedle.

    Kalendář si integrace dohledá sama podle nastavení, takže se nedá
    zapsat do špatného. Výsledek se ukáže v atributu výběru — tlačítko
    samo o sobě nic nezobrazí.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "naplanovat"
    _attr_icon = "mdi:calendar-check"

    def __init__(self, koordinator, entry) -> None:
        super().__init__(koordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_naplanovat"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="NaPohodu", manufacturer="NaPohodu", model="Byt",
        )

    async def async_press(self) -> None:
        # Hodnoty drží koordinátor, ne entity: hledat je podle jména
        # by se rozešlo při prvním přejmenování.
        await self.coordinator.naplanuj(self.coordinator.plan_volba or "",
                                        self.coordinator.plan_od,
                                        self.coordinator.plan_do)


class UlozitDny(CoordinatorEntity, ButtonEntity):
    """Zapíše do kalendáře všechny dny naklikané v mřížce.

    Jeden stisk na čtrnáct dní. Zaškrtávání samo nic nezapisuje právě
    proto, aby se dalo naklikat víc dní najednou — a protože po sobě
    jde výběr ještě projít, než se uloží.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "ulozit_dny"
    _attr_icon = "mdi:calendar-arrow-right"

    def __init__(self, koordinator, entry) -> None:
        super().__init__(koordinator)
        self._attr_unique_id = f"{entry.entry_id}_ulozit_dny"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="NaPohodu", manufacturer="NaPohodu", model="Byt")

    @property
    def extra_state_attributes(self) -> dict:
        pridat_, zrusit = self.coordinator.scena_kolik_ceka()
        return {
            "k_ulozeni": (
                ", ".join(
                    ([f"přidat {pridat_}"] if pridat_ else [])
                    + ([f"zrušit {zrusit}"] if zrusit else []))
                or "nic"),
            "posledni_vysledek": self.coordinator.scena_vysledek,
        }

    async def async_press(self) -> None:
        await self.coordinator.scena_uloz()


class ZahoditDny(CoordinatorEntity, ButtonEntity):
    """Zahodí rozpracovaný výběr. Kalendář zůstane, jak byl."""

    _attr_has_entity_name = True
    _attr_translation_key = "zahodit_dny"
    _attr_icon = "mdi:calendar-remove-outline"

    def __init__(self, koordinator, entry) -> None:
        super().__init__(koordinator)
        self._attr_unique_id = f"{entry.entry_id}_zahodit_dny"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="NaPohodu", manufacturer="NaPohodu", model="Byt")

    async def async_press(self) -> None:
        self.coordinator.scena_zahod()
