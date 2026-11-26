"""Integrace NaPohodu — udržuje v místnostech teplotu a kvalitní vzduch."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from . import vybava as vb
from . import vykon as vy
from .const import (CONF_STINENI_MAPA, CONF_STINENI_PREDSTIH, CONF_ZALUZIE,
                    DOMAIN, PODENTITA_MISTNOST, PODENTITA_ZONA)
from .coordinator import NaPohoduCoordinator
from .services import zaregistruj
from .typy import NaPohoduEntry

_LOGGER = logging.getLogger(__name__)

# Nastavuje se jen přes rozhraní. Bez tohohle by Home Assistant u
# integrace, která má `async_setup`, čekal i nastavení z YAML.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMY: list[Platform] = [
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.CLIMATE,
    Platform.DATETIME,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
]


def _preved(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Dorovná uložené nastavení na to, co umí tahle verze.

    Měnit výchozí hodnotu nestačí: výchozí platí jen pro nově
    zakládanou místnost, kdežto ta stávající má v konfiguraci
    uloženou tu starou a nic by se u ní nezměnilo.

    Předstih stínění: stínilo se o stupeň dřív, než teplota došla na
    cíl. Zrušeno, stíní se až při překročení cíle. Nastavení zůstává,
    kdo chce stínit dřív, nastaví si ho zpátky.
    """
    for pod in list(entry.subentries.values()):
        if pod.subentry_type != PODENTITA_MISTNOST:
            continue
        stary = pod.data.get(CONF_STINENI_PREDSTIH)
        if stary is None or float(stary) == 0.0:
            continue
        hass.config_entries.async_update_subentry(
            entry, pod, data={**pod.data, CONF_STINENI_PREDSTIH: 0.0})
        _LOGGER.info(
            "NaPohodu: %s — předstih stínění %.1f °C zrušen, stíní se "
            "až při překročení cíle", pod.title, float(stary))


def _uklid(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Smaže entity, které v místnosti nemají co dělat.

    Přestat je zakládat nestačí. Registr entit si pamatuje všechno,
    co kdy existovalo, a platforma z něj sama nic nemaže — takže
    vypínač okna v místnosti bez okna by po aktualizaci zůstal
    v dashboardu viset jako „nedostupný" a ručně by se musel mazat.

    Co kde má význam, se bere ze `vybava`, odkud se tím samým
    pravidlem řídí i zakládání entit a nastavení. Klíč, který tabulka
    nezná, se nemaže — radši zůstane přebytečná entita než aby zmizela
    ta, na kterou se někdo nedopatřením zapomněl.

    Nejde o jednorázový převod: když se z místnosti okno odebere
    i později, uklidí se při dalším startu stejně.
    """
    registr = er.async_get(hass)
    zapisy = er.async_entries_for_config_entry(registr, entry.entry_id)

    def smaz(zapis, kde: str) -> None:
        registr.async_remove(zapis.entity_id)
        _LOGGER.info("NaPohodu: %s — %s smazána, takové zařízení tu "
                     "není", kde, zapis.entity_id)

    # Entity celého bytu. Zatím jediná závisí na vybavení: přepočtená
    # rychlost větru bez čidla větru nemá co hlásit.
    if not vb.ma_vitr({**entry.data, **entry.options}):
        for zapis in zapisy:
            if zapis.unique_id == f"{entry.entry_id}_vitr":
                smaz(zapis, "byt")

    for pod in list(entry.subentries.values()):
        if pod.subentry_type != PODENTITA_MISTNOST:
            continue
        v = vb.pro_mistnost(entry, pod)
        mapa = pod.data.get(CONF_STINENI_MAPA) or {}
        # Výběr stavu nese v identifikátoru konkrétní žaluzii, protože
        # jich místnost může mít víc. Tabulka druhů na to nestačí:
        # odebráním druhé žaluzie osiří entita, jejíž jméno nikde
        # nezůstane, a musí se dopočítat z toho, co v místnosti zbylo.
        zaluzie = {f"stav_{z}" for z in (pod.data.get(CONF_ZALUZIE) or [])}
        predpona = f"{pod.subentry_id}_"
        for zapis in zapisy:
            if not (zapis.unique_id or "").startswith(predpona):
                continue
            klic = zapis.unique_id[len(predpona):]
            # Tečka je tu podmínkou schválně: jen tak se pozná odkaz
            # na entitu žaluzie. Bez ní by se o klíč pojmenovaný
            # „stav_cehosi" jednou smazalo něco jiného.
            if klic.startswith("stav_") and "." in klic:
                prebyva = klic not in zaluzie
            elif klic in vb.PODLE_ROLE:
                # Tlačítka stínění nezávisejí na přiřazené žaluzii, ale
                # na tom, jestli role v mapě vůbec na nějakou míří.
                prebyva = not vy.cile_zaluzii(vb.PODLE_ROLE[klic], mapa)
            else:
                prebyva = not vb.ma_smysl(klic, v)
            if prebyva:
                smaz(zapis, pod.title)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Služby musí existovat dřív než zápis konfigurace.

    Registrovat je až při načtení zápisu znamená, že při nenačtené
    integraci služby v Home Assistantu vůbec nejsou — a automatizace,
    která je zavolá, spadne na „služba neexistuje" místo na hlášku,
    že integrace není načtená. Přitom nenačtený zápis je zrovna ten
    stav, kdy se to stane.
    """
    await zaregistruj(hass)
    return True


async def async_setup_entry(hass: HomeAssistant,
                            entry: NaPohoduEntry) -> bool:
    _preved(hass, entry)
    _uklid(hass, entry)

    koordinator = NaPohoduCoordinator(hass, entry)
    await koordinator.async_nacti()
    await koordinator.async_config_entry_first_refresh()
    # Koordinátor patří zápisu konfigurace, ne globálnímu slovníku:
    # odebráním zápisu zmizí s ním a platforma si ho nemusí hledat
    # podle entry_id. V hass.data zůstávají jen věci sdílené napříč
    # zápisy, tedy uložené stavy žaluzií pro služby.
    entry.runtime_data = koordinator

    mistnosti = sum(1 for p in entry.subentries.values()
                    if p.subentry_type == PODENTITA_MISTNOST)
    zony = sum(1 for p in entry.subentries.values()
               if p.subentry_type == PODENTITA_ZONA)
    _LOGGER.info("NaPohodu: %d místností, %d zón", mistnosti, zony)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMY)
    entry.async_on_unload(entry.add_update_listener(_znovu_nacti))
    return True


async def _znovu_nacti(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Přibyla nebo se změnila místnost či zóna."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant,
                             entry: NaPohoduEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMY)
