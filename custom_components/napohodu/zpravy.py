"""Zprávy.

Posílá se přes `notify.send_message` na notify entity, které si vybereš.
U Telegramu vytváří integrace jednu entitu na každý chat, takže příjemce
se volí výběrem entity, ne psaním čísla.

Zpráva má cenu jen tehdy, když s ní jde něco udělat nebo když vysvětlí
něco překvapivého. Proto tři úrovně a tvrdé omezení opakování — automatika,
která upozorňuje pořád, se přestane číst.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# co se posílá
UROVEN_NIC = "nic"
UROVEN_DULEZITE = "dulezite"     # ochrana a chyby
UROVEN_VSE = "vse"               # k tomu běžná větrání

# jak dlouho se stejná zpráva neopakuje
KLID_S = {
    "vitr": 30 * 60,
    "dest": 30 * 60,
    "nouzove": 60 * 60,
    "chyba": 60 * 60,
    "vetrani": 20 * 60,
    "souhrn": 20 * 3600,
}

DULEZITE = {"vitr", "dest", "chyba", "souhrn"}


@dataclass
class Hlasic:
    """Rozhoduje, co odejde. Neposílá — to dělá koordinátor."""

    uroven: str = UROVEN_DULEZITE
    posledni: dict[str, float] = field(default_factory=dict)

    def smi(self, druh: str, cas_s: float) -> bool:
        if self.uroven == UROVEN_NIC:
            return False
        if self.uroven == UROVEN_DULEZITE and druh not in DULEZITE:
            return False
        if cas_s - self.posledni.get(druh, -1e9) < KLID_S.get(druh, 600):
            return False
        self.posledni[druh] = cas_s
        return True

    def zprava(self, druh: str, mistnost: str, cas_s: float,
               **udaje) -> str | None:
        """Vrátí text, nebo nic, když se posílat nemá."""
        if not self.smi(druh, cas_s):
            return None
        return SKLADBA.get(druh, lambda m, u: None)(mistnost, udaje)


def _vitr(m, u):
    return (f"{m}: zavírám okno kvůli větru "
            f"({u.get('naraz', 0):.0f} m/s v nárazech).")


def _dest(m, u):
    return f"{m}: zavírám okno, prší ({u.get('dest', 0):.1f} mm/h)."


def _nouzove(m, u):
    return (f"{m}: nouzové noční provětrání, CO2 {u.get('co2', 0):.0f}. "
            f"Otevřeno jen krátce.")


def _chyba(m, u):
    return f"{m}: {u.get('text', 'pohon nereaguje')}"


def _vetrani(m, u):
    return f"{m}: otevírám, {u.get('duvod', '')}."


def _souhrn(m, u):
    d = u.get("dnes", {})
    return (f"{m} za dnešek: {d.get('pohyby', 0)}x pohyb okna, "
            f"otevřeno {d.get('otevreno_min', 0)} min, "
            f"nejvyšší CO2 {d.get('co2_max', 0)}, "
            f"nejnižší teplota {d.get('nejnizsi_teplota', '?')} °C.")


SKLADBA = {
    "vitr": _vitr,
    "dest": _dest,
    "nouzove": _nouzove,
    "chyba": _chyba,
    "vetrani": _vetrani,
    "souhrn": _souhrn,
}
