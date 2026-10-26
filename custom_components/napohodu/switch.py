"""Přepínač, kterým se zóně povolí sahat na okno.

Ve výchozím stavu vypnutý. Do té doby integrace jen počítá a ukazuje,
co by udělala, což je bezpečnější způsob, jak ji poprvé nasadit.
"""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import dny as dn
from .const import (DOMAIN, PODENTITA_KLIMA, PODENTITA_MISTNOST,
                    PODENTITA_SCENA)
from .entity import NaPohoduEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = hass.data[DOMAIN][entry.entry_id]
    for pod in entry.subentries.values():
        if pod.subentry_type == PODENTITA_MISTNOST:
            pridat([OvladatOkno(k, pod), OvladatStineni(k, pod),
                    OtevritProPohodu(k, pod), ZvlhcovatVeSpanku(k, pod),
                    OvladatTopeni(k, pod)],
                   config_subentry_id=pod.subentry_id)
        elif pod.subentry_type == PODENTITA_KLIMA:
            pridat([OvladatKlimu(k, pod)], config_subentry_id=pod.subentry_id)
        elif pod.subentry_type == PODENTITA_SCENA:
            pridat([DenSceny(k, entry, pod, i)
                    for i in range(dn.DNU_DOPREDU)],
                   config_subentry_id=pod.subentry_id)


class NaPohoduPrepinac(NaPohoduEntity, SwitchEntity, RestoreEntity):
    """Povolení sahat na pohon. Ve výchozím stavu vypnuté."""

    _attr_entity_category = EntityCategory.CONFIG
    _klic_hodnoty = "ovladat"

    def __init__(self, k, pod, klic):
        super().__init__(k, pod, klic)
        self._zap = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        posledni = await self.async_get_last_state()
        if posledni is not None:
            self._zap = posledni.state == "on"
        self.coordinator.hodnoty[
            (self.pod_id, self._klic_hodnoty)] = float(self._zap)

    @property
    def is_on(self) -> bool:
        return self._zap

    async def async_turn_on(self, **kwargs) -> None:
        await self._nastav(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._nastav(False)

    async def _nastav(self, hodnota: bool) -> None:
        self._zap = hodnota
        self.coordinator.hodnoty[
            (self.pod_id, self._klic_hodnoty)] = float(hodnota)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class ZVolbyMistnosti(NaPohoduPrepinac):
    """Přepínač, který ve výchozím stavu kopíruje formulář.

    Výchozí stav nese formulář místnosti, protože tyhle volby se tam
    zakládají. Přepínač je pak jen pohodlnější cesta, jak je měnit
    z panelu.
    """

    _vychozi_klic = ""

    async def async_added_to_hass(self) -> None:
        # Nejdřív obnova, pak formulář — a ten vyhraje jen tehdy, když
        # ho člověk opravdu změnil. Opačné pořadí znamenalo, že obnova
        # formulář vždycky přepsala a nastavení se neprojevilo.
        await super().async_added_to_hass()
        z_formulare = bool(self.pod.data.get(self._vychozi_klic, True))
        klic = (self.pod_id, self._klic_hodnoty)
        if self.coordinator.formular_zmenen(klic, float(z_formulare)):
            self._zap = z_formulare
        self.coordinator.hodnoty[klic] = float(self._zap)


class OtevritProPohodu(ZVolbyMistnosti):
    """Smí se otevřít i tehdy, když k tomu není důvod?"""

    _attr_icon = "mdi:weather-sunny"
    _klic_hodnoty = "pro_pohodu"
    _vychozi_klic = "pro_pohodu"

    def __init__(self, k, pod):
        super().__init__(k, pod, "otevirat_i_pro_pohodu")


class ZvlhcovatVeSpanku(ZVolbyMistnosti):
    """Smí zvlhčovač běžet i při zapnutém spánku?"""

    _attr_icon = "mdi:air-humidifier"
    _klic_hodnoty = "zvlhcovac_ve_spanku"
    _vychozi_klic = "zvlhcovac_ve_spanku"

    def __init__(self, k, pod):
        super().__init__(k, pod, "zvlhcovat_i_ve_spanku")


class OvladatOkno(NaPohoduPrepinac):
    _attr_icon = "mdi:window-shutter-auto"
    _klic_hodnoty = "ovladat"

    def __init__(self, k, pod):
        super().__init__(k, pod, "ovladat_okno")


class OvladatStineni(NaPohoduPrepinac):
    _attr_icon = "mdi:blinds-horizontal"
    _klic_hodnoty = "ovladat_stineni"

    def __init__(self, k, pod):
        super().__init__(k, pod, "ovladat_stineni")


class OvladatKlimu(NaPohoduPrepinac):
    _attr_icon = "mdi:air-conditioner"
    _klic_hodnoty = "ovladat"

    def __init__(self, k, pod):
        super().__init__(k, pod, "ovladat_klimu")


class OvladatTopeni(NaPohoduPrepinac):
    """Povolí zapisovat cílovou teplotu do hlavic místnosti."""

    _attr_icon = "mdi:radiator"
    _klic_hodnoty = "ovladat_topeni"

    def __init__(self, k, pod):
        super().__init__(k, pod, "ovladat_topeni")


class DenSceny(CoordinatorEntity, SwitchEntity):
    """Jeden den v zaškrtávací mřížce scény.

    Dlaždice patří odstupu od dneška, ne datu — jen tak zůstane mřížka
    na kartě pořád stejná. Zaškrtnutí se ukládá na datum, takže přes
    noc neputuje: dlaždice se jen posunou o jednu a zaškrtnutý den
    zůstane zaškrtnutý tam, kam patří.
    """

    _attr_icon = "mdi:calendar-check"

    def __init__(self, k, entry, pod, odstup: int) -> None:
        super().__init__(k)
        self._pod_id = pod.subentry_id
        self._odstup = odstup
        # V jméně entity je číslo dlaždice, ne datum: z něho vzniká
        # `switch.napohodu_<scéna>_den_03`, a to se nesmí přes noc
        # měnit. Datum je ve jméně, které se ukazuje na kartě.
        self._attr_translation_key = "scena_den"
        self._attr_translation_placeholders = {"cislo": f"{odstup + 1:02d}"}
        self._attr_unique_id = (f"{entry.entry_id}_{pod.subentry_id}"
                                f"_den_{odstup:02d}")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, pod.subentry_id)},
            name=f"NaPohodu {pod.title}",
            manufacturer="NaPohodu", model="Scéna")

    @property
    def _definice(self) -> dict:
        return self.coordinator.sceny().get(self._pod_id) or {}

    @property
    def _den(self):
        return dn.datum(self._odstup)

    @property
    def _stav_dne(self) -> dict:
        return dn.pro_den(self.coordinator.plan_zaznamy(), self._pod_id,
                           self._den, self.coordinator.plan_rozbal)

    @property
    def name(self) -> str:
        # Datum, ne číslo dlaždice: na mřížce je to jediné, co se čte.
        return dn.popis(self._odstup)

    @property
    def is_on(self) -> bool:
        return self._stav_dne["plati"]

    @property
    def extra_state_attributes(self) -> dict:
        s = self._stav_dne
        return {
            "datum": self._den.isoformat(),
            "scena": self._definice.get("nazev"),
            # Když den drží opakovaná nebo vícedenní událost, zrušit
            # ho kliknutím nejde — smazala by se i ta ostatní.
            "zdroj": ("opakovaná nebo vícedenní událost" if s["odjinud"]
                      else "zaškrtnutí" if s["plati"] else "nic"),
            "da_se_odskrtnout": bool(s["vlastni"]) and not s["odjinud"],
        }

    async def async_turn_on(self, **kwargs) -> None:
        if self._stav_dne["plati"]:
            return                      # už platí, nepřidávej druhý
        await self.coordinator.plan_zapis(
            dn.novy_zaznam(self._pod_id, self._definice, self._den))
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        s = self._stav_dne
        for z in s["vlastni"]:
            await self.coordinator.plan_smaz(z["uid"])
        if s["odjinud"]:
            _LOGGER.info(
                "NaPohodu: %s %s drží opakovaná nebo vícedenní událost, "
                "odškrtnutím nezmizí — zruš ji v kalendáři scény.",
                self._definice.get("nazev") or "scéna",
                self._den.isoformat())
        self.async_write_ha_state()
