"""Náhrada registru oprav: jen si pamatuje, co se založilo a zrušilo."""

from enum import StrEnum


class IssueSeverity(StrEnum):
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"


def _registr(hass):
    if not hasattr(hass, "opravy_registr"):
        hass.opravy_registr = {}
    return hass.opravy_registr


def async_create_issue(hass, domain, issue_id, *, is_fixable,
                       severity, translation_key,
                       translation_placeholders=None, **_kw):
    _registr(hass)[(domain, issue_id)] = {
        "is_fixable": is_fixable, "severity": str(severity),
        "translation_key": translation_key,
        "translation_placeholders": translation_placeholders or {},
    }


def async_delete_issue(hass, domain, issue_id, **_kw):
    _registr(hass).pop((domain, issue_id), None)
