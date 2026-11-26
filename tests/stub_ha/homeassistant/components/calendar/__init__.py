"""Náhrada kalendáře pro testy.

Dělení na `__init__` a `const` je stejné jako ve skutečném Home
Assistantu: výčet funkcí se přes balíček nevyváží, takže se musí
brát z `calendar.const`.
"""

from dataclasses import dataclass
from datetime import datetime


from .const import CalendarEntityFeature  # noqa: F401


@dataclass
class CalendarEvent:
    start: datetime
    end: datetime
    summary: str
    description: str = ""
    uid: str | None = None
    rrule: str | None = None
    recurrence_id: str | None = None


class CalendarEntity:
    _attr_event = None
    _attr_supported_features = 0

    def async_write_ha_state(self):
        pass
