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
    # poloha, na které žaluzie po povelu skutečně skončila — podle ní
    # se pozná ruční přestavení
    stineni_poloha: dict[str, float] = field(default_factory=dict)
    stineni_cas_s: float = -1e9
    prvni_beh: bool = True
    chyby: list[str] = field(default_factory=list)
    zarizeni: dict[str, bool] = field(default_factory=dict)
    # poslední odeslaný povel si držíme, ať na kartě nezmizí po minutě
    posledni_popis: str | None = None
    topeni_cil: float | None = None
    topeni_rezim: str | None = None
    topeni_cas_s: float = -1e9


class Vykonavac:
    """Jeden na zónu. Drží si, co už poslal."""

    def __init__(self, hass: "HomeAssistant", zona_id: str,
                 po_startu: bool = True) -> None:
        self.hass = hass
        self.zona_id = zona_id
        self.stav = StavVykonu(prvni_beh=po_startu)

    # ------------------------------------------------------------ okno

    TOLERANCE_POLOHY = 0.6      # jemnější rozdíly pohon stejně neudrží

    def zkontroluj_polohu(self, zaluzie: str,
                          poloha: float | None) -> str | None:
        """Ověří, že žaluzie je tam, kam jsme ji poslali.

        Bez toho by ruční přestavení zůstalo skryté: paměť tvrdí, že je
        zastíněno, takže se po západu slunce už nic nepošle. Když se
        poloha rozešla, paměť se zahodí a příští rozhodnutí ji srovná.
        """
        ocekavana = self.stav.stineni_poloha.get(zaluzie)
        if poloha is None or ocekavana is None:
            return None
        if abs(poloha - ocekavana) <= self.TOLERANCE_POLOHY:
            return None

        byval = self.stav.posledni_stineni.pop(zaluzie, None)
        self.stav.stineni_poloha.pop(zaluzie, None)
        _LOGGER.info("NaPohodu: %s je na %.1f %%, čekal jsem %.1f %% — "
                     "někdo ji přestavil, zapomínám stav %s",
                     zaluzie, poloha, ocekavana, byval)
        return byval

    def zapomen(self) -> None:
        """Zahodí paměť o posledních povelech.

        Používá se, když si člověk přestaví žaluzie ručně nebo když chce
        po restartu srovnat všechno do polohy, kterou automatika žádá.
        Bez toho by integrace mlčela, protože si myslí, že už poslala.
        """
        self.stav.posledni_povel = None
        self.stav.posledni_cas_s = -1e9
        self.stav.posledni_stineni.clear()
        self.stav.stineni_poloha.clear()
        self.stav.stineni_cas_s = -1e9
        self.stav.prvni_beh = False    # tlačítko chce pohyb, ne mlčení
        self.stav.chyby.clear()

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

    async def topeni(self, entity: list[str], povel: "PovelTopeni",
                     cas_s: float) -> str | None:
        """Nastaví hlavicím teplotu. Posílá jen při skutečné změně.

        Režim None znamená nesahat na režim — o zapnutí si rozhoduje
        hlavice sama. Teplota se posílá vždycky, bez ní hlavice neví,
        na co regulovat.
        """
        rezim, cil = povel.rezim, povel.cil
        if not entity or cil is None:
            return None
        zmena_rezimu = rezim is not None and rezim != self.stav.topeni_rezim
        zmena_cile = (self.stav.topeni_cil is None
                      or abs(cil - self.stav.topeni_cil) >= TOPENI_ZMENA_MIN)
        uplynulo = cas_s - self.stav.topeni_cas_s >= TOPENI_KLID_S
        if not zmena_rezimu and not (zmena_cile and uplynulo):
            return None

        try:
            if zmena_rezimu:
                await self.hass.services.async_call(
                    "climate", "set_hvac_mode",
                    {"entity_id": entity, "hvac_mode": rezim}, blocking=False)
            await self.hass.services.async_call(
                "climate", "set_temperature",
                {"entity_id": entity, "temperature": cil}, blocking=False)
        except Exception as e:  # pragma: no cover
            self.stav.chyby.append(f"topení: {e}")
            _LOGGER.warning("NaPohodu: topení %s selhalo: %s", entity, e)
            return None

        if rezim is not None:
            self.stav.topeni_rezim = rezim
        self.stav.topeni_cil = cil
        self.stav.topeni_cas_s = cas_s
        _LOGGER.info("NaPohodu: topení %s -> %.1f °C (%s)",
                     entity, cil, povel.duvod)
        return f"{cil:.1f} °C — {povel.duvod}"

    async def zarizeni(self, entity: list[str], zapnout: bool | None,
                       klic: str) -> str | None:
        """Zapne nebo vypne pomocná zařízení, třeba čističku nebo odtah.

        Povel se posílá jen při změně. Opakované zapínání už zapnuté
        čističky nic nezlepší a jen zatěžuje síť.
        """
        if not entity or zapnout is None:
            return None
        if self.stav.zarizeni.get(klic) == zapnout:
            return None

        sluzba = "turn_on" if zapnout else "turn_off"
        for e in entity:
            domena = e.split(".", 1)[0]
            try:
                await self.hass.services.async_call(
                    domena, sluzba, {"entity_id": e}, blocking=False)
            except Exception as ex:  # pragma: no cover
                self.stav.chyby.append(f"{e}: {ex}")
                _LOGGER.warning("NaPohodu: %s na %s selhalo: %s",
                                sluzba, e, ex)
                return None
        self.stav.zarizeni[klic] = zapnout
        _LOGGER.info("NaPohodu: %s -> %s", klic, "zapnuto" if zapnout else "vypnuto")
        return f"{klic}: {'zapnuto' if zapnout else 'vypnuto'}"

    async def stineni(self, cile: dict[str, str], cas_s: float,
                      klid_min: float) -> str | None:
        """Nastaví každé žaluzii ten její stav, který plní žádanou roli.

        Žaluzií může být víc a každá může mít pro stejnou roli jinak
        pojmenovaný stav. Jedou postupně a každá si pamatuje svou polohu
        zvlášť — když jednu přestavíš ručně, ostatní se kvůli ní nerozjedou.
        """
        if not cile:
            return None

        # Po startu se žaluziemi nehýbeme. Nevíme, kde stojí, a rachot
        # bez důvodu je horší než minuta, kdy nejsou přesně nastavené.
        # Zapamatujeme si, co bychom chtěli, a čekáme na skutečnou změnu.
        if self.stav.prvni_beh:
            self.stav.prvni_beh = False
            self.stav.posledni_stineni.update(cile)
            self.stav.stineni_cas_s = cas_s
            _LOGGER.debug("NaPohodu: po startu přebírám polohy %s", cile)
            return None

        zbyva = {z: n for z, n in cile.items()
                 if self.stav.posledni_stineni.get(z) != n}
        if not zbyva:
            return None

        if cas_s - self.stav.stineni_cas_s < klid_min * 60:
            return None            # ať se lamely nehoupou

        try:  # pozdní import, ať se modul dá testovat bez Home Assistanta
            from .services import proved_stav_stineni
        except ImportError:  # pragma: no cover
            from services import proved_stav_stineni

        hotovo = []
        for z, nazev in zbyva.items():
            vysledek = await proved_stav_stineni(self.hass, z, nazev)
            if vysledek.get("povedlo_se"):
                self.stav.posledni_stineni[z] = nazev
                poloha = vysledek.get("poloha_po")
                if poloha is not None:
                    self.stav.stineni_poloha[z] = float(poloha)
                hotovo.append(nazev)
                _LOGGER.info("NaPohodu: žaluzie %s -> %s", z, nazev)
            else:
                self.stav.chyby.append(f"{z}: {vysledek.get('chyba')}")
                _LOGGER.warning("NaPohodu: stínění %s na %s selhalo: %s",
                                nazev, z, vysledek.get("chyba"))

        if not hotovo:
            return None
        self.stav.stineni_cas_s = cas_s
        return "stínění: " + ", ".join(sorted(set(hotovo)))


# kdy smí automatika hýbat žaluziemi
REZIM_VZDY = "vzdy"
REZIM_JEN_PRYC = "jen_pryc"       # doma si je řídíme sami
REZIM_PRAZDNA = "prazdna"         # doma, ale jen když v pokoji nikdo není
REZIM_NIKDY = "nikdy"

# kdy se po západu slunce zatahuje kvůli soukromí
SOUKROMI_NIKDY = "nikdy"
SOUKROMI_HNED = "hned"            # hned po západu
SOUKROMI_POHYB = "pri_pohybu"     # až když do místnosti někdo přijde


ROLE = ("zastinit", "odstinit", "soukromi", "pryc")


def role_stineni(zisk: float, prah: float, horko: bool, zima: bool,
                 doma: bool, rezim: str = REZIM_VZDY,
                 po_zapadu: bool = False, pohyb: bool = False,
                 soukromi_kdy: str = SOUKROMI_NIKDY,
                 v_pokoji: bool = False) -> str | None:
    """Který pojmenovaný stav má platit.

    Prázdný návrat znamená nechat být, a to je u žaluzií správná výchozí
    odpověď. Automatika, která přestavuje to, co si člověk před chvílí
    nastavil ručně, je horší než žádná.

    Režim „jen v prázdné místnosti" je kompromis pro pokoje, kterými se
    prochází. Kuchyň se zaclonit má, i když jsi doma, ale ne když v ní
    zrovna stojíš — to bys měl zataženo pokaždé, když jdeš pro vodu.

    Pořadí je dané tím, co je naléhavější. Prázdný byt přebíjí vše.
    Soukromí po setmění přebíjí režim, protože zatáhnout po západu chceme
    i tam, kde si jinak žaluzie řídíme sami. Slunce je až poslední, a po
    západu už stejně žádné není.
    """
    if not doma:
        return "pryc"
    if rezim == REZIM_NIKDY:
        return None

    if po_zapadu and soukromi_kdy != SOUKROMI_NIKDY:
        if soukromi_kdy == SOUKROMI_HNED or (
                soukromi_kdy == SOUKROMI_POHYB and pohyb):
            return "soukromi"

    if rezim == REZIM_JEN_PRYC:
        return None
    if rezim == REZIM_PRAZDNA and v_pokoji:
        # někdo tu je, takže si žaluzie nastaví sám
        return None

    if zisk < prah:
        return None
    if horko:
        return "zastinit"
    if zima:
        return "odstinit"
    return None


def cile_zaluzii(role: str | None, mapa: dict) -> dict[str, str]:
    """Ke každé žaluzii najde její stav, který danou roli plní.

    Mapa je uložená u místnosti ve tvaru {"cover.o1|zastinit": "zastíněno"}.
    Žaluzie, která pro tu roli nemá nic přiřazené, se prostě nehne.
    """
    if not role:
        return {}
    cile = {}
    for klic, nazev in (mapa or {}).items():
        if not nazev or "|" not in klic:
            continue
        zaluzie, r = klic.rsplit("|", 1)
        if r == role:
            cile[zaluzie] = nazev
    return cile


# ---------------------------------------------------------------- topení

TOPENI_ZMENA_MIN = 0.3       # menší rozdíl nemá cenu posílat
TOPENI_KLID_S = 5 * 60


# Značkové teploty. Poznáš z nich, že povel dorazil od nás a proč:
# 5,5 je otevřené okno (Better Thermostat posílá 5,0), 7,7 je mimo
# topnou sezónu. Kulaté číslo by se pletlo s ruční obsluhou.
ZNACKA_OKNO = 5.5
ZNACKA_MIMO_SEZONU = 7.7


@dataclass
class PovelTopeni:
    """Co poslat hlavici. None znamená nesahat na to."""

    rezim: str | None = None
    cil: float | None = None
    duvod: str = ""


def cil_topeni(cil: float, okno_otevreno: bool, utlum: float,
               sezona: bool, topit_mimo: bool,
               odvzdusneni: bool, odvzdusneni_t: float,
               pri_oknu: str = "nechat",
               sezonu_ridi_hlavice: bool = True,
               znacka_okno: float = ZNACKA_OKNO,
               znacka_mimo: float = ZNACKA_MIMO_SEZONU) -> PovelTopeni:
    """Jakou teplotu poslat hlavici a jaký režim.

    Teplotu posíláme vždycky — bez ní hlavice neví, na co regulovat.
    Režim necháváme na hlavici, když si sezónu určuje sama, ať se na
    přechodu mezi sezónami nehádáme.

    Zvláštní hodnoty místo vypnutí: hlavice, která neumí přečíst externí
    okenní senzor, se utlumí tím, že dostane velmi nízký cíl. Značkové
    číslo navíc prozradí, že povel přišel od integrace.
    """
    if odvzdusneni:
        return PovelTopeni("heat", odvzdusneni_t, "odvzdušnění")

    if not sezona and not topit_mimo:
        rezim = None if sezonu_ridi_hlavice else "off"
        return PovelTopeni(rezim, znacka_mimo, "mimo topnou sezónu")

    if okno_otevreno:
        if pri_oknu == "znacka":
            return PovelTopeni(None, znacka_okno, "otevřené okno")
        if pri_oknu == "vypnout":
            return PovelTopeni("off", znacka_okno, "otevřené okno")
        if pri_oknu == "utlum":
            return PovelTopeni("heat", utlum, "otevřené okno, útlum")
        # hlavice si otevřené okno ošetří sama z okenního senzoru
        return PovelTopeni(None if sezonu_ridi_hlavice else "heat", cil,
                           "otevřené okno, řeší hlavice")

    return PovelTopeni(None if sezonu_ridi_hlavice else "heat", cil, "topím")
