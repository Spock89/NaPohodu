"""Okno pro topení a stav větrání."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (BinarySensorDeviceClass,
                                                    BinarySensorEntity)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.device_registry import DeviceInfo

from .const import (CONF_ZDROJ_OKENNIHO_M, DOMAIN,
                    PODENTITA_MISTNOST)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import vybava as vb
from .entity import NaPohoduEntity
from .typy import NaPohoduEntry


# Entity samy nic nedotazují — stav do nich tlačí koordinátor a povely
# jdou přes služby Home Assistantu, takže není co omezovat. Nula tedy
# znamená bez omezení, a hlavně je to řečeno nahlas: bez téhle deklarace
# se u platformy nedá poznat, jestli se na to zapomnělo.
PARALLEL_UPDATES = 0

async def async_setup_entry(hass: HomeAssistant, entry: NaPohoduEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = entry.runtime_data
    for pod in entry.subentries.values():
        if pod.subentry_type == PODENTITA_MISTNOST:
            sada = [Obsazeno(k, pod), Klid(k, pod)]
            # Čidlo okna v místnosti, která o žádném okně neví, hlásí
            # napořád „zavřeno" — a to je horší než nic: termostat
            # i karta se tváří, že je tu okno hlídané, a přitom se jen
            # opisuje prázdno. Stačí kontakt, ovládat okno netřeba.
            if vb.ma_smysl("okno", vb.pro_mistnost(entry, pod)):
                sada += [OknoOtevreno(k, pod), Okno(k, pod)]
            pridat(sada, config_subentry_id=pod.subentry_id)
    pridat([TopnaSezona(k, entry)])


class OknoOtevreno(NaPohoduEntity, BinarySensorEntity):
    """Vstup pro Better Thermostat.

    Kopíruje stav oken místnosti podle nastaveného zdroje. Nesouvisí
    s topnou sezónou — jen říká termostatu, jestli je otevřeno.

    Nikdy nesmí být nedostupný, jinak se s ním stane nedostupným
    i celý termostat.
    """

    _attr_device_class = BinarySensorDeviceClass.WINDOW
    # Vlastnost, ne `_attr_available`: hodnota se tím nemění, ale
    # kdyby obojí stálo vedle sebe, vyhraje vlastnost a to druhé je
    # mrtvý řádek, který tvrdí, že se tím něco nastavuje.
    _attr_available = True

    def __init__(self, k, pod):
        super().__init__(k, pod, "okno_otevreno")

    @property
    def is_on(self) -> bool:
        m = self.mistnost
        if m is None:
            return False
        zdroj = self.pod.data.get(CONF_ZDROJ_OKENNIHO_M, "nase_otevreni")
        kontakt = m.atributy.get("kontakt_hlasi")
        if zdroj == "nikdy":
            return False          # topení se otevřeným oknem neřídí
        if zdroj == "fyzicke":
            return bool(kontakt)
        if zdroj == "oboji":
            return bool(m.okno_otevreno or kontakt)
        return bool(m.okno_otevreno)

    @property
    def extra_state_attributes(self) -> dict:
        return {"k_cemu": "vstup pro Better Thermostat, ne stav topení",
                "zdroj": self.pod.data.get(CONF_ZDROJ_OKENNIHO_M,
                                           "nase_otevreni")}


class Obsazeno(NaPohoduEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, k, pod):
        super().__init__(k, pod, "obsazeno")

    @property
    def is_on(self) -> bool:
        m = self.mistnost
        return bool(m and m.obsazeno)

    @property
    def extra_state_attributes(self) -> dict:
        m = self.mistnost
        return {"indicie": m.atributy.get("indicie", [])} if m else {}


class Klid(NaPohoduEntity, BinarySensorEntity):

    def __init__(self, k, pod):
        super().__init__(k, pod, "klid")

    @property
    def is_on(self) -> bool:
        m = self.mistnost
        return bool(m and m.klid)


class Okno(NaPohoduEntity, BinarySensorEntity):
    """Skutečný stav oken místnosti."""

    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(self, k, pod):
        super().__init__(k, pod, "okno")

    @property
    def is_on(self) -> bool:
        m = self.mistnost
        return bool(m and m.okno_otevreno)


class TopnaSezona(CoordinatorEntity, BinarySensorEntity):
    """Zapnuto znamená topnou sezónu. Mimo ni se topí klimatizací,
    v sezóně radiátory — ať se ty dva zdroje nepřetahují."""

    _attr_has_entity_name = True
    _attr_translation_key = "topna_sezona"

    def __init__(self, koordinator, entry) -> None:
        super().__init__(koordinator)
        self._attr_unique_id = f"{entry.entry_id}_topna_sezona"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="NaPohodu",
            manufacturer="NaPohodu",
            model="Byt",
        )

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.topna_sezona)
