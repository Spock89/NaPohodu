"""Přepínač, kterým se zóně povolí sahat na okno.

Ve výchozím stavu vypnutý. Do té doby integrace jen počítá a ukazuje,
co by udělala, což je bezpečnější způsob, jak ji poprvé nasadit.
"""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import dny as dn
from .const import (DOMAIN, PODENTITA_KLIMA, PODENTITA_MISTNOST,
                    )
from .entity import NaPohoduEntity

_LOGGER = logging.getLogger(__name__)


def klic_dne(odstup: int) -> str:
    """Identifikátor dlaždice. Jedno místo pro entitu i pro kartu."""
    return f"napohodu_den_{odstup:02d}"


def _sprav_identifikatory(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Přejmenuje dlaždice z dřívějších vydání.

    Ve 2.44 a 2.45 si identifikátor odvozoval Home Assistant ze jména,
    a to je u dlaždice datum — vznikly z toho `switch.dnes` a spol.
    Registr si první jméno pamatuje, takže by oprava sama na stávající
    instalaci nedosáhla a mřížka by zůstala prázdná i po aktualizaci.
    """
    registr = er.async_get(hass)
    for i in range(dn.DNU_DOPREDU):
        stary = registr.async_get_entity_id(
            "switch", DOMAIN, f"{entry.entry_id}_den_{i:02d}")
        novy = f"switch.{klic_dne(i)}"
        if stary and stary != novy and registr.async_get(novy) is None:
            _LOGGER.info("NaPohodu: přejmenovávám %s na %s", stary, novy)
            registr.async_update_entity(stary, new_entity_id=novy)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            pridat: AddEntitiesCallback) -> None:
    k = hass.data[DOMAIN][entry.entry_id]
    # Mřížka dnů patří vybrané scéně, ne každé zvlášť: s každou novou
    # by karta narostla o pětatřicet dlaždic a musela by se generovat
    # znovu.
    #
    # Zakládá se vždycky, i když zrovna žádná scéna není. Dřív se
    # zakládala jen se scénou, takže po smazání poslední scény zmizely
    # entity, na které se vygenerovaný dashboard odkazuje — a karta
    # kalendáře se pak místo prázdna donekonečna točí, protože na
    # chybějící entitu nečeká s hláškou, ale s kolečkem.
    _sprav_identifikatory(hass, entry)
    pridat([DenSceny(k, entry, i) for i in range(dn.DNU_DOPREDU)])


    for pod in entry.subentries.values():
        if pod.subentry_type == PODENTITA_MISTNOST:
            pridat([OvladatOkno(k, pod), OvladatStineni(k, pod),
                    OtevritProPohodu(k, pod), ZvlhcovatVeSpanku(k, pod),
                    OvladatTopeni(k, pod)],
                   config_subentry_id=pod.subentry_id)
        elif pod.subentry_type == PODENTITA_KLIMA:
            pridat([OvladatKlimu(k, pod)], config_subentry_id=pod.subentry_id)



class NaPohoduPrepinac(NaPohoduEntity, SwitchEntity, RestoreEntity):
    """Povolení sahat na pohon. Ve výchozím stavu vypnuté."""

    _attr_entity_category = EntityCategory.CONFIG
    _klic_hodnoty = "ovladat"

    def __init__(self, k, pod, klic):
        super().__init__(k, pod, klic)
        self._zap = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        posledni = await self.async_get_last_state()
        if posledni is not None:
            self._zap = posledni.state == "on"
        self.coordinator.hodnoty[
            (self.pod_id, self._klic_hodnoty)] = float(self._zap)

    @property
    def is_on(self) -> bool:
        return self._zap

    async def async_turn_on(self, **kwargs) -> None:
        await self._nastav(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._nastav(False)

    async def _nastav(self, hodnota: bool) -> None:
        self._zap = hodnota
        self.coordinator.hodnoty[
            (self.pod_id, self._klic_hodnoty)] = float(hodnota)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class ZVolbyMistnosti(NaPohoduPrepinac):
    """Přepínač, který ve výchozím stavu kopíruje formulář.

    Výchozí stav nese formulář místnosti, protože tyhle volby se tam
    zakládají. Přepínač je pak jen pohodlnější cesta, jak je měnit
    z panelu.
    """

    _vychozi_klic = ""

    async def async_added_to_hass(self) -> None:
        # Nejdřív obnova, pak formulář — a ten vyhraje jen tehdy, když
        # ho člověk opravdu změnil. Opačné pořadí znamenalo, že obnova
        # formulář vždycky přepsala a nastavení se neprojevilo.
        await super().async_added_to_hass()
        z_formulare = bool(self.pod.data.get(self._vychozi_klic, True))
        klic = (self.pod_id, self._klic_hodnoty)
        if self.coordinator.formular_zmenen(klic, float(z_formulare)):
            self._zap = z_formulare
        self.coordinator.hodnoty[klic] = float(self._zap)


class OtevritProPohodu(ZVolbyMistnosti):
    """Smí se otevřít i tehdy, když k tomu není důvod?"""

    _attr_icon = "mdi:weather-sunny"
    _klic_hodnoty = "pro_pohodu"
    _vychozi_klic = "pro_pohodu"

    def __init__(self, k, pod):
        super().__init__(k, pod, "otevirat_i_pro_pohodu")


class ZvlhcovatVeSpanku(ZVolbyMistnosti):
    """Smí zvlhčovač běžet i při zapnutém spánku?"""

    _attr_icon = "mdi:air-humidifier"
    _klic_hodnoty = "zvlhcovac_ve_spanku"
    _vychozi_klic = "zvlhcovac_ve_spanku"

    def __init__(self, k, pod):
        super().__init__(k, pod, "zvlhcovat_i_ve_spanku")


class OvladatOkno(NaPohoduPrepinac):
    _attr_icon = "mdi:window-shutter-auto"
    _klic_hodnoty = "ovladat"

    def __init__(self, k, pod):
        super().__init__(k, pod, "ovladat_okno")


class OvladatStineni(NaPohoduPrepinac):
    _attr_icon = "mdi:blinds-horizontal"
    _klic_hodnoty = "ovladat_stineni"

    def __init__(self, k, pod):
        super().__init__(k, pod, "ovladat_stineni")


class OvladatKlimu(NaPohoduPrepinac):
    _attr_icon = "mdi:air-conditioner"
    _klic_hodnoty = "ovladat"

    def __init__(self, k, pod):
        super().__init__(k, pod, "ovladat_klimu")


class OvladatTopeni(NaPohoduPrepinac):
    """Povolí zapisovat cílovou teplotu do hlavic místnosti."""

    _attr_icon = "mdi:radiator"
    _klic_hodnoty = "ovladat_topeni"

    def __init__(self, k, pod):
        super().__init__(k, pod, "ovladat_topeni")


class DenSceny(CoordinatorEntity, SwitchEntity):
    """Jeden den v zaškrtávací mřížce vybrané scény.

    Dlaždice patří odstupu od dneška, ne datu — jen tak zůstane mřížka
    na kartě pořád stejná. Zaškrtnutí se ukládá na datum, takže přes
    noc neputuje: dlaždice se jen posunou o jednu a zaškrtnutý den
    zůstane zaškrtnutý tam, kam patří.

    Scénu nese rolovátko, ne dlaždice. Jinak by karta s každou novou
    scénou narostla o celou mřížku.
    """

    # Dlaždice schválně nepatří k žádnému zařízení. Jméno se pak
    # skládá z jediné věci — z `_attr_name` — a jméno zařízení se před
    # ně nemá jak dostat: složené jméno „zařízení + entita" vzniká
    # v Home Assistantu jedině tehdy, když entita zařízení má.
    #
    # Samotné `_attr_has_entity_name = False` nestačilo. V té verzi
    # Home Assistanta, která tohle má doopravdy ovládat, se jméno
    # zařízení lepilo dál a na dlaždici široké sedminu karty z toho
    # zbylo „NaP…" — datum se nevešlo vůbec. Tahle cesta je proti
    # verzím odolná, protože nezávisí na žádném přepínači.
    _attr_has_entity_name = False
    _attr_icon = "mdi:calendar-check"

    def __init__(self, k, entry, odstup: int) -> None:
        super().__init__(k)
        self._odstup = odstup
        # V jméně entity je číslo dlaždice, ne datum: z něho vzniká
        # `switch.napohodu_den_03`, a to se nesmí přes noc měnit.
        # Datum je ve jméně, které se ukazuje na kartě.
        self._attr_unique_id = f"{entry.entry_id}_den_{odstup:02d}"
        # Identifikátor se nastavuje napevno. Home Assistant ho jinak
        # odvodí ze jména — a to je tady datum, takže by z dlaždic
        # vznikly `switch.dnes`, `switch.zitra`, `switch.st_28_10`.
        # Karta hledá `switch.napohodu_den_00` a nenašla by ani jednu,
        # takže se mřížka negenerovala vůbec. Jméno s datem je jen to,
        # co se čte na dlaždici.
        self.entity_id = f"switch.{klic_dne(odstup)}"
        # Jméno se zapisuje do `_attr_name`, ne do přepsané vlastnosti
        # `name`: ta je v Home Assistantu `cached_property` a přepsat
        # ji obyčejnou vlastností znamená, že jméno nedojde — karta pak
        # spadne na jméno zařízení a na dlaždicích stojí „NaP…".
        # Přes `_attr_name` si HA hlídá i vyprázdnění své paměti.
        self._attr_name = dn.popis(odstup)

    @property
    def _pod_id(self) -> str | None:
        return self.coordinator.scena_vybrana()[0]

    @property
    def _definice(self) -> dict:
        return self.coordinator.scena_vybrana()[1]

    @property
    def _den(self):
        return dn.datum(self._odstup)

    @property
    def _stav_dne(self) -> dict:
        if self._pod_id is None:
            return {"plati": False, "vlastni": [], "odjinud": False}
        return dn.pro_den(self.coordinator.plan_zaznamy(), self._pod_id,
                          self._den, self.coordinator.plan_rozbal)

    def _obnov_jmeno(self) -> None:
        """Zkratka dne na dlaždici. Po půlnoci se posune o jeden den."""
        self._attr_name = dn.popis(self._odstup)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._obnov_jmeno()

    def _handle_coordinator_update(self) -> None:
        self._obnov_jmeno()
        super()._handle_coordinator_update()

    @property
    def _ceka(self) -> dict[str, set]:
        if self._pod_id is None:
            return {"pridat": set(), "zrusit": set()}
        return self.coordinator.scena_ceka(self._pod_id)

    @property
    def is_on(self) -> bool:
        """Jak to bude vypadat po uložení, ne jak to je teď.

        Mřížka je rozpracovaný výběr: zaškrtnutí se nezapisuje hned,
        aby šlo naklikat čtrnáct dní a uložit je jedním stiskem.
        """
        den, ceka = self._den, self._ceka
        if den in ceka["pridat"]:
            return True
        if den in ceka["zrusit"]:
            return False
        return self._stav_dne["plati"]

    @property
    def icon(self) -> str:
        """Tvar nese stav zaškrtnutí, barvu den.

        Rozpracovaná změna má přednost: dokud se neuloží, je důležité
        vidět, co se zapíše a co zruší. Víkend a svátek jsou na druhé
        ose, v barvě dlaždice — kdyby je nesl taky tvar, praly by se
        o jedno místo dvě různé věci.
        """
        den, ceka = self._den, self._ceka
        if den in ceka["pridat"]:
            return "mdi:calendar-plus"
        if den in ceka["zrusit"]:
            return "mdi:calendar-remove"
        return ("mdi:calendar-check" if self._stav_dne["plati"]
                else "mdi:calendar-blank-outline")

    @property
    def extra_state_attributes(self) -> dict:
        s = self._stav_dne
        den, ceka = self._den, self._ceka
        return {
            "datum": den.isoformat(),
            # Spodní řádek dlaždice. Karta ho vypisuje místo stavu,
            # protože „Zapnuto" u zaškrtávátka nic neříká a datum se
            # na horní řádek vedle zkratky dne nevejde.
            "datum_popis": dn.datum_popis(self._odstup),
            # Víkend a svátek. Na dlaždici je víkend vidět ze zkratky
            # dne a z ikony, svátek z hvězdičky; obarvit ho vestavěná
            # karta neumí.
            "typ_dne": dn.typ_dne(den),
            "den": dn.DNY_TYDNE[den.weekday()],
            "vikend": dn.vikend(den),
            "svatek": dn.svatek(den),
            "scena": self._definice.get("nazev"),
            # Když den drží opakovaná nebo vícedenní událost, zrušit
            # ho kliknutím nejde — smazala by se i ta ostatní.
            "zdroj": ("opakovaná nebo vícedenní událost" if s["odjinud"]
                      else "zaškrtnutí" if s["plati"] else "nic"),
            "da_se_odskrtnout": bool(s["vlastni"]) and not s["odjinud"],
            "v_kalendari": s["plati"],
            "ceka": ("přidat" if den in ceka["pridat"]
                     else "zrušit" if den in ceka["zrusit"] else None),
        }

    async def async_turn_on(self, **kwargs) -> None:
        if self._pod_id is None:
            return
        den, ceka = self._den, self._ceka
        ceka["zrusit"].discard(den)
        if not self._stav_dne["plati"]:
            ceka["pridat"].add(den)
        self.async_write_ha_state()
        # Počítadlo „k uložení" visí na jiné entitě, musí se dozvědět.
        self.coordinator.async_update_listeners()

    async def async_turn_off(self, **kwargs) -> None:
        if self._pod_id is None:
            return
        den, ceka = self._den, self._ceka
        ceka["pridat"].discard(den)
        s = self._stav_dne
        if s["odjinud"]:
            _LOGGER.info(
                "NaPohodu: %s %s drží opakovaná nebo vícedenní událost, "
                "odškrtnutím nezmizí — zruš ji v kalendáři scény.",
                self._definice.get("nazev") or "scéna", den.isoformat())
        elif s["vlastni"]:
            ceka["zrusit"].add(den)
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()
