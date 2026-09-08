"""Klouzavé průměry venkovní teploty.

Adaptivní cíl potřebuje týdenní průměr, topná sezóna třídenní. Místo
dvou statistických senzorů v Home Assistantu si je integrace počítá sama
z jediného čidla exponenciálním průměrem.

Exponenciální průměr má proti klouzavému okénku dvě výhody: nepotřebuje
historii, takže přežije i výpadek databáze, a starší hodnoty ubývají
plynule místo skokového vypadnutí z okna.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

TAU_TYDEN_H = 7 * 24.0
TAU_TRI_DNY_H = 3 * 24.0


@dataclass
class Prumery:
    tyden: float | None = None
    tri_dny: float | None = None
    cas_s: float | None = None

    def aktualizuj(self, teplota: float, cas_s: float) -> None:
        """Přidá měření. Váha se odvíjí od času, ne od počtu vzorků."""
        if teplota is None:
            return
        if self.cas_s is None or self.tyden is None:
            self.tyden = self.tri_dny = teplota
            self.cas_s = cas_s
            return

        hodin = max(0.0, (cas_s - self.cas_s) / 3600.0)
        if hodin <= 0:
            return
        # výpadek delší než týden bereme jako nový začátek
        if hodin > TAU_TYDEN_H:
            self.tyden = self.tri_dny = teplota
            self.cas_s = cas_s
            return

        self.tyden = self._krok(self.tyden, teplota, hodin, TAU_TYDEN_H)
        self.tri_dny = self._krok(self.tri_dny, teplota, hodin, TAU_TRI_DNY_H)
        self.cas_s = cas_s

    @staticmethod
    def _krok(stav: float, nova: float, hodin: float, tau: float) -> float:
        vaha = 1.0 - math.exp(-hodin / tau)
        return stav + (nova - stav) * vaha

    def jako_slovnik(self) -> dict:
        return {"tyden": self.tyden, "tri_dny": self.tri_dny,
                "cas_s": self.cas_s}

    @classmethod
    def ze_slovniku(cls, d: dict | None) -> "Prumery":
        if not d:
            return cls()
        return cls(d.get("tyden"), d.get("tri_dny"), d.get("cas_s"))
