"""Výčty kalendáře; ve skutečnosti v calendar/const.py."""

from enum import IntFlag


class CalendarEntityFeature(IntFlag):
    CREATE_EVENT = 1
    DELETE_EVENT = 2
