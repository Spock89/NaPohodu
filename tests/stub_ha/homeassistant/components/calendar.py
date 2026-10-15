from dataclasses import dataclass
from datetime import datetime
from enum import IntFlag


class CalendarEntityFeature(IntFlag):
    CREATE_EVENT = 1
    DELETE_EVENT = 2


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

    def async_update_event_listeners(self):
        pass
