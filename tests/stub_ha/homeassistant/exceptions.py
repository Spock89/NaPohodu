"""Náhrada výjimek Home Assistantu."""


class HomeAssistantError(Exception):
    pass


class ServiceValidationError(HomeAssistantError):
    pass
