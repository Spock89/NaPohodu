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
