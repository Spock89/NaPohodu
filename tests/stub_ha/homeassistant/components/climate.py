"""Náhrada climate pro testy. Jen to, co platforma opravdu používá."""

from enum import IntFlag, StrEnum


class HVACMode(StrEnum):
    OFF = "off"
    HEAT = "heat"


class HVACAction(StrEnum):
    OFF = "off"
    IDLE = "idle"
    HEATING = "heating"


class ClimateEntityFeature(IntFlag):
    TARGET_TEMPERATURE = 1
    TURN_ON = 2
    TURN_OFF = 4


class ClimateEntity:
    # Jako u SwitchEntity: skutečný Home Assistant čte jméno
    # z `_attr_name` a `name` je u něj cached_property.
    @property
    def name(self):
        return getattr(self, "_attr_name", None)

    # Co skutečný Home Assistant odvozuje z `_attr_*`. Bez toho se
    # nedá ověřit, co entita navenek nabízí — a právě tím se řídí,
    # co na ni smí přijít za povel.
    @property
    def hvac_modes(self):
        return getattr(self, "_attr_hvac_modes", [])

    @property
    def supported_features(self):
        return getattr(self, "_attr_supported_features",
                       ClimateEntityFeature(0))
