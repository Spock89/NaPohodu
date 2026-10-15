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
    """Jedna položka v nabídce: co znamená a koho se týká."""

    popis: str                 # co se ukáže na dashboardu
    druh: str                  # nikdo / vic / obsazeno / prazdno / cil
    mistnost: str | None = None    # None = celý byt


def nabidka(mistnosti: list[str]) -> list[Volba]:
    """Co všechno jde naplánovat.

    Všechny varianty pro všechny místnosti: zapisuje se do vlastního
    kalendáře integrace, takže není kam se netrefit a nabídku nemá
    smysl zkracovat podle toho, co je kde přiřazené.
    """
    out = [Volba("nikdo doma", "nikdo"), Volba("víc lidí", "vic")]
    for nazev in mistnosti:
        out.append(Volba(f"{nazev}: je tu někdo", "obsazeno", nazev))
        out.append(Volba(f"{nazev}: nikdo tu nebude", "prazdno", nazev))
        out.append(Volba(f"{nazev}: cílová teplota", "cil", nazev))
    return out


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


# ---------------------------------------------------------------- plán
# Vlastní kalendář integrace. Událost nenese význam v názvu, ale
# v uloženém záznamu — takže se nedá přepsat překlepem a nemusí se
# hádat z textu. Název se z něj jen skládá pro zobrazení.

DRUHY = {
    "nikdo": "nikdo doma",
    "vic": "víc lidí",
    "obsazeno": "je tu někdo",
    "prazdno": "nikdo tu nebude",
    "cil": "cílová teplota",
}

# Co nabízíme k opakování. Víc než tohle se v bytě nehodí a každá
# další možnost je další způsob, jak to nastavit špatně.
OPAKOVANI = {
    "jednou": None,
    "denne": "FREQ=DAILY",
    "tydne": "FREQ=WEEKLY",
    "vsedni_dny": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
    "vikend": "FREQ=WEEKLY;BYDAY=SA,SU",
    "za_dva_tydny": "FREQ=WEEKLY;INTERVAL=2",
    "mesicne": "FREQ=MONTHLY",
}


def pravidlo(opakovani: str, kolikrat: int) -> str | None:
    """Opakování na pravidlo podle iCalendaru.

    Akce `calendar.create_event` opakování neumí, ale entita kalendáře
    ano — a přesně tohle jí posílá i webové rozhraní, když v dialogu
    zaškrtneš „opakovat".
    """
    zaklad = OPAKOVANI.get(opakovani)
    if not zaklad:
        return None
    if kolikrat and kolikrat > 0:
        return f"{zaklad};COUNT={int(kolikrat)}"
    return zaklad


def nazev(druh: str, mistnost: str | None = None,
          cil: float | None = None) -> str:
    """Jak se událost jmenuje v kalendáři.

    Název je jen popisek pro člověka; integrace se řídí uloženým
    záznamem. Když si ho přepíšeš, nic se nerozbije.
    """
    co = DRUHY.get(druh, druh)
    if druh == "cil" and cil is not None:
        co = f"cíl {cil:.1f} °C".replace(".", ",")
    return f"{mistnost}: {co}" if mistnost else f"NaPohodu: {co}"


def rozbal(zaznam: dict, od, do, rrulestr=None) -> list[tuple]:
    """Výskyty jedné události v zadaném okně.

    Kalendář musí vracet opakovanou událost rozloženou na jednotlivé
    výskyty, ne jako jeden záznam s pravidlem. Rozbalení dělá
    dateutil, když je po ruce; bez něj zbyde aspoň první výskyt, takže
    se plán nerozpadne, jen přestane opakovat.
    """
    zacatek = zaznam["od"]
    konec = zaznam["do"]
    delka = konec - zacatek
    pravidlo_text = zaznam.get("rrule")
    if not pravidlo_text:
        return [(zacatek, konec)] if konec > od and zacatek < do else []
    if rrulestr is None:
        return [(zacatek, konec)] if konec > od and zacatek < do else []
    try:
        rada = rrulestr(pravidlo_text, dtstart=zacatek)
    except Exception:          # pragma: no cover - cizí knihovna
        return [(zacatek, konec)] if konec > od and zacatek < do else []
    # Okno se posune o délku události, aby se do něj dostal i výskyt,
    # který začal dřív a ještě běží.
    return [(x, x + delka) for x in rada.between(od - delka, do, inc=True)]


def nejblizsi(vyskyty: list[tuple], ted) -> tuple | None:
    """Co platí teď, jinak co začne nejdřív. Nic staršího nás nezajímá."""
    bezici = [(a, b) for a, b in vyskyty if a <= ted < b]
    if bezici:
        return max(bezici, key=lambda x: x[1])
    budouci = [(a, b) for a, b in vyskyty if a > ted]
    return min(budouci, key=lambda x: x[0]) if budouci else None
