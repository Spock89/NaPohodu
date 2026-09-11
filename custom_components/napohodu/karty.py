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
    ("uvnitr", "Nejchladnější místo v pokoji", " °C"),
    ("venku", "Venku u tohoto okna", " °C"),
    ("rosny_bod", "Rosný bod", " °C"),
    ("zastupce", "Větrá za nás", None),
    ("provedeno", "Poslední povel", None),
    ("ovladani", "Ovládání", None),
    ("topeni", "Topení", None),
    ("zvlhcovac_bezi", "Zvlhčovač", None),
    ("cisticka_bezi", "Čistička", None),
    ("odtah_bezi", "Odtah", None),
    ("vlhkost", "Vlhkost v pokoji", " %"),
    ("duvody", "Diagnostika", None),
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


def _graf(nadpis: str, hodin: int, polozky: list[tuple[str, str]],
          existuje) -> list[str]:
    """Graf se vynechá, když by v něm nebylo co kreslit."""
    radky = [(e, n) for e, n in polozky if existuje(e)]
    if len(radky) < 2:
        return []
    r = ["  - type: history-graph", f"    title: {nadpis}",
         f"    hours_to_show: {hodin}", "    entities:"]
    for e, n in radky:
        r += [f"      - entity: {e}", f'        name: "{n}"']
    return r + [""]


def _budik(eid: str, nazev: str, min_: float, max_: float,
           pasma: bool = True) -> list[str]:
    """Malý ručičkový ukazatel."""
    r = ["      - type: gauge", f"        entity: {eid}",
         f'        name: "{nazev}"', f"        min: {min_}",
         f"        max: {max_}", "        needle: true"]
    if pasma:
        r += ["        segments:",
              '          - from: 15', '            color: "#4a90d9"',
              '          - from: 20', '            color: "#5cb85c"',
              '          - from: 26', '            color: "#f0ad4e"',
              '          - from: 28', '            color: "#d9534f"']
    return r


def dashboard(mistnosti: list[str], oblasti: list[str], existuje,
              cidla: dict | None = None, zaluzie: dict | None = None,
              venku: str | None = None, s_okny: set | None = None,
              s_klidem: set | None = None) -> str:
    """Poskládá kartu. `existuje` řekne, jestli entita opravdu je.

    `cidla` a `zaluzie` jsou entity, které integrace nevytváří — teploměr
    místnosti a její žaluzie. Do grafů patří, takže si je vezmeme
    z konfigurace.
    """
    cidla = cidla or {}
    zaluzie = zaluzie or {}
    s_okny = s_okny if s_okny is not None else set(mistnosti)
    s_klidem = s_klidem if s_klidem is not None else set(mistnosti)
    c = ["# Vygenerováno integrací NaPohodu.",
         "# Vlož jako Manuální kartu. Až přidáš místnost, vygeneruj znovu.",
         "", "type: vertical-stack", "cards:"]

    # --- odchylky s oddělovači, ať se místnosti nepletou ---
    polozky = []
    for i, m in enumerate(mistnosti):
        if i:
            polozky.append("      - type: divider")
        polozky += _radek(f"number.napohodu_{m}_odchylka_teploty",
                          m.capitalize())
        polozky += _radek(f"sensor.napohodu_{m}_cilova_teplota",
                          "   výsledný cíl")
        if cidla.get(m):
            polozky += _radek(cidla[m], "   teď v místnosti")
    c += _hlavicka("Cílová teplota", "mdi:target")
    c += _karta("", "", [x for x in polozky if _ok(x, existuje)])
    c.append("")

    # --- základ výpočtu ---
    polozky = []
    for klic, jmeno in (("tydenni", "Venku \u2300 za týden"),
                        ("tridenni", "Venku \u2300 za tři dny")):
        eid = f"sensor.napohodu_venkovni_teplota_{klic}_prumer"
        if not existuje(eid):
            continue
        if polozky:
            polozky.append("      - type: divider")
        polozky += _radek(eid, jmeno)
        polozky += _atribut(eid, "zdroj", "   odkud")
        polozky += _atribut(eid, "vlastni_vypocet", "   vlastní výpočet", " °C")
    if existuje("sensor.napohodu_vitr_v_narazech"):
        polozky.append("      - type: divider")
        polozky += _radek("sensor.napohodu_vitr_v_narazech", "Vítr v nárazech")
        polozky += _atribut("sensor.napohodu_vitr_v_narazech", "rychlost",
                            "   ustálená rychlost", " m/s")
        polozky += _atribut("sensor.napohodu_vitr_v_narazech", "blokuje",
                            "   blokuje okna")
        polozky += _atribut("sensor.napohodu_vitr_v_narazech", "prahy",
                            "   prahy")
    if existuje("binary_sensor.napohodu_topna_sezona"):
        polozky.append("      - type: divider")
        polozky += _radek("binary_sensor.napohodu_topna_sezona",
                          "Topná sezóna")
    if polozky:
        c += _hlavicka("Základ výpočtu", "mdi:calendar-week", "subtitle")
        c += _karta("", "", polozky)
        c.append("")

    # --- okna ---
    c += _hlavicka("Okna a proč", "mdi:window-open-variant")
    for m in mistnosti:
        stav = f"sensor.napohodu_{m}_stav"
        if not existuje(stav):
            continue
        polozky = _radek(stav, "Rozhodnutí")
        if m in s_okny:
            polozky += _radek(f"binary_sensor.napohodu_{m}_okno", "Okno")
        for a, n, s in ATRIBUTY_STAVU:
            polozky += _atribut(stav, a, n, s)

        # ručičky nahoře: cíl vedle skutečnosti, ať je rozdíl vidět hned
        cil = f"sensor.napohodu_{m}_cilova_teplota"
        cidlo = cidla.get(m, "")
        if existuje(cil) and existuje(cidlo):
            c += ["  - type: horizontal-stack", "    cards:"]
            c += _budik(cil, "Cíl", 15, 30)
            c += _budik(cidlo, m.capitalize(), 15, 30)
            c.append("")

        c += _karta("", "", polozky, nazev=m.capitalize())
        c.append("")

    # --- oblasti ---
    polozky = []
    for o in oblasti:
        eid = f"sensor.napohodu_{o}_sdileny_vzduch"
        if not existuje(eid):
            continue
        if polozky:
            polozky.append("      - type: divider")
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
        if polozky:
            polozky.append("      - type: divider")
        polozky += _radek(eid, m.capitalize())
        polozky += _atribut(eid, "role_stineni", "   co je teď potřeba")
        polozky += _atribut(eid, "stineni_stav", "   nastavená poloha")
    if polozky:
        c += _hlavicka("Slunce a stínění", "mdi:blinds-horizontal", "subtitle")
        c += _karta("", "", polozky)
        c.append("")

    # --- obsazenost ---
    polozky = []
    for klic, popis, kde in (("obsazeno", "obsazeno", None),
                             ("klid", "klid", s_klidem),
                             ("okno_otevreno", "okno pro topení", None)):
        pridano = False
        for m in mistnosti:
            if kde is not None and m not in kde:
                continue          # místnost, kde se klid neřeší
            eid = f"binary_sensor.napohodu_{m}_{klic}"
            if existuje(eid):
                polozky += _radek(eid, f"{m.capitalize()} — {popis}")
                pridano = True
        if pridano:
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
    for klic, popis in (("ovladat_okno", "okna"),
                        ("ovladat_stineni", "žaluzie"),
                        ("ovladat_topeni", "topení")):
        for m in mistnosti:
            eid = f"switch.napohodu_{m}_{klic}"
            if existuje(eid):
                polozky += _radek(eid, f"{m.capitalize()} — {popis}")
        polozky.append("      - type: divider")
    c += _karta("", "", polozky[:-1], nazev="Co smí ovládat")
    c.append("")

    # --- grafy ---
    # Do jednoho grafu se nevejde všechno čitelně. Cíle jsou skoro
    # totožné, takže stačí jeden, a k němu skutečné teploty místností.
    hlavni = mistnosti[0] if mistnosti else None
    teploty = []
    if hlavni:
        teploty.append((f"sensor.napohodu_{hlavni}_cilova_teplota", "Cíl"))
    teploty += [(cidla[m], m.capitalize()) for m in mistnosti if cidla.get(m)]
    if venku:
        teploty.append((venku, "Venku"))
    c += _graf("Teploty", 48, teploty, existuje)

    # do grafu pohybů patří jen to, co se opravdu hýbe
    okna = [(f"binary_sensor.napohodu_{m}_okno", f"Okno {m}")
            for m in mistnosti if m in s_okny]
    zal = []
    for m in mistnosti:
        for i, z in enumerate(zaluzie.get(m, []) or []):
            zal.append((z, f"Žaluzie {m}" + (f" {i + 1}" if i else "")))
    klidy = [(f"binary_sensor.napohodu_{m}_klid", f"Klid {m}")
             for m in mistnosti if m in s_klidem]
    c += _graf("Okna, žaluzie a klid", 24, okna + zal + klidy, existuje)

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
