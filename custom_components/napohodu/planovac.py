"""Zakládání událostí plánu z dashboardu.

Kalendář v Home Assistantu se dá vyplnit v panelu Kalendář, jenže tam
si musí člověk sám pamatovat, který kalendář co znamená — a napsat ho
do špatného je tichá chyba, která se projeví až v zimě.

Tohle je druhá cesta: na dashboardu se vybere **co** ze seznamu, zadá
se od kdy do kdy a zmáčkne se tlačítko. Kalendář si integrace dohledá
sama podle toho, kam je v nastavení přiřazený, takže vedle nesprávné
volby neexistuje.

Opakované události takhle založit nejdou: akce `calendar.create_event`
pole pro opakování nemá, umí jen jednorázovou událost. Pravidelný
vzorec patří buď do panelu Kalendář, kde se opakování naklikat dá,
nebo do týdenního rozvrhu, který je přesně na to.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Volba:
    """Jedna položka v nabídce: co to znamená a kam se to zapíše."""

    popis: str                 # co se ukáže na dashboardu
    pole: str                  # které nastavení drží cílový kalendář
    mistnost: str | None = None    # None = celý byt


def nabidka(byt: dict, mistnosti: list[tuple[str, dict]],
            pole_nikdo: str, pole_vic: str,
            pole_obsazeno: str, pole_prazdno: str) -> list[Volba]:
    """Co všechno jde naplánovat. Jen tam, kde je kam to zapsat.

    Volba bez přiřazeného kalendáře by skončila chybou až po stisku
    tlačítka. Tady se do nabídky rovnou nedostane.
    """
    out = []
    if _kalendar(byt.get(pole_nikdo)):
        out.append(Volba("nikdo doma", pole_nikdo))
    if _kalendar(byt.get(pole_vic)):
        out.append(Volba("víc lidí", pole_vic))
    for nazev, data in mistnosti:
        if _kalendar(data.get(pole_obsazeno)):
            out.append(Volba(f"{nazev}: je tu někdo", pole_obsazeno, nazev))
        if _kalendar(data.get(pole_prazdno)):
            out.append(Volba(f"{nazev}: nikdo tu nebude", pole_prazdno,
                             nazev))
    return out


def _kalendar(entity) -> str | None:
    """První kalendář ze seznamu. Do rozvrhu se zapsat nedá."""
    for eid in (entity or []):
        if str(eid).startswith("calendar."):
            return eid
    return None


def kam(volba: Volba, byt: dict,
        mistnosti: dict[str, dict]) -> str | None:
    """Do kterého kalendáře volba patří."""
    zdroj = byt if volba.mistnost is None else mistnosti.get(volba.mistnost,
                                                             {})
    return _kalendar(zdroj.get(volba.pole))


def zkontroluj(od, do) -> str | None:
    """Co brání založení. Prázdno znamená, že je to v pořádku.

    Obrácené pořadí časů kalendář přijme a vznikne z toho událost,
    která nikdy neplatí — a hledá se to špatně.
    """
    if od is None or do is None:
        return "chybí začátek nebo konec"
    if do <= od:
        return "konec musí být po začátku"
    return None
