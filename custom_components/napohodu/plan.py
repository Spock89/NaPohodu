"""Plán obsazenosti: co se teprve stane.

Čidla vědí, co je teď. Plán ví, co bude — a to je rozdíl, na kterém
záleží: zdivo i hlavice reagují pomalu, takže útlum, náběh i větrání
se vyplatí spustit dřív, než se situace změní.

Zdrojem je kalendář nebo týdenní rozvrh v Home Assistantu. Oba umí
říct, jestli něco platí teď, a kdy se to změní; víc po nich nechceme.
Význam jim dává až nastavení integrace — který z nich znamená
„nikdo doma" a který „víc lidí". Tím odpadá hádání z názvů událostí,
kde by překlep tiše nic neudělal.

Pravidlo, které platí všude: **skutečnost smí přítomnost jen přidat,
nikdy ubrat.** Když čidlo vidí pohyb, je místnost obsazená, ať si plán
říká co chce. Opačně by stačil jeden zapomenutý záznam v kalendáři
a člověk sedí ve studeném pokoji.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Udalost:
    """Co plán říká o jedné věci: platí to teď, a kdy se to změní.

    Časy jsou v sekundách téže osy jako `cas_s` v jádře. Když je zdroj
    neumí dodat, zůstanou prázdné — plán pak platí pro „teď" a dopředu
    se z něj nic neplánuje.
    """

    bezi: bool = False
    do_s: float | None = None        # kdy skončí, pokud běží
    od_s: float | None = None        # kdy začne, pokud neběží


def slouc(udalosti: list[Udalost]) -> Udalost:
    """Víc zdrojů dohromady: stačí jeden, aby to platilo.

    Běží-li víc najednou, platí to déle z nich — jinak by se útlum
    ukončil podle toho, který skončí první. Nic neběží? Zajímá nás,
    co začne nejdřív, protože na to se chystáme.
    """
    bezici = [u for u in udalosti if u.bezi]
    if bezici:
        konce = [u.do_s for u in bezici if u.do_s is not None]
        # Když u jednoho konec neznáme, neumíme říct, kdy to skončí.
        do_s = (max(konce) if konce and len(konce) == len(bezici)
                else None)
        return Udalost(bezi=True, do_s=do_s)
    zacatky = [u.od_s for u in udalosti if u.od_s is not None]
    return Udalost(bezi=False, od_s=min(zacatky) if zacatky else None)


def predvetrat(vic: Udalost, cas_s: float, predstih_min: float) -> bool:
    """Chystá se návštěva, takže je čas vyvětrat dopředu.

    Začínat na osmi stovkách CO2 ve chvíli, kdy se byt zaplní, je
    pozdě. Nula předstih vypíná.
    """
    if predstih_min <= 0 or vic.bezi or vic.od_s is None:
        return False
    return 0 <= vic.od_s - cas_s <= predstih_min * 60


def konci_do(nikdo: Udalost, cas_s: float, predstih_min: float) -> bool:
    """Nepřítomnost brzy skončí, takže se přestává utlumovat.

    Náběh musí začít dřív, než se lidi vrátí. Bez známého konce se
    nedá naplánovat nic a útlum platí dál.
    """
    if not nikdo.bezi or nikdo.do_s is None or predstih_min <= 0:
        return False
    return nikdo.do_s - cas_s <= predstih_min * 60


def popis(nikdo: Udalost, vic: Udalost, cas_s: float) -> str | None:
    """Co plán zrovna říká. Bez plánu nic — řádek se pak v kartě skryje."""
    casti = []
    if nikdo.bezi:
        casti.append("nikdo doma" + _dokdy(nikdo.do_s, cas_s))
    elif vic.bezi:
        casti.append("víc lidí" + _dokdy(vic.do_s, cas_s))
    if not vic.bezi and vic.od_s is not None:
        za = int((vic.od_s - cas_s) / 60)
        if 0 <= za <= 24 * 60:
            casti.append(f"víc lidí za {za} min")
    if not nikdo.bezi and not vic.bezi and nikdo.od_s is not None:
        za = int((nikdo.od_s - cas_s) / 60)
        if 0 <= za <= 24 * 60:
            casti.append(f"prázdno za {za} min")
    return ", ".join(casti) or None


def _dokdy(do_s: float | None, cas_s: float) -> str:
    if do_s is None:
        return ""
    return f", ještě {int((do_s - cas_s) / 60)} min"
