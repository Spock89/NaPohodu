"""Typ zápisu konfigurace. Vlastní modul, aby nevznikl kruh v importech.

Koordinátor si bere seznam šoupátek z `number`, takže kdyby `number`
sahalo pro typ zpátky do `coordinator`, importovaly by se moduly
navzájem a integrace by se nenačetla. Alias patří sem a jméno
koordinátoru se bere jen při kontrole typů — tělo aliasu se za běhu
nevyhodnocuje.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from .coordinator import NaPohoduCoordinator

# Zápis konfigurace, který s sebou nese svůj koordinátor. Platformy ho
# proto nemusí hledat v hass.data podle entry_id a typ se nemusí
# hádat: `entry.runtime_data` je koordinátor, a je to vidět.
type NaPohoduEntry = ConfigEntry[NaPohoduCoordinator]
