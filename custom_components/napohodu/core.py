"""Rozhodovací jádro chytrého větrání.

Čistý Python bez závislosti na Home Assistantu, aby šlo testovat samostatně.
Logika je přenesená z odladěného Node-RED flow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------- konstanty

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
    chlazeni_nad_cil: float = 1.0
    chlazeni_rozdil: float = 1.0
    chlazeni_min_venku: float = 12.0

    # Denní mez se odvozuje od cíle, ne od stavu při otevření ani
    # absolutně. Cíl je vidět, takže mez je předvídatelná, a zároveň
    # sleduje sezónu: v zimě s cílem 21 zavře na 19,5, v létě s cílem
    # 26 na 24,5, aniž by se muselo cokoli přenastavovat.
    denni_pod_cil: float = 1.5
    # Tloušťka hysterezní smyčky: o kolik se musí teplota vrátit, než
    # se po zavření kvůli chladu otevře znovu. Z ní se odvozuje i to,
    # že se neotevře těsně nad mezí. Širší smyčka znamená delší cykly
    # a větší rozkyv — nic mezi tím neexistuje.
    tloustka: float = 1.0
    # O kolik pod noční mez smí teplota ve spánku spadnout, než se
    # okno zavře. Vyšší číslo znamená méně pohybů okna za noc.
    spanek_pojistka: float = 2.0
    nocni_min: float = 18.0
    # zavřít v noci hned po vyvětrání, nebo větrat dál a chladit
    # místnost až na noční mez
    noc_zavrit_po_vyvetrani: bool = True
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
    # kolikrát po sobě se zavřelo kvůli teplotě; každé další zdvojnásobí
    # pauzu, aby okno nelítalo tam a sem
    teplotni_zavreni: int = 0
    # při jaké teplotě se zavřelo kvůli chladu; znovu se otevře až po
    # návratu o tloušťku smyčky
    teplota_zavrela_na: float | None = None
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


def konflikt_mezi(cil: float, denni_pod_cil: float, nocni_min: float,
                  # Tloušťka hysterezní smyčky: o kolik se musí teplota vrátit, než
    # se po zavření kvůli chladu otevře znovu. Z ní se odvozuje i to,
    # že se neotevře těsně nad mezí. Širší smyčka znamená delší cykly
    # a větší rozkyv — nic mezi tím neexistuje.
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
    if denni_pod_cil < 0.5:
        potize.append(
            f"„Ve dne smí klesnout pod cíl o“ je jen {denni_pod_cil:.1f} °C: "
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
        if n.noc_do <= v.hodina < 9:
            seznam.append("ranní klid")
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


def _pod_cilem(v: Vstup, p: Pamet, n: Nastaveni, t_in: float) -> bool:
    """Je v pokoji doopravdy chladno, nebo jen spadlo čidlo v okně?

    Při zavřeném okně stačí porovnat s cílem. Při otevřeném ne: čidlo
    ve okenním rámu se okamžitě stáhne k venkovní teplotě a vypadá to,
    že se místnost vychladila, přestože se nestalo nic. Proto se měří
    pokles od teploty, na které se otevíralo — stejně jako u pulzu
    a u nočního režimu.
    """
    if not p.otevreno or p.komfort_start is None:
        return t_in < v.cil - 0.5
    return t_in <= v.cil - n.denni_pod_cil


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
            mez = v.cil - n.denni_pod_cil
            seznam.append(f"zavřu při poklesu na {mez:.1f} °C "
                          f"(teď {t_in:.1f})")
        elif p.den_mez is not None:
            seznam.append(f"zavřu při poklesu na {p.den_mez:.1f} °C "
                          f"(teď {t_in:.1f})")
        else:
            seznam.append("mez poklesu neznám — okno bylo otevřené už "
                          "při startu nebo ho otevřel někdo jiný")
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
        if v.pm_platny and venku_lepsi and v.pm10 >= 30:
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

    # --- 4. vzduch --------------------------------------------------
    if p.pm_prumer is None:
        p.pm_prumer = v.pm25
    pm_skok = (v.pm_platny
               and v.pm25 > p.pm_prumer + n.pm_skok
               and v.pm25 > n.pm_skok_min)
    if v.pm_platny:
        p.pm_prumer += (v.pm25 - p.pm_prumer) * 0.15

    if v.pm_platny:
        pm_spatne = (v.pm25 > n.pm_prah or v.pm10 > 50 or pm_skok) and not v.smog
    else:
        pm_spatne = (v.pm25 > n.pm_prah_bez_ventilatoru or v.pm10 > 70) and not v.smog

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
                     or (v.pm25 < n.pm_prah_cisto and v.pm10 < 30)))

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
    chlazeni = (t_max > v.cil + n.chlazeni_nad_cil
                and v.t_out < t_max - n.chlazeni_rozdil
                and v.t_out > n.chlazeni_min_venku
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
    elif t_max > v.cil and v.t_out > t_max:
        brani = "venku tepleji než uvnitř"
    elif not chlazeni and v.t_out < t_in and _pod_cilem(v, p, n, t_in):
        # když se zároveň někde přehřívá, chlazení má přednost
        brani = f"uvnitř {t_in:.1f} °C, pod cílem"

    if not brani:
        if p.rezim != "komfort" or p.komfort_start is None:
            p.komfort_start = t_in
        p.rezim = "komfort"
        if p.otevreno:
            return beze_zmeny("chladím" if chlazeni
                              else "venku je příjemně, otevřeno", True)
        return otevri("chlazení větráním" if chlazeni
                      else "venku je příjemně, nechávám otevřeno", None)

    if p.rezim == "komfort":
        p.rezim = "pulz"
        p.komfort_start = None
        if not potreba:
            # Zavření kvůli teplotě se pozná podle kódu: koordinátor
            # na něj nasadí pauzu, aby se okno hned neotevřelo znovu.
            # Bez toho lítalo tam a sem i ve dne, protože malý pokoj
            # se vrátí na teplotu za dvacet minut.
            kvuli_teplote = ("uvnitř" in brani or "pod cílem" in brani
                             or "venku" in brani)
            if kvuli_teplote:
                p.teplota_zavrela_na = t_in
            return zavri(f"zavírám, {brani}",
                         kod="teplota" if kvuli_teplote else "")

    # --- 6. noční režim ---------------------------------------------
    if noc:
        rano = n.noc_do <= v.hodina < 9
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
            pojistka = mez - n.spanek_pojistka if v.spanek else mez
            if t_in <= pojistka:
                p.noc_zavreno_teplotou = True
                return zavri(f"noc: kleslo na {t_in:.1f} °C", kod="noc_zima")
            # Noční větrání mělo původně ložnici zároveň vychladit na
            # noční mez, takže se čekalo jen na pokles teploty. Když je
            # venku mírně, pokles nepřijde a okno zůstane otevřené do
            # rána — proto se dá zavřít už po vyvětrání.
            if (n.noc_zavrit_po_vyvetrani and v.co2 < n.co2_zavrit
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
            if rano:
                return beze_zmeny(f"noc: ranní ruch, neotvírám (CO2 {v.co2:.0f})")
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
        p.teplota_zavrela_na = None   # vyvětráno, smyčka se ruší
        p.pulzy_za_sebou = 0          # povedlo se, couvání se ruší
        return zavri(f"vyvětráno, CO2 {v.co2:.0f}", kod="cisto")

    # Po zavření kvůli teplotě se čeká na návrat o tloušťku smyčky.
    # Bez toho se okno vrátilo, jakmile pokoj skočil o desetinu — a to
    # v malém pokoji trvá pár minut.
    if (p.teplota_zavrela_na is not None and not p.otevreno
            and v.co2 <= n.co2_noc_krize):
        vratit = p.teplota_zavrela_na + n.tloustka
        if t_in < vratit:
            return beze_zmeny(
                f"čekám na prohřátí, {t_in:.1f} z {vratit:.1f} °C", False)
        p.teplota_zavrela_na = None

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
        p.den_mez = round(v.cil - n.denni_pod_cil, 1)
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

def pasmo_text(cil: float, t_in: float, denni_pod_cil: float,
               nocni_min: float, tloustka: float, otevreno: bool,
               spanek: bool = False, noc: bool = False,
               spanek_pojistka: float = 2.0,
               zavrela_na: float | None = None) -> list[str]:
    """Stupnice s mezemi a tím, kde je teplota právě teď.

    Nastavit čtyři čísla a pak hádat, co dělají, je k ničemu. Tohle
    ukáže, kde se okno zavře, odkud se znovu otevře a jak daleko od
    obojího jsme.
    """
    mez_zavri = (nocni_min - spanek_pojistka if spanek
                 else nocni_min if noc else cil - denni_pod_cil)
    popis_mezi = ("pojistka ve spánku" if spanek
                  else "noční mez" if noc else "denní mez")
    zaklad = zavrela_na if zavrela_na is not None else mez_zavri
    mez_otevri = zaklad + tloustka

    body = [(cil, f"cíl {cil:.1f}"),
            (mez_otevri, f"znovu otevřu od {mez_otevri:.1f}"),
            (mez_zavri, f"{popis_mezi} {mez_zavri:.1f} — tady zavřu")]
    radky = []
    for hodnota, popis in sorted(body, key=lambda x: -x[0]):
        radky.append(f"{hodnota:5.1f} ┤ {popis}")

    kde = sorted(body + [(t_in, "")], key=lambda x: -x[0]).index((t_in, ""))
    radky.insert(kde, f"{t_in:5.1f} ●  teď, "
                      + ("otevřeno" if otevreno else "zavřeno"))

    if otevreno:
        radky.append(f"zavřu při poklesu na {mez_zavri:.1f} °C")
    elif t_in < mez_otevri:
        radky.append(f"kvůli teplotě neotevřu, čekám na {mez_otevri:.1f} °C")
    else:
        radky.append("teplota otevření nebrání")
    return radky
