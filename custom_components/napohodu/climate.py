"""Termostat místnosti: navenek climate, uvnitř odchylka od cíle.

Cílovou teplotu si integrace počítá sama z venkovního průměru a
místnost ji posouvá jen odchylkou. Termostatová karta, hlasovky i
HomeKit ale umí mluvit jen o absolutní teplotě, takže by se s tímhle
rozporem jinak nedalo nic z toho použít.

Překlad mezi obojím je jednoduchý: **nastavená teplota se přepočítá
na odchylku** od základu, který integrace spočítala. Kdo nastaví o půl
stupně víc, dostane o půl stupně víc — a když se venkovní průměr
zítra pohne, cíl se pohne s ním a to půlstupňové přání zůstane. Tím se
nevypíná, proč integrace vznikla; jen se k ní přidává druhá klika.

Entita proto nemá vlastní paměť. Všechno, co nastaví, jde do téhož
posuvníku odchylky, který je na kartě a v nastavení — dvě místa, jedna
hodnota. Rozsah kolečka je základ ±mez odchylky, takže se kolečkem
nedá dojet nikam, odkud by to stejně skočilo zpátky.
"""

from __future__ import annotations

import logging

from homeassistant.components.climate import (ClimateEntity,
                                              ClimateEntityFeature,
                                              HVACAction, HVACMode)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (CONF_CLIMATE, CONF_ODCHYLKA, DOMAIN, ODCHYLKA_KROK,
                    ODCHYLKA_MEZ, PODENTITA_MISTNOST)
from .entity import NaPohoduEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = hass.data[DOMAIN][entry.entry_id]
    for pod in entry.subentries.values():
        # Jen tam, kde je co ovládat. Termostat bez hlavice by byl
        # kolečko, kterým se nic nestane — a v HomeKitu by se nabízel
        # jako plnohodnotné topení.
        if (pod.subentry_type == PODENTITA_MISTNOST
                and (pod.data.get(CONF_CLIMATE) or [])):
            pridat([TermostatMistnosti(k, pod)],
                   config_subentry_id=pod.subentry_id)


class TermostatMistnosti(NaPohoduEntity, ClimateEntity):
    """Jedna místnost jako termostat."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = ODCHYLKA_KROK
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (ClimateEntityFeature.TARGET_TEMPERATURE
                                | ClimateEntityFeature.TURN_ON
                                | ClimateEntityFeature.TURN_OFF)
    # Novější Home Assistant jinak hlásí, že entita přepíná režim
    # postaru. Netýká se chování, jen způsobu zápisu.
    _enable_turn_on_off_backwards_compatibility = False
    _attr_icon = "mdi:home-thermometer"

    def __init__(self, k, pod) -> None:
        super().__init__(k, pod, "termostat")

    # ------------------------------------------------------------ čtení

    @property
    def _zaklad(self) -> float:
        """Cíl bez odchylky. Od něj se odchylka počítá i zpátky."""
        m = self.mistnost
        return m.cil_zaklad if m else 22.0

    @property
    def _odchylka(self) -> float:
        return self.coordinator.hodnota(self.pod_id, CONF_ODCHYLKA, 0.0)

    @property
    def current_temperature(self) -> float | None:
        m = self.mistnost
        return m.teplota if m else None

    @property
    def target_temperature(self) -> float | None:
        """Cíl místnosti, ne jen to, co se nastavilo.

        Když zrovna platí naplánovaná cílová teplota, je to ona:
        plán odchylku přebíjí a tvářit se jinak by znamenalo ukazovat
        číslo, podle kterého se netopí.
        """
        m = self.mistnost
        return m.cil if m else None

    @property
    def min_temp(self) -> float:
        return round(self._zaklad - ODCHYLKA_MEZ, 1)

    @property
    def max_temp(self) -> float:
        return round(self._zaklad + ODCHYLKA_MEZ, 1)

    @property
    def hvac_mode(self) -> HVACMode:
        zapnuto = self.coordinator.hodnoty.get(
            (self.pod_id, "ovladat_topeni"), 0.0) > 0
        return HVACMode.HEAT if zapnuto else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        """Topí se, nebo ne.

        Rozhoduje povel, který hlavice dostaly, ne cíl místnosti:
        útlum i otevřené okno ho stahují dolů a podle cíle by karta
        tvrdila, že se topí, i když se zrovna netopí schválně.
        """
        if self.hvac_mode is HVACMode.OFF:
            return HVACAction.OFF
        m = self.mistnost
        if m is None or m.povel_topeni is None or m.teplota is None:
            return HVACAction.IDLE
        return (HVACAction.HEATING if m.povel_topeni > m.teplota
                else HVACAction.IDLE)

    @property
    def extra_state_attributes(self) -> dict:
        m = self.mistnost
        return {
            # Ať je z karty poznat, že se nenastavuje teplota, ale
            # posun — a od čeho se posouvá.
            "zaklad": f"{self._zaklad:.1f} °C",
            "odchylka": round(self._odchylka, 1),
            "plan_cil": m.plan_cil if m else None,
            "povel_hlavicim": m.povel_topeni if m else None,
        }

    # ------------------------------------------------------------ zápis

    async def async_set_temperature(self, **kwargs) -> None:
        cil = kwargs.get(ATTR_TEMPERATURE)
        if cil is None:
            return
        m = self.mistnost
        if m is not None and m.plan_cil is not None:
            # Plán cíl přebíjí, takže uložená odchylka by se teď
            # nijak neprojevila. Mlčky to spolknout je horší než to
            # říct: na kartě by se kolečko vrátilo zpátky a vypadalo
            # by to, že termostat nefunguje.
            raise ServiceValidationError(
                f"V místnosti {m.nazev} teď platí naplánovaná cílová "
                f"teplota {m.plan_cil:.1f} °C a ta je konečná. "
                f"Odchylku přestav, až plán skončí, nebo zruš plán.")

        # Zaokrouhlení na krok posuvníku: hodnota mimo jeho mřížku by
        # se v nastavení ukázala tam, kam nejde posunout.
        odchylka = (cil - self._zaklad) / ODCHYLKA_KROK
        odchylka = round(odchylka) * ODCHYLKA_KROK
        odchylka = max(-ODCHYLKA_MEZ, min(ODCHYLKA_MEZ, odchylka))

        self.coordinator.hodnoty[(self.pod_id, CONF_ODCHYLKA)] = odchylka
        self.async_write_ha_state()
        # Posuvník odchylky ukazuje tutéž hodnotu a musí se to dozvědět.
        self.coordinator.async_update_listeners()
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """OFF sedí na přepínači Ovládat topení.

        Vypíná jen zápis do hlavic té místnosti — okna ani stínění se
        tím nezastaví. Termostat, který vypne i větrání, by nikdo
        nečekal.
        """
        self.coordinator.hodnoty[(self.pod_id, "ovladat_topeni")] = (
            1.0 if hvac_mode is HVACMode.HEAT else 0.0)
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
