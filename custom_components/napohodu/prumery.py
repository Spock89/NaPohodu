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

# Kolik časových konstant trvá, než se exponenciálnímu týdennímu
# průměru začne věřit. Do té doby se používá obyčejný průměr všeho
# naměřeného, který není zatížený prvním čtením.
USAZENI_NASOBEK = 3


@dataclass
class Prumery:
    tyden: float | None = None
    tri_dny: float | None = None
    cas_s: float | None = None
    # Kdy se průměr nasadil. Nasazuje se z jediného prvního čtení, a to
    # může být klidně babí léto — cíl se pak počítá z průměru, který
    # odpovídá tomu dni, ne tomu týdnu, a stahuje se sedmidenní
    # konstantou, tedy pomalu. Dokud je mladý, nesmí si cíl dovolit
    # všechno; proto je potřeba vědět, odkdy se učí.
    zaseto_s: float | None = None
    # Vážený součet a doba od nasazení. Z nich vyjde obyčejný průměr
    # všeho, co se naměřilo — ten není zatížený prvním čtením a je to
    # z dostupných dat nejpoctivější odhad, dokud je exponenciální
    # průměr mladý.
    soucet: float = 0.0
    doba_h: float = 0.0

    def tyden_pouzitelny(self, cas_s: float) -> float | None:
        """Týdenní průměr tak, jak se má použít.

        Exponenciální průměr se nasazuje z **jediného prvního čtení**:
        kdo integraci spustí v babím létě, nese si dvacet stupňů
        v průměru i do listopadu, protože sedmidenní konstanta chybu
        stahuje po týdnech. Dokud se učí kratší dobu, než je ta
        konstanta, je poctivější obyčejný průměr všeho naměřeného —
        ten první čtení nepřeceňuje a po pár dnech už odpovídá počasí.

        Potom se přechází na exponenciální, protože ten na rozdíl od
        obyčejného zapomíná: po měsíci provozu by průměr „od začátku"
        mluvil pořád o létě.
        """
        if self.tyden is None:
            return None
        if self.usazeny(cas_s) or self.doba_h <= 0:
            return self.tyden
        return self.soucet / self.doba_h

    def usazeny(self, cas_s: float) -> bool:
        """Učí se dýl, než je jeho vlastní časová konstanta?

        Přepíná se po **třech** časových konstantách, ne po jedné.
        Po týdnu zbývá z chyby prvního čtení 37 %, takže by cíl v ten
        den o stupeň poskočil zpátky nahoru — přesně to, čemu se tu
        předchází. Po třech týdnech zbývá 5 % a přechod není poznat:
        měřeno na zapnutí v babím létě a ochlazení druhý den vychází
        největší skok cíle 1,1 °C při přepnutí po týdnu, 0,4 °C po
        dvou a 0,2 °C po třech, což je už jen zaokrouhlení.
        """
        if self.zaseto_s is None or self.tyden is None:
            return False
        return (cas_s - self.zaseto_s) >= USAZENI_NASOBEK * TAU_TYDEN_H * 3600

    def aktualizuj(self, teplota: float, cas_s: float) -> None:
        """Přidá měření. Váha se odvíjí od času, ne od počtu vzorků."""
        if teplota is None:
            return
        if self.cas_s is None or self.tyden is None:
            self.tyden = self.tri_dny = teplota
            self.cas_s = cas_s
            self.zaseto_s = cas_s
            self.soucet = self.doba_h = 0.0
            return

        hodin = max(0.0, (cas_s - self.cas_s) / 3600.0)
        if hodin <= 0:
            return
        # výpadek delší než týden bereme jako nový začátek
        if hodin > TAU_TYDEN_H:
            self.tyden = self.tri_dny = teplota
            self.cas_s = cas_s
            self.zaseto_s = cas_s
            self.soucet = self.doba_h = 0.0
            return

        self.tyden = self._krok(self.tyden, teplota, hodin, TAU_TYDEN_H)
        self.tri_dny = self._krok(self.tri_dny, teplota, hodin, TAU_TRI_DNY_H)
        self.soucet += teplota * hodin
        self.doba_h += hodin
        self.cas_s = cas_s

    @staticmethod
    def _krok(stav: float, nova: float, hodin: float, tau: float) -> float:
        vaha = 1.0 - math.exp(-hodin / tau)
        return stav + (nova - stav) * vaha

    def jako_slovnik(self) -> dict:
        return {"zaseto_s": self.zaseto_s, "soucet": self.soucet,
                "doba_h": self.doba_h,
                "tyden": self.tyden, "tri_dny": self.tri_dny,
                "cas_s": self.cas_s}

    @classmethod
    def ze_slovniku(cls, d: dict | None) -> "Prumery":
        if not d:
            return cls()
        # Starší uložený průměr „zaseto_s" nemá. Bere se za usazený:
        # když se učí od doby před touhle verzí, nepatrně mladý není.
        return cls(d.get("tyden"), d.get("tri_dny"), d.get("cas_s"),
                   d.get("zaseto_s", d.get("cas_s")),
                   float(d.get("soucet") or 0.0),
                   float(d.get("doba_h") or 0.0))

