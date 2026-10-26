"""Zaškrtávací dny scény: jeden přepínač na každý den dopředu.

Kalendář v Home Assistantu umí jen „přidat událost" po jedné, takže
čtrnáct dní v měsíci znamená čtrnáct dialogů. Tohle je druhá cesta:
scéna dostane na každý den dopředu jeden přepínač a ty se na kartě
vyskládají do mřížky po sedmi. Vyjde z toho kalendářová mříž, kde se
den zapne a vypne kliknutím.

Přepínač neplatí pro datum, ale pro **odstup od dneška** — dlaždice
číslo pět je vždycky „za pět dní". Jen tak může mřížka na kartě
zůstat pořád stejná a nezestárnout, protože jméno i stav si nese
entita. Zaškrtnutí se ale ukládá na **datum**, takže se přes noc
nesveze jinam: co zaškrtneš na třetího, platí třetího a zaškrtnutá je
ta dlaždice, která na třetího zrovna ukazuje.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from homeassistant.util import dt as dt_util

# Kolik dní dopředu se dá zaškrtávat. Pětatřicet proto, že po celý
# měsíc pokrývá jeho zbytek i celý příští — na plánování dopředu je
# potřeba vidět za hranici měsíce, jinak se první dny toho dalšího
# zadávají až na poslední chvíli.
DNU_DOPREDU = 35

# Zkratky dnů v týdnu. Vlastní, ne ze systému: Home Assistant běží
# s jazykem systému, a ten bývá anglický i u česky nastaveného bytu.
DNY_TYDNE = ("po", "út", "st", "čt", "pá", "so", "ne")


def datum(odstup: int, dnes: date | None = None) -> date:
    """Datum, na které dlaždice s tímhle odstupem zrovna ukazuje."""
    return (dnes or dt_util.now().date()) + timedelta(days=odstup)


def popis(odstup: int, dnes: date | None = None) -> str:
    """Co je na dlaždici napsané: „pá 31. 10.".

    Dnešek a zítřek se jmenují slovy — na mřížce je pak hned vidět,
    kde začíná, a den v týdnu u nich nikdo nehledá.
    """
    d = datum(odstup, dnes)
    if odstup == 0:
        return "dnes"
    if odstup == 1:
        return "zítra"
    return f"{DNY_TYDNE[d.weekday()]} {d.day}. {d.month}."


def _vlastni(zaznam: dict) -> bool:
    """Je to jednodenní záznam bez opakování, tedy jedno zaškrtnutí?

    Jen takový smí dlaždice smazat. Opakovaná nebo vícedenní událost
    je něco, co člověk zadal jako celek, a zrušit mu ji kliknutím na
    jeden den by znamenalo smazat i dny, o kterých není řeč.
    """
    if zaznam.get("rrule"):
        return False
    od, do = zaznam.get("od"), zaznam.get("do")
    if od is None or do is None:
        return False
    return (do - od) <= timedelta(days=1)


def _pokryva(zaznam: dict, den: date, rozbal) -> bool:
    """Platí ten záznam na ten den?

    Rozbaluje se, protože opakovaná událost sama o sobě drží jen
    první výskyt — den podle vzorce se musí poznat taky, jinak by
    dlaždice tvrdila, že scéna ten den není, a druhé kliknutí by na
    to samé datum přidalo zaškrtnutí navíc.
    """
    zacatek = dt_util.start_of_local_day(
        datetime(den.year, den.month, den.day))
    for a, b in rozbal(zaznam, zacatek - timedelta(days=1),
                       zacatek + timedelta(days=2)):
        if a < zacatek + timedelta(days=1) and b > zacatek:
            return True
    return False


def pro_den(zaznamy, scena_id: str, den: date, rozbal) -> dict:
    """Co o tom dni plán říká: platí, a dá se to odsud zrušit?

    `vlastni` jsou záznamy, které smí dlaždice smazat. `odjinud`
    znamená, že den drží ještě něco dalšího — opakování nebo
    vícedenní označení — a odškrtnutím tedy nezmizí.
    """
    moje = [z for z in zaznamy
            if z.get("druh") == "scena" and z.get("scena") == scena_id
            and _pokryva(z, den, rozbal)]
    vlastni = [z for z in moje if _vlastni(z)]
    return {"plati": bool(moje), "vlastni": vlastni,
            "odjinud": bool([z for z in moje if not _vlastni(z)])}


def novy_zaznam(scena_id: str, definice: dict, den: date) -> dict:
    """Záznam pro jeden zaškrtnutý den.

    Má stejnou podobu jako celodenní událost z kalendáře scény, aby
    se dál v plánu nedalo poznat, odkud přišel — rozbalení na denní
    okna, opis pro případ smazané scény i mazání fungují stejně.
    """
    zacatek = dt_util.start_of_local_day(
        datetime(den.year, den.month, den.day))
    return {
        "uid": uuid.uuid4().hex,
        "druh": "scena",
        "scena": scena_id,
        "nazev_sceny": definice.get("nazev"),
        # Opis pro případ, že scénu smažeš: plán se tím nerozsype,
        # jen zamrzne v podobě, v jaké byl zadán. Stejné pravidlo
        # jako u kalendáře scény.
        "opis": {"prazdno": list(definice.get("prazdno") or []),
                 "zavreno": list(definice.get("zavreno") or []),
                 "cil": dict(definice.get("cil") or {})},
        "celodenni": True,
        "okno": list(definice.get("okno") or ["07:00", "18:00"]),
        "od": zacatek,
        "do": zacatek + timedelta(days=1),
        "popis": "",
        "rrule": None,
    }
