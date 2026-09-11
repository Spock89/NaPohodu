"""Sluneční zisk oknem.

Kolik slunce dopadá na konkrétní svislé okno podle jeho orientace a
polohy slunce. Adaptive Cover z toho počítá polohu žaluzie, my z toho
potřebujeme jen tepelný zisk, abychom věděli, jestli má smysl odclonit
kvůli teplu nebo naopak zastínit.

Azimut: 0 = sever, 90 = východ, 180 = jih, 270 = západ.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Okno:
    """Fyzické okno. Místnost jich může mít víc a na různé strany."""

    nazev: str = "okno"
    azimut: float = 180.0
    plocha: float = 1.0          # relativní váha, ne m2
    zorne_pole: float = 90.0     # ± od azimutu, za tím slunce nesvítí dovnitř
    min_elevace: float = 5.0     # pod tím stíní okolí


def _rozdil_uhlu(a: float, b: float) -> float:
    """Nejmenší rozdíl dvou azimutů, 0 až 180."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def dni(elevace: float, jasno: float = 1.0) -> float:
    """Přímé sluneční záření kolmo k paprskům, W/m2.

    Zjednodušený model podle ASHRAE: čím níž je slunce, tím delší cestu
    urazí atmosférou a tím víc ho ubyde.
    """
    if elevace <= 0:
        return 0.0
    sin_e = math.sin(math.radians(elevace))
    vzduch = 1.0 / max(sin_e, 0.05)
    return 950.0 * (0.7 ** (vzduch ** 0.678)) * max(0.0, min(1.0, jasno))


def dopad(okno: Okno, azimut_slunce: float, elevace: float,
          jasno: float = 1.0) -> float:
    """Ozáření svislé roviny okna, W/m2. Nula, když slunce nesvítí dovnitř."""
    if elevace < okno.min_elevace:
        return 0.0
    odchylka = _rozdil_uhlu(azimut_slunce, okno.azimut)
    if odchylka >= okno.zorne_pole:
        return 0.0

    # kosinus úhlu dopadu na svislou plochu
    kosinus = (math.cos(math.radians(elevace))
               * math.cos(math.radians(odchylka)))
    if kosinus <= 0:
        return 0.0
    return dni(elevace, jasno) * kosinus * okno.plocha


def zisk_mistnosti(okna: list[Okno], azimut_slunce: float, elevace: float,
                   jasno: float = 1.0) -> float:
    """Součet přes všechna okna místnosti."""
    return sum(dopad(o, azimut_slunce, elevace, jasno) for o in okna)


def okna_na_slunci(okna: list[Okno], azimut_slunce: float, elevace: float,
                   prah: float = 150.0, jasno: float = 1.0) -> list[Okno]:
    """Která okna právě stojí za to stínit nebo odclonit."""
    return [o for o in okna
            if dopad(o, azimut_slunce, elevace, jasno) >= prah]
