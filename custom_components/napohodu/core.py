"""Rozhodovací jádro chytrého větrání.

Čistý Python bez závislosti na Home Assistantu, aby šlo testovat samostatně.
Logika je přenesená z odladěného Node-RED flow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------- konstanty

# Pojmenovaná čísla rozhodování. Zadrátovaná do výrazu jsou
# k nenalezení a nikdo neví, proč tam jsou.
# Pojistka ve spánku: o kolik pod noční mez smí teplota spadnout, než
# se okno zavře. Ve spánku se kvůli teplotě nevětrá, takže tohle je
# jediná teplotní záchrana — bez ní by mráz ložnici vychladil.
SPANEK_POJISTKA = 2.0

# Kontrola účinku: o kolik se měřená hodnota musí zlepšit, aby se
# otevřené okno dalo považovat za užitečné. Pod tím je to v šumu čidla.
UCINEK_CO2_PPM = 50.0
UCINEK_TEPLOTA = 0.3

# Couvání po neúspěšném pulzu: když větrání nezabírá, zkoušet to pořád
# dokola nemá cenu. Netýká se teplotního kmitání, to řeší tloušťka
# smyčky.
PAUZA_PO_PULZU_S = 15 * 60

PM10_NASOBEK = 1.4       # PM10 bývá tolikrát vyšší než PM2.5
PM_VYHLAZENI = 0.15      # jak rychle průměr prachu reaguje

MAGNUS_A = 17.27
MAGNUS_B = 237.7


class Akce(Enum):
    NIC = "nic"
    OTEVRIT = "otevrit"
    ZAVRIT = "zavrit"


@dataclass(frozen=True)
class Nastaveni:
    """Ladicí parametry zóny. Vše, co bylo v Node-REDu konstantou."""

    co2_otevrit: float = 800.0
    co2_zavrit: float = 700.0
    co2_noc: float = 1000.0
    co2_noc_krize: float = 1250.0

    pm_prah: float = 35.0
    pm_prah_bez_ventilatoru: float = 50.0
    pm_prah_cisto: float = 20.0
    # o kolik musí být venku lepší, aby mělo smysl otevřít
    pm_rozdil: float = 5.0
    # bez venkovního čidla se to pozná z toho, jak prach reaguje
    # na otevřené okno
    pm_uceni_s: float = 8 * 60      # než se vzduch v místnosti promíchá
    pm_poznatek_s: float = 2 * 3600  # jak dlouho poznatek platí
    # od kterého stupně se vzduch bere za vyvětraný; „moderate" jinak
    # drží okno otevřené, i kdyby bylo CO2 na čtyřech stovkách
    pm_skok: float = 15.0
    pm_skok_min: float = 25.0

    dest_prah: float = 0.3     # nad tímhle se zavírá, i když je vynuceno
    projezd_s: int = 120
    min_drzeni_s: int = 20 * 60
    obnova_s: int = 30 * 60

    komfort_odstup: float = 4.0
    chlazeni_rozdil: float = 1.0
    chlazeni_min_venku: float = 12.0

    # Denní mez se odvozuje od cíle, ne od stavu při otevření ani
    # absolutně. Cíl je vidět, takže mez je předvídatelná, a zároveň
    # sleduje sezónu: v zimě s cílem 21 zavře na 19,5, v létě s cílem
    # 26 na 24,5, aniž by se muselo cokoli přenastavovat.
    # Denní hysterezní pásmo kolem cíle. Kvůli teplotě se otevře nad
    # cíl + hystereze (chlazení) nebo pod cíl − hystereze (ohřev)
    # a dojede se na protější hranu pásma, ne na cíl — po zavření přesně
    # na cíli se teplota hned vrací a cyklus začíná znovu.
    denni_hystereze: float = 1.5
    # Tloušťka noční hysterezní smyčky: o kolik se musí pokoj prohřát
    # nad noční mez, než se v noci otevře znovu, a jak těsně nad mezí
    # se ještě neotvírá. Ve dne se nepoužívá — tam je hysterezí sám
    # odstup od cíle, protože se zavírá na cíli a otevírá o odstup
    # dál. Dřív platila i ve dne a obě pásma se sčítala.
    tloustka: float = 1.0
    nocni_min: float = 18.0
    # po jaké době otevřeného okna se ověří, že větrání vůbec zabírá;
    # nula kontrolu vypne
    ucinek_po_s: float = 30 * 60
    krize_pod_mez: float = 1.5

    noc_od: float = 22.0
    noc_do: float = 6.5


    rozpocet_stupnominut: float = 200.0
    narazove_strop_s: float = 10 * 60
    rucni_klid_s: float = 30 * 60


@dataclass
class Vstup:
    """Naměřený stav v jednom okamžiku."""

    co2: float = 500.0
    pm25: float = 0.0
    pm10: float = 0.0
    pm_platny: bool = True
    # prach venku — bez něj se nepozná, jestli větrání pomůže
    pm25_venku: float | None = None
    pm10_venku: float | None = None

    t_in: float = 21.0          # nejchladnější místo — kondenzace, topení
    t_in_max: float | None = None   # nejteplejší místo — přehřívání, chlazení
    # Nevyplněno znamená, že venkovní teplotu neznáme — po restartu,
    # nebo když čidlo vypadlo. Není to důvod něco dělat.
    t_out: float | None = None
    # Nevyplněno znamená, že venkovní vlhkost neznáme. Rosný bod se
    # pak nepočítá, místo aby se odhadoval z vymyšleného čísla.
    rh_out: float | None = None
    cil: float = 22.0

    dest: float = 0.0
    vitr_blokuje: bool = False
    smog: bool = False
    doma: bool = True
    spanek: bool = False
    # řídí se tahle místnost nočním klidem? Kuchyň, kde se nespí ani
    # neruší, má větrat v noci stejně jako přes den
    vetrat: bool = False
    vynuceno: bool = False

    hodina: float = 12.0
    cas_s: float = 0.0

    # větrá za nás jiná zóna, takže se sami otevřeme až při krizi
    zastupce: bool = False
    # společné nárazové větrání: v mrazu otevřít všude naráz a krátce
    narazove: bool = False


@dataclass
class Pamet:
    """Stav, který přežívá mezi rozhodnutími."""

    otevreno: bool = False
    cas_povelu_s: float = -1e9
    pm_prumer: float | None = None
    vetra_se: bool = False
    rezim: str = "pulz"
    noc_mez: float | None = None
    noc_krize: bool = False
    noc_zavreno_teplotou: bool = False
    noc_start: float | None = None
    den_mez: float | None = None
    komfort_start: float | None = None
    # učení bez venkovního čidla: prach při otevření a jak dlouho
    # ještě platí poznatek, že venku je horší
    pm_pri_otevreni: float | None = None
    pm_otevreno_od_s: float | None = None
    pm_venku_horsi_do_s: float = 0.0
    # po ručním zásahu se čeká na nový podnět, ať se s člověkem
    # automatika nepřetahuje
    rucni_do_s: float = 0.0
    # kolik pulzů po sobě skončilo, aniž by se vzduch dostal pod práh.
    # Když větrání nezabírá, nemá cenu zkoušet to pořád dokola stejně.
    pulzy_za_sebou: int = 0
    # při jaké teplotě se zavřelo kvůli chladu; znovu se otevře až po
    # návratu o tloušťku smyčky
    # Zavřelo se kvůli teplotě v pokoji? Smyčka se pak počítá od hrany
    # pásma, ne od teploty při zavření — ta se pokaždé liší podle toho,
    # jak hluboko se to stihlo přehnat, a při větší tloušťce z toho
    # vycházely nesmyslné hodnoty.
    # běží chlazení? Dokud běží, dojede se na cíl. Bez téhle paměti by
    # se za chlazení počítal každý pokoj o dvě desetiny nad cílem a tím
    # by obešel noční pravidlo.
    chladi: bool = False
    # a totéž pro opačný směr: teplejší vzduch zvenčí dohání cíl
    ohrivam: bool = False
    # kontrola účinku: kdy a s jakými hodnotami se otevřelo
    ucinek_od_s: float = 0.0
    ucinek_co2: float = 0.0
    ucinek_t_in: float = 0.0
    zavreno_chladem: bool = False
    zavreno_teplem: bool = False
    # běží právě pulz zkrácený kvůli nárazovému větrání? Spouštěcí
    # podmínka zmizí hned, jak CO2 klesne, ale okno běží dál.
    narazove_pulz: bool = False
    # poslední skutečné rozhodnutí, ať jde dohledat, co se dělo
    posledni_akce: str = ""
    posledni_duvod: str = ""
    posledni_kdy_s: float = 0.0
    posledni_co2: float = 0.0
    posledni_t_in: float = 0.0
    pohyby: int = 0


@dataclass
class Rozhodnuti:
    akce: Akce
    duvod: str
    # Strojový kód důvodu. Rozhodovat se podle českého textu je past:
    # „vyvětráno" obsahuje „větr" a zpráva o čistém vzduchu se pak pošle
    # jako varování před větrem.
    kod: str = ""
    limit_s: float | None = None
    t_in_korig: float = 0.0
    korekce: float = 0.0     # ponecháno kvůli starším kartám, vždy nula
    rosny_bod: float = 0.0
    co2: float = 0.0


# ---------------------------------------------------------------- pomocné


def teplota_skla(t_in: float, t_out: float, podil: float) -> float:
    """Teplota vnitřního povrchu zasklení.

    Sklo je vždycky chladnější než vzduch v pokoji, protože jím teplo
    uniká. Podíl říká, jakou část rozdílu teplot sklo „sežere" — horší
    okno větší. Pro trojsklo to je okolo osmi procent, pro běžné
    dvojsklo pětina, pro starší dvojsklo třetina, pro jednoduché
    zasklení přes polovinu.
    """
    return t_in - max(0.0, podil) * (t_in - t_out)


def max_vlhkost(t_in: float, t_out: float, podil: float,
                rezerva: float = 1.0) -> float:
    """Nejvyšší vlhkost v pokoji, při které se okno ještě neorosí.

    V mrazu má sklo okolo pěti stupňů a při vnitřních dvaceti dvou
    a šedesáti procentech je rosný bod kolem čtrnácti — okno se tedy
    orosí, přestože vlhkost sama o sobě vypadá rozumně. Správná horní
    mez proto není jedno číslo, ale závisí na venkovní teplotě.

    Rezerva je odstup rosného bodu od skla; bez ní by se zvlhčovalo
    přesně na hranici orosení.
    """
    povrch = teplota_skla(t_in, t_out, podil)
    if povrch >= t_in:
        # sklo je teplejší než vzduch v pokoji, orosit se nemůže
        return 100.0
    sklo = povrch - max(0.0, rezerva)
    if sklo >= t_in:
        return 100.0
    # obrácený Magnusův vzorec: jaká vlhkost dá rosný bod na skle
    horni = (MAGNUS_A * sklo) / (MAGNUS_B + sklo)
    dolni = (MAGNUS_A * t_in) / (MAGNUS_B + t_in)
    return round(min(100.0, max(0.0, 100.0 * math.exp(horni - dolni))), 1)


def rosny_bod(t: float, rh: float) -> float:
    """Magnusův vzorec. Vlhkost se ořízne, aby logaritmus nespadl."""
    rh = min(100.0, max(1.0, rh))
    g = (MAGNUS_A * t) / (MAGNUS_B + t) + math.log(rh / 100.0)
    return (MAGNUS_B * g) / (MAGNUS_A - g)


def _v_pasmu(hodina: float, od: float, do: float) -> bool:
    """Je hodina v pásmu? Pásmo může přecházet přes půlnoc."""
    if od == do:
        return False
    if od < do:
        return od <= hodina < do
    return hodina >= od or hodina < do


def nocni_utlum(hodina: float, noc_od: float, noc_do: float, utlum: float,
                predstih_min: float = 60.0, spanek: bool = False) -> float:
    """O kolik v noci ubrat topení.

    Klesá se s předstihem před začátkem noci, aby to nebyl skok —
    hlavice i zdivo reagují pomalu a náhlá změna se stejně nestihne
    projevit. Zapnutý spánek platí hned, bez ohledu na hodinu, a po
    skončení noci se útlum pouští.
    """
    if utlum <= 0:
        return 0.0
    if spanek:
        return round(utlum, 2)

    if _v_pasmu(hodina, noc_od, noc_do):
        return round(utlum, 2)

    predstih_h = max(predstih_min, 0.0) / 60.0
    if predstih_h <= 0:
        return 0.0

    zacatek = (noc_od - predstih_h) % 24.0
    if not _v_pasmu(hodina, zacatek, noc_od):
        return 0.0
    od_zacatku = (hodina - zacatek) % 24.0
    return round(utlum * od_zacatku / predstih_h, 2)


def cil_adaptivni(prumer_venku: float, posun: float = 0.0,
                  dolni: float = 20.0, horni: float = 27.0,
                  pritopit: float = 0.0) -> float:
    """Adaptivní komfortní teplota podle EN 16798-1."""
    zaklad = 0.33 * prumer_venku + 18.8 + posun
    return round(min(max(zaklad, dolni) + pritopit, horni), 1)


def konflikt_mezi(cil: float, denni_hystereze: float, nocni_min: float,
                  # Tloušťka noční hysterezní smyčky: o kolik se musí pokoj prohřát
    # nad noční mez, než se v noci otevře znovu, a jak těsně nad mezí
    # se ještě neotvírá. Ve dne se nepoužívá — tam je hysterezí sám
    # odstup od cíle, protože se zavírá na cíli a otevírá o odstup
    # dál. Dřív platila i ve dne a obě pásma se sčítala.
    tloustka: float = 1.0) -> list[str]:
    """Nesrovnalosti mezi mezemi větrání a cílovou teplotou.

    Mez nad cílem znamená, že se okno zavře hned po otevření, nebo se
    vůbec neotevře — a není to nikde vidět, protože každé nastavení
    samo o sobě vypadá rozumně.

    Hlášky pojmenovávají nastavení tak, jak ho člověk vidí na
    obrazovce, a říkají, co s tím udělat. Bez toho je z hlášky jen
    „konflikt nastavení" a nikdo neví, kam sáhnout.
    """
    potize = []
    if denni_hystereze < 0.5:
        potize.append(
            f"„Denní hystereze“ je jen {denni_hystereze:.1f} °C: "
            f"okno se otevře a hned zavře. Zvyš na 1 °C a víc.")

    if nocni_min >= cil:
        potize.append(
            f"„V noci vychladnout nejvýš na“ {nocni_min:.1f} °C je nad "
            f"cílem {cil:.1f} °C: v noci se vůbec nevyvětrá. Sniž mez, "
            f"nebo zvyš cílovou teplotu.")
    elif nocni_min + tloustka >= cil:
        potize.append(
            f"„V noci vychladnout nejvýš na“ {nocni_min:.1f} °C je moc "
            f"blízko cíli {cil:.1f} °C: noční větrání potřebuje aspoň "
            f"{tloustka:.1f} °C rezervu, takže se nerozjede. "
            f"Sniž mez pod {cil - tloustka:.1f} °C.")
    return potize


def zimni_pritapeni(prumer_venku: float, prah: float = 7.0,
                    o_kolik: float = 1.0, nabeh: float = 2.5) -> float:
    """O kolik přitopit, když je venku zima.

    Adaptivní norma je psaná na letní komfort v přirozeně větraných
    budovách: čím tepleji venku, tím vyšší teplotu lidé doma snesou.
    V zimě se jen opře o dolní hranici a dál nic.

    Přitom v mrazu chladnou stěny a okna, klesá střední radiační
    teplota a člověku je při stejném vzduchu chladněji, protože do
    studených ploch vyzařuje vlastní teplo.

    Parametry říkají: pod prahem se začne přitápět a po náběhu se
    dojde na plnou hodnotu, kde to zůstane. Dál už se nepřidává —
    hlubší mrazy na tom nic nemění a v našich šířkách se stejně
    málokdy objeví.

    Práh nula znamená vypnuto.
    """
    if prah <= 0 or o_kolik <= 0 or prumer_venku >= prah:
        return 0.0
    pod = prah - prumer_venku
    if nabeh <= 0:
        return round(o_kolik, 2)
    return round(min(pod / nabeh, 1.0) * o_kolik, 2)


def _je_noc(hodina: float, n: Nastaveni, spanek: bool) -> bool:
    """Platí noční pravidla?

    Zapnutý spánek platí vždycky, i mimo noční hodiny. Noční hodiny
    platí pro každou místnost — vyšší práh CO2 a klid v bytě nejsou
    věc jedné místnosti. Dřív se to dalo místnosti vypnout a vznikaly
    tím tři různé „klidy", u kterých nešlo poznat, který platí.
    """
    if spanek:
        return True
    if n.noc_od > n.noc_do:          # přes půlnoc
        return hodina >= n.noc_od or hodina < n.noc_do
    return n.noc_od <= hodina < n.noc_do


# ---------------------------------------------------------------- jádro


# o kolik pod původní teplotu smí místnost zůstat, než se znovu otevře


def duvody(v: Vstup, p: Pamet, n: Nastaveni = Nastaveni()) -> list[str]:
    """Vyjmenuje všechno, co právě brání větrání.

    Popisek pod rozhodnutím ukáže jen ten první důvod, takže se snadno
    stane, že člověk jednu překážku odstraní a nic se nezmění. Tohle
    ukáže celý seznam.
    """
    seznam = []
    if v.t_out is None:
        # Bez venkovní teploty se nerozhoduje, takže ostatní důvody
        # nemá cenu vypisovat — nic z nich teď neplatí.
        return ["venkovní teplotu neznám, čekám na čidlo"]
    if v.vitr_blokuje:
        seznam.append("vítr")
    if v.dest > n.dest_prah:
        seznam.append(f"déšť {v.dest:.1f}")
    if not v.doma:
        seznam.append("nikdo není doma")

    tin = v.t_in
    noc = _je_noc(v.hodina, n, v.spanek)

    if noc:
        seznam.append("noční klid")
        if v.zastupce:
            seznam.append("větrá za nás soused")
        if tin <= n.nocni_min + n.tloustka:
            seznam.append(f"pod noční mezí {n.nocni_min:.1f} °C")
        prah = n.co2_noc
    else:
        prah = n.co2_zavrit if p.vetra_se else n.co2_otevrit

    if v.co2 <= prah:
        seznam.append(f"CO2 {v.co2:.0f} pod prahem {prah:.0f}")
    if (v.t_out is not None and v.rh_out is not None
            and rosny_bod(v.t_out, v.rh_out) > tin - 2):
        seznam.append("rosný bod")
    if v.smog:
        seznam.append("smog venku")
    if v.cas_s < p.pm_venku_horsi_do_s:
        seznam.append("prach se tahá zvenčí, zjištěno z posledního větrání")
    if (v.pm25_venku is not None and v.pm25 > 0
            and v.pm25_venku > v.pm25 - n.pm_rozdil):
        seznam.append(f"prach venku je horší nebo stejný "
                      f"({v.pm25_venku:.0f} proti {v.pm25:.0f}), "
                      f"větráním to nespravím")
    if v.cas_s - p.cas_povelu_s < n.min_drzeni_s:
        zbyva = int((n.min_drzeni_s - (v.cas_s - p.cas_povelu_s)) / 60)
        seznam.append(f"drží se stav ještě {zbyva} min")

    return seznam


def _pod_cilem(v: Vstup, n: Nastaveni, t_in: float) -> bool:
    """Je v pokoji doopravdy chladno, nebo jen spadlo čidlo v okně?

    Při zavřeném okně stačí porovnat s cílem. Při otevřeném ne: čidlo
    ve okenním rámu se okamžitě stáhne k venkovní teplotě a vypadá to,
    že se místnost vychladila, přestože se nestalo nic. Proto se měří
    pokles od teploty, na které se otevíralo — stejně jako u pulzu
    a u nočního režimu.
    """
    # Jedna mez, tvoje nastavená. Dřív tu byla pevná půlstupňová pro
    # zavřené okno a nastavená pro otevřené — dvě pravidla pro totéž,
    # takže nastavení nad půl stupně se nikdy neprojevilo.
    return t_in <= v.cil - n.denni_hystereze


def posledni(p: Pamet, cas_s: float) -> list[str]:
    """Co a proč se naposledy stalo. Doplněk k tomu, co teprve bude."""
    if not p.posledni_akce:
        return ["zatím nic, integrace jen sleduje"]
    pred = int((cas_s - p.posledni_kdy_s) / 60)
    kdy = f"před {pred} min" if pred else "právě teď"
    radky = [f"{p.posledni_akce} — {p.posledni_duvod} ({kdy})",
             f"tehdy CO2 {p.posledni_co2:.0f}, uvnitř "
             f"{p.posledni_t_in:.1f} °C"]
    if p.pulzy_za_sebou > 1:
        radky.append(f"{p.pulzy_za_sebou}. větrání po sobě bez vyvětrání, "
                     f"pauzy se prodlužují")
    return radky


def ocekavani(v: Vstup, p: Pamet, n: Nastaveni = Nastaveni()) -> list[str]:
    """Na co se čeká a co příští změnu spustí.

    Popisek říká, co se stalo. Tohle říká, co se stane — bez toho člověk
    kouká na otevřené okno u vyvětrané místnosti a neví, jestli se
    zavře za minutu, nebo za hodinu.
    """
    seznam = []
    t_in = v.t_in
    noc = _je_noc(v.hodina, n, v.spanek)

    if v.cas_s < p.rucni_do_s:
        seznam.append(f"sáhl jsi na okno, čekám na nový podnět "
                      f"(ještě {int((p.rucni_do_s - v.cas_s) / 60)} min)")

    zbyva = n.min_drzeni_s - (v.cas_s - p.cas_povelu_s)
    if zbyva > 0:
        seznam.append(f"nejdřív za {int(zbyva / 60)} min (držím stav)")

    if p.otevreno:
        if noc and p.noc_mez is not None:
            seznam.append(f"zavřu při poklesu na {p.noc_mez:.1f} °C "
                          f"(teď {t_in:.1f})")
        elif p.rezim == "komfort" and p.komfort_start is not None:
            mez = v.cil - n.denni_hystereze
            seznam.append(f"zavřu při poklesu na {mez:.1f} °C "
                          f"(teď {t_in:.1f})")
        elif p.den_mez is not None:
            seznam.append(f"zavřu při poklesu na {p.den_mez:.1f} °C "
                          f"(teď {t_in:.1f})")
        else:
            mez = v.cil - n.denni_hystereze
            seznam.append(f"zavřu při poklesu na {mez:.1f} °C "
                          f"(teď {t_in:.1f})")
        # Zavření nebrání jen CO2. „Vyvětráno" znamená všechno naráz,
        # takže se musí vyjmenovat, co zbývá — jinak člověk kouká na
        # nízké CO2 a nechápe, proč je pořád otevřeno.
        chybi = []
        if v.narazove:
            seznam.append(f"nárazové větrání zkracuje na "
                          f"{n.narazove_strop_s / 60:.0f} min")
        if v.co2 >= n.co2_zavrit:
            chybi.append(f"CO2 pod {n.co2_zavrit:.0f} (teď {v.co2:.0f})")
        if v.vetrat:
            chybi.append("vypnout ruční větrání")
        venku_lepsi = (v.pm25_venku is None
                       or v.pm25_venku <= v.pm25 - n.pm_rozdil)
        if v.pm_platny and venku_lepsi and v.pm25 >= n.pm_prah_cisto:
            chybi.append(f"PM2.5 pod {n.pm_prah_cisto:.0f} "
                         f"(teď {v.pm25:.0f})")
        if (v.pm_platny and venku_lepsi
                and v.pm10 >= n.pm_prah_cisto * PM10_NASOBEK):
            chybi.append(f"PM10 pod 30 (teď {v.pm10:.0f})")

        if chybi:
            seznam.append("k vyvětráno chybí: " + ", ".join(chybi))
        else:
            seznam.append("vyvětráno, čekám na pokles teploty "
                          "nebo na dojezd větrání")
    else:
        prah = n.co2_noc if noc else n.co2_otevrit
        seznam.append(f"otevřu nad CO2 {prah:.0f} (teď {v.co2:.0f})")
        if (v.pm25_venku is not None and v.pm25 > 0
                and v.pm25_venku > v.pm25 - n.pm_rozdil):
            seznam.append(f"kvůli prachu neotevřu, venku je horší "
                          f"({v.pm25_venku:.0f} proti {v.pm25:.0f}) — "
                          f"větráním to nespravím")
        elif v.cas_s < p.pm_venku_horsi_do_s:
            kolik = int((p.pm_venku_horsi_do_s - v.cas_s) / 60)
            seznam.append(f"kvůli prachu neotevřu — při posledním větrání "
                          f"stoupal, takže se tahá zvenčí (platí ještě "
                          f"{kolik} min)")
        if noc:
            seznam.append(f"a jen nad {n.nocni_min + n.tloustka:.1f} °C "
                          f"(teď {t_in:.1f})")

    return seznam


def rucni_zasah(p: Pamet, n: Nastaveni, cas_s: float, otevreno: bool) -> None:
    """Někdo sáhl na okno rukou. Rozdělaná akce se ruší.

    Bez tohohle by automatika po uplynutí doby držení stavu poslala
    povel znovu a přetahovala se s člověkem. Rozdělané větrání tedy
    zahodíme a počkáme na nový podnět — vyšší CO2, jiná teplota, noc.
    Ochrana proti větru a dešti se tím neruší, ta stojí nad vším.
    """
    p.otevreno = otevreno
    p.rezim = "pulz"
    p.den_mez = None
    p.noc_mez = None
    p.komfort_start = None
    p.vetra_se = otevreno
    p.cas_povelu_s = cas_s
    p.rucni_do_s = cas_s + n.rucni_klid_s


def rozhodni(v: Vstup, p: Pamet, n: Nastaveni = Nastaveni()) -> Rozhodnuti:
    """Vrátí, co se má s oknem stát. Paměť se upravuje na místě."""

    # Teplota se bere tak, jak ji čidlo hlásí. Dřív se při otevřeném
    # okně dopočítávala korekce, ale hodnota pak neodpovídala ničemu,
    # co jde ověřit — a za rok si na to nikdo nevzpomene.
    t_in = v.t_in
    # V zimě rozhoduje nejchladnější čidlo (kondenzace, topení), v horku
    # naopak nejteplejší — nechceme pouštět vedro do přehřáté místnosti.
    t_max = v.t_in_max if v.t_in_max is not None else v.t_in
    dew = (rosny_bod(v.t_out, v.rh_out)
           if v.t_out is not None and v.rh_out is not None else -99.0)

    def hotovo(akce: Akce, duvod: str, limit_s: float | None = None,
               kod: str = "") -> Rozhodnuti:
        return Rozhodnuti(akce, duvod, kod, limit_s, round(t_in, 2),
                          0.0, round(dew, 1), v.co2)

    def otevri(duvod: str, limit_s: float | None, *, hned: bool = False,
               kod: str = "") -> Rozhodnuti:
        return _povel(True, duvod, limit_s, hned, kod)

    def zavri(duvod: str, *, hned: bool = False, kod: str = "") -> Rozhodnuti:
        return _povel(False, duvod, None, hned, kod)

    def _povel(chci_otevreno: bool, duvod: str, limit_s: float | None,
               hned: bool, kod: str = "") -> Rozhodnuti:
        limit = n.projezd_s if hned else max(n.projezd_s, n.min_drzeni_s)
        if v.cas_s - p.cas_povelu_s < limit:
            zbyva = int(limit - (v.cas_s - p.cas_povelu_s))
            chci = "otevřít" if chci_otevreno else "zavřít"
            if zbyva >= 60:
                kolik = f"{zbyva // 60} min"
            else:
                kolik = f"{zbyva} s"
            return hotovo(Akce.NIC, f"chci {chci}, držím stav ještě {kolik}",
                          kod="drzeni")
        p.otevreno = chci_otevreno
        p.cas_povelu_s = v.cas_s
        p.pohyby += 1
        p.posledni_akce = "otevřít" if chci_otevreno else "zavřít"
        p.posledni_duvod = duvod
        p.posledni_kdy_s = v.cas_s
        p.posledni_co2 = v.co2
        p.posledni_t_in = t_in
        return hotovo(Akce.OTEVRIT if chci_otevreno else Akce.ZAVRIT,
                      duvod, limit_s, kod)

    def beze_zmeny(duvod: str, chci_otevreno: bool | None = None) -> Rozhodnuti:
        # obnova povelu, kdyby se stav rozešel se skutečností (ne v noci)
        if (chci_otevreno is not None
                and not _je_noc(v.hodina, n, v.spanek)
                and v.cas_s - p.cas_povelu_s > n.obnova_s):
            p.cas_povelu_s = v.cas_s
            # Skutečný důvod se veze s sebou. Bez něj se v diagnostice
            # objevilo jen „obnova povelu" a nebylo poznat, proč je
            # okno vlastně otevřené.
            return hotovo(Akce.OTEVRIT if chci_otevreno else Akce.ZAVRIT,
                          ("obnova povelu: "
                           + ("otevřít" if chci_otevreno else "zavřít")
                           + f" — {duvod}"),
                          kod="obnova")
        return hotovo(Akce.NIC, duvod)

    # --- 1. vítr ---------------------------------------------------
    if v.vitr_blokuje:
        if not p.otevreno:
            return beze_zmeny("vítr, zavřeno", False)
        p.rezim = "pulz"
        return zavri("zavírám kvůli větru", hned=True, kod="vitr")

    # --- 1b. déšť ---------------------------------------------------
    # Ochrana bytu stojí nad ručním rozhodnutím stejně jako vítr.
    if v.dest > n.dest_prah:
        if not p.otevreno:
            return beze_zmeny("prší, zavřeno", False)
        p.rezim = "pulz"
        return zavri(f"zavírám kvůli dešti ({v.dest:.1f})", hned=True, kod="dest")

    # --- 2. nikdo doma ---------------------------------------------
    if not v.doma:
        if not p.otevreno:
            return beze_zmeny("nikdo není doma")
        p.rezim = "pulz"
        return zavri("nikdo není doma", hned=True, kod="pryc")

    # --- 2b. čerstvý ruční zásah ------------------------------------
    # Ochrana výš už proběhla, takže vítr a déšť okno zavřou i tak.
    if v.cas_s < p.rucni_do_s:
        zbyva = int((p.rucni_do_s - v.cas_s) / 60)
        return hotovo(Akce.NIC,
                      f"sáhl jsi na okno, nechávám to na tobě "
                      f"(ještě {zbyva} min)", kod="rucni_zasah")

    # --- 3. ruční otevření -----------------------------------------
    if v.vynuceno:
        if p.otevreno:
            return beze_zmeny("ručně otevřeno", True)
        return otevri("ručně otevřeno", None, hned=True, kod="rucni")

    # Bez venkovní teploty se podle teploty nerozhoduje. Po restartu
    # čidlo chvíli nehlásí a dřív se místo něj použila vymyšlená
    # hodnota, na jejíž základ se zavíralo okno.
    if v.t_out is None:
        return beze_zmeny("venkovní teplotu neznám, čekám na čidlo",
                          p.otevreno)

    # Otevřené okno bez záznamu se přijme za vlastní. Stávalo se to,
    # když povel přišel na okno, které už otevřené bylo — paměť se
    # plnila jen při přechodu ze zavřeného. Diagnostika pak tvrdila, že
    # okno otevřel někdo jiný, přestože o řádek výš stál náš povel.
    if p.otevreno and p.ucinek_od_s <= 0:
        p.ucinek_od_s = v.cas_s
        p.ucinek_co2 = v.co2
        p.ucinek_t_in = t_in
    if (p.otevreno and p.den_mez is None and p.noc_mez is None
            and p.komfort_start is None
            and t_in > v.cil - n.denni_hystereze):
        # Jen když je teplota nad mezí. Jinak by přijetí okna rovnou
        # vedlo k jeho zavření, přestože se otevřelo z jiného důvodu.
        p.den_mez = round(v.cil - n.denni_hystereze, 1)

    # --- 3b. zabírá to vůbec? ----------------------------------------
    # Marně otevřené okno v zimě stojí teplo a nic za to nevrací.
    # Když se po nastavené době nezlepšilo ani CO2, ani teplota, zavře
    # se a chvíli se to nezkouší. Nouzové větrání a tvoje ruční žádost
    # tím neprochází, ty mají přednost.
    if (p.otevreno and n.ucinek_po_s > 0 and p.ucinek_od_s > 0
            and v.cas_s - p.ucinek_od_s >= n.ucinek_po_s
            and v.co2 <= n.co2_noc_krize
            and not v.vetrat and not v.vynuceno):
        lepsi_co2 = v.co2 <= p.ucinek_co2 - UCINEK_CO2_PPM
        # teplota se má posunout k cíli, ať z které strany
        blize = abs(t_in - v.cil) <= abs(p.ucinek_t_in - v.cil) - UCINEK_TEPLOTA
        if not lepsi_co2 and not blize:
            p.pulzy_za_sebou += 1
            minuty = int(n.ucinek_po_s / 60)
            return zavri(
                f"bez účinku: za {minuty} min CO2 {p.ucinek_co2:.0f} → "
                f"{v.co2:.0f}, teplota {p.ucinek_t_in:.1f} → {t_in:.1f} °C",
                kod="bez_ucinku")

    # --- 4. vzduch --------------------------------------------------
    if p.pm_prumer is None:
        p.pm_prumer = v.pm25
    pm_skok = (v.pm_platny
               and v.pm25 > p.pm_prumer + n.pm_skok
               and v.pm25 > n.pm_skok_min)
    if v.pm_platny:
        p.pm_prumer += (v.pm25 - p.pm_prumer) * PM_VYHLAZENI

    if v.pm_platny:
        pm_spatne = ((v.pm25 > n.pm_prah
                      or v.pm10 > n.pm_prah * PM10_NASOBEK or pm_skok)
                     and not v.smog)
    else:
        pm_spatne = ((v.pm25 > n.pm_prah_bez_ventilatoru
                      or v.pm10 > n.pm_prah_bez_ventilatoru * PM10_NASOBEK)
                     and not v.smog)

    # Venkovní prach rozhoduje, jestli má větrání vůbec smysl. Když je
    # venku horší, otevřením se to nezlepší — jen by se větralo dokola
    # a hodnota by rostla. Bez venkovního čidla se řídíme jen příznakem
    # smogu, tedy jako dřív.
    pm_venku_lepsi = True
    if v.pm25_venku is not None:
        pm_venku_lepsi = v.pm25_venku <= v.pm25 - n.pm_rozdil
        if v.pm10_venku is not None and v.pm10 > 0:
            pm_venku_lepsi = pm_venku_lepsi and (
                v.pm10_venku <= v.pm10 - n.pm_rozdil)
    else:
        # Bez venkovního čidla se to pozná z chování: když prach uvnitř
        # při otevřeném okně stoupá, tahá se dovnitř. Poznatek pár hodin
        # vydrží, ať se okno nezkouší otevřít každou minutu.
        if p.otevreno and v.pm_platny:
            if p.pm_pri_otevreni is None:
                p.pm_pri_otevreni = v.pm25
                p.pm_otevreno_od_s = v.cas_s
            elif (p.pm_otevreno_od_s is not None
                    and v.cas_s - p.pm_otevreno_od_s >= n.pm_uceni_s
                    and v.pm25 > p.pm_pri_otevreni + n.pm_rozdil):
                p.pm_venku_horsi_do_s = v.cas_s + n.pm_poznatek_s
        else:
            p.pm_pri_otevreni = None
            p.pm_otevreno_od_s = None
        pm_venku_lepsi = v.cas_s >= p.pm_venku_horsi_do_s

    if not pm_venku_lepsi:
        pm_spatne = False          # větráním se prach nespraví

    pm_cisto = (not pm_spatne
                and (not v.pm_platny
                     or not pm_venku_lepsi
                     or (v.pm25 < n.pm_prah_cisto and v.pm10 < n.pm_prah_cisto * PM10_NASOBEK)))

    if v.co2 > n.co2_otevrit:
        p.vetra_se = True
    if v.co2 < n.co2_zavrit:
        p.vetra_se = False
    prah_startu = n.co2_zavrit if p.vetra_se else n.co2_otevrit
    if v.zastupce and not v.narazove:
        # větrá za nás soused, sami otevřeme až když to nestačí.
        # Při nárazovém větrání naopak otevíráme všude, o to jde.
        prah_startu = max(prah_startu, n.co2_noc)

    potreba = v.co2 > prah_startu or v.vetrat or pm_spatne
    cisto = v.co2 < n.co2_zavrit and not v.vetrat and pm_cisto

    # --- 5. komfort a chlazení --------------------------------------
    noc = _je_noc(v.hodina, n, v.spanek)
    # Po zavření kvůli dostatečnému ochlazení se čeká na návrat o
    # tloušťku smyčky, stejně jako v chladném směru.
    chlazeni_po_pauze = (not p.zavreno_teplem or p.otevreno
                         or t_max >= v.cil + n.denni_hystereze)
    # Zapíná se s odstupem, aby se neotvíralo kvůli dvěma desetinám,
    # ale dojede se na cíl. Dřív se tou samou hranicí zapínalo
    # i vypínalo, takže se pokoj zastavil o odstup nad cílem.
    prah_chlazeni = (v.cil - n.denni_hystereze
                     if (p.otevreno and p.chladi)
                     else v.cil + n.denni_hystereze)
    # Ohřev větráním je zrcadlový obraz chlazení: venku je tepleji než
    # v pokoji a pokoj je pod cílem. Dojede se na cíl, stejně jako
    # u chlazení — proto taky vlastní příznak.
    prah_ohrevu = (v.cil + n.denni_hystereze
                   if (p.otevreno and p.ohrivam)
                   else v.cil - n.denni_hystereze)
    ohrev = (t_in < prah_ohrevu
             and v.t_out > t_in + n.chlazeni_rozdil
             and not v.smog)
    chlazeni = (t_max > prah_chlazeni
                and v.t_out < t_max - n.chlazeni_rozdil
                and v.t_out > n.chlazeni_min_venku
                and chlazeni_po_pauze
                and not v.smog)

    brani = ""
    if v.smog:
        brani = "smog venku"
    elif dew > t_in - 2:
        brani = f"rosný bod {dew:.1f}"
    elif not chlazeni and v.t_out < v.cil - n.komfort_odstup:
        brani = f"venku {v.t_out:.1f} °C"
    elif not chlazeni and (noc or _v_pasmu(v.hodina, n.noc_od, n.noc_do)):
        # Nočních hodin se to drží i tam, kde se klid neřeší. Že je
        # venku příjemně, není ve tři ráno důvod nechat okno otevřené —
        # tím se probudí dům, ne místnost. Chlazení je výjimka, kvůli
        # němu se v létě otevírá právě v noci.
        brani = "noční hodiny"
    elif t_max > v.cil + n.denni_hystereze and v.t_out > t_max:
        # Teplejší vzduch zvenčí byl důvod, proč se otevíralo. Zavírá
        # se proto, že už je dost teplo, ne proto, že je venku tepleji.
        brani = "dost teplo, jsme na horní hraně pásma"
    elif not chlazeni and not ohrev and v.t_out < t_in \
            and _pod_cilem(v, n, t_in):
        # když se zároveň někde přehřívá, chlazení má přednost
        brani = f"uvnitř {t_in:.1f} °C, pod cílem"

    if not brani:
        if p.rezim != "komfort" or p.komfort_start is None:
            p.komfort_start = t_in
        p.rezim = "komfort"
        # Ohřev větráním se pojmenuje stejně jako chlazení, jinak se
        # z hlášky nepozná, že jde o cílené dohánění teploty.
        p.chladi = chlazeni
        p.ohrivam = ohrev and not chlazeni
        if chlazeni:
            popis_bezi, popis_nove = "chladím", "chlazení větráním"
        elif ohrev:
            popis_bezi = popis_nove = "ohřev venkovním vzduchem"
        else:
            popis_bezi = "venku je příjemně, otevřeno"
            popis_nove = "venku je příjemně, nechávám otevřeno"
        if p.otevreno:
            return beze_zmeny(popis_bezi, True)
        return otevri(popis_nove, None)

    p.chladi = chlazeni
    p.ohrivam = ohrev and not chlazeni

    if p.rezim == "komfort":
        p.rezim = "pulz"
        p.komfort_start = None
        if not potreba and t_max <= v.cil - n.denni_hystereze:
            p.zavreno_teplem = True
        if not potreba:
            # Zavření kvůli teplotě se pozná podle kódu: koordinátor
            # na něj nasadí pauzu, aby se okno hned neotevřelo znovu.
            # Bez toho lítalo tam a sem i ve dne, protože malý pokoj
            # se vrátí na teplotu za dvacet minut.
            # Jen teplota v pokoji. Zavření kvůli venkovní teplotě
            # s rozkyvem uvnitř nemá co dělat a nasazovat na něj
            # smyčku znamenalo čekat na nesmyslné hodnoty.
            kvuli_teplote = "uvnitř" in brani or "pod cílem" in brani
            if kvuli_teplote:
                p.zavreno_chladem = True
            return zavri(f"zavírám, {brani}",
                         kod="teplota" if kvuli_teplote else "")

    # --- 6. noční režim ---------------------------------------------
    if noc:
        krize = v.co2 > n.co2_noc_krize
        # Když za nás větrá soused, sami se v noci otevřeme až při krizi.
        # Lepší pomalejší výměna přes dveře než průvan nad postelí.
        prah_noc = n.co2_noc_krize if v.zastupce else n.co2_noc
        # Jedna mez, absolutní. Relativní pokles od stavu při otevření
        # ji posouval podle toho, jak bylo zrovna teplo, takže nebylo
        # poznat, kde okno zavře — a vyšší z obou hodnot stejně skoro
        # vždycky vyhrála podlaha.
        mez = p.noc_mez if p.noc_mez is not None else n.nocni_min

        if p.otevreno:
            # Ve spánku se kvůli teplotě nevětrá ani nezavírá. Okno dělá
            # při každém pohybu rámus a teplota se v malém pokoji vrací
            # za dvacet minut, takže z toho byla celá noc lítání tam
            # a sem. Zbývá jen pojistka hluboko pod mezí, aby se
            # v mrazu ložnice nevychladila donekonečna.
            pojistka = mez - SPANEK_POJISTKA if v.spanek else mez
            if t_in <= pojistka:
                p.noc_zavreno_teplotou = True
                return zavri(f"noc: kleslo na {t_in:.1f} °C", kod="noc_zima")
            # Noční větrání mělo původně ložnici zároveň vychladit na
            # noční mez, takže se čekalo jen na pokles teploty. Když je
            # venku mírně, pokles nepřijde a okno zůstane otevřené do
            # rána — proto se dá zavřít už po vyvětrání.
            # Ve spánku otevírá krizový práh a zavírá noční. Jsou to
            # dvě hodnoty, které si uživatel nastavuje a vidí, takže je
            # poznat, v jakém pásmu okno zůstane otevřené. Bez toho by
            # okno otevřené před spaním zůstalo celou noc: otevřít ho
            # smí jen krize, ale zavřít se smělo až po vyvětrání,
            # kterého spící člověk nedosáhne.
            if v.spanek and v.co2 < n.co2_noc:
                return zavri(f"noc: klid, CO2 {v.co2:.0f}",
                             kod="noc_hotovo")
            if (v.co2 < n.co2_zavrit
                    and not pm_spatne and not v.vetrat and not v.vynuceno):
                return zavri(f"noc: vyvětráno, CO2 {v.co2:.0f}",
                             kod="noc_hotovo")
            return beze_zmeny(f"noc: větrá {t_in:.1f} °C, CO2 {v.co2:.0f}", True)

        # Po zavření kvůli teplotě se místnost musí znovu prohřát, ne jen
        # na chvíli skočit. Čidlo umístěné v okně po zavření rychle
        # vyskočí — bez téhle hystereze by se okno otevřelo za pár minut.
        if p.noc_zavreno_teplotou and p.noc_start is not None:
            vratit = p.noc_start - n.tloustka
            if t_in >= vratit:
                p.noc_zavreno_teplotou = False
            elif not krize:
                return beze_zmeny(
                    f"noc: čekám na prohřátí, {t_in:.1f} z {vratit:.1f} °C",
                    False)

        # Ve spánku otvírá jen krizový práh. Běžné dusno se vydrží,
        # protože rámus okna vzbudí spolehlivěji než CO2.
        prah_spanek = n.co2_noc_krize if v.spanek else prah_noc
        if v.co2 > prah_spanek or pm_spatne or v.vetrat:
            if krize and t_in > n.nocni_min - n.krize_pod_mez:
                p.noc_mez = n.nocni_min - n.krize_pod_mez
                p.noc_krize = True
                return otevri("noc: nouzové větrání", 12 * 60, kod="noc_krize")
            if t_in <= n.nocni_min + n.tloustka:
                return beze_zmeny(f"noc: dusno, ale jen {t_in:.1f} °C")
            p.noc_mez = n.nocni_min
            p.noc_start = t_in
            p.noc_krize = False
            p.noc_zavreno_teplotou = False
            return otevri(f"noc: otevírám do {p.noc_mez:.1f} °C", 4 * 3600,
                          kod="noc_otevri")
        return beze_zmeny(f"noc: klid, CO2 {v.co2:.0f}", False)

    p.noc_mez = None

    # --- 7. spánek nebo vyvětráno ------------------------------------
    if cisto:
        if not p.otevreno:
            return beze_zmeny(f"čisto, CO2 {v.co2:.0f}", False)
        p.den_mez = None
        p.narazove_pulz = False
        p.zavreno_chladem = False   # vyvětráno, smyčka se ruší
        p.zavreno_teplem = False
        p.pulzy_za_sebou = 0          # povedlo se, couvání se ruší
        return zavri(f"vyvětráno, CO2 {v.co2:.0f}", kod="cisto")

    # Po zavření kvůli teplotě se čeká na návrat o tloušťku smyčky.
    # Bez toho se okno vrátilo, jakmile pokoj skočil o desetinu — a to
    # v malém pokoji trvá pár minut.
    if p.zavreno_chladem and not p.otevreno and v.co2 <= n.co2_noc_krize:
        # Ve dne je hysterezí sám odstup od cíle: zavírá se na cíli
        # a otevírá o odstup od něj. Tloušťka se tu dřív přičítala
        # navíc, takže se obě pásma sčítala a nikdo to neuhlídal.
        vratit = v.cil if not _je_noc(v.hodina, n, v.spanek) else min(
            _mez_chladu(v, p, n) + n.tloustka, v.cil)
        if t_in < vratit:
            return beze_zmeny(
                f"čekám na prohřátí, {t_in:.1f} z {vratit:.1f} °C", False)
        p.zavreno_chladem = False

    # --- 8. pulzní větrání -------------------------------------------
    if potreba:
        if p.otevreno:
            if p.den_mez is not None and t_in <= p.den_mez:
                return zavri(f"kleslo na {t_in:.1f} °C")
            return beze_zmeny(f"větrá se, CO2 {v.co2:.0f}", True)

        dt = max(t_in - v.t_out, 1.0)
        if v.t_out >= v.cil - 1:
            minuty = 90.0
        else:
            minuty = max(5.0, min(45.0, n.rozpocet_stupnominut / dt))
        if noc:
            minuty *= 1.5
        zkraceno = False
        if v.narazove:
            # Krátký průvan vymění vzduch rychleji než dlouhé větrání
            # jedním oknem a stěny se nestihnou vychladit.
            if minuty > n.narazove_strop_s / 60:
                zkraceno = True
            minuty = min(minuty, n.narazove_strop_s / 60)

        p.rezim = "pulz"
        p.den_mez = round(v.cil - n.denni_hystereze, 1)
        duvod = f"CO2 {v.co2:.0f}"
        if pm_spatne:
            duvod = f"PM2.5 {v.pm25:.0f}" + ("" if v.pm_platny else " (bez ventilátoru)")
        dolni = 3 if v.narazove else 30
        p.narazove_pulz = zkraceno
        if zkraceno:
            duvod += f", nárazově jen {minuty:.0f} min"
        return otevri(duvod, min(max(minuty, dolni), 120) * 60, kod="pulz")

    return beze_zmeny(f"mrtvá zóna, CO2 {v.co2:.0f}")


# ------------------------------------------------------- obrázek smyčky

def pevna_pravidla_bytu() -> list[str]:
    """Pravidla bez nastavení, která platí pro celý byt.

    Nenastavitelné chování se nesmí nikde neobjevit — jinak se zapomene,
    že vůbec existuje, a není pak poznat, proč se něco děje. Tahle část
    nezávisí na místnosti, takže patří do jedné karty, ne pod každou.
    """
    return [
        "Denní hysterezní pásmo obemyká cíl z obou stran: nad horní "
        "hranou se chladí, pod dolní ohřívá, a dojede se vždycky na "
        "protější hranu — ne na cíl, jinak se teplota hned vrací.",
        "V noci se kvůli teplotě otevírá jen pro chlazení. Ohřev "
        "venkovním vzduchem čeká do rána — ticho je v noci cennější "
        "než pár stupňů.",
        f"Otevřené okno ověřím: když se za nastavenou dobu CO2 "
        f"nesnížilo aspoň o {UCINEK_CO2_PPM:.0f} ppm ani teplota "
        f"nepřiblížila k cíli o {UCINEK_TEPLOTA:.1f} °C, zavřu — "
        f"nad krizovým prahem a při ruční žádosti ne.",
        f"Prach se vyhlazuje, aby jeden náraz nerozhodoval: každé měření "
        f"posune průměr o {PM_VYHLAZENI * 100:.0f} %.",
        f"Když větrání nezabírá na CO2, další pulz zkusím až za "
        f"{PAUZA_PO_PULZU_S // 60:.0f} min a pauza se s každým dalším "
        f"zdvojnásobí, nejvýš na hodinu. Teplotního kmitání se to "
        f"netýká, to řeší tloušťka smyčky.",
    ]


def pevna_pravidla(spanek: bool, noc: bool, nocni_min: float,
                   co2_noc: float, co2_krize: float) -> list[str]:
    """Pravidla bez nastavení, která závisí na stavu místnosti."""
    if spanek:
        return [
            f"Ve spánku rozhoduje jen CO2: otevře nad {co2_krize:.0f}, "
            f"zavře pod {co2_noc:.0f} ppm. Teplota okno neotvírá ani "
            f"nezavírá.",
            f"Jediná teplotní pojistka: zavřu, až klesne na "
            f"{nocni_min - SPANEK_POJISTKA:.1f} °C, tedy "
            f"{SPANEK_POJISTKA:.0f} °C pod noční mezí.",
        ]
    if noc:
        return [f"V noci zavřu, až je vyvětráno, nebo při poklesu na "
                f"{nocni_min:.1f} °C."]
    return []


def _mez_chladu(v: "Vstup", p: "Pamet", n: "Nastaveni") -> float:
    """Dolní hrana pásma: kde se zavírá kvůli chladu."""
    noc = _je_noc(v.hodina, n, v.spanek)
    if v.spanek:
        return n.nocni_min - SPANEK_POJISTKA
    if noc:
        return p.noc_mez if p.noc_mez is not None else n.nocni_min
    return v.cil - n.denni_hystereze


def pasmo_predpoved(radky: list[str]) -> str:
    """Poslední řádek stupnice, tedy předpověď.

    Patří mimo blok s pevnou šířkou: ten nezalamuje a dlouhá věta se
    v kartě odřízne. Ve bloku zůstanou jen krátké řádky se stupnicí,
    kde na zarovnání záleží.
    """
    return radky[-1] if radky else ""


def pasmo_jen_stupnice(radky: list[str]) -> list[str]:
    """Stupnice bez poslední věty."""
    return radky[:-1] if radky else []


def pasmo_text(cil: float, t_in: float, hystereze: float,
               nocni_min: float, tloustka: float, otevreno: bool,
               spanek: bool = False, noc: bool = False,
               spanek_pojistka: float = 2.0,
               t_max: float | None = None,
               zavreno_chladem: bool = False,
               zavreno_teplem: bool = False,
               chladi: bool = False,
               ohrivam: bool = False,
               duvod: str = "") -> list[str]:
    """Stupnice s mezemi a tím, kde je teplota právě teď.

    Hranice se pojmenovávají tím, co jsou, ne budoucím slovesem.
    Dřív stálo u horní „nad ní začnu chladit", i když se zrovna
    chladilo, a u dvou hranic naráz „tady zavřu", přestože zavřít jde
    v dané chvíli jen na jedné straně. Předpověď patří do věty pod
    stupnici, ne k hranicím.
    """
    t_max = t_max if t_max is not None else t_in
    dolni = (nocni_min - spanek_pojistka if spanek
             else nocni_min if noc else cil - hystereze)
    popis_dolni = ("pojistka ve spánku" if spanek
                   else "noční mez" if noc else "dolní mez")
    horni = cil + hystereze

    body = [(horni, "horní hrana pásma"),
            (cil, "cíl"),
            (dolni, popis_dolni)]
    if zavreno_teplem:
        body.append((horni, "hranice chlazení"))
    if zavreno_chladem and not noc:
        pass          # ve dne je hranicí cíl, ten už v seznamu je
    elif zavreno_chladem:
        body.append((min(dolni + tloustka, cil), "znovu otevřu odtud"))

    znacka = t_max if chladi or t_max > horni else t_in
    cidlo = ("nejteplejší čidlo" if znacka == t_max and t_max != t_in
             else "nejchladnější čidlo")
    radky = []
    for hodnota, popis in sorted(set(body), key=lambda x: -x[0]):
        radky.append(f"{hodnota:5.1f} \u2524 {popis}")
    kde = sorted(set(body) | {(znacka, "")},
                 key=lambda x: -x[0]).index((znacka, ""))
    radky.insert(kde, f"{znacka:5.1f} \u25cf teď, {cidlo}, "
                      + ("otevřeno" if otevreno else "zavřeno"))

    if otevreno:
        proc = f"Otevřeno: {duvod}. " if duvod else "Otevřeno. "
        if chladi:
            radky.append(f"{proc}Chladím, zavřu na {dolni:.1f} °C.")
        elif ohrivam:
            radky.append(f"{proc}Ohřívám, zavřu na {horni:.1f} °C.")
        else:
            radky.append(f"{proc}Zavřu při poklesu na {dolni:.1f} °C; "
                         f"nad {horni:.1f} °C se přepne na chlazení, "
                         f"které dojede na cíl.")
    elif zavreno_chladem:
        otevru = cil if not noc else min(dolni + tloustka, cil)
        radky.append(f"Zavřeno kvůli chladu. Kvůli teplotě otevřu "
                     f"od {otevru:.1f} °C.")
    elif zavreno_teplem:
        radky.append(f"Vychlazeno. Chladit začnu znovu od {horni:.1f} °C.")
    else:
        radky.append(f"Kvůli teplotě bych otevřel nad {horni:.1f} °C "
                     f"(chlazení), nebo pod {dolni:.1f} °C, když je "
                     f"venku tepleji (ohřev).")
    return radky
