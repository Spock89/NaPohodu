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
    ("denni_pokles", "Ve dne smí klesnout o"),
    ("nocni_pokles", "V noci smí klesnout o"),
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
    ("topeni", "Topení — posíláme", None),
    ("topeni_rezim", "Topení — režim", None),
    ("topeni_hlavice", "Topení — hlásí hlavice", None),
    ("odvzdusneni", "Odvzdušnění", None),
    ("zvlhcovac_bezi", "Zvlhčovač", None),
    ("ventilatory", "Ventilátory", None),
    ("ventilatory_proc", "Ventilátory proč", None),
    ("cisticka_bezi", "Čistička", None),
    ("vlhkost", "Vlhkost v pokoji", " %"),
    ("narazove_vetrani", "Nárazové větrání běží", None),
    ("pauza_po_pulzu_min", "Pauza po větrání", " min"),
    ("nocni_klid", "Noční klid", None),
    ("rucni_zasah", "Sáhl jsi na okno", None),
    ("kontakt_hlasi", "Kontakt hlásí otevřeno", None),
    ("prach_zvenci", "Prach se tahá zvenčí", None),
    ("dnes", "Souhrn dne", None),
    ("co_bylo", "Poslední rozhodnutí", None),
    ("co_dal", "Co změnu spustí", None),
    ("duvody", "Diagnostika", None),
]


# Hranice sekce. V jedné kartě se značky zahodí, na stránce se podle
# nich vytvoří samostatné sekce, které jdou chytat a přesouvat.
SEKCE = "#--SEKCE--"

# Pořadí sekcí na stránce. Karty se staví v tom pořadí, v jakém je
# pohodlné je poskládat v kódu, ale na stránce mají být jinak — tohle
# je ta druhá věc a mění se přesunutím jednoho řádku.
PORADI_SEKCI = [
    "Cílová teplota",
    "#pokoj",                 # každá místnost se svými budíky
    "Ladění",
    "Otevřít nad CO2",
    "Obsazenost a klid",
    "Sdílený vzduch",
    "Základ výpočtu",
    "Slunce a stínění",
    "Co smí ovládat",
    "Grafy",
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
          existuje, min_radku: int = 2) -> list[str]:
    """Graf se vynechá, když by v něm nebylo co kreslit.

    Srovnávací grafy potřebují aspoň dvě čáry, u jedné veličiny stačí
    jedna — vlhkost v jediné místnosti má taky co říct.
    """
    radky = [(e, n) for e, n in polozky if existuje(e)]
    if len(radky) < min_radku:
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


def _jako_pohled(radky: list[str]) -> list[str]:
    """Udělá z karet celý pohled, ne jednu složenou kartu.

    Karty vedle sebe natvrdo by na mobilu zůstaly vedle sebe a
    zmáčkly se. Pohled typu masonry si je přeskládá sám — na počítači
    do několika sloupců, na telefonu pod sebe.
    """
    out = ["title: NaPohodu", "path: napohodu", "icon: mdi:home-heart",
           "type: masonry", "cards:"]
    return out + radky


def _klic_sekce(sekce: list[str]) -> tuple:
    """Kam sekce v pořadí patří. Neznámé skončí na konci."""
    prvni = next((r for r in sekce if r.strip().startswith("- type:")), "")
    if "horizontal-stack" in prvni:
        znacka = "#pokoj"          # budíky místnosti a její údaje
    else:
        text = "\n".join(sekce)
        znacka = next((z for z in PORADI_SEKCI
                       if z != "#pokoj" and f": {z}" in text), None)
    try:
        return (PORADI_SEKCI.index(znacka), 0)
    except ValueError:
        return (len(PORADI_SEKCI), 0)


def _serad(sekce: list[list[str]]) -> list[list[str]]:
    """Setřídí sekce podle PORADI_SEKCI, uvnitř zachová vzájemné pořadí."""
    return [s for _, s in sorted(
        ((_klic_sekce(s), s) for s in sekce),
        key=lambda x: x[0])]


def _do_sekci(radky: list[str]) -> list[str]:
    """Rozdělí karty na sekce podle značek v proudu.

    Dřív se hranice hádaly z nadpisů a velikosti bloků a lámalo se to
    při každé změně. Teď je pořadí i seskupení dané tím, kam generátor
    značku postaví — rozložení se pak mění přesunutím jednoho bloku.
    """
    sekce, drzim = [], []
    for r in radky:
        if r == SEKCE:
            if any(x.strip() for x in drzim):
                sekce.append(drzim)
            drzim = []
            continue
        drzim.append(r)
    if any(x.strip() for x in drzim):
        sekce.append(drzim)

    out = ["type: sections", "max_columns: 4", "title: NaPohodu",
           "path: napohodu", "icon: mdi:home-heart", "sections:"]
    for s2 in _serad(sekce):
        out += ["  - type: grid", "    cards:"]
        out += ["    " + r if r.strip() else r for r in s2]
    return out


def dashboard(mistnosti: list[str], oblasti: list[str], existuje,
              cidla: dict | None = None, zaluzie: dict | None = None,
              venku: str | None = None, co2_cidla: dict | None = None,
              rh_cidla: dict | None = None, s_okny: set | None = None,
              s_klidem: set | None = None, jako_pohled: bool = False,
              podoba: str = "karta") -> str:
    """Poskládá kartu. `existuje` řekne, jestli entita opravdu je.

    `cidla` a `zaluzie` jsou entity, které integrace nevytváří — teploměr
    místnosti a její žaluzie. Do grafů patří, takže si je vezmeme
    z konfigurace.
    """
    cidla = cidla or {}
    co2_cidla = co2_cidla or {}
    rh_cidla = rh_cidla or {}
    zaluzie = zaluzie or {}
    s_okny = s_okny if s_okny is not None else set(mistnosti)
    s_klidem = s_klidem if s_klidem is not None else set(mistnosti)
    c = []

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
        polozky += _atribut("sensor.napohodu_vitr_v_narazech", "pricina",
                            "   příčina blokace")
    if existuje("binary_sensor.napohodu_topna_sezona"):
        polozky.append("      - type: divider")
        polozky += _radek("binary_sensor.napohodu_topna_sezona",
                          "Topná sezóna")
    if polozky:
        c.append(SEKCE)
        c += _hlavicka("Základ výpočtu", "mdi:calendar-week", "subtitle")
        c += _karta("", "", polozky)
        c.append("")

    # --- okna ---
    for m in mistnosti:
        c.append(SEKCE)
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
        polozky += _atribut(eid, "vetra_i_za", "   větráme i za")
        polozky += _atribut(eid, "klid", "   je klid")
    if polozky:
        c.append(SEKCE)
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
        polozky += _atribut(eid, "zadana_poloha", "   žádaná poloha")
        polozky += _atribut(eid, "stineni_stav", "   nastavený stav")
        polozky += _atribut(eid, "zaluzie_poloha", "   skutečná poloha")
        polozky += _atribut(eid, "prestaveno_rukou", "   přestaveno rukou")
    if polozky:
        c.append(SEKCE)
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
        c.append(SEKCE)
        c += _hlavicka("Obsazenost a klid", "mdi:account-check", "subtitle")
        c += _karta("", "", polozky[:-1])
        c.append("")

    # --- ladění ---
    c.append(SEKCE)
    c += _hlavicka("Ladění", "mdi:tune")
    for i, (klic, nadpis) in enumerate(POSUVNIKY):
        if klic == "otevrit_nad_co2":
            c.append(SEKCE)      # prahy CO2 do vlastní sekce
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
    c.append(SEKCE)
    c.append(SEKCE)
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

    c += _karta("", "", polozky[:-1], nazev="Co smí ovládat")
    c.append("")

    c.append(SEKCE)

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
    c += _hlavicka("Grafy", "mdi:chart-line")
    c += _graf("Teploty", 48, teploty, existuje)

    # CO2 je hodnota, podle které se větrá nejčastěji — bez grafu se
    # prahy ladí naslepo.
    c += _graf("CO2 v místnostech", 24,
               [(co2_cidla[m], m.capitalize())
                for m in mistnosti if co2_cidla.get(m)], existuje,
               min_radku=1)

    # vlhkost kolísá se větráním a topením, a pozná se z ní, jestli
    # nehrozí plíseň nebo naopak vysušený vzduch
    c += _graf("Vlhkost", 48,
               [(rh_cidla[m], m.capitalize())
                for m in mistnosti if rh_cidla.get(m)], existuje,
               min_radku=1)

    # do grafu pohybů patří jen to, co se opravdu hýbe
    okna = [(f"binary_sensor.napohodu_{m}_okno", f"Okno {m}")
            for m in mistnosti if m in s_okny]
    # Pojmenovaná poloha, ne entita cover — ta v grafu ukáže jen
    # otevřeno, protože žaluzie jsou skoro pořád otevřené.
    zal = [(f"sensor.napohodu_{m}_zaluzie", f"Žaluzie {m}")
           for m in mistnosti if zaluzie.get(m)]
    klidy = [(f"binary_sensor.napohodu_{m}_klid", f"Klid {m}")
             for m in mistnosti if m in s_klidem]
    c += _graf("Okna, žaluzie a klid", 24, okna + zal + klidy, existuje)

    karty = [x for x in c if x is not None]

    if podoba == "stranka":
        hlava = ["# Vygenerováno integrací NaPohodu.",
                 "#",
                 "# Celá stránka. Dashboard -> tužka -> tři tečky ->",
                 "# Nezpracovaný editor konfigurace. Vlož tenhle blok do",
                 "# seznamu views jako další položku, na úroveň ostatních",
                 "# položek začínajících pomlčkou.",
                 "#",
                 "# Sekce se pak dají chytat a přesouvat.",
                 ""]
        return "\n".join(hlava + _do_sekci(karty)) + "\n"

    if jako_pohled:
        hlava = ["# Vygenerováno integrací NaPohodu.",
                 "#",
                 "# Dashboard -> tužka -> tři tečky -> Upravit v YAML.",
                 "# Vlož tenhle blok do seznamu views jako další položku.",
                 "# Na počítači se karty seřadí do sloupců, na telefonu",
                 "# pod sebe.",
                 ""]
        return "\n".join(hlava + _jako_pohled(
            [r for r in karty if r != SEKCE])) + "\n"

    hlava = ["# Vygenerováno integrací NaPohodu.",
             "#",
             "# Dashboard -> tužka -> Přidat kartu -> úplně dole Manuální.",
             "# Smaž obsah a vlož tenhle text.",
             "# Po přidání místnosti si přijď pro novou verzi.",
             ""]
    karty = [r for r in karty if r != SEKCE]
    return "\n".join(hlava + ["type: vertical-stack", "cards:"] + karty) + "\n"


def _ok(radek: str, existuje) -> bool:
    if "entity: " not in radek:
        return True
    return existuje(radek.split("entity: ", 1)[1].strip())
