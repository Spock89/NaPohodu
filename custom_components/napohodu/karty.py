"""Generátor karet pro dashboard.

Entity vznikají podle toho, jak si pojmenuješ místnosti a oblasti, takže
ručně psaná karta se rozejde při každém přejmenování. Tenhle modul si
projde registr entit a poskládá kartu z toho, co skutečně existuje.

Vrací YAML jako text. Vložení je na tobě — služba nesmí přepisovat
dashboard, který sis nakreslil sám.
"""

from __future__ import annotations

# pořadí a názvy, aby karta dávala smysl a nebyla jen výpisem
POSUVNIKY = [
    ("odchylka_teploty", "Odchylka teploty"),
    ("vzduch_proti_teplu", "Vzduch proti teplu"),
    ("minimum_na_noc", "Minimum na noc"),
    ("trvale_otevreno_do_rozdilu", "Trvale otevřeno do rozdílu"),
    ("utlum_pri_otevrenem_okne", "Útlum při otevřeném okně"),
    ("otevrit_nad_co2", "Otevřít nad CO2"),
    ("zavrit_pod_co2", "Zavřít pod CO2"),
    ("v_noci_otevrit_nad_co2", "V noci otevřít nad"),
    ("nouzove_otevrit_nad_co2", "Nouzově otevřít nad"),
]

ATRIBUTY_STAVU = [
    ("co2", "CO2", " ppm"),
    ("uvnitr", "Uvnitř (rozhoduje)", " °C"),
    ("venku", "Venku (pro tuhle místnost)", " °C"),
    ("rosny_bod", "Rosný bod", " °C"),
    ("zastupce", "Větrá za nás", None),
    ("provedeno", "Poslední povel", None),
    ("ovladani", "Ovládání", None),
    ("duvody", "Co brání větrání", None),
]


def _radek(eid: str, nazev: str, odsazeni: str = "      ") -> list[str]:
    return [f"{odsazeni}- entity: {eid}", f'{odsazeni}  name: "{nazev}"']


def _atribut(eid: str, atribut: str, nazev: str,
             pripona: str | None = None) -> list[str]:
    r = ["      - type: attribute",
         f"        entity: {eid}",
         f"        attribute: {atribut}",
         f'        name: "{nazev}"']
    if pripona:
        r.append(f'        suffix: "{pripona}"')
    return r


def _karta(nadpis: str, ikona: str, polozky: list[str],
           nazev: str | None = None) -> list[str]:
    if not polozky:
        return []
    r = ["  - type: entities"]
    if nazev:
        r.append(f"    title: {nazev}")
    r += ["    show_header_toggle: false", "    entities:"] + polozky
    return r


def _hlavicka(text: str, ikona: str, styl: str = "title") -> list[str]:
    return ["  - type: heading", f"    heading: {text}",
            f"    heading_style: {styl}", f"    icon: {ikona}", ""]


def dashboard(mistnosti: list[str], oblasti: list[str],
              existuje) -> str:
    """Poskládá kartu. `existuje` řekne, jestli entita opravdu je."""
    c = ["# Vygenerováno integrací NaPohodu.",
         "# Vlož jako Manuální kartu. Až přidáš místnost, vygeneruj znovu.",
         "", "type: vertical-stack", "cards:"]

    # --- teploty ---
    polozky = []
    for m in mistnosti:
        polozky += _radek(f"number.napohodu_{m}_odchylka_teploty", m.capitalize())
        polozky += _radek(f"sensor.napohodu_{m}_cilova_teplota", "   výsledný cíl")
    c += _hlavicka("Cílová teplota", "mdi:target")
    c += _karta("", "", [x for x in polozky if _ok(x, existuje)])
    c.append("")

    # --- okna ---
    c += _hlavicka("Okna a proč", "mdi:window-open-variant")
    for m in mistnosti:
        stav = f"sensor.napohodu_{m}_stav"
        if not existuje(stav):
            continue
        polozky = _radek(stav, "Rozhodnutí")
        polozky += _radek(f"binary_sensor.napohodu_{m}_okno", "Okno")
        for a, n, s in ATRIBUTY_STAVU:
            polozky += _atribut(stav, a, n, s)
        c += _karta("", "", polozky, nazev=m.capitalize())
        c.append("")

    # --- oblasti ---
    polozky = []
    for o in oblasti:
        eid = f"sensor.napohodu_{o}_sdileny_vzduch"
        if not existuje(eid):
            continue
        polozky += _radek(eid, o.capitalize())
        polozky += _atribut(eid, "mistnosti", "   místnosti")
        polozky += _atribut(eid, "zastupce", "   větrá za nás")
    if polozky:
        c += _hlavicka("Sdílený vzduch", "mdi:home-group", "subtitle")
        c += _karta("", "", polozky)
        c.append("")

    # --- stínění ---
    polozky = []
    for m in mistnosti:
        eid = f"sensor.napohodu_{m}_slunce_na_oknech"
        if not existuje(eid):
            continue
        polozky += _radek(eid, m.capitalize())
        polozky += _atribut(eid, "role_stineni", "   role")
        polozky += _atribut(eid, "stineni_stav", "   žaluzie stojí na")
    if polozky:
        c += _hlavicka("Slunce a stínění", "mdi:blinds-horizontal", "subtitle")
        c += _karta("", "", polozky)
        c.append("")

    # --- obsazenost ---
    polozky = []
    for klic, popis in (("obsazeno", "obsazeno"), ("klid", "klid"),
                        ("okno_otevreno", "topení vypnuto")):
        for m in mistnosti:
            eid = f"binary_sensor.napohodu_{m}_{klic}"
            if existuje(eid):
                polozky += _radek(eid, f"{m.capitalize()} — {popis}")
        polozky.append("      - type: divider")
    if polozky:
        c += _hlavicka("Obsazenost a klid", "mdi:account-check", "subtitle")
        c += _karta("", "", polozky[:-1])
        c.append("")

    # --- ladění ---
    c += _hlavicka("Ladění", "mdi:tune")
    for klic, nadpis in POSUVNIKY:
        polozky = []
        for m in mistnosti:
            eid = f"number.napohodu_{m}_{klic}"
            if existuje(eid):
                polozky += _radek(eid, m.capitalize())
        c += _karta("", "", polozky, nazev=nadpis)
        if polozky:
            c.append("")

    # --- ovládání a tlačítka ---
    polozky = []
    for klic, popis in (("ovladat_okno", "okna"), ("ovladat_stineni", "žaluzie")):
        for m in mistnosti:
            eid = f"switch.napohodu_{m}_{klic}"
            if existuje(eid):
                polozky += _radek(eid, f"{m.capitalize()} — {popis}")
        polozky.append("      - type: divider")
    c += _karta("", "", polozky[:-1], nazev="Co smí ovládat")
    c.append("")

    polozky = []
    if existuje("button.napohodu_srovnat_vse"):
        polozky += _radek("button.napohodu_srovnat_vse", "Všechno naráz")
        polozky.append("      - type: divider")
    for klic, popis in (("srovnat_okno", "okna"), ("srovnat_zaluzie", "žaluzie")):
        for m in mistnosti:
            eid = f"button.napohodu_{m}_{klic}"
            if existuje(eid):
                polozky += _radek(eid, f"{m.capitalize()} — {popis}")
    c += _karta("", "", polozky, nazev="Srovnat do žádané polohy")

    return "\n".join(x for x in c if x is not None) + "\n"


def _ok(radek: str, existuje) -> bool:
    if "entity: " not in radek:
        return True
    return existuje(radek.split("entity: ", 1)[1].strip())
