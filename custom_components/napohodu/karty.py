"""Generátor karet pro dashboard.

Entity vznikají podle toho, jak si pojmenuješ místnosti a oblasti, takže
ručně psaná karta se rozejde při každém přejmenování. Tenhle modul si
projde registr entit a poskládá kartu z toho, co skutečně existuje.

Vrací YAML jako text. Vložení je na tobě — služba nesmí přepisovat
dashboard, který sis nakreslil sám.
"""

from __future__ import annotations

import math

# pořadí a názvy, aby karta dávala smysl a nebyla jen výpisem
# Pořadí, názvy a jedna řádka, co to dělá — bez ní člověk za měsíc
# neví, co která hodnota znamená, a nastavuje naslepo.
# Posuvníky pro celý byt. Nepatří místnosti, takže mají vlastní sekci.
GLOBALNI = [
    ("narazovy_rezim_od_rozdilu", "Nárazový režim od rozdílu",
     "O kolik se venkovní teplota musí lišit od cílové, než se přepne "
     "na nárazové větrání. Za prahem se otevírá jen z důvodu a zavírá "
     "hned, jakmile důvod pomine."),
    ("dalsi_pokus_po_zmene_venku_o", "Další pokus po změně venku o",
     "Po marném větrání se čeká, až se venkovní teplota posune o tolik "
     "stupňů. Čas je jen zástupná veličina, důvod byl venku."),
    ("nebo_nejpozdeji_za", "Nebo nejpozději za",
     "Strop čekání. Když se venku změní dřív, zkusí se dřív."),
    ("predvetrat_pred_planovanou_navstevou",
     "Předvětrat před plánovanou návštěvou",
     "Kolik minut před začátkem události „víc lidí“ se začne větrat až "
     "na čistou hodnotu CO2. Nula vypíná."),
]

POSUVNIKY = [
    ("moje_odchylka_teploty", "Moje odchylka teploty",
     "Přičte se k vypočtenému cíli. Tvoje osobní „chci tepleji“."),
    ("ve_dne_otevrit_pri_odchylce_od_cile_o",
     "Ve dne otevřít při odchylce od cíle o",
     "O kolik se teplota musí odchýlit od cíle, aby se kvůli ní "
     "otevřelo — nad cílem chladí venkovním vzduchem, pod cílem ohřívá."),
    ("ve_dne_zavrit_az_za_cilem_o", "Ve dne zavřít až za cílem o",
     "Jak daleko za cíl se dojede, než se zavře: při chlazení pod cíl, "
     "při ohřevu nad cíl."),
    ("v_noci_otevrit_pri_odchylce_od_cile_o",
     "V noci otevřít při odchylce od cíle o",
     "Totéž pro noční hodiny a spánek. V noci se obvykle nastavuje "
     "širší pásmo, aby okno nejezdilo."),
    ("v_noci_zavrit_az_za_cilem_o", "V noci zavřít až za cílem o",
     "Totéž pro noční hodiny a spánek."),
    ("venku_musi_byt_za_dojezdem_o", "Venku musí být za dojezdem o",
     "O kolik musí být venkovní vzduch za dojezdem pásma, aby se "
     "vyplatilo větrat. Bez rezervy se cyklus doplazí k hraně a nikdy "
     "ji nepřejde."),
    ("pojistka_nevychladit_pod", "Pojistka: nevychladit pod",
     "Pod touhle teplotou se okno zavře, ať je otevřené z jakéhokoli "
     "důvodu. Obchází ji jen ruční žádost o vyvětrání."),
    ("pojistka_neprehrat_nad", "Pojistka: nepřehřát nad",
     "Nad touhle teplotou se okno zavře, ať je otevřené z jakéhokoli "
     "důvodu."),
    ("nejkratsi_doba_drzeni_polohy", "Nejkratší doba držení polohy",
     "Jak dlouho okno zůstane v poloze, do které dojelo. Po téhle době "
     "se zároveň ověří, že větrání vůbec zabírá."),
    ("po_rucnim_zasahu_nechat_byt", "Po ručním zásahu nechat být",
     "Když sáhneš na okno rukou, automatika se do něj tak dlouho "
     "neplete."),
    ("po_rucnim_prestaveni_zaluzii_nechat_byt",
     "Po ručním přestavení žaluzií nechat být",
     "Totéž pro žaluzie. Polohu si u nich člověk vybírá vědomě, tak "
     "bývá tahle doba delší než u okna. Nula znamená, že automatika "
     "pokračuje hned."),
    ("chladit_jen_pri_venkovni_teplote_nad",
     "Chladit jen při venkovní teplotě nad",
     "Pod touhle venkovní teplotou se chlazení větráním nespustí — "
     "zavření není okamžité a u okna je mezitím výrazně chladněji."),
    ("prach_je_spatny_od_pm2_5", "Prach je špatný od PM2.5",
     "Od téhle úrovně se vzduch bere za zaprášený a větrá se kvůli němu. "
     "PM10 se odvozuje z téhož čísla."),
    ("prach_je_cisty_pod_pm2_5", "Prach je čistý pod PM2.5",
     "Pod touhle úrovní se vzduch bere za čistý. Mezera mezi prahy brání "
     "přepínání na hraně."),
    ("v_noci_posun_cilove_teploty", "V noci posun cílové teploty",
     "O kolik stupňů v noci ubrat z cílové teploty. Nula netlumí. "
     "Klesá plynule hodinu před začátkem noci, spánek platí hned."),
    ("pri_otevrenem_okne_topit_na", "Při otevřeném okně topit na",
     "Teplota, na kterou se hlavice stáhnou, když je okno otevřené. "
     "Je to celá teplota, ne odečet od cíle."),
    ("otevrit_nad_co2", "Otevřít nad CO2",
     "Přes den otevřu, když CO2 vyleze nad tuhle hodnotu."),
    ("zavrit_pod_co2", "Zavřít pod CO2",
     "Zavřu, až CO2 spadne sem. Mezera mezi prahy brání kmitání."),
    ("v_noci_otevrit_nad_co2", "V noci otevřít nad",
     "V noci je práh vyšší, aby se neotvíralo kvůli maličkosti."),
    ("nouzove_otevrit_nad_co2", "Nouzově otevřít nad",
     "Nad tímhle se otevře, i když je zima nebo se spí."),
]

# Co je vidět pořád: stav, rozhodnutí a to, co se zrovna děje.
ATRIBUTY_STAVU = [
    ("co2", "CO2", " ppm"),
    ("teplota_rozhodna", "Teplota v pokoji", None),
    ("venku", "Venku u tohoto okna", " °C"),
    ("vlhkost", "Vlhkost v pokoji", " %"),
    ("provedeno", "Poslední povel", None),
    ("co_bylo", "Poslední rozhodnutí", None),
    ("co_dal", "Co změnu spustí", None),
    ("ucinek", "Zabírá to? (od otevření)", None),
    ("plan_bytu", "Plán bytu", None),
    ("plan", "Plán místnosti", None),
    ("duvody", "Diagnostika", None),
    ("topeni", "Topení — posíláme", None),
    ("zvlhcovac_bezi", "Zvlhčovač", None),
    ("cisticka_bezi", "Čistička", None),
]

# Řádky, které většinu času nemají co říct. Zůstávají na svém místě
# v kartě, ale vyrobí se jako podmíněné: dokud atribut nemá hodnotu,
# řádek se vůbec nezobrazí, místo aby svítil „Neznámý".
JEN_KDYZ_JE = {"ucinek", "plan_bytu", "plan"}

# Řádky, které mluví o okně. V místnosti, kde se okno neovládá, se
# nevyrobí vůbec — dřív se vyrobily a každý z nich napsal jinými slovy
# totéž, že se tu okno neovládá. Tři řádky, které říkají jen „tenhle
# řádek sem nepatří", jsou horší než žádný.
JEN_S_OKNEM = {
    "venku",                # „Venku u tohoto okna" — čidlo u okna
    "provedeno", "co_bylo", "co_dal", "ucinek", "duvody",
    "rucni_zasah", "kontakt_hlasi", "otevreno_min",
    "narazove_vetrani", "cekani_po_marnem", "pauza_po_pulzu_min",
    "vetrani_za_sebou", "prach_zvenci",
}

# Totéž u stínění: ruka, klid po ní a chybějící entita jsou výjimečné
# stavy, ne každodenní údaje.
ATRIBUTY_STINENI_OBCAS = [
    ("prestaveno_rukou", "přestaveno rukou"),
    ("zaluzie_rucni_klid", "ruční klid"),
    ("zaluzie_overuji", "ověřuji rozejití"),
    ("zaluzie_chybi", "chybějící entita"),
]

# Podrobnosti: zajímavé při ladění, ne při pohledu z chodby. Jdou na
# konec karty místnosti, aby nad nimi bylo to podstatné.
ATRIBUTY_PODROBNE = [
    ("ovladani", "Ovládání", None),
    ("rosny_bod", "Rosný bod", " °C"),
    ("teplota_trend", "Kam se teplota hýbe", None),
    ("je_noc", "Noční hodiny", None),
    ("spi_se", "Spí se tu", None),
    ("nocni_klid", "Noční klid", None),
    ("rucni_zasah", "Sáhl jsi na okno", None),
    ("kontakt_hlasi", "Kontakt hlásí otevřeno", None),
    ("otevreno_min", "Otevřeno už", " min"),
    ("skupina_prazdna", "Skupina hlásí prázdno", None),
    ("zastupce", "Větrá za nás", None),
    ("zadost_sousedum", "Žádám sousedy o", None),
    ("narazove_vetrani", "Nárazové větrání běží", None),
    ("narazove_mozne", "Nárazový režim je možný", None),
    ("cekani_po_marnem", "Čekání po marném větrání", None),
    ("pauza_po_pulzu_min", "Pauza po větrání", " min"),
    ("vetrani_za_sebou", "Větrání po sobě bez vyvětrání", None),
    ("prach_zvenci", "Prach se tahá zvenčí", None),
    ("prach_ze_zvlhcovace", "Prach je ze zvlhčovače", None),
    ("co2_vlastni", "CO2 z vlastního čidla", " ppm"),
    ("co2_max", "CO2 nejhorší v oblasti", " ppm"),
    ("prahy_z_oblasti", "Prahy bere z oblasti", None),
    ("topeni_rezim", "Topení — režim", None),
    ("topeni_utlum", "Topení — útlum", None),
    ("topeni_poslano", "Topení — poslední povel", None),
    ("topeni_hlavice", "Topení — hlásí hlavice", None),
    ("odvzdusneni", "Odvzdušnění", None),
    ("nejnizsi_teplota", "Nejnižší teplota dneška", " °C"),
    ("dnes", "Souhrn dne", None),
]


# Značka bloku v proudu řádků. Blok, který se při generování
# odškrtne, se takhle dá vyhodit celý včetně jeho hranic sekcí.
ZNACKA_BLOKU = "#--BLOK--"


def _jen_zapnute(radky: list[str], bloky: set | None) -> list[str]:
    """Vyhodí řádky bloků, které nikdo nechce.

    Filtruje se až nad hotovým proudem: každý blok se jinak musel
    obalit podmínkou a odsazení by se roztrhalo při první úpravě.
    """
    zapnuto = set(bloky) if bloky is not None else set(BLOKY)
    out, blok = [], None
    for r in radky:
        if r.startswith(ZNACKA_BLOKU):
            blok = r[len(ZNACKA_BLOKU):]
            continue
        if blok is not None and blok not in zapnuto:
            continue
        out.append(r)
    return out


# Hranice sekce. V jedné kartě se značky zahodí, na stránce se podle
# nich vytvoří samostatné sekce, které jdou chytat a přesouvat.
SEKCE = "#--SEKCE--"

# Pořadí sekcí na stránce. Karty se staví v tom pořadí, v jakém je
# pohodlné je poskládat v kódu, ale na stránce mají být jinak — tohle
# je ta druhá věc a mění se přesunutím jednoho řádku.
# Kde se Ladění rozdělí na kratší sekce a jak se nová jmenuje.
ZLOMY_LADENI = {
    "prach_je_spatny_od_pm2_5": "Ladění — prach",
    "ve_dne_otevrit_pri_odchylce_od_cile_o": "Ladění — pásmo",
    "pojistka_nevychladit_pod": "Ladění — meze",
    "v_noci_posun_cilove_teploty": "Ladění — topení",
    "otevrit_nad_co2": "Ladění — CO2",
}

# Co které šoupátko potřebuje, aby mělo smysl. Místnost bez okna nemá
# co dělat s pásmem ani s pojistkami, místnost bez hlavice s nočním
# posunem. Generovat je stejně znamená stránku plnou nastavení, která
# nic neovlivní — a hledá se v tom pak to, co ovlivní.
POTREBUJE = {
    # Při jaké odchylce se začne větrat platí i pro místnost bez okna,
    # pokud je v zóně s místností, která okno má: požádá o vyvětrání
    # souseda a hranici si určuje tímhle svým číslem. Bez té druhé
    # značky se šoupátko v kartě nevyrobilo, přestože se podle něj
    # rozhoduje. Zavírací hrana se u žádosti nepoužívá — ta končí
    # na cíli, ne na protější hraně pásma.
    "ve_dne_otevrit_pri_odchylce_od_cile_o": ("okno", "vetrani_zonou"),
    "ve_dne_zavrit_az_za_cilem_o": "okno",
    "v_noci_otevrit_pri_odchylce_od_cile_o": ("okno", "vetrani_zonou"),
    "v_noci_zavrit_az_za_cilem_o": "okno",
    "venku_musi_byt_za_dojezdem_o": "okno",
    "pojistka_nevychladit_pod": "okno",
    "pojistka_neprehrat_nad": "okno",
    "nejkratsi_doba_drzeni_polohy": "okno",
    "po_rucnim_zasahu_nechat_byt": "okno",
    "chladit_jen_pri_venkovni_teplote_nad": "okno",
    "po_rucnim_prestaveni_zaluzii_nechat_byt": "zaluzie",
    "prach_je_spatny_od_pm2_5": "prach",
    "prach_je_cisty_pod_pm2_5": "prach",
    "v_noci_posun_cilove_teploty": "topeni",
    "pri_otevrenem_okne_topit_na": "topeni",
    "otevrit_nad_co2": "co2",
    "zavrit_pod_co2": "co2",
    "v_noci_otevrit_nad_co2": "co2",
    "nouzove_otevrit_nad_co2": "co2",
}

# Hlavní bloky stránky. Dají se při generování odškrtnout — výchozí
# stav je všechno zapnuté.
BLOKY = ["mistnosti", "cilova_teplota", "zaklad", "ladeni", "stineni",
         "grafy", "zvlhcovace", "obsazenost", "napoveda", "ovladani",
         "podrobnosti"]

# Home Assistant skládá sekce do mřížky po řádcích a řádek je vysoký
# jako jeho nejvyšší sekce — pod krátkou tedy zůstane díra. Pořadí je
# proto seřazené tak, aby vedle sebe stály podobně vysoké sekce.
PORADI_SEKCI = [
    "#pokoj",                 # každá místnost se svými budíky, hned nahoře
    # Dál podle toho, jak se s kartou pracuje: nejdřív ruční ovládání
    # a plánování, pak nastavení od nejčastěji přestavovaného, a
    # nakonec výpisy, které se jen čtou. Mřížka zarovnává řádky, takže
    # vedle krátké sekce u vysoké zůstane díra — pořadí podle použití
    # za to stojí, hledá se v něm bez přemýšlení.
    "Ovládání oken",          # s žaluziemi a zvlhčovači v jedné sekci
    "Plánování",              # zadání plánu včetně kalendáře
    "Cílová teplota",
    "Ladění — topení",
    "Ladění — meze",
    "Ladění — pásmo",
    "Ladění — CO2",
    "Ladění — prach",
    "Základ výpočtu",
    "Slunce a stínění",
    "Srovnat do žádané polohy",
    "Grafy",
    "Obsazenost a klid",      # se sdíleným vzduchem v jedné sekci
    "Ladění",                 # odchylka a časování oken
    "Jak zadat plán ručně",
    "Platí bez nastavení",
    "— podrobnosti",          # ladicí výpisy místností, úplně nakonec
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


def _markdown(radky: list[tuple]) -> list[str]:
    """Karta, která řádek bez hodnoty vynechá.

    Karta se seznamem to neumí: prázdný atribut v ní svítí jako
    „Neznámý" a zabírá místo, i když zrovna nemá co říct.

    Každý řádek je (entita, atribut, popisek, jednotka).
    """
    if not radky:
        return []
    out = ["  - type: markdown", "    content: |-"]
    for eid, atribut, popis, jednotka in radky:
        out.append(f"      {{% set x = state_attr('{eid}', "
                   f"'{atribut}') %}}")
        out.append("      {% if x is not none and x != '' %}")
        out.append(f"      - **{popis}:** {{{{ x }}}}{jednotka or ''}")
        out.append("      {% endif %}")
    out.append("")
    return out


def _atribut_kdyz_je(eid: str, atribut: str, nazev: str,
                     pripona: str | None = None) -> list[str]:
    """Řádek, který se schová, dokud atribut nemá hodnotu.

    Karta se seznamem prázdný řádek skrýt neumí a svítí v něm
    „Neznámý". Podmíněný řádek to umí a zůstane přitom na svém místě
    mezi ostatními — šablona se vyhodnocuje za běhu, takže řádek
    naskočí i zmizí sám.
    """
    # Řádek pod „row:" je mapa, ne položka seznamu — pomlčka se proto
    # musí zahodit a odsazení srovnat.
    telo = [r.strip() for r in _atribut(eid, atribut, nazev, pripona)]
    telo[0] = telo[0].removeprefix("- ")
    return (["      - type: conditional", "        conditions:",
             "          - condition: template",
             f"            value_template: \"{{{{ state_attr('{eid}', "
             f"'{atribut}') is not none }}}}\"",
             "        row:"]
            + [f"          {r}" for r in telo])


def _karta(polozky: list[str], nazev: str | None = None) -> list[str]:
    if not polozky:
        return []
    r = ["  - type: entities"]
    if nazev:
        # Dvojtečka v názvu rozbíjí YAML, proto uvozovky vždycky.
        r.append(f'    title: "{nazev}"')
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


# Barvy pásem. Modrá pod, zelená v pásmu, žlutá nad, červená tam, kde
# zasahují pojistky. Světlejší zelená je pásmo, které platí jen v noci —
# když je noční odchylka jiná než denní, jinak se s tou zelenou slije.
POD = "#4a90d9"
V_PASMU = "#5cb85c"
V_PASMU_NOC = "#9acd32"
NAD = "#f0ad4e"
KRAJ = "#d9534f"


def _segmenty(pasma: list[tuple[float, str]], min_: float) -> list[str]:
    """Hrany pásem do YAML: vzestupně, bez duplicit, od minima stupnice.

    Dvě hrany na témž čísle vzniknou, kdykoli se denní a noční
    odchylka rovnají. Lovelace by z toho nakreslil pásmo nulové
    šířky a barvy by se posunuly o jednu.
    """
    out, videne = [], {}
    for od, barva in sorted(pasma, key=lambda x: x[0]):
        if od <= min_:
            videne[min_] = barva       # vše pod stupnicí má barvu dna
            continue
        videne[round(od, 1)] = barva
    if min_ not in videne:
        videne[min_] = pasma[0][1] if pasma else POD
    for od in sorted(videne):
        out += [f"          - from: {od}",
                f'            color: "{videne[od]}"']
    return ["        segments:"] + out


def _budik(eid: str, nazev: str, min_: float, max_: float,
           pasma: list[tuple[float, str]] | bool = True) -> list[str]:
    """Malý ručičkový ukazatel.

    Hrany pásem se počítají z nastavení místnosti, ne z pevných čísel.
    Lovelace šablony v konfiguraci karty nevyhodnocuje, takže se do
    YAML zapíšou jako čísla — a proto se hodnoty, které se během dne
    hýbou, nevážou na absolutní stupně. Tomu slouží odchylka od cíle.
    """
    r = ["      - type: gauge", f"        entity: {eid}",
         f'        name: "{nazev}"', f"        min: {min_}",
         f"        max: {max_}", "        needle: true"]
    if pasma is True:
        # Nouzová varianta: bez nastavení z běžící integrace zbyde
        # jen obecná teplotní stupnice.
        pasma = [(15, POD), (20, V_PASMU), (26, NAD), (28, KRAJ)]
    if pasma:
        r += _segmenty(pasma, min_)
    return r


def _budiky_mistnosti(prah: dict | None, existuje, cil: str,
                      odchylka: str, co2: str, prach: str) -> list[str]:
    """Čtyři hlavní veličiny vedle sebe: cíl, odchylka, CO2, prach.

    Hrany pásem počítá integrace z toho, podle čeho se rozhoduje; sem
    přijdou hotové. Bez nich se ručičky postaví bez barev — stupnice
    beze zvýraznění je pořád lepší než chybějící ukazatel a barvy se
    doplní, až se karta vygeneruje nad běžící integrací.

    Ručička, která v místnosti nemá čidlo, se nevyrobí — řada se jen
    zúží.
    """
    dolni = float(prah["mez_dolni"]) if prah else 18.0
    horni = float(prah["mez_horni"]) if prah else 27.0
    pasmo = (max(float(prah["pasmo_den"]), float(prah["pasmo_noc"]))
             if prah else 2.5)
    uzsi = (min(float(prah["pasmo_den"]), float(prah["pasmo_noc"]))
            if prah else 2.5)
    krize = float(prah["co2_krize"]) if prah else 1400.0
    spatne = float(prah["pm_spatne"]) if prah else 35.0

    karty = []
    if cil and existuje(cil):
        # U cíle stačí pojistky: ty se během dne nehýbou, takže je
        # vidět, jestli cíl vůbec leží tam, kde se s ním dá pracovat.
        karty += _budik(cil, "Cíl", math.floor(dolni - 2),
                        math.ceil(horni + 2),
                        [(math.floor(dolni - 2), POD), (dolni, V_PASMU),
                         (horni, KRAJ)] if prah else [])
    if odchylka and existuje(odchylka):
        # Souměrně kolem cíle. Červená začíná na dvojnásobku pásma:
        # pojistky jsou v absolutních stupních, takže jejich odstup od
        # cíle se během dne mění a do pevné stupnice se zapsat nedá.
        rozsah = max(5, math.ceil(2 * pasmo + 1))
        karty += _budik(
            odchylka, "Od cíle", -rozsah, rozsah,
            [(-rozsah, POD), (-pasmo, V_PASMU_NOC), (-uzsi, V_PASMU),
             (uzsi, V_PASMU_NOC), (pasmo, NAD), (2 * pasmo, KRAJ)]
            if prah else [])
    if co2 and existuje(co2):
        karty += _budik(
            co2, "CO2", 400, int(math.ceil((krize + 200) / 100) * 100),
            [(400, V_PASMU), (float(prah["co2_otevrit"]), NAD),
             (krize, KRAJ)] if prah else [])
    if prach and existuje(prach):
        karty += _budik(
            prach, "Prach", 0, max(50, int(math.ceil(2 * spatne))),
            [(0, V_PASMU), (float(prah["pm_cisto"]), NAD),
             (spatne, KRAJ)] if prah else [])
    if not karty:
        return []
    # Mřížka o čtyřech sloupcích, ne stack: ve stacku si dvě ručičky
    # rozdělí celou šířku a vyjdou vyšší než čtyři. Takhle má sloupec
    # pořád stejnou šířku, takže ručičky jsou stejně velké, ať už jsou
    # dvě nebo čtyři — a na úzkém displeji se zalomí.
    return (["  - type: grid", "    columns: 4", "    square: false",
             "    cards:"] + karty + [""])


def _napoveda_planu(mistnosti: list[str], skupiny: list[str]) -> list[str]:
    """Nápověda k ručnímu zadání plánu, podle skutečného nastavení.

    Obecný návod je tu k ničemu: jediné, co se dá splést, jsou přesná
    jména — a ta zná jen tahle instalace. Proto se řádky vypisují
    hotové k opsání, ne jako vzorec se zástupnými symboly.
    """
    if not mistnosti and not skupiny:
        return []
    radky = ["NaPohodu: nikdo doma", "NaPohodu: víc lidí"]
    for kdo in list(mistnosti) + list(skupiny):
        radky += [f"{kdo}: je tu někdo",
                  f"{kdo}: nikdo tu nebude",
                  f"{kdo}: zavřená okna",
                  f"{kdo}: nikdo tu nebude, zavřená okna",
                  f"{kdo}: cíl 21,5 °C"]
    c = [SEKCE]
    c += _hlavicka("Jak zadat plán ručně", "mdi:help-circle", "subtitle")
    c.append("  - type: markdown")
    c.append("    content: |-")
    c.append("      Z **dashboardu** se význam ukládá k události, takže"
             " na názvu nezáleží a nedá se pokazit překlepem.")
    c.append("      V **panelu Kalendář** je název jediný nosič významu —"
             " tam platí přesně tyhle tvary:")
    c.append("      ```")
    for r in radky:
        c.append(f"      {r}")
    c.append("      ```")
    c.append("      Zakládej je v kalendáři **NaPohodu Plán**"
             " (`calendar.napohodu_plan`); opakování v panelu funguje."
             " Čemu integrace nerozumí, zůstane uložené a ozve se"
             " zprávou — nespolkne se to tiše.")
    c.append("      *Nikdo tu nebude = utlumí topení a okna nechá jet"
             " dál. Zavřená okna = drží okno zavřené, i když je zbytek"
             " bytu plný lidí.*")
    c.append("")
    return c


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
    # Sekce místnosti začíná mřížkou ručiček. Dřív to byl stack a po
    # přechodu na mřížku se sekce přestaly poznávat — skončily na konci
    # stránky, protože značka seděla na typu karty.
    if "grid" in prvni:
        znacka = "#pokoj"          # budíky místnosti a její údaje
    else:
        text = "\n".join(sekce)
        # Názvy karet jsou v uvozovkách kvůli dvojtečkám, nadpisy ne —
        # hledá se proto obojí.
        znacka = next((z for z in PORADI_SEKCI
                       if z != "#pokoj"
                       and (f": {z}" in text or f': "{z}"' in text
                            or z in text)), None)
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
              nazvy: dict | None = None,
              se_zvlhcovacem: set | None = None,
              zvlhcovace: dict | None = None,
              s_cistickou: set | None = None,
              pm_cidla: dict | None = None,
              prahy: dict | None = None,
              vybaveni: dict | None = None,
              bloky: set | None = None,
              venku: str | None = None,
              co2_cidla: dict | None = None,
              rh_cidla: dict | None = None, s_okny: set | None = None,
              s_klidem: set | None = None, jako_pohled: bool = False,
              podoba: str = "karta",
              skupiny: list | None = None) -> str:
    """Poskládá kartu. `existuje` řekne, jestli entita opravdu je.

    `cidla` a `zaluzie` jsou entity, které integrace nevytváří — teploměr
    místnosti a její žaluzie. Do grafů patří, takže si je vezmeme
    z konfigurace.
    """
    cidla = cidla or {}
    # Klíč místnosti je bez diakritiky, protože z něj vznikají
    # identifikátory entit. Do popisků ale patří pravé jméno.
    nazvy = nazvy or {}
    # zvlhčovače jen tam, kde opravdu jsou; bez toho by karta nabízela
    # meze vlhkosti i místnostem, které žádný nemají
    se_zvlhcovacem = se_zvlhcovacem if se_zvlhcovacem is not None else set(
        mistnosti)
    s_cistickou = s_cistickou if s_cistickou is not None else set(mistnosti)

    def jm(m: str) -> str:
        return nazvy.get(m) or m.capitalize()

    co2_cidla = co2_cidla or {}
    pm_cidla = pm_cidla or {}
    # Co která místnost má. Bez toho se generují i nastavení, která
    # v ní nic neovlivní — neznámá místnost se bere jako vybavená vším.
    vybaveni = vybaveni or {}
    VSE = set()
    for x in POTREBUJE.values():
        VSE |= {x} if isinstance(x, str) else set(x)

    def ma(m: str, co) -> bool:
        mam = vybaveni.get(m, VSE)
        potreba = {co} if isinstance(co, str) else set(co)
        return bool(potreba & mam)

    # Hrany barevných pásem pro ručičky. Počítá je integrace z toho,
    # podle čeho se rozhoduje; karta je jen přepíše do YAML.
    prahy = prahy or {}
    rh_cidla = rh_cidla or {}
    zaluzie = zaluzie or {}
    s_okny = s_okny if s_okny is not None else set(mistnosti)
    s_klidem = s_klidem if s_klidem is not None else set(mistnosti)
    c = []

    c.append(ZNACKA_BLOKU + "cilova_teplota")
    # --- odchylky s oddělovači, ať se místnosti nepletou ---
    polozky = []
    for i, m in enumerate(mistnosti):
        if i:
            polozky.append("      - type: divider")
        polozky += _radek(
            f"number.napohodu_{m}_moje_odchylka_teploty", jm(m))
        polozky += _radek(f"sensor.napohodu_{m}_cilova_teplota",
                          "   výsledný cíl")
        if cidla.get(m):
            polozky += _radek(cidla[m], "   teď v místnosti")
    c += _hlavicka("Cílová teplota", "mdi:target")
    c += _karta([x for x in polozky if _ok(x, existuje)])
    c.append("")

    c.append(ZNACKA_BLOKU + "zaklad")
    # --- základ výpočtu ---
    polozky = []
    for klic, jmeno in (("tydenni", "Venku \u2300 za týden"),
                        ("tridenni", "Venku \u2300 za tři dny")):
        eid = _prvni(existuje,
                     f"sensor.napohodu_venkovni_teplota_{klic}_prumer",
                     "sensor.napohodu_venku_za_"
                     + ("tyden" if klic == "tydenni" else "tri_dny"))
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
    if mistnosti:
        # přítomnost je společná pro celý byt, proto sem a jen jednou
        polozky.append("      - type: divider")
        polozky += _atribut(f"sensor.napohodu_{mistnosti[0]}_stav",
                            "doma_podle", "Doma podle")
        polozky.append("      - type: divider")
        polozky += _atribut(f"sensor.napohodu_{mistnosti[0]}_stav",
                            "cil_rozpad", "Z čeho se cíl skládá")
    if existuje("binary_sensor.napohodu_topna_sezona"):
        polozky.append("      - type: divider")
        polozky += _radek("binary_sensor.napohodu_topna_sezona",
                          "Topná sezóna")
    zaklad = list(polozky)

    # přepínače ovládání hned pod cílovou teplotou, ať je po ruce
    polozky = []
    for klic, popis, kde in (("ovladat_okno", "okna", s_okny),
                             ("ovladat_stineni", "žaluzie", None),
                             ("ovladat_topeni", "topení", None)):
        for m in mistnosti:
            # Přepínač „ovládat okna" tam, kde žádné okno není, nemá co
            # zapnout ani vypnout.
            if kde is not None and m not in kde:
                continue
            eid = f"switch.napohodu_{m}_{klic}"
            if existuje(eid):
                polozky += _radek(eid, f"{jm(m)} — {popis}")
        polozky.append("      - type: divider")
    c += _karta(polozky[:-1], nazev="Co smí ovládat")

    # Volby místnosti, které nejsou číslo: otevírání pro pohodu
    # a zvlhčování ve spánku. Posuvník z nich udělat nejde.
    polozky = []
    for klic, popis in (("otevirat_i_pro_pohodu", "otevírat pro pohodu"),
                        ("zvlhcovat_i_ve_spanku", "zvlhčovat ve spánku")):
        pred = len(polozky)
        for m in mistnosti:
            eid = f"switch.napohodu_{m}_{klic}"
            if existuje(eid):
                polozky += _radek(eid, f"{jm(m)} — {popis}")
        if len(polozky) > pred:
            polozky.append("      - type: divider")
    if polozky:
        c += _karta(polozky[:-1], nazev="Co se smí dít")
    c.append("")

    if zaklad:
        c.append(SEKCE)
        c += _hlavicka("Základ výpočtu", "mdi:calendar-week", "subtitle")
        c += _karta(zaklad)
        c.append("")

    # --- pravidla bez nastavení, pro celý byt jednou ---
    if mistnosti:
        c += _hlavicka("Nastavení pro celý byt", "mdi:home-switch",
                       "subtitle")
        # posuvníky pro celý byt visí na hlavním zařízení integrace
        for klic, nazev, popis in GLOBALNI:
            eid = f"number.napohodu_{klic}"
            if not existuje(eid):
                continue
            c += _karta(_radek(eid, nazev), nazev=None)
            c.append("  - type: markdown")
            c.append(f"    content: '*{popis}*'")
        c.append("  - type: markdown")
        c.append("    content: |-")
        c.append(f"      {{% set q = state_attr("
                 f"'sensor.napohodu_{mistnosti[0]}_stav',"
                 f" 'nastaveni_bytu') %}}")
        c.append("      {% if q %}{% for z in q %}")
        c.append("      - {{ z }}")
        c.append("      {% endfor %}{% endif %}")
        c.append("")
        # Vlastní sekce: je to výpis pravidel, která se nenastavují,
        # takže se čte zvlášť od toho, co se nastavit dá.
        c.append(SEKCE)
        c += _hlavicka("Platí bez nastavení", "mdi:gavel", "subtitle")
        c.append("  - type: markdown")
        c.append("    content: |-")
        c.append(f"      {{% set r = state_attr("
                 f"'sensor.napohodu_{mistnosti[0]}_stav',"
                 f" 'pevna_pravidla_bytu') %}}")
        c.append("      {% if r %}{% for z in r %}")
        c.append("      - {{ z }}")
        c.append("      {% endfor %}{% endif %}")
        c.append("")

    c.append(ZNACKA_BLOKU + "mistnosti")
    # --- okna ---
    for m in mistnosti:
        c.append(SEKCE)
        stav = f"sensor.napohodu_{m}_stav"
        if not existuje(stav):
            continue
        # „Rozhodnutí" je rozhodnutí o okně. Místnost, která okno
        # neovládá, ho sice taky spočítané má, ale nic podle něj
        # nedělá — v kartě by to byla věta o něčem, co se nestane.
        polozky = _radek(stav, "Rozhodnutí") if m in s_okny else []
        if m in s_okny:
            polozky += _radek(f"binary_sensor.napohodu_{m}_okno", "Okno")
        for a, n, s in ATRIBUTY_STAVU:
            # Řádek zařízení, které místnost nemá, by jen svítil
            # „nenastaveno". Karta se seznamem prázdný řádek skrýt
            # neumí, tak se vůbec nevyrobí.
            if a == "zvlhcovac_bezi" and m not in se_zvlhcovacem:
                continue
            if a == "cisticka_bezi" and m not in s_cistickou:
                continue
            if a in JEN_S_OKNEM and m not in s_okny:
                continue
            if a in JEN_KDYZ_JE:
                polozky += _atribut_kdyz_je(stav, a, n, s)
            else:
                polozky += _atribut(stav, a, n, s)

        # Ručičky nahoře: hlavní čtyři veličiny vedle sebe a pod nimi
        # šoupátko odchylky, aby se kvůli jednomu stupni nemuselo
        # překlikávat jinam.
        cil = f"sensor.napohodu_{m}_cilova_teplota"
        cidlo = cidla.get(m, "")
        budiky = _budiky_mistnosti(
            prahy.get(m), existuje, cil,
            f"sensor.napohodu_{m}_odchylka_od_cile",
            co2_cidla.get(m, ""), pm_cidla.get(m, ""))
        if budiky:
            c += budiky
            # Ručička „Od cíle" ukazuje odchylku, takže skutečná
            # teplota patří hned pod ni — karta typu gauge umí
            # vypsat jen tu hodnotu, na které stojí jehla.
            polozky_pod = []
            if existuje(cidlo):
                polozky_pod += _radek(cidlo, "Teď v místnosti")
            posun = f"number.napohodu_{m}_moje_odchylka_teploty"
            if existuje(posun):
                polozky_pod += _radek(posun, "Posun cíle v místnosti")
            if polozky_pod:
                c += _karta(polozky_pod)
                c.append("")

        c += _karta(polozky, nazev=jm(m))

        # Konflikt, stupnice a předpověď v jedné kartě. Stupnice patří
        # do bloku s pevnou šířkou kvůli zarovnání, věta naopak mimo —
        # v bloku se nezalomí a na mobilu se odřízne.
        c.append("  - type: markdown")
        c.append("    content: |-")
        c.append(f"      {{% set x = state_attr('{stav}',"
                 f" 'konflikt_mezi') %}}")
        c.append(f"      {{% set y = state_attr('{stav}',"
                 f" 'teplotni_pasmo') %}}")
        c.append(f"      {{% set u = state_attr('{stav}',"
                 f" 'teplotni_predpoved') %}}")
        c.append("      {% if x %}⚠ **Konflikt nastavení**")
        c.append("      {% for z in x %}")
        c.append("      - {{ z }}")
        c.append("      {% endfor %}")
        c.append("      {% endif %}{% if y %}**Teplotní pásmo větrání**")
        c.append("      ```")
        c.append("      {% for z in y %}{{ z }}")
        c.append("      {% endfor %}```")
        c.append("      {% endif %}{% if u %}{{ u }}")
        c.append("      {% endif %}")
        c.append(f"      {{% set w = state_attr('{stav}',"
                 f" 'pevna_pravidla') %}}")
        c.append("      {% if w %}*Platí bez nastavení:*")
        c.append("      {% for z in w %}")
        c.append("      - {{ z }}")
        c.append("      {% endfor %}{% endif %}")
        c.append("")

    c.append(ZNACKA_BLOKU + "stineni")
    # --- oblasti ---
    # --- stínění ---
    polozky = []
    for m in mistnosti:
        eid = f"sensor.napohodu_{m}_slunce_na_oknech"
        if not existuje(eid):
            continue
        if polozky:
            polozky.append("      - type: divider")
        polozky += _radek(eid, jm(m))
        polozky += _atribut(eid, "role_stineni", "   co je teď potřeba")
        polozky += _atribut(eid, "zadana_poloha", "   žádaná poloha")
        polozky += _atribut(eid, "stineni_stav", "   nastavený stav")
        polozky += _atribut(eid, "zaluzie_poloha", "   skutečná poloha")
        polozky += _atribut(eid, "stineni_duvody", "   proč je tam, kde je")
        polozky += _atribut(eid, "stineni_co_dal", "   co pohyb spustí")
    if polozky:
        c.append(SEKCE)
        c += _hlavicka("Slunce a stínění", "mdi:blinds-horizontal", "subtitle")
        c += _karta(polozky)
        c += _markdown(
            [(f"sensor.napohodu_{m}_slunce_na_oknech", a,
              f"{jm(m)} — {n}", None)
             for m in mistnosti
             if existuje(f"sensor.napohodu_{m}_slunce_na_oknech")
             for a, n in ATRIBUTY_STINENI_OBCAS])

    c.append(ZNACKA_BLOKU + "obsazenost")
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
                polozky += _radek(eid, f"{jm(m)} — {popis}")
                pridano = True
        if pridano:
            polozky.append("      - type: divider")
    if polozky:
        c.append(SEKCE)
        c += _hlavicka("Obsazenost a klid", "mdi:account-check", "subtitle")
        c += _karta(polozky[:-1])
        c.append("")

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
        # bez tohohle nebylo poznat, že si místnost bez okna řekla
        # sousedům o chlazení nebo ohřev
        polozky += _atribut(eid, "teplo_za", "   chladíme a hřejeme i za")
        polozky += _atribut(eid, "klid", "   je klid")
    if polozky:
        c += _hlavicka("Sdílený vzduch", "mdi:home-group", "subtitle")
        c += _karta(polozky)
        c.append("")

    # --- plánovač ---
    # Co, odkdy, dokdy, jak často a tlačítko. Zapisuje se do vlastního
    # kalendáře integrace, takže není kam se netrefit.
    polozky = []
    for eid, popis in (("select.napohodu_co_naplanovat", "Co naplánovat"),
                       ("datetime.napohodu_plan_od", "Od"),
                       ("datetime.napohodu_plan_do", "Do"),
                       ("select.napohodu_jak_casto", "Jak často"),
                       ("number.napohodu_kolikrat_zopakovat",
                        "   kolikrát zopakovat"),
                       ("number.napohodu_planovana_cilova_teplota",
                        "   cílová teplota"),
                       ("button.napohodu_naplanovat", "Naplánovat")):
        if existuje(eid):
            polozky += _radek(eid, popis)
    if polozky:
        polozky += _atribut("select.napohodu_co_naplanovat",
                            "posledni_vysledek", "   naposledy")
        # Vlastní sekce: zadávání plánu je úkon sám pro sebe a hledá se
        # podle nadpisu, ne pod obsazeností.
        c.append(SEKCE)
        c += _hlavicka("Plánování", "mdi:calendar-clock")
        c += _hlavicka("Naplánovat obsazenost", "mdi:calendar-plus",
                       "subtitle")
        c += _karta(polozky)
        # Vlastní kalendář integrace. Je vidět, co je naplánované, a dá
        # se odtud i mazat — ručně založené události plán nezná, proto
        # se ukazuje tenhle, ne všechny.
        if existuje("calendar.napohodu_plan"):
            c += ["  - type: calendar",
                  "    initial_view: listWeek",
                  "    entities:",
                  "      - calendar.napohodu_plan"]
        c.append("")

    c.append(ZNACKA_BLOKU + "napoveda")
    # --- jak zadat plán ručně ---
    # Z dashboardu se význam ukládá do záznamu, takže název je jen
    # popisek. V panelu Kalendář je naopak jediný nosič významu —
    # a tam se bez přesného tvaru nedá trefit. Proto se vypisuje
    # podle skutečného nastavení, se jmény, která tahle instalace má.
    c += _napoveda_planu([jm(m) for m in mistnosti], skupiny or [])


    c.append(ZNACKA_BLOKU + "ladeni")
    # --- ladění ---
    c.append(SEKCE)
    c += _hlavicka("Ladění", "mdi:tune")
    for klic, nadpis, popis in POSUVNIKY:
        # Jedna sekce s třiceti kartami rozhodí rozvržení do sloupců,
        # protože ostatní jsou krátké. Ladění se proto dělí po tématech.
        if klic in ZLOMY_LADENI:
            c.append(SEKCE)
            c += _hlavicka(ZLOMY_LADENI[klic], "mdi:tune", "subtitle")
        polozky = []
        for m in mistnosti:
            # Šoupátko, které v té místnosti nic neovlivní, se
            # negeneruje: pásmo bez okna ani noční posun bez hlavice
            # nemají co dělat.
            potreba = POTREBUJE.get(klic)
            if potreba and not ma(m, potreba):
                continue
            eid = f"number.napohodu_{m}_{klic}"
            if existuje(eid):
                polozky += _radek(eid, jm(m))
        c += _karta(polozky, nazev=nadpis)
        if polozky:
            # jedna řádka, co ta hodnota dělá
            c.append("  - type: markdown")
            c.append(f"    content: \"*{popis}*\"")
            c.append("")

    c.append(ZNACKA_BLOKU + "ovladani")
    # --- ovládání a tlačítka ---
    c.append(SEKCE)

    # ruční ovládání oken
    polozky = []
    for m in mistnosti:
        for klic, popis in (("otevrit_okno", "otevřít"),
                            ("zavrit_okno", "zavřít")):
            eid = f"button.napohodu_{m}_{klic}"
            if existuje(eid):
                polozky += _radek(eid, f"{jm(m)} — {popis}")
    c += _karta(polozky, nazev="Ovládání oken")
    c.append("")

    # ruční ovládání žaluzií: výběr stavu a tlačítka rolí
    polozky = []
    for m in mistnosti:
        pred = len(polozky)
        for i in range(1, len(zaluzie.get(m) or []) + 1):
            eid = f"select.napohodu_{m}_zaluzie_{i}_stav"
            if existuje(eid):
                polozky += _radek(eid, f"{jm(m)} — žaluzie {i}")
        for klic, popis in (("zastinit", "zastínit"),
                            ("odclonit", "odclonit"),
                            ("zatahnout_kvuli_soukromi", "soukromí"),
                            ("nastavit_jako_kdyz_nikdo_neni_doma",
                             "nikdo doma"),
                            ("vychozi_stav_zaluzii", "výchozí stav")):
            eid = f"button.napohodu_{m}_{klic}"
            if existuje(eid):
                polozky += _radek(eid, f"{jm(m)} — {popis}")
        if len(polozky) > pred:
            polozky.append("      - type: divider")
    c += _karta(polozky[:-1], nazev="Ovládání žaluzií")
    c.append("")

    c.append(ZNACKA_BLOKU + "zvlhcovace")
    # --- zvlhčovače: jen místnosti, které ho mají ---
    polozky = []
    for m in mistnosti:
        stav = f"sensor.napohodu_{m}_stav"
        if not existuje(stav) or m not in se_zvlhcovacem:
            continue
        pred = len(polozky)
        polozky += _atribut(stav, "zvlhcovac_bezi", jm(m))
        polozky += _atribut(stav, "vlhkost", "   vlhkost v pokoji")
        polozky += _atribut(stav, "zvlhcovac_proc", "   kdy zapnu a vypnu")
        polozky += _atribut(stav, "prach_ze_zvlhcovace",
                            "   prach je z něj")
        for klic, popis in (("zvlhcovat_pod_vlhkosti", "   zapnout pod"),
                            ("vypnout_zvlhcovac_nad", "   vypnout nad")):
            eid = f"number.napohodu_{m}_{klic}"
            if existuje(eid):
                polozky += _radek(eid, popis)
        if len(polozky) > pred:
            polozky.append("      - type: divider")
    if polozky:
        # Patří k ovládání: je to další přístroj v místnosti, ne
        # samostatné téma, a krátká sekce navíc rozhází mřížku.
        c += _hlavicka("Zvlhčovače", "mdi:air-humidifier", "subtitle")
        c += _karta(polozky[:-1], nazev="Zvlhčovače")
        c.append("")

    # Srovnání má vlastní sekci: jsou to tlačítka, která posílají
    # povely znovu, a hledají se podle nadpisu.
    c.append(SEKCE)
    polozky = []
    if existuje("button.napohodu_srovnat_vse"):
        polozky += _radek("button.napohodu_srovnat_vse", "Všechno naráz")
        if existuje("button.napohodu_vynulovat_vnitrni_stavy"):
            polozky += _radek("button.napohodu_vynulovat_vnitrni_stavy",
                              "Vynulovat vnitřní stavy")
        polozky.append("      - type: divider")
    # Identifikátor entity vzniká z přeloženého jména, ne z klíče
    # v kódu — „srovnat_stineni" se jmenuje Srovnat žaluzie, takže
    # entita končí na srovnat_zaluzie.
    for klic, popis, kde in (("srovnat_okno", "okna", s_okny),
                             ("srovnat_zaluzie", "žaluzie", None),
                             ("srovnat_topeni", "topení", None)):
        for m in mistnosti:
            # Srovnávat okno tam, kde žádné není, nemá co srovnat.
            if kde is not None and m not in kde:
                continue
            eid = f"button.napohodu_{m}_{klic}"
            if existuje(eid):
                polozky += _radek(eid, f"{jm(m)} — {popis}")
    c += _karta(polozky, nazev="Srovnat do žádané polohy")
    c.append("")


    c.append(ZNACKA_BLOKU + "grafy")
    # --- grafy ---
    c.append(SEKCE)
    # Do jednoho grafu se nevejde všechno čitelně. Cíle jsou skoro
    # totožné, takže stačí jeden, a k němu skutečné teploty místností.
    hlavni = mistnosti[0] if mistnosti else None
    teploty = []
    if hlavni:
        teploty.append((f"sensor.napohodu_{hlavni}_cilova_teplota", "Cíl"))
    teploty += [(cidla[m], jm(m)) for m in mistnosti if cidla.get(m)]
    if venku:
        teploty.append((venku, "Venku"))
    c += _hlavicka("Grafy", "mdi:chart-line")
    c += _graf("Teploty", 48, teploty, existuje)

    # CO2 je hodnota, podle které se větrá nejčastěji — bez grafu se
    # prahy ladí naslepo.
    c += _graf("CO2 v místnostech", 24,
               [(co2_cidla[m], jm(m))
                for m in mistnosti if co2_cidla.get(m)], existuje,
               min_radku=1)

    # vlhkost kolísá se větráním a topením, a pozná se z ní, jestli
    # nehrozí plíseň nebo naopak vysušený vzduch
    c += _graf("Vlhkost", 48,
               [(rh_cidla[m], jm(m))
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

    # Zvlhčovače zvlášť: zajímá, kdy běžely, a jen tam, kde jsou.
    # Bere se skutečná entita zařízení, ne naše představa o ní —
    # u infraportu se ty dvě věci můžou rozejít.
    zvlh = [(e, f"Zvlhčovač {jm(m)}")
            for m in mistnosti for e in (zvlhcovace or {}).get(m, [])]
    c += _graf("Zvlhčovače", 48, zvlh, existuje, min_radku=1)

    c.append(ZNACKA_BLOKU + "podrobnosti")
    # Podrobnosti každé místnosti zvlášť a úplně nakonec. Řádek, který
    # nemá hodnotu, se vynechá — karta se seznamem to neumí, markdown
    # ano, a prázdné „Neznámý" jen zabíralo místo.
    for m in mistnosti:
        stav = f"sensor.napohodu_{m}_stav"
        if not existuje(stav):
            continue
        c.append(SEKCE)
        c += _hlavicka(f"{jm(m)} — podrobnosti", "mdi:magnify", "subtitle")
        c += _markdown([(stav, a, n, jed) for a, n, jed in ATRIBUTY_PODROBNE
                        if not (a in JEN_S_OKNEM and m not in s_okny)])

    karty = _jen_zapnute([x for x in c if x is not None],
                         bloky)

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


def _prvni(existuje, *kandidati: str) -> str | None:
    """První identifikátor, který v Home Assistantu opravdu existuje.

    Identifikátor vzniká z přeloženého jména, ale po přejmenování si
    Home Assistant drží ten původní. Starší instalace tak mají jiná
    jména než nová a karta musí zkusit obojí.
    """
    for eid in kandidati:
        if eid and existuje(eid):
            return eid
    return kandidati[0] if kandidati else None


def _ok(radek: str, existuje) -> bool:
    if "entity: " not in radek:
        return True
    return existuje(radek.split("entity: ", 1)[1].strip())
