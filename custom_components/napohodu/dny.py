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
    """Datum, na které dlaždice s tímhle odstupem zrovna ukazuje.

    Počítá se od **pondělí toho týdne**, ne ode dneška. Jen tak jsou
    svislice mřížky pevně dny v týdnu a sobota s nedělí stojí vždycky
    na konci řádku. Kdyby se počítalo ode dneška, posouval by se
    víkend mřížkou každý den o jedno políčko.

    Dny před dneškem tím padnou na začátek prvního řádku; zaškrtnout
    se nedají a karta je nechává prázdné.
    """
    d = dnes or dt_util.now().date()
    pondeli = d - timedelta(days=d.weekday())
    return pondeli + timedelta(days=odstup)


def velikonoce(rok: int) -> date:
    """Velikonoční neděle. Počítá se, protože se každý rok stěhuje.

    Anonymní gregoriánský výpočet — nic se nestahuje a nic se nemusí
    doplňovat, takže to platí i za deset let.
    """
    a = rok % 19
    b, c = divmod(rok, 100)
    d_, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d_ - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mesic, den = divmod(h + l - 7 * m + 114, 31)
    return date(rok, mesic, den + 1)


# Státní svátky a dny pracovního klidu s pevným datem.
SVATKY = {
    (1, 1): "Nový rok",
    (5, 1): "Svátek práce",
    (5, 8): "Den vítězství",
    (7, 5): "Cyril a Metoděj",
    (7, 6): "Jan Hus",
    (9, 28): "Den české státnosti",
    (10, 28): "Vznik Československa",
    (11, 17): "Den boje za svobodu",
    (12, 24): "Štědrý den",
    (12, 25): "1. svátek vánoční",
    (12, 26): "2. svátek vánoční",
}


def svatek(den: date) -> str | None:
    """Jméno svátku, nebo nic. České, protože byt stojí v Praze."""
    pevny = SVATKY.get((den.month, den.day))
    if pevny:
        return pevny
    nedele = velikonoce(den.year)
    if den == nedele - timedelta(days=2):
        return "Velký pátek"
    if den == nedele + timedelta(days=1):
        return "Velikonoční pondělí"
    return None


def vikend(den: date) -> bool:
    return den.weekday() >= 5


def popis(odstup: int, dnes: date | None = None) -> str:
    """Horní řádek dlaždice: „dnes", „zítra", jinak zkratka dne.

    Celé „út 27. 10." se do sedminy karty nevejde a karta text
    nezalomí — jen ho ořízne. Datum proto nese `datum_popis` na
    druhém řádku a sem se vejde jen tohle.

    První dvě dlaždice se jmenují slovy, protože se na ně kliká
    nejčastěji a v mřížce je pak hned vidět, kde začíná. Den v týdnu
    se u nich nehledá a datum je stejně na řádku pod tím.
    """
    # Porovnává se datum, ne pořadí dlaždice: mřížka začíná pondělím
    # toho týdne, takže dnešek sedí na tolikáté dlaždici, kolikátý je
    # dnes den v týdnu.
    d = dnes or dt_util.now().date()
    kdy = datum(odstup, d)
    if kdy == d:
        return "dnes"
    if kdy == d + timedelta(days=1):
        return "zítra"
    return DNY_TYDNE[kdy.weekday()]


def datum_popis(odstup: int, dnes: date | None = None) -> str:
    """Datum na spodní řádek dlaždice: „29." a prvního „1.11."

    Krátké schválně. Dlaždice je sedmina karty a okraje se v běžných
    kartách nastavit nedají, takže se musí vejít text: „29. 10." se
    ořízlo na „29. …". Měsíc se píše jen prvního, jak je v kalendáři
    zvykem — jinde ho prozradí sousední dny.

    Svátek nese hvězdička, bez mezery, ať zabere co nejmíň. Do ikony
    se nevejde — tu už má zabranou stav zaškrtnutí — a tady je vidět
    pořád, ať je den zaškrtnutý nebo ne. Jméno svátku je v atributech.
    """
    d = datum(odstup, dnes)
    zaklad = f"{d.day}.{d.month}." if d.day == 1 else f"{d.day}."
    return zaklad + ("★" if svatek(d) else "")


def stav_dlazdice(odstup: int, dnes: date | None = None) -> str:
    """„minulost", „volno" nebo „pracovní".

    Podle tohohle karta rozhoduje, jestli dlaždici ukázat a jakou
    barvou. Rozhodnout to musí entita, ne pozice v mřížce: který
    sloupec je víkend sice pevný je, ale kolik polí na začátku je
    z minulého týdne, se mění každý den — a YAML má zůstat stejný.
    """
    d = dnes or dt_util.now().date()
    kdy = datum(odstup, d)
    if kdy < d:
        return "minulost"
    return typ_dne(kdy)


def typ_dne(den: date) -> str:
    """„volno" pro víkend a svátek, jinak „pracovní".

    Rozhoduje entita, ne karta: který sloupec je víkend, se každým
    dnem posune, kdežto YAML má zůstat pořád stejný.

    Obarvit podle toho dlaždici vestavěné karty neumí — barvu ikony
    určuje stav entity, ne její atribut, a nic jiného se v nich
    nastavit nedá. Víkend je proto poznat ze zkratky dne a z ikony
    prázdného dne, svátek z hvězdičky v popisku. Atribut je tu ke
    čtení pro automatizace a pro karty, které barvit podle atributu
    umí.
    """
    return "volno" if vikend(den) or svatek(den) else "pracovní"


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
        "popis": definice.get("popis") or "",
        "rrule": None,
    }
