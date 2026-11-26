"""Stav integrace jedním kliknutím.

Problém se hlásí ze telefonu fotkou obrazovky — a z fotky se nedá
poznat, jestli se místnost rozhodla špatně, nebo dostala špatný vstup.
Tahle platforma vysype do JSON všechno, z čeho se rozhodovalo:
nastavení, podentity, výsledek posledního cyklu i paměť, kterou si
integrace drží mezi restarty.

Home Assistant si soubor načte sám podle jména (`diagnostics.py`),
žádná registrace k tomu není; v nastavení integrace se objeví
*Stáhnout diagnostická data*.

Co se nesmí dostat do souboru: hesla, tokeny a souřadnice. NaPohodu
žádné nemá — nastavení je jen výběr entit a čísla — ale soubor může
někdo poslat do veřejného vlákna, tak se cedí stejně, aby na to
pozdější přírůstek nenarazil.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

# Jméno pole stačí, že tohle slovo obsahuje. Výčtem přesných jmen by
# první jinak pojmenovaný přírůstek propadl.
TAJNE = ("latitude", "longitude", "token", "password", "api_key",
         "secret", "souradnice")
SKRYTO = "**skryto**"


def _cedit(hodnota: Any) -> Any:
    """Projde slovníky i seznamy a vyhodí, co se nemá posílat dál."""
    if isinstance(hodnota, dict):
        out = {}
        for k, v in hodnota.items():
            if isinstance(k, str) and any(t in k.lower() for t in TAJNE):
                out[k] = SKRYTO
            else:
                out[str(k)] = _cedit(v)
        return out
    if isinstance(hodnota, (list, tuple, set)):
        return [_cedit(v) for v in hodnota]
    if is_dataclass(hodnota) and not isinstance(hodnota, type):
        return _cedit(asdict(hodnota))
    if isinstance(hodnota, (str, int, float, bool)) or hodnota is None:
        return hodnota
    # Čas, výčet, cokoli dalšího: radši text než spadnutý export.
    return str(hodnota)


async def async_get_config_entry_diagnostics(
        hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Všechno, z čeho se rozhodovalo, v jednom souboru."""
    k = (hass.data.get(DOMAIN) or {}).get(entry.entry_id)

    out: dict[str, Any] = {
        "nastaveni": {
            "spolecne": _cedit({**entry.data, **entry.options}),
            "podentity": [
                {"druh": pod.subentry_type, "nazev": pod.title,
                 "id": pod.subentry_id, "data": _cedit(pod.data)}
                for pod in entry.subentries.values()
            ],
        },
    }
    if k is None:
        # Integrace se nenačetla. Právě tehdy je export nejpotřebnější,
        # takže se nevrací chyba, ale to, co je k dispozici.
        out["koordinator"] = "nenačtený"
        return out

    out["koordinator"] = {
        # Ruční hodnoty šoupátek a přepínačů. Klíč je dvojice, a ta se
        # do JSON nevejde — skládá se na „podentita|klíč".
        "hodnoty": {f"{a}|{b}": v for (a, b), v in k.hodnoty.items()},
        "okna_stav": _cedit(k.okna_stav),
        "zvlhcuje": sorted(k.zvlhcuje),
        "prumery": _cedit(k.prumery.jako_slovnik()),
        "vitr_mereni": _cedit(k.vitr_mereni),
        # Naměřená náběhová křivka po přihrádkách venkovní teploty.
        # Právě tady se pozná, jestli je předstih příchodu z měření,
        # nebo se ještě nemá co naučit.
        "naber": {pid: n.uloz() for pid, n in k._naber.items()},
        "pamet": _cedit(k._uloz_pameti()),
    }
    out["mistnosti"] = {
        pid: _cedit({
            "nazev": m.nazev, "cil": m.cil, "cil_zaklad": m.cil_zaklad,
            "teplota": m.teplota, "povel_topeni": m.povel_topeni,
            "obsazeno": m.obsazeno, "klid": m.klid,
            "okno_otevreno": m.okno_otevreno, "slunce": m.slunce,
            "plan_cil": m.plan_cil, "plan_zavreno": m.plan_zavreno,
            "plan_prazdno": m.plan_prazdno,
            "rozhodnuti": m.rozhodnuti,
            "atributy": m.atributy,
        })
        for pid, m in k.mistnosti.items()
    }
    out["zony"] = {
        zid: _cedit({"nazev": z.nazev, "mistnosti": z.mistnosti,
                     "atributy": z.atributy})
        for zid, z in k.zony.items()
    }
    return out
