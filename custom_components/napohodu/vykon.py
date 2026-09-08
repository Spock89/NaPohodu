"""Vykonávání rozhodnutí.

Do téhle chvíle integrace jen počítala. Tenhle modul jako jediný sahá na
pohony, a je proto psaný opatrně: každý povel má důvod, mezi povely se
drží odstup a nic se neposílá, dokud to uživatel nepovolí přepínačem.

Okna se ovládají přes cover.open_cover a cover.close_cover. Stínění přes
uložené pojmenované posloupnosti, protože tvoje žaluzie neumí naklápění
přímo a úhlu se dosahuje najížděním.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

try:  # uvnitř Home Assistantu balíček, v testech samostatný modul
    from . import core
except ImportError:  # pragma: no cover
    import core

if TYPE_CHECKING:  # kvůli testům se Home Assistant neimportuje za běhu
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Kratší odstup nemá smysl, pohon se stejně nestihne rozjet a zastavit.
MIN_ODSTUP_S = 30.0


@dataclass
class StavVykonu:
    """Co jsme naposledy poslali. Brání opakování a poskakování."""

    posledni_povel: str | None = None
    posledni_cas_s: float = -1e9
    pulz_do_s: float | None = None
    posledni_stineni: dict[str, str] = field(default_factory=dict)
    stineni_cas_s: float = -1e9
    chyby: list[str] = field(default_factory=list)


class Vykonavac:
    """Jeden na zónu. Drží si, co už poslal."""

    def __init__(self, hass: "HomeAssistant", zona_id: str) -> None:
        self.hass = hass
        self.zona_id = zona_id
        self.stav = StavVykonu()

    # ------------------------------------------------------------ okno

    async def okno(self, okno_entita: str | None, r: core.Rozhodnuti,
                   cas_s: float, otevreno: bool) -> str | None:
        """Provede rozhodnutí o okně. Vrací popis toho, co poslal."""
        if not okno_entita:
            return None

        # pulz dojel: zavřít, i když jádro zrovna nic nechce
        if (self.stav.pulz_do_s is not None and otevreno
                and cas_s >= self.stav.pulz_do_s):
            self.stav.pulz_do_s = None
            return await self._povel(okno_entita, "close_cover", cas_s,
                                     "pulz dojel")

        if r.akce is core.Akce.NIC:
            return None

        if r.akce is core.Akce.OTEVRIT:
            self.stav.pulz_do_s = (cas_s + r.limit_s) if r.limit_s else None
            return await self._povel(okno_entita, "open_cover", cas_s, r.duvod)

        self.stav.pulz_do_s = None
        return await self._povel(okno_entita, "close_cover", cas_s, r.duvod)

    async def _povel(self, entita: str, sluzba: str, cas_s: float,
                     duvod: str) -> str | None:
        if (sluzba == self.stav.posledni_povel
                and cas_s - self.stav.posledni_cas_s < MIN_ODSTUP_S):
            return None            # totéž jsme právě poslali
        try:
            await self.hass.services.async_call(
                "cover", sluzba, {"entity_id": entita}, blocking=False)
        except Exception as e:  # pragma: no cover - výpadek pohonu
            self.stav.chyby.append(f"{sluzba}: {e}")
            _LOGGER.warning("NaPohodu: %s na %s selhalo: %s", sluzba, entita, e)
            return None
        self.stav.posledni_povel = sluzba
        self.stav.posledni_cas_s = cas_s
        _LOGGER.info("NaPohodu: %s na %s — %s", sluzba, entita, duvod)
        return f"{sluzba} ({duvod})"

    # ------------------------------------------------------------ stínění

    async def stineni(self, zaluzie: list[str] | str | None,
                      nazev_stavu: str | None, cas_s: float,
                      klid_min: float) -> str | None:
        """Nastaví pojmenovaný stav na všech žaluziích zóny.

        Žaluzií může být víc, například dvě okna v obýváku. Jedou
        postupně a každá si pamatuje svůj poslední stav zvlášť — když
        jednu přestavíš ručně, ostatní se kvůli ní nerozjedou.
        """
        if not zaluzie or not nazev_stavu:
            return None
        seznam = [zaluzie] if isinstance(zaluzie, str) else list(zaluzie)
        zbyva = [z for z in seznam
                 if self.stav.posledni_stineni.get(z) != nazev_stavu]
        if not zbyva:
            return None
        if cas_s - self.stav.stineni_cas_s < klid_min * 60:
            return None            # ať se lamely nehoupou

        try:  # pozdní import, ať se modul dá testovat bez Home Assistanta
            from .services import proved_stav_stineni
        except ImportError:  # pragma: no cover
            from services import proved_stav_stineni

        hotovo = []
        for z in zbyva:
            vysledek = await proved_stav_stineni(self.hass, z, nazev_stavu)
            if vysledek.get("povedlo_se"):
                self.stav.posledni_stineni[z] = nazev_stavu
                hotovo.append(z)
                _LOGGER.info("NaPohodu: žaluzie %s -> %s", z, nazev_stavu)
            else:
                self.stav.chyby.append(f"{z}: {vysledek.get('chyba')}")
                _LOGGER.warning("NaPohodu: stínění %s na %s selhalo: %s",
                                nazev_stavu, z, vysledek.get("chyba"))

        if not hotovo:
            return None
        self.stav.stineni_cas_s = cas_s
        return f"stínění: {nazev_stavu} ({len(hotovo)}x)"


# kdy smí automatika hýbat žaluziemi
REZIM_VZDY = "vzdy"
REZIM_JEN_PRYC = "jen_pryc"       # doma si je řídíme sami
REZIM_NIKDY = "nikdy"

# kdy se po západu slunce zatahuje kvůli soukromí
SOUKROMI_NIKDY = "nikdy"
SOUKROMI_HNED = "hned"            # hned po západu
SOUKROMI_POHYB = "pri_pohybu"     # až když do místnosti někdo přijde


def stav_stineni(zisk: float, prah: float, horko: bool, zima: bool,
                 doma: bool, jmena: dict, rezim: str = REZIM_VZDY,
                 po_zapadu: bool = False, pohyb: bool = False,
                 soukromi_kdy: str = SOUKROMI_NIKDY) -> str | None:
    """Který pojmenovaný stav má platit.

    Prázdný návrat znamená nechat být, a to je u žaluzií správná výchozí
    odpověď. Automatika, která přestavuje to, co si člověk před chvílí
    nastavil ručně, je horší než žádná.

    Pořadí je dané tím, co je naléhavější. Prázdný byt přebíjí vše.
    Soukromí po setmění přebíjí režim, protože zatáhnout po západu chceme
    i tam, kde si jinak žaluzie řídíme sami. Slunce je až poslední, a po
    západu už stejně žádné není.
    """
    if not doma:
        return jmena.get("pryc") or None
    if rezim == REZIM_NIKDY:
        return None

    if po_zapadu and soukromi_kdy != SOUKROMI_NIKDY:
        if soukromi_kdy == SOUKROMI_HNED or (
                soukromi_kdy == SOUKROMI_POHYB and pohyb):
            return jmena.get("soukromi") or None

    if rezim == REZIM_JEN_PRYC:
        return None

    if zisk < prah:
        return None
    if horko:
        return jmena.get("zastinit") or None
    if zima:
        return jmena.get("odstinit") or None
    return None
