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
from datetime import timedelta


@dataclass(frozen=True)
class Volba:
    """Jedna položka v nabídce: co znamená a koho se týká."""

    popis: str                 # co se ukáže na dashboardu
    druh: str                  # viz DRUHY
    mistnost: str | None = None    # None = celý byt nebo skupina
    skupina: str | None = None     # jméno skupiny místností


# Co se dá zadat jedné místnosti nebo skupině. Prázdno a zavřená okna
# jsou dvě různé věci a musí jít zadat zvlášť: „v ložnici nikdo
# nebude" je informace o vytápění, kdežto „v prvním patře zavřená
# okna" je povel, který nesmí ochromit větrání zbytku bytu.
PRO_MISTNOST = ("obsazeno", "prazdno", "zavreno", "prazdno_zavreno", "cil")


def nabidka(mistnosti: list[str],
            skupiny: list[str] | None = None) -> list[Volba]:
    """Co všechno jde naplánovat.

    Všechny varianty pro všechny místnosti i skupiny: zapisuje se do
    vlastního kalendáře integrace, takže není kam se netrefit a nabídku
    nemá smysl zkracovat podle toho, co je kde přiřazené.
    """
    out = [Volba("nikdo doma", "nikdo"), Volba("víc lidí", "vic")]
    for nazev in mistnosti:
        for druh in PRO_MISTNOST:
            out.append(Volba(f"{nazev}: {DRUHY[druh]}", druh, nazev))
    for nazev in (skupiny or []):
        for druh in PRO_MISTNOST:
            out.append(Volba(f"{nazev}: {DRUHY[druh]}", druh,
                             None, nazev))
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
    "zavreno": "zavřená okna",
    "prazdno_zavreno": "nikdo tu nebude, zavřená okna",
    "cil": "cílová teplota",
    "scena": "scéna",
}

# Složený povel se rozpadne na jednotlivé. Jeden záznam je lepší než
# dvě události na totéž: „odjíždíme na týden" je jedna věc a mazat se
# má taky jednou.
ROZPAD = {"prazdno_zavreno": ("prazdno", "zavreno")}


def obsahuje(druh_zaznamu: str, hledany: str) -> bool:
    """Nese tenhle záznam zadaný povel?"""
    return hledany in ROZPAD.get(druh_zaznamu, (druh_zaznamu,))


# --------------------------------------------------------------- scéna
# Scéna je pojmenovaná sada dopadů: pro každou místnost buď cílová
# teplota, nebo „nikdo tu nebude", nebo „zavřená okna". V kalendáři
# scény pak stačí označit den — událost nenese nic než odkaz na ni,
# takže se nedá splést název ani rozsypat překlepem.


def dopad_sceny(definice: dict | None) -> dict:
    """Rozpad scény na jednotlivé povely místnostem.

    Vrací stejné druhy, jaké umí plán sám, takže se dál nikde nemusí
    vědět, že scéna existuje: „prazdno" a „zavreno" jako seznamy
    místností, „cil" jako místnost na teplotu.
    """
    d = definice or {}
    return {
        "prazdno": list(d.get("prazdno") or []),
        "zavreno": list(d.get("zavreno") or []),
        "cil": {k: float(v) for k, v in (d.get("cil") or {}).items()
                if v is not None},
    }


def scena_plati(zaznam: dict, definice: dict | None,
                druh: str, mistnost: str | None) -> bool:
    """Dělá tahle scéna tomuhle pokoji tenhle povel?

    Definice se bere živá, aby se změna scény promítla do všech
    naplánovaných dní. Když se scéna smaže, nastoupí opis uložený
    při zadání — běžící plán se tím nerozsype, jen zamrzne v podobě,
    v jaké byl zadán. Totéž pravidlo jako u skupin.
    """
    if zaznam.get("druh") != "scena":
        return False
    d = dopad_sceny(definice if definice is not None
                    else zaznam.get("opis"))
    if druh == "cil":
        return mistnost in d["cil"]
    return mistnost in d.get(druh, [])


def scena_cil(zaznam: dict, definice: dict | None,
              mistnost: str) -> float | None:
    """Jakou teplotu scéna téhle místnosti nastavuje."""
    d = dopad_sceny(definice if definice is not None
                    else zaznam.get("opis"))
    return d["cil"].get(mistnost)


def patri(zaznam: dict, mistnost: str | None,
          skupiny: dict | None = None) -> bool:
    """Vztahuje se záznam na tuhle místnost?

    Skupina se drží jménem, aby „1. patro" znamenalo 1. patro i po
    přidání místnosti. Opis členů z doby zadání je záloha: když
    skupinu smažeš, plán nespadne a jede dál podle něj.
    """
    if zaznam.get("druh") == "scena":
        # Scéna se na místnosti neváže jménem, ale svou definicí.
        # Řeší se zvlášť, viz scena_plati.
        return False
    if zaznam.get("skupina"):
        clenove = (skupiny or {}).get(zaznam["skupina"])
        if clenove is None:
            clenove = zaznam.get("clenove") or []
        return mistnost in clenove
    return (zaznam.get("mistnost") or None) == (mistnost or None)

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
    "lichy_tyden": "FREQ=WEEKLY",
    "sudy_tyden": "FREQ=WEEKLY",
    "vikend_lichy": "FREQ=WEEKLY;BYDAY=SA,SU",
    "vikend_sudy": "FREQ=WEEKLY;BYDAY=SA,SU",
}

# Lichost a sudost se v iCalendaru vyjádřit nedá: `INTERVAL=2` je
# „každý druhý týden od začátku", ne „lichý týden". V roce s 53 týdny
# se to převrátí a od Nového roku by plán padal do opačných týdnů.
# Proto se opakuje každý týden a ty nesprávné se při rozbalování
# zahodí podle čísla týdne podle ISO — to je přesně ten lichý a sudý
# týden, který má člověk na papírku od školy nebo ze střídavé péče.
PARITA = {"lichy_tyden": 1, "sudy_tyden": 0,
          "vikend_lichy": 1, "vikend_sudy": 0}


def parita(opakovani: str) -> int | None:
    """Zbytek čísla týdne po dělení dvěma, na který se plán omezuje."""
    return PARITA.get(opakovani)


def pravidlo(opakovani: str, kolikrat: int) -> str | None:
    """Opakování na pravidlo podle iCalendaru.

    Akce `calendar.create_event` opakování neumí, ale entita kalendáře
    ano — a přesně tohle jí posílá i webové rozhraní, když v dialogu
    zaškrtneš „opakovat".
    """
    zaklad = OPAKOVANI.get(opakovani)
    if not zaklad:
        return None
    # U lichých a sudých týdnů se počet do pravidla nedává: `COUNT` by
    # počítal i týdny, které se potom vyhodí, takže by z osmi opakování
    # zbyla čtyři. Omezuje se až po filtru, při rozbalování.
    if kolikrat and kolikrat > 0 and opakovani not in PARITA:
        return f"{zaklad};COUNT={int(kolikrat)}"
    return zaklad


def nazev(druh: str, kdo: str | None = None,
          cil: float | None = None) -> str:
    """Jak se událost jmenuje v kalendáři.

    `kdo` je místnost nebo skupina; prázdno znamená celý byt. Název je
    jen popisek pro člověka, pokud se událost zadala z dashboardu —
    integrace se řídí uloženým záznamem a přepsaným názvem se nic
    nerozbije. U události založené v panelu Kalendář je to naopak
    jediný nosič významu, proto se drží přesně těchhle tvarů.
    """
    co = DRUHY.get(druh, druh)
    if druh == "cil" and cil is not None:
        co = f"cíl {cil:.1f} °C".replace(".", ",")
    return f"{kdo}: {co}" if kdo else f"NaPohodu: {co}"


# Skládaný povel musí jít na řadu dřív než jeho části, jinak by se
# „nikdo tu nebude, zavřená okna" poznalo jen jako prázdno.
PODLE_DELKY = sorted(DRUHY.items(), key=lambda x: -len(x[1]))


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
        vyskyty = [(zacatek, konec)]
        return [x for x in _po_dnech(vyskyty, zaznam)
                if x[1] > od and x[0] < do]
    if rrulestr is None:
        vyskyty = [(zacatek, konec)]
        return [x for x in _po_dnech(vyskyty, zaznam)
                if x[1] > od and x[0] < do]
    try:
        rada = rrulestr(pravidlo_text, dtstart=zacatek)
    except Exception:          # pragma: no cover - cizí knihovna
        vyskyty = [(zacatek, konec)]
        return [x for x in _po_dnech(vyskyty, zaznam)
                if x[1] > od and x[0] < do]
    par = zaznam.get("parita")
    if par is not None:
        vyskyty = [(x, x + delka)
                   for x in _lichy_nebo_sudy(rada, int(par), do,
                                             int(zaznam.get("kolikrat") or 0))]
    else:
        # Okno se posune o délku události, aby se do něj dostal i výskyt,
        # který začal dřív a ještě běží.
        vyskyty = [(x, x + delka)
                   for x in rada.between(od - delka, do, inc=True)]
    return [x for x in _po_dnech(vyskyty, zaznam)
            if x[1] > od and x[0] < do]


def _po_dnech(vyskyty: list[tuple], zaznam: dict) -> list[tuple]:
    """Celodenní událost rozpadne na denní okna scény.

    V kalendáři scény se den označí kliknutím a žádný čas se nezadává.
    Platit celou noc ale nemá smysl — scéna si nese vlastní okno dne,
    třeba 7:00–18:00, a celodenní událost znamená „použij ho". Když
    takhle označíš tři dny v kuse, vznikne okno pro každý z nich; bez
    toho by scéna běžela i obě noci mezi nimi.

    Okno se ukládá k záznamu při zadání, takže rozbalení nepotřebuje
    znát scénu a funguje i po jejím smazání.
    """
    okno = zaznam.get("okno")
    if not zaznam.get("celodenni") or not okno:
        return vyskyty
    try:
        od_h, od_m = [int(x) for x in str(okno[0]).split(":")[:2]]
        do_h, do_m = [int(x) for x in str(okno[1]).split(":")[:2]]
    except (ValueError, IndexError, TypeError):   # pragma: no cover
        return vyskyty

    out = []
    for zacatek, konec in vyskyty:
        den = zacatek.replace(hour=0, minute=0, second=0, microsecond=0)
        # Poslední den je v kalendáři nevlastní: celodenní událost na
        # jeden den končí ráno toho dalšího.
        posledni = (konec - timedelta(microseconds=1)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        while den <= posledni:
            a = den.replace(hour=od_h, minute=od_m)
            b = den.replace(hour=do_h, minute=do_m)
            if b <= a:                      # okno přes půlnoc
                b += timedelta(days=1)
            out.append((a, b))
            den += timedelta(days=1)
    return out


def _lichy_nebo_sudy(rada, par: int, do, kolikrat: int) -> list:
    """Výskyty jen v lichých nebo jen v sudých týdnech.

    Počítá se od začátku řady, ne od začátku okna: omezení počtu
    opakování má platit na ty týdny, které zbyly po filtru, jinak by
    z osmi opakování byla čtyři.

    Týden podle ISO začíná v pondělí, takže sobota s nedělí padnou do
    stejného týdne a víkend se nerozdělí na dvě poloviny.
    """
    out = []
    for x in rada:
        if x > do:
            break
        if x.isocalendar()[1] % 2 != par:
            continue
        out.append(x)
        if kolikrat and len(out) >= kolikrat:
            break
    return out


def nejblizsi(vyskyty: list[tuple], ted) -> tuple | None:
    """Co platí teď, jinak co začne nejdřív. Nic staršího nás nezajímá."""
    bezici = [(a, b) for a, b in vyskyty if a <= ted < b]
    if bezici:
        return max(bezici, key=lambda x: x[1])
    budouci = [(a, b) for a, b in vyskyty if a > ted]
    return min(budouci, key=lambda x: x[0]) if budouci else None


# Co povel udělá, řečeno pro člověka. Zpráva o začátku události má
# říct dopad, ne jen jméno: „zavřená okna" je název, „držím okna
# zavřená a nepustím k nim ani zónu" je to, co se stane.
DOPAD = {
    "nikdo": "zavírám okna a tlumím topení",
    "vic": "beru byt jako obsazený, větrám dopředu",
    "obsazeno": "beru místnost jako obsazenou",
    "prazdno": "tlumím topení, okna jedou dál",
    "zavreno": "držím okna zavřená",
    "prazdno_zavreno": "tlumím topení a držím okna zavřená",
}


def dopad(druhy) -> str:
    """Souhrn dopadů několika povelů dohromady."""
    texty = []
    for d in druhy:
        x = DOPAD.get(d)
        if x and x not in texty:
            texty.append(x)
    return ", ".join(texty)


def chyby(zaznam: dict, skupiny: dict, mistnosti, mez=(10.0, 30.0),
          sceny: dict | None = None) -> list:
    """Co je na záznamu špatně. Prázdno znamená, že je v pořádku.

    Hlásí se dopředu, dokud se s tím dá něco dělat. Tiše to spolknout
    by znamenalo, že člověk zjistí chybu teprve podle toho, že se
    v zimě nic nestalo.
    """
    out = []
    druh = zaznam.get("druh") or ""
    if druh == "nerozumim":
        out.append("nerozumím názvu události")
    if druh == "scena" and sceny is not None \
            and zaznam.get("scena") not in sceny:
        # Scéna se dá smazat, naplánované dny po ní zůstanou. Nespadne
        # to, jedou podle opisu — ale člověk to má vědět.
        out.append(f"scéna „{zaznam.get('nazev_sceny') or '?'}“ už "
                   f"neexistuje, jedu podle opisu z doby zadání")
    if zaznam.get("skupina") and zaznam["skupina"] not in skupiny:
        out.append(f"skupina „{zaznam['skupina']}“ už neexistuje, "
                   f"jedu podle členů z doby zadání")
    if zaznam.get("mistnost") and zaznam["mistnost"] not in mistnosti:
        out.append(f"místnost „{zaznam['mistnost']}“ v nastavení není")
    if druh == "cil":
        cil = zaznam.get("cil")
        if cil is None:
            out.append("chybí cílová teplota")
        elif not mez[0] <= float(cil) <= mez[1]:
            out.append(f"naplánovaná teplota {cil} °C je mimo rozsah "
                       f"{mez[0]:.0f}–{mez[1]:.0f} °C")
    return out
