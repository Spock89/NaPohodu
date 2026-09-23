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
    rozejiti: dict[str, int] = field(default_factory=dict)
    # role a splněné podmínky se drží pro každou žaluzii zvlášť —
    # dvě okna v pokoji můžou mít různé nastavení a tím i různý průběh
    posledni_role: dict = field(default_factory=dict)
    # Platily minule všechny zaškrtnuté podmínky návratu do výchozího
    # stavu? Podle toho se pozná okamžik, kdy se má poslat povel.
    # Nevyplněno znamená, že jsme ještě nic neviděli — po startu se
    # nic neposílá, jen se zapamatuje, jak to zrovna je.
    drive_splneno: dict = field(default_factory=dict)
    # poloha se hned po sekvenci ještě ustaluje, takže první změřená
    # hodnota je prozatímní a jednou se opraví podle skutečnosti
    poloha_predbezna: set = field(default_factory=set)
    stineni_cas_s: float = -1e9
    prvni_beh: bool = True
    chyby: list[str] = field(default_factory=list)
    zarizeni: dict[str, bool] = field(default_factory=dict)
    # poslední odeslaný povel si držíme, ať na kartě nezmizí po minutě
    posledni_popis: str | None = None
    # vykonavač zavřel po dojezdu pulzu — jádro o tom musí vědět,
    # jinak hned otevře znovu a okno kmitá
    pulz_zavrel: bool = False
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

    TOLERANCE_POLOHY = 1.2      # pohon polohu neudrží přesněji
    ODKLAD_KONTROLY_S = 180.0   # než pohon dojede a ustálí se
    ROZEJITI_KRAT = 2           # dvakrát po sobě, ať to není jen dojezd

    def zkontroluj_polohu(self, zaluzie: str, poloha: float | None,
                          cas_s: float = 0.0,
                          jede: bool = False) -> str | None:
        """Ověří, že žaluzie je tam, kam jsme ji poslali.

        Bez toho by ruční přestavení zůstalo skryté: paměť tvrdí, že je
        zastíněno, takže se po západu slunce už nic nepošle.

        Tři pojistky proti falešnému poplachu. Za jízdy se nekontroluje
        vůbec. Chvíli po povelu taky ne, protože pohon dojíždí a hlásí
        polohu se zpožděním. A rozejití se musí potvrdit dvakrát za
        sebou — jednorázový přeskok je skoro vždycky dojezd, ne ruka.
        """
        ocekavana = self.stav.stineni_poloha.get(zaluzie)
        if poloha is None or ocekavana is None or jede:
            return None
        if cas_s - self.stav.stineni_cas_s < self.ODKLAD_KONTROLY_S:
            return None

        if abs(poloha - ocekavana) <= self.TOLERANCE_POLOHY:
            self.stav.rozejiti.pop(zaluzie, None)
            self.stav.poloha_predbezna.discard(zaluzie)
            return None

        # První rozejití po povelu není ruční zásah, ale dojezd. Poloha
        # naměřená hned po sekvenci je prozatímní — pohon ještě jede,
        # a u sekvencí končících příkazem stop skončí pokaždé o kus jinde.
        # Skutečnou polohu si tedy jednou opravíme místo zapomínání,
        # jinak by se stav dokola nastavoval znovu.
        if zaluzie in self.stav.poloha_predbezna:
            self.stav.poloha_predbezna.discard(zaluzie)
            self.stav.stineni_poloha[zaluzie] = poloha
            self.stav.rozejiti.pop(zaluzie, None)
            _LOGGER.debug("NaPohodu: %s se ustálila na %.1f %% "
                          "(čekal jsem %.1f), beru to za správné",
                          zaluzie, poloha, ocekavana)
            return None

        kolikrat = self.stav.rozejiti.get(zaluzie, 0) + 1
        self.stav.rozejiti[zaluzie] = kolikrat
        if kolikrat < self.ROZEJITI_KRAT:
            _LOGGER.debug("NaPohodu: %s je na %.1f %% místo %.1f %%, "
                          "čekám na potvrzení", zaluzie, poloha, ocekavana)
            return None

        byval = self.stav.posledni_stineni.pop(zaluzie, None)
        self.stav.stineni_poloha.pop(zaluzie, None)
        self.stav.rozejiti.pop(zaluzie, None)
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
        self.stav.rozejiti.clear()
        self.stav.poloha_predbezna.clear()
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
            self.stav.pulz_zavrel = True
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
                    self.stav.poloha_predbezna.add(z)
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


ROLE = ("zastinit", "odstinit", "soukromi", "pryc", "vychozi")

# Slunce kolísá kolem prahu a role by se s ním překlápěla. Když už se
# kvůli slunci hýbe, drží se, dokud zisk nespadne výrazně niž.
SLUNCE_DRZI = 0.6


def role_stineni(zisk: float, prah: float, horko: bool, zima: bool,
                 doma: bool, rezim: str = REZIM_VZDY,
                 po_zapadu: bool = False, pohyb: bool = False,
                 soukromi_kdy: str = SOUKROMI_NIKDY,
                 v_pokoji: bool = False,
                 klid: bool = False,
                 role_drive: str | None = None,
                 vratit: bool = False) -> str | None:
    """Který pojmenovaný stav má platit.

    Prázdný návrat znamená nechat být, a to je u žaluzií správná výchozí
    odpověď. Automatika, která přestavuje to, co si člověk před chvílí
    nastavil ručně, je horší než žádná.

    Po setmění se řídí jen soukromím, jinak se poloha nechává. Ráno
    se naopak to, co soukromí zatáhlo, musí zase roztáhnout — ale až
    když se v místnosti přestane spát.

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

    # Výchozí stav se nastavuje jen tehdy, když k tomu nastal důvod,
    # který si uživatel vybral — konec klidu, rozednění, odchod z bytu.
    # Samovolné vracení dělalo nesmysly.
    if vratit:
        return "vychozi"

    if rezim == REZIM_JEN_PRYC:
        return None
    if rezim == REZIM_PRAZDNA and v_pokoji:
        # někdo tu je, takže si žaluzie nastaví sám
        return None

    # Po setmění se kvůli slunci nehýbe, protože žádné není. Bez téhle
    # podmínky by pravidlo „je chladno, pusť slunce dovnitř" odstínilo
    # ložnici uprostřed noci a soukromí by ji po prvním pohybu zatáhlo
    # zpátky.
    if po_zapadu:
        return None

    # Kde se spí, se nehýbe ani přes den. Spící člověk nepotřebuje
    # světlo a čidlo ho často nevidí, takže by se žaluzie rozjela
    # právě ve chvíli, kdy nemá.
    if klid:
        return None

    # Sluneční zisk rozhoduje jen o zastínění. Zaclonit má smysl
    # tehdy, když slunce doopravdy hřeje — jinak by se stínilo
    # v mrákotě. Hysterezi ta hranice má, aby se role nepřeklápěla
    # s každým mráčkem.
    drzi = role_drive == "zastinit"
    hranice = prah * SLUNCE_DRZI if drzi else prah
    if horko and zisk >= hranice:
        return "zastinit"

    # Odclonit se naopak vyplatí vždycky, když je chladno. Světlo je
    # příjemné a každé teplo zvenčí je zadarmo, takže zavírat kvůli
    # tomu, že slunce zrovna nesvítí dost, by byl nesmysl.
    if zima:
        return "odstinit"

    # Nic z toho neplatí: žaluzie se nechává, jak je. Vracet ji někam
    # jen proto, že zrovna není důvod ji hýbat, znamená jezdit sem
    # a tam bez užitku.
    return None


def cile_zaluzii(role: str | None, mapa: dict) -> dict[str, str]:
    """Ke každé žaluzii najde její stav, který danou roli plní.

    Mapa je uložená jako {"cover.o1": {"zastinit": "zastíněno"}}. Dřív
    se ukládala plocho pod klíčem "cover.o1|zastinit" — entity_id
    v názvu klíče se ale dá snadno poškodit, tak se starý tvar jen
    přečte a dál se nepoužívá.

    Žaluzie, která pro tu roli nemá nic přiřazené, se prostě nehne.
    """
    if not role:
        return {}
    cile = {}
    for klic, hodnota in (mapa or {}).items():
        if isinstance(hodnota, dict):
            nazev = hodnota.get(role)
            if nazev:
                cile[klic] = nazev
            continue
        # starší plochý tvar
        if hodnota and "|" in klic:
            zaluzie, r = klic.rsplit("|", 1)
            if r == role:
                cile[zaluzie] = hodnota
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


def duvody_stineni(role: str | None, zisk: float, prah: float,
                   horko: bool, zima: bool, doma: bool, po_zapadu: bool,
                   klid: bool, rezim: str, soukromi_kdy: str) -> list[str]:
    """Proč je žaluzie tam, kde je. Stejný smysl jako diagnostika oken."""
    if not doma:
        return ["nikdo není doma"]
    if rezim == REZIM_NIKDY:
        return ["žaluzie si řídíš sám"]

    seznam = []
    if role == "soukromi":
        seznam.append("po setmění, aby nebylo vidět dovnitř")
    elif role == "zastinit":
        seznam.append(f"slunce hřeje ({zisk:.0f} z {prah:.0f} W) a je horko")
    elif role == "odstinit":
        seznam.append("je chladno, slunce se hodí dovnitř")
    elif role == "vychozi":
        seznam.append("nastal důvod vrátit se do výchozího stavu")
    else:
        if po_zapadu:
            seznam.append("je tma, kvůli slunci se nehýbe")
        elif klid:
            seznam.append("je tu klid, nehýbeme")
        elif rezim == REZIM_JEN_PRYC:
            seznam.append("doma si je řídíš sám")
        else:
            seznam.append("není důvod hýbat")
    return seznam


SPOUSTEC_CESKY = {"konec_klidu": "konec klidu", "rozednilo": "rozednění"}


def ocekavani_stineni(role: str | None, zisk: float, prah: float,
                      po_zapadu: bool, klid: bool, horko: bool,
                      zima: bool, soukromi_kdy: str,
                      vraceni: list | None) -> list[str]:
    """Co příští pohyb žaluzie spustí."""
    vraceni = [SPOUSTEC_CESKY.get(x, x) for x in (vraceni or [])]
    seznam = []
    if po_zapadu:
        if soukromi_kdy == SOUKROMI_POHYB and role != "soukromi":
            seznam.append("zatáhnu, až tě čidlo uvidí")
        if vraceni:
            seznam.append("ráno vrátím do výchozího stavu, až nastane "
                          + " a zároveň ".join(vraceni))
        if not seznam:
            seznam.append("do rána se nic dít nebude")
        return seznam

    if klid:
        seznam.append("dokud je tu klid, nehýbu")
    if role == "zastinit":
        seznam.append(f"odstíním, až zisk klesne pod {prah * SLUNCE_DRZI:.0f} W"
                      f" (teď {zisk:.0f})")
    elif horko:
        seznam.append(f"zastíním, až zisk překročí {prah:.0f} W "
                      f"(teď {zisk:.0f})")
    elif zima:
        seznam.append("držím odstíněno, dokud je chladno")
    if vraceni and role != "vychozi":
        seznam.append("vrátím do výchozího, až nastane "
                      + " a zároveň ".join(vraceni))
    return seznam or ["čekám na změnu počasí nebo teploty"]
