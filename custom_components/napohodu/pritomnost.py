"""Obsazenost a klid.

Dva nezávislé pojmy, které se v původním flow mísily.

**Obsazeno** — má se o místnost starat. Prázdná místnost se nemusí
vytápět na cíl ani chladit.

**Klid** — nemá se v ní hlučet. Okno se pak otevírá jen když je to
opravdu potřeba a nezavírá se kvůli drobnostem.

Ložnice je typicky neobsazená, ale v noci vyžaduje klid. Obývák je
naopak trvale obsazený a klid v něm platí jen výjimečně.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ZdrojObsazenosti(Enum):
    VZDY = "vzdy"                # bere se jako trvale obsazená
    CIDLO = "cidlo"              # PIR s doběhem, viz níž
    SPANEK = "spanek"            # obsazená, jen když se v ní spí
    CIDLO_NEBO_SPANEK = "cidlo_nebo_spanek"
    NIKDY = "nikdy"              # sklad, chodba — jen bezpečnost


class ZdrojKlidu(Enum):
    ZADNY = "zadny"
    SPANEK = "spanek"            # jen když svítí spánkový přepínač
    NOC = "noc"                  # podle hodiny, bez ohledu na spánek
    SPANEK_NEBO_NOC = "spanek_nebo_noc"


class StineniPryc(Enum):
    """Co dělat se stíněním, když nikdo není doma."""
    NIC = "nic"
    ROZTAHNOUT = "roztahnout"
    ZATAHNOUT = "zatahnout"


@dataclass(frozen=True)
class Indicie:
    """Vedlejší důkaz, že je někdo v místnosti.

    Puštěná televize, zapnutá světla, odběr v zásuvce. Na rozdíl od PIR
    nevyžadují pohyb, takže jsou pro sedícího člověka spolehlivější.
    Vyhodnocuje je koordinátor, sem přichází už jen ano/ne.
    """

    nazev: str
    dobeh_s: float = 0.0          # jak dlouho po zhasnutí ještě platí
    max_stari_s: float = 0.0      # 0 = stáří se nehlídá


@dataclass
class StavIndicie:
    aktivni: bool | None = None
    od_s: float = 0.0             # jak dlouho je v tomto stavu
    stari_s: float = 0.0          # kdy se naposledy ozvala


@dataclass(frozen=True)
class NastaveniPritomnosti:
    obsazenost: ZdrojObsazenosti = ZdrojObsazenosti.VZDY
    klid: ZdrojKlidu = ZdrojKlidu.SPANEK

    # PIR nevidí nehybného člověka, proto doběh po posledním pohybu
    dobeh_s: float = 30 * 60
    # když se čidlo dlouho neozvalo, nejspíš mu došla baterie
    max_stari_s: float = 6 * 3600

    stineni_pryc: StineniPryc = StineniPryc.NIC

    # vedlejší důkazy obsazenosti; stačí jeden aktivní
    indicie: tuple[Indicie, ...] = ()


@dataclass
class Signaly:
    """Co je právě k dispozici. Chybějící entita = None, ne False."""

    doma: bool = True            # na_palube, platí pro celý byt
    cidlo: bool | None = None    # přítomnost v místnosti
    spanek: bool | None = None   # spánkový přepínač místnosti
    je_noc: bool = False

    # jak dlouho je čidlo v současném stavu a kdy se naposledy ozvalo
    cidlo_od_s: float = 0.0
    cidlo_stari_s: float = 0.0

    indicie: dict = None          # nazev -> StavIndicie

    def __post_init__(self):
        if self.indicie is None:
            self.indicie = {}


def _verohodne(aktivni: bool | None, od_s: float, stari_s: float,
               dobeh_s: float, max_stari_s: float) -> bool | None:
    """Společné pravidlo pro PIR i pro indicie.

    Zapnuto je spolehlivé. Vypnuto platí až po uplynutí doběhu. Zdroj,
    který se dlouho neozval, je nejspíš mrtvý a nevěříme mu vůbec.
    """
    if aktivni is None:
        return None
    if max_stari_s and stari_s > max_stari_s:
        return None
    if aktivni:
        return True
    return True if od_s < dobeh_s else False


def indicie_aktivni(s: Signaly, n: NastaveniPritomnosti) -> list[str]:
    """Které vedlejší důkazy právě platí."""
    zapnute = []
    for i in n.indicie:
        st = (s.indicie or {}).get(i.nazev)
        if st is None:
            continue
        if _verohodne(st.aktivni, st.od_s, st.stari_s,
                      i.dobeh_s, i.max_stari_s):
            zapnute.append(i.nazev)
    return zapnute


def _cidlo_verohodne(s: Signaly, n: NastaveniPritomnosti) -> bool | None:
    """Vrátí, co čidlo doopravdy říká. None znamená nevíme.

    Zapnuté čidlo je spolehlivé. Vypnuté znamená jen, že se nikdo nehýbe,
    takže se ještě po dobu doběhu bere jako obsazeno. Čidlo, které se
    dlouho neozvalo, je nejspíš vybité a nevěříme mu vůbec.
    """
    return _verohodne(s.cidlo, s.cidlo_od_s, s.cidlo_stari_s,
                      n.dobeh_s, n.max_stari_s)


def obsazeno(s: Signaly, n: NastaveniPritomnosti) -> bool:
    """Má se o místnost starat?"""
    if not s.doma:
        return False            # prázdný byt přebíjí všechno
    z = n.obsazenost
    if z is ZdrojObsazenosti.VZDY:
        return True
    if z is ZdrojObsazenosti.NIKDY:
        return False

    # vedlejší důkaz stačí sám o sobě
    if indicie_aktivni(s, n):
        return True
    verdikt = _cidlo_verohodne(s, n)
    cidlo = bool(verdikt)
    spanek = bool(s.spanek)
    if z is ZdrojObsazenosti.CIDLO:
        # nevěrohodné čidlo nesmí místnost trvale vypnout
        return cidlo if verdikt is not None else True
    if z is ZdrojObsazenosti.SPANEK:
        return spanek
    return cidlo or spanek


def klid(s: Signaly, n: NastaveniPritomnosti) -> bool:
    """Má se v místnosti šetřit hlukem?"""
    z = n.klid
    if z is ZdrojKlidu.ZADNY:
        return False
    spanek = bool(s.spanek)
    if z is ZdrojKlidu.SPANEK:
        return spanek
    if z is ZdrojKlidu.NOC:
        return s.je_noc
    return spanek or s.je_noc


# ---------------------------------------------------------------- oblačnost

def oblacnost(namerene_w: float | None, elevace: float,
              dni_fn=None) -> float:
    """Podíl skutečného a teoretického záření, 0 až 1.

    Vstupem je čidlo globálního záření na střeše. Když chybí nebo je
    slunce pod obzorem, vrací 1 a použije se model jasné oblohy.
    """
    if namerene_w is None or elevace <= 3:
        return 1.0
    if dni_fn is None:
        try:
            from .slunce import dni as dni_fn
        except ImportError:  # pragma: no cover
            from slunce import dni as dni_fn
    import math
    sin_e = math.sin(math.radians(elevace))
    # teoretické globální vodorovné záření: přímé + hrubý odhad rozptýleného
    teoreticke = dni_fn(elevace, 1.0) * sin_e * 1.1
    if teoreticke <= 10:
        return 1.0
    return max(0.0, min(1.0, namerene_w / teoreticke))
