"""Náběhová křivka: za jak dlouho se místnost nahřeje o kolik.

Předstih nahřátí byl odjakživa pevné číslo z nastavení, stejné
v lednu i v květnu. U návratu domů to většinou projde — nikdo neměří,
jestli bylo natopeno přesně v šest. U **příchodu** ale pevné číslo
selhává viditelně: nahřát o dva stupně trvá v mrazu násobek toho, co
na podzim, takže se buď topí zbytečně dlouho dopředu, nebo se to
nestihne. A „nestihlo se to" je ta horší varianta, protože právě kvůli
ní se příchod plánuje.

Tenhle modul si proto pamatuje, co místnost **doopravdy zvládá**:
kolik stupňů za hodinu přibylo, když se topilo. Nic se nemodeluje ani
nepočítá z výkonu radiátorů — bere se, co se naměřilo.

Dělí se to podle venkovní teploty, protože na ní ta rychlost nejvíc
závisí: čím chladněji, tím víc tepla uteče ven a tím pomaleji se
nahřívá. Přihrádky jsou po pěti stupních; jemnější dělení by znamenalo
čekat na data v každé z nich celou zimu.

Dokud se nic nenaměřilo, modul **nic netvrdí** a vrací prázdno. Volající
pak použije pevný předstih z nastavení jako dosud. To je schválně:
hádat rychlost z ničeho by znamenalo plánovat příchod podle výmyslu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Hranice přihrádek podle venkovní teploty, po pěti stupních.
DOLE = -20.0
KROK = 5.0
PRIHRADEK = 8

# Co se bere za věrohodně naměřenou rychlost. Pod dolní mezí už to
# není nahřívání, ale šum čidla; nad horní mezí to nebyl pokoj, ale
# otevřené okno, slunce do čidla nebo ruční zásah na hlavici.
NEJMIN_C_ZA_H = 0.2
NEJVIC_C_ZA_H = 8.0

# Kolik vzorků stačí, aby se přihrádce věřilo. Jeden může být náhoda
# — třeba se zrovna topilo do rozsvíceného pokoje plného lidí.
DOST_VZORKU = 2

# Jak rychle se průměr učí. Prvních pár vzorků táhne silně, pak se
# ustálí: topení se v průběhu zimy nemění, ale pokoj po výměně oken
# ano a modul se na to má stihnout přizpůsobit.
SETRVACNOST = 5


def prihradka(t_out: float) -> int:
    """Do které přihrádky venkovní teplota spadá."""
    i = int((t_out - DOLE) // KROK)
    return max(0, min(PRIHRADEK - 1, i))


@dataclass
class Naber:
    """Naměřené rychlosti nahřívání, po přihrádkách podle venku."""

    # rychlost ve stupních za hodinu a počet vzorků, na každou přihrádku
    rychlosti: list[float] = field(
        default_factory=lambda: [0.0] * PRIHRADEK)
    vzorky: list[int] = field(default_factory=lambda: [0] * PRIHRADEK)

    def zapis(self, c_za_h: float, t_out: float) -> bool:
        """Zaznamená naměřenou rychlost. Vrací, jestli se přijala.

        Nesmysly se zahazují mlčky: naměřit se dá leccos, ale
        nahřívání to být nemusí.
        """
        if not (NEJMIN_C_ZA_H <= c_za_h <= NEJVIC_C_ZA_H):
            return False
        i = prihradka(t_out)
        n = self.vzorky[i] + 1
        vaha = min(n, SETRVACNOST)
        self.rychlosti[i] += (c_za_h - self.rychlosti[i]) / vaha
        self.vzorky[i] = n
        return True

    def rychlost(self, t_out: float) -> float | None:
        """Kolik stupňů za hodinu při téhle venkovní teplotě.

        Když vlastní přihrádka ještě nic neví, hledá se nejbližší,
        která ví. Je to hrubé, ale pořád bližší pravdě než pevné
        číslo z nastavení — sousední přihrádka je o pět stupňů vedle,
        kdežto pevný předstih neví nic o venku vůbec.
        """
        i = prihradka(t_out)
        if self.vzorky[i] >= DOST_VZORKU:
            return self.rychlosti[i]
        for vzdalenost in range(1, PRIHRADEK):
            for j in (i - vzdalenost, i + vzdalenost):
                if 0 <= j < PRIHRADEK and self.vzorky[j] >= DOST_VZORKU:
                    return self.rychlosti[j]
        return None

    def predstih_s(self, rozdil: float, t_out: float,
                   strop_s: float) -> float | None:
        """Za jak dlouho se nahřeje o `rozdil` stupňů.

        Prázdno znamená „nevím" — volající pak sáhne po pevném
        předstihu z nastavení. Strop je od toho, aby jedna pomalá
        místnost nezačala topit od rána.
        """
        if rozdil <= 0:
            return 0.0
        v = self.rychlost(t_out)
        if not v:
            return None
        return min(rozdil / v * 3600.0, strop_s)

    def naucene(self) -> int:
        """Kolik přihrádek už něco ví. Jen pro výpis v kartě."""
        return sum(1 for n in self.vzorky if n >= DOST_VZORKU)

    def uloz(self) -> dict:
        return {"rychlosti": [round(x, 3) for x in self.rychlosti],
                "vzorky": list(self.vzorky)}

    @classmethod
    def nacti(cls, ulozene: dict | None) -> "Naber":
        """Poškozený nebo starší záznam se bere jako prázdný.

        Spadnout kvůli uložené hodnotě by znamenalo, že integrace
        nenastartuje — a to kvůli něčemu, co se dá naměřit znovu.
        """
        n = cls()
        if not isinstance(ulozene, dict):
            return n
        try:
            r = list(ulozene.get("rychlosti") or [])
            v = list(ulozene.get("vzorky") or [])
            if len(r) == PRIHRADEK and len(v) == PRIHRADEK:
                n.rychlosti = [float(x) for x in r]
                n.vzorky = [int(x) for x in v]
        except (TypeError, ValueError):
            return cls()
        return n


@dataclass
class Mereni:
    """Rozdělané měření jedné nahřívací šňůry.

    Měřit po jednotlivých kolech nejde: za minutu přibude setina
    stupně, což je pod rozlišením čidla. Sleduje se proto celý úsek,
    po který se topí, a vyhodnotí se až na konci.
    """

    od_s: float
    od_t: float
    t_out: float

    def vyhodnot(self, cas_s: float, t_in: float,
                 nejkratsi_s: float = 20 * 60,
                 nejmensi_rozdil: float = 0.3) -> float | None:
        """Rychlost ve stupních za hodinu, nebo prázdno.

        Krátké úseky a malé rozdíly se zahazují: u nich je šum čidla
        větší než to, co se měří.
        """
        doba = cas_s - self.od_s
        rozdil = t_in - self.od_t
        if doba < nejkratsi_s or rozdil < nejmensi_rozdil:
            return None
        return rozdil / (doba / 3600.0)
