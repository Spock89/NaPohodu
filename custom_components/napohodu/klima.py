"""Sdílený zdroj chladu a tepla.

Jedna klimatizace na celý byt nepatří žádné místnosti, protože obsluhuje
všechny. Vnitřní jednotka v každé místnosti je jiný případ — ta patří té
místnosti a řídí se sama.

Tenhle modul řeší jen ten sdílený případ. Neovládá nic, jen počítá, jakou
teplotu jednotce poslat a jestli má vůbec jet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# co jednotka umí
UMI_CHLADIT = "chlazeni"
UMI_TOPIT = "topeni"
UMI_OBOJI = "oboji"

# co má dělat
STAV_VYP = "vypnout"
STAV_CHLADIT = "chladit"
STAV_TOPIT = "topit"
STAV_SUSIT = "susit"
STAV_UTLUM = "utlum"

# jednotka měří především svoji místnost, dál dotlačí jen omezeně
DOTLAK_MAX = 2.0

# cíl se nesmí vrtět, kompresor ani člověk to nemají rád
ZMENA_MIN = 0.5
KLID_S = 15 * 60


@dataclass
class Pokoj:
    """Co o místnosti potřebuje sdílená jednotka vědět."""

    nazev: str
    t_in: float | None = None       # nejteplejší místo
    cil: float = 22.0
    obsazeno: bool = True
    pocita_se: bool = True
    rh_in: float | None = None
    okno_otevreno: bool = False


@dataclass
class Nastaveni:
    umi: str = UMI_CHLADIT
    v_pokoji: str = ""              # název místnosti, kde jednotka stojí
    chladit_od: float = 1.0         # o kolik nad cílem se začne chladit
    topit_od: float = 1.0
    utlum_chlazeni: float = 28.0    # při dlouhé nepřítomnosti
    utlum_topeni: float = 16.0
    susit_od: float | None = None   # vlhkost, None = nesušit
    dlouha_nepritomnost: bool = False


@dataclass
class Pamet:
    posledni_cil: float | None = None
    posledni_stav: str | None = None
    posledni_cas_s: float = -1e9


@dataclass
class Rozhodnuti:
    stav: str = STAV_VYP
    cil: float | None = None
    duvod: str = ""
    poslat: bool = False            # až tady se pozná, jestli volat službu
    podle: list[str] = field(default_factory=list)


def _pocitane(pokoje: list[Pokoj]) -> list[Pokoj]:
    """Prázdná dílna cíl netahá."""
    return [p for p in pokoje if p.pocita_se and p.obsazeno]


def dotlak(pokoje: list[Pokoj], vlastni: Pokoj | None) -> float:
    """O kolik jít pod vlastní cíl, aby se chlad dostal i do ostatních.

    Jednotka měří svoji místnost, takže cíl musí být v její stupnici.
    Když je jinde tepleji, je potřeba přitlačit — ale jen omezeně, jinak
    by místnost s jednotkou zmrzla.
    """
    ostatni = [p for p in _pocitane(pokoje)
               if p is not vlastni and p.t_in is not None]
    if not ostatni:
        return 0.0
    prekroceni = [max(0.0, p.t_in - p.cil) for p in ostatni]
    return min(DOTLAK_MAX, sum(prekroceni) / len(prekroceni))


def rozhodni(pokoje: list[Pokoj], p: Pamet, cas_s: float,
             t_out: float, topna_sezona: bool,
             n: Nastaveni = Nastaveni()) -> Rozhodnuti:
    """Co má sdílená jednotka dělat."""
    vlastni = next((x for x in pokoje if x.nazev == n.v_pokoji), None)
    zaklad = vlastni.cil if vlastni else (
        max((x.cil for x in _pocitane(pokoje)), default=22.0))
    pocitane = _pocitane(pokoje)

    # --- dlouhá nepřítomnost: držet útlum, ne vypnout úplně ---
    if n.dlouha_nepritomnost:
        cil = (n.utlum_topeni if topna_sezona else n.utlum_chlazeni)
        return _vysledek(p, cas_s, STAV_UTLUM, cil,
                         "dlouhá nepřítomnost", [])

    if not pocitane:
        return _vysledek(p, cas_s, STAV_UTLUM,
                         n.utlum_topeni if topna_sezona else n.utlum_chlazeni,
                         "nikdo doma", [])

    # --- volné chlazení oknem má přednost, ale jen když opravdu chladí ---
    # Okno otevřené kvůli CO2 při horku dovnitř tahá teplo, takže jednotka
    # jede dál. Rozhoduje venkovní teplota, ne stav okna.
    okno_chladi = any(x.okno_otevreno for x in pocitane) and t_out < zaklad

    horke = [x for x in pocitane
             if x.t_in is not None and x.t_in > x.cil + n.chladit_od]
    chladne = [x for x in pocitane
               if x.t_in is not None and x.t_in < x.cil - n.topit_od]
    # pojistka proti přechlazení: stačí jedna místnost pod cílem
    pod_cilem = any(x.t_in is not None and x.t_in < x.cil - 0.5
                    for x in pocitane)

    umi_chladit = n.umi in (UMI_CHLADIT, UMI_OBOJI)
    umi_topit = n.umi in (UMI_TOPIT, UMI_OBOJI)

    if umi_chladit and horke and not pod_cilem:
        if okno_chladi:
            return _vysledek(p, cas_s, STAV_VYP, None,
                             "chladí otevřené okno", [])
        cil = round(zaklad - dotlak(pokoje, vlastni), 1)
        return _vysledek(p, cas_s, STAV_CHLADIT, cil,
                         "chladím", [x.nazev for x in horke])

    # --- topení: jen mimo topnou sezónu, ať si s radiátory nelezou do cesty ---
    if umi_topit and chladne and not topna_sezona:
        cil = round(zaklad + dotlak_topeni(pokoje, vlastni), 1)
        return _vysledek(p, cas_s, STAV_TOPIT, cil,
                         "topím, mimo topnou sezónu",
                         [x.nazev for x in chladne])

    # --- sušení: spotřeba za komfort, proto volitelné ---
    if umi_chladit and n.susit_od is not None:
        vlhke = [x for x in pocitane
                 if x.rh_in is not None and x.rh_in > n.susit_od]
        if vlhke:
            return _vysledek(p, cas_s, STAV_SUSIT, round(zaklad, 1),
                             "vlhko", [x.nazev for x in vlhke])

    return _vysledek(p, cas_s, STAV_VYP, None, "teplota v pořádku", [])


def dotlak_topeni(pokoje: list[Pokoj], vlastni: Pokoj | None) -> float:
    """Totéž při topení, jen obráceně."""
    ostatni = [x for x in _pocitane(pokoje)
               if x is not vlastni and x.t_in is not None]
    if not ostatni:
        return 0.0
    chybi = [max(0.0, x.cil - x.t_in) for x in ostatni]
    return min(DOTLAK_MAX, sum(chybi) / len(chybi))


def _vysledek(p: Pamet, cas_s: float, stav: str, cil: float | None,
              duvod: str, podle: list[str]) -> Rozhodnuti:
    """Povel se posílá jen při skutečné změně.

    Cíl, který se vrtí o desetinu každou minutu, nikomu nepomůže a jen
    zbytečně přepíná kompresor.
    """
    r = Rozhodnuti(stav=stav, cil=cil, duvod=duvod, podle=podle)

    zmena_stavu = stav != p.posledni_stav
    zmena_cile = (cil is not None and p.posledni_cil is not None
                  and abs(cil - p.posledni_cil) >= ZMENA_MIN)
    prvni = p.posledni_stav is None or (cil is not None
                                        and p.posledni_cil is None)
    uplynulo = cas_s - p.posledni_cas_s >= KLID_S

    if zmena_stavu or prvni or (zmena_cile and uplynulo):
        r.poslat = True
        p.posledni_stav = stav
        p.posledni_cil = cil
        p.posledni_cas_s = cas_s
    return r
