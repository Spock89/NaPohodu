"""Posloupnosti poloh žaluzií.

Některé pohony umí naklopit lamely přímo přes tilt. Jiné, jako Tarken,
mají jen polohu v procentech a požadovaného náklonu se dosahuje
najížděním přes mezipolohy, prodlevami a zastavením za jízdy.

Sekvence se zapisuje jedním řádkem, ať se nemusí proklikávat formulář:

    0, 5s, 14, 3s, 12.7        najeď dolů, počkej, nahoru, počkej, dolů
    0, =0, 5                   najeď dolů, počkej na potvrzení, pak nahoru
    10, 1.2s, stop             rozjeď a za chvíli zastav
    tilt 40                    pohony, které naklápění umí přímo

Číslo je poloha v procentech, číslo s „s" je čekání, „=N" čeká, až pohon
ohlásí polohu N, „stop" zastaví jízdu a „tilt N" naklopí lamely.

Desetinná čísla se píšou s tečkou, protože čárka odděluje kroky.

Čekání na potvrzení je spolehlivější než čekání na čas, ale funguje jen
u pohonů, které polohu hlásí. Když ji nehlásí, použij čekání v sekundách.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class Druh(Enum):
    POLOHA = "poloha"
    TILT = "tilt"
    CEKAT = "cekat"
    CEKAT_POLOHU = "cekat_polohu"
    STOP = "stop"


@dataclass(frozen=True)
class Krok:
    druh: Druh
    hodnota: float = 0.0

    def __str__(self) -> str:
        if self.druh is Druh.POLOHA:
            return _cislo(self.hodnota)
        if self.druh is Druh.TILT:
            return f"tilt {_cislo(self.hodnota)}"
        if self.druh is Druh.CEKAT:
            return f"{_cislo(self.hodnota)}s"
        if self.druh is Druh.CEKAT_POLOHU:
            return f"={_cislo(self.hodnota)}"
        return "stop"


def _cislo(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(round(x, 2))


class ChybaSekvence(ValueError):
    """Sekvence se nedá přečíst. Zpráva je určená uživateli."""


MAX_KROKU = 12
MAX_CEKANI_S = 120.0


def preved(zapis: str) -> list[Krok]:
    """Z řádku udělá seznam kroků. Při chybě vysvětlí, co je špatně."""
    if not zapis or not zapis.strip():
        raise ChybaSekvence("Sekvence je prázdná.")

    kroky: list[Krok] = []
    for kus in re.split(r"[,;]|\s*->\s*", zapis):
        kus = kus.strip().lower()
        if not kus:
            continue

        if kus == "stop":
            kroky.append(Krok(Druh.STOP))
            continue

        m = re.fullmatch(r"=\s*(\d+(?:\.\d+)?)", kus)
        if m:
            kroky.append(Krok(Druh.CEKAT_POLOHU,
                              _v_rozsahu(m.group(1), "Poloha")))
            continue

        m = re.fullmatch(r"tilt\s+(-?\d+(?:\.\d+)?)", kus)
        if m:
            kroky.append(Krok(Druh.TILT, _v_rozsahu(m.group(1), "Náklon")))
            continue

        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*s", kus)
        if m:
            cekani = float(m.group(1))
            if not 0 < cekani <= MAX_CEKANI_S:
                raise ChybaSekvence(
                    f"Čekání {cekani} s je mimo rozsah 0 až {int(MAX_CEKANI_S)} s.")
            kroky.append(Krok(Druh.CEKAT, cekani))
            continue

        m = re.fullmatch(r"-?\d+(?:\.\d+)?", kus)
        if m:
            kroky.append(Krok(Druh.POLOHA, _v_rozsahu(kus, "Poloha")))
            continue

        raise ChybaSekvence(
            f"Kroku „{kus}“ nerozumím. Použij číslo (poloha v %), "
            f"číslo s „s“ (čekání), „=N“ (čekání na polohu), „stop“ "
            f"nebo „tilt N“.")

    if not kroky:
        raise ChybaSekvence("Sekvence neobsahuje žádný krok.")
    if len(kroky) > MAX_KROKU:
        raise ChybaSekvence(
            f"Sekvence má {len(kroky)} kroků, nejvíc jich smí být {MAX_KROKU}.")
    if all(k.druh in (Druh.CEKAT, Druh.CEKAT_POLOHU, Druh.STOP)
           for k in kroky):
        raise ChybaSekvence("Sekvence jen čeká, nikam nejede.")
    if kroky[0].druh is Druh.STOP:
        raise ChybaSekvence("Sekvence nemůže začínat zastavením.")
    return kroky


def _v_rozsahu(text: str, co: str) -> float:
    hodnota = float(text)
    if not 0 <= hodnota <= 100:
        raise ChybaSekvence(f"{co} {text} je mimo rozsah 0 až 100 %.")
    return hodnota


def zpet(kroky: list[Krok]) -> str:
    """Opačný převod, pro uložení a zobrazení."""
    return ", ".join(str(k) for k in kroky)


def doba_s(kroky: list[Krok], projezd_s: float = 120.0) -> float:
    """Odhad, jak dlouho sekvence poběží. Pro pojistku proti zaseknutí."""
    celkem = 0.0
    for k in kroky:
        if k.druh is Druh.CEKAT:
            celkem += k.hodnota
        elif k.druh is Druh.CEKAT_POLOHU:
            celkem += TIMEOUT_POLOHY_S
        elif k.druh is Druh.POLOHA:
            celkem += min(projezd_s, 15.0)
    return celkem


@dataclass
class Stav:
    """Pojmenovaná cílová poloha, například „zastíněno“."""

    nazev: str
    sekvence: str

    @property
    def kroky(self) -> list[Krok]:
        return preved(self.sekvence)

    def jako_slovnik(self) -> dict:
        return {"nazev": self.nazev, "sekvence": self.sekvence}


# ---------------------------------------------------------------- vykonání

TIMEOUT_POLOHY_S = 30.0
TOLERANCE = 0.6
KROK_DOTAZU_S = 0.5


@dataclass
class Vysledek:
    """Co se při běhu stalo. Slouží testeru i zápisu do protokolu."""

    poloha_pred: float | None = None
    poloha_po: float | None = None
    provedeno: list[str] = field(default_factory=list)
    trvani_s: float = 0.0
    chyba: str | None = None

    @property
    def povedlo_se(self) -> bool:
        return self.chyba is None

    def jako_slovnik(self) -> dict:
        return {
            "poloha_pred": self.poloha_pred,
            "poloha_po": self.poloha_po,
            "provedeno": self.provedeno,
            "trvani_s": self.trvani_s,
            "chyba": self.chyba,
            "povedlo_se": self.povedlo_se,
        }


class Ovladac(Protocol):
    """Co musí umět ten, kdo sekvenci skutečně provede.

    Oddělené od Home Assistantu, aby se dalo testovat bez pohonu.
    """

    async def poloha(self) -> float | None: ...
    async def nastav_polohu(self, hodnota: float) -> None: ...
    async def nastav_tilt(self, hodnota: float) -> None: ...
    async def stop(self) -> None: ...
    async def cekej(self, sekund: float) -> None: ...
    def cas(self) -> float: ...


async def spust(kroky: list[Krok], ovladac: Ovladac,
                timeout_polohy_s: float = TIMEOUT_POLOHY_S) -> Vysledek:
    """Provede sekvenci a vrátí, co se stalo. Nikdy nevyhodí výjimku."""
    v = Vysledek()
    zacatek = ovladac.cas()
    v.poloha_pred = await ovladac.poloha()

    try:
        for k in kroky:
            if k.druh is Druh.POLOHA:
                await ovladac.nastav_polohu(k.hodnota)
            elif k.druh is Druh.TILT:
                await ovladac.nastav_tilt(k.hodnota)
            elif k.druh is Druh.STOP:
                await ovladac.stop()
            elif k.druh is Druh.CEKAT:
                await ovladac.cekej(k.hodnota)
            elif k.druh is Druh.CEKAT_POLOHU:
                await _cekej_na_polohu(k.hodnota, ovladac, timeout_polohy_s)
            v.provedeno.append(str(k))
    except TimeoutError as e:
        v.chyba = str(e)
    except Exception as e:  # pragma: no cover - pojistka proti pádu pohonu
        v.chyba = f"{type(e).__name__}: {e}"

    v.poloha_po = await ovladac.poloha()
    v.trvani_s = round(ovladac.cas() - zacatek, 1)
    return v


async def _cekej_na_polohu(cil: float, ovladac: Ovladac,
                           timeout_s: float) -> None:
    """Bez tohohle se další povel pošle dřív, než pohon dojede,
    a on ho zahodí."""
    konec = ovladac.cas() + timeout_s
    while True:
        ted = await ovladac.poloha()
        if ted is not None and abs(ted - cil) <= TOLERANCE:
            return
        if ovladac.cas() >= konec:
            kde = "nic" if ted is None else _cislo(ted)
            raise TimeoutError(
                f"Poloha {_cislo(cil)} % se nedostavila do "
                f"{_cislo(timeout_s)} s, pohon hlásí {kde}.")
        await ovladac.cekej(KROK_DOTAZU_S)


# ---------------------------------------------------------------- hromadně

def z_textu(text: str) -> dict[str, str]:
    """Přečte stavy zapsané po řádcích: „název = sekvence".

    Slouží hromadné úpravě v nastavení, ať se nemusí klikat po jednom.
    """
    stavy: dict[str, str] = {}
    for cislo, radek in enumerate(( text or "").splitlines(), 1):
        radek = radek.strip()
        if not radek or radek.startswith("#"):
            continue
        if "=" not in radek:
            raise ChybaSekvence(
                f"Řádek {cislo}: chybí rovnítko. Piš „název = sekvence“.")
        nazev, zapis = radek.split("=", 1)
        nazev, zapis = nazev.strip(), zapis.strip()
        if not nazev:
            raise ChybaSekvence(f"Řádek {cislo}: chybí název stavu.")
        try:
            stavy[nazev] = zpet(preved(zapis))
        except ChybaSekvence as e:
            raise ChybaSekvence(f"Řádek {cislo} ({nazev}): {e}") from e
    return stavy


def do_textu(stavy: dict[str, str]) -> str:
    """Opačný převod, pro předvyplnění formuláře."""
    return "\n".join(f"{n} = {s}" for n, s in sorted(stavy.items()))
