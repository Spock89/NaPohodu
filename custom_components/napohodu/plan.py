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


# Jak se plán pojmenovává. Byt a místnost mluví každý o něčem jiném,
# a když se slova půjčí, řádek v kartě tvrdí nesmysl: plán jedné
# místnosti se hlásí jako „nikdo doma" za celý byt.
@dataclass(frozen=True)
class Slova:
    prazdno: str
    plno: str


BYT = Slova(prazdno="nikdo doma", plno="víc lidí")
MISTNOST = Slova(prazdno="nikdo tu nebude", plno="je tu někdo")


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
    # Odkud to je. Bez toho se při víc kalendářích nedá zjistit, který
    # z nich zrovna mluví — a právě to člověk hledá, když mu plán
    # tvrdí něco, co nečeká.
    zdroj: str | None = None


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
        posledni = max(bezici, key=lambda u: (u.do_s is not None, u.do_s
                                              if u.do_s is not None else 0))
        return Udalost(bezi=True, do_s=do_s, zdroj=posledni.zdroj)
    cekajici = [u for u in udalosti if u.od_s is not None]
    if not cekajici:
        return Udalost()
    prvni = min(cekajici, key=lambda u: u.od_s)
    return Udalost(bezi=False, od_s=prvni.od_s, zdroj=prvni.zdroj)


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


def popis(nikdo: Udalost, vic: Udalost, cas_s: float,
          slova: Slova = BYT) -> str | None:
    """Co plán zrovna říká. Bez plánu nic — řádek se pak v kartě skryje.

    Slova se předávají, protože plán bytu a plán místnosti mluví každý
    o něčem jiném. Ke každé hlášce patří i zdroj: při víc kalendářích
    je to jediný způsob, jak poznat, který z nich zrovna mluví.
    """
    casti = []
    if nikdo.bezi:
        casti.append(slova.prazdno + _dokdy(nikdo.do_s, cas_s)
                     + _odkud(nikdo.zdroj))
    elif vic.bezi:
        casti.append(slova.plno + _dokdy(vic.do_s, cas_s)
                     + _odkud(vic.zdroj))
    if not vic.bezi and vic.od_s is not None:
        za = int((vic.od_s - cas_s) / 60)
        if 0 <= za <= 24 * 60:
            casti.append(f"{slova.plno} za {za} min{_odkud(vic.zdroj)}")
    if not nikdo.bezi and not vic.bezi and nikdo.od_s is not None:
        za = int((nikdo.od_s - cas_s) / 60)
        if 0 <= za <= 24 * 60:
            casti.append(f"{slova.prazdno} za {za} min{_odkud(nikdo.zdroj)}")
    return ", ".join(casti) or None


def _odkud(zdroj: str | None) -> str:
    return f" ({zdroj})" if zdroj else ""


def _dokdy(do_s: float | None, cas_s: float) -> str:
    if do_s is None:
        return ""
    return f", ještě {int((do_s - cas_s) / 60)} min"
