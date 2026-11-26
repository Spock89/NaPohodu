"""Náhrada climate pro testy. Jen to, co platforma opravdu používá.

Dělení na `__init__` a `const` je stejné jako ve skutečném Home
Assistantu: výčty se přes balíček nevyvážejí, takže se musí brát
z `climate.const`. Jinak by tu prošel import, který v Home
Assistantu spadne.
"""

from .const import ClimateEntityFeature, HVACAction, HVACMode  # noqa: F401


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
