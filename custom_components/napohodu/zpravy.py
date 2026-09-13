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

# jak dlouho se stejná zpráva neopakuje
KLID_S = {
    "vitr": 30 * 60,
    "dest": 30 * 60,
    "nouzove": 60 * 60,
    "chyba": 60 * 60,
    "vetrani": 20 * 60,
    "zavirani": 20 * 60,
    "souhrn": 20 * 3600,
}

DRUHY = ("vitr", "dest", "nouzove", "vetrani", "zavirani", "chyba", "souhrn")
VYCHOZI = ("vitr", "dest", "chyba", "souhrn")


@dataclass
class Hlasic:
    """Rozhoduje, co odejde. Neposílá — to dělá koordinátor."""

    druhy: tuple[str, ...] = VYCHOZI
    posledni: dict[tuple[str, str], float] = field(default_factory=dict)

    def smi(self, druh: str, mistnost: str, cas_s: float) -> bool:
        """Opakování se hlídá pro každou místnost zvlášť.

        Se společným klíčem by zpráva z ložnice umlčela kuchyni —
        a ta místnost, která pošle jako první, by ostatní přehlušila.
        """
        if druh not in self.druhy:
            return False
        klic = (druh, mistnost)
        if cas_s - self.posledni.get(klic, -1e9) < KLID_S.get(druh, 600):
            return False
        self.posledni[klic] = cas_s
        return True

    def zprava(self, druh: str, mistnost: str, cas_s: float,
               **udaje) -> str | None:
        """Vrátí text, nebo nic, když se posílat nemá."""
        if not self.smi(druh, mistnost, cas_s):
            return None
        return SKLADBA.get(druh, lambda m, u: None)(mistnost, udaje)


def _vitr(m, u):
    """Uvádí hodnotu, která blokaci spustila, ne tu aktuální.

    Blokace drží, dokud vítr neklesne pod uklidňovací mez, takže mezitím
    už může být venku klid — a zpráva s aktuálním číslem by lhala.
    """
    rychlost = u.get("rychlost")
    naraz = u.get("naraz")
    if rychlost is None and naraz is None:
        return f"{m}: zavírám okno kvůli větru."
    prahy = u.get("prahy") or {}
    co = u.get("co_prekrocilo")
    kvuli = {"nárazy": "nárazy jsou nad prahem",
             "rychlost": "rychlost je nad prahem",
             "hystereze": "vítr ještě neklesl dost nízko"}.get(co, "")
    return (f"{m}: zavírám okno kvůli větru — {kvuli}. "
            f"Rychlost {rychlost:.1f} z {prahy.get('rychlost', '?')}, "
            f"náraz {naraz:.1f} z {prahy.get('naraz', '?')}, "
            f"povolí pod {prahy.get('povoli_pod', '?')}.")


def _dest(m, u):
    return f"{m}: zavírám okno, prší ({u.get('dest', 0):.1f} mm/h)."


def _nouzove(m, u):
    return (f"{m}: nouzové noční provětrání, CO2 {u.get('co2', 0):.0f}. "
            f"Otevřeno jen krátce.")


def _chyba(m, u):
    return f"{m}: {u.get('text', 'pohon nereaguje')}"


def _vetrani(m, u):
    return f"{m}: otevírám, {u.get('duvod', '')}."


def _zavirani(m, u):
    return f"{m}: zavírám, {u.get('duvod', '')}."


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
    "zavirani": _zavirani,
    "souhrn": _souhrn,
}
