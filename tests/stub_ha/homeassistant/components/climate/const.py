"""Výčty climate; ve skutečnosti v climate/const.py."""

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


