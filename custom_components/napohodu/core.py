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
# Kontrola účinku: o kolik se měřená hodnota musí zlepšit, aby se
# otevřené okno dalo považovat za užitečné. Pod tím je to v šumu čidla.
UCINEK_CO2_PPM = 50.0
UCINEK_TEPLOTA = 0.3

# Couvání po neúspěšném pulzu: když větrání nezabírá, zkoušet to pořád
# dokola nemá cenu. Netýká se teplotního kmitání, to řeší tloušťka
# smyčky.
PAUZA_PO_PULZU_S = 15 * 60

# Na kolik dílů se doba držení polohy dělí pro další úseky sledování
# účinku. První úsek čeká celou dobu, protože dřív se zavřít nedá;
# další na nic čekat nemusí a kratší úsek pozná obrat dřív.
UCINEK_DILU = 5
UCINEK_NEJKRATSI_S = 5 * 60

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

    # Hysterezní pásmo kolem cíle, zvlášť pro den a pro noc. Otevře se
    # při odchylce od cíle o „otevrit", zavře až za cílem o „zavrit" —
    # při chlazení pod cílem, při ohřevu nad ním. Obě hodnoty platí
    # souměrně pro chlazení i pro topení.
    hyst_den_otevrit: float = 2.5
    hyst_den_zavrit: float = 1.0
    hyst_noc_otevrit: float = 2.5
    hyst_noc_zavrit: float = 1.0
    # Absolutní pojistky: zavřou okno bez ohledu na to, proč je
    # otevřené. Obchází je jen ruční žádost o vyvětrání.
    mez_dolni: float = 18.0
    mez_horni: float = 27.0
    # Smí se otevřít i tehdy, když k tomu není důvod, jen pro pohodu?
    pro_pohodu: bool = True

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
    # Po marném větrání se další pokus čeká na změnu venkovních
    # podmínek, ne na hodiny. Čas je jen zástupná veličina — skutečný
    # důvod, proč to nešlo, bylo venku.
    # Jak daleko smí být venkovní teplota od cíle, než se přestane
    # otvírat pro pohodu a větrá se jen z důvodu. Platí i při vypnutém
    # nárazovém větrání — jinak by v mrazu zůstalo okno otevřené.
    narazove_odstup: float = 15.0
    zmena_podminek: float = 2.0      # o kolik °C venku, nula vypne
    nejdriv_znovu_s: float = 60 * 60  # nebo nejpozději za tuhle dobu
    obnova_s: int = 30 * 60

    # Vzduch musí dosáhnout za dojezd pásma, ne jen být lepší než
    # v pokoji. Bez té rezervy se cyklus doplazí k hraně a nikdy ji
    # nepřejde, takže větrání dojezd nikdy nedokončí.
    rezerva_venku: float = 2.0
    # Pod touhle venkovní teplotou se nechladí. Dolní hrana pásma by
    # pokoj zastavila, jenže zavření není okamžité — drží se nejkratší
    # doba držení polohy — a chlazení se řídí nejteplejším čidlem,
    # takže u okna je mezitím výrazně chladněji.
    chlazeni_min_venku: float = 7.0

    # Denní mez se odvozuje od cíle, ne od stavu při otevření ani
    # absolutně. Cíl je vidět, takže mez je předvídatelná, a zároveň
    # sleduje sezónu: v zimě s cílem 21 zavře na 19,5, v létě s cílem
    # 26 na 24,5, aniž by se muselo cokoli přenastavovat.
    # Denní hysterezní pásmo kolem cíle. Kvůli teplotě se otevře nad
    # cíl + hystereze (chlazení) nebo pod cíl − hystereze (ohřev)
    # a dojede se na protější hranu pásma, ne na cíl — po zavření přesně
    # na cíli se teplota hned vrací a cyklus začíná znovu.
    # Tloušťka noční hysterezní smyčky: o kolik se musí pokoj prohřát
    # nad noční mez, než se v noci otevře znovu, a jak těsně nad mezí
    # se ještě neotvírá. Ve dne se nepoužívá — tam je hysterezí sám
    # hystereze kolem cíle: otevírá o ni od cíle, zavírá na protější
    # dál. Dřív platila i ve dne a obě pásma se sčítala.

    noc_od: float = 22.0
    noc_do: float = 6.5


    rozpocet_stupnominut: float = 200.0
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
    # Žádost od místnosti v zóně, která sama okno nemá. Zóna sdílí
    # vzduch, a tím i teplo — jedno okno má obsloužit obě.
    cizi_chlazeni: bool = False
    cizi_ohrev: bool = False


@dataclass
class Pamet:
    """Stav, který přežívá mezi rozhodnutími."""

    otevreno: bool = False
    cas_povelu_s: float = -1e9
    pm_prumer: float | None = None
    vetra_se: bool = False
    rezim: str = "pulz"
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
    chladi: bool = False
    # a totéž pro opačný směr: teplejší vzduch zvenčí dohání cíl
    ohrivam: bool = False
    # kontrola účinku: kdy a s jakými hodnotami se otevřelo
    ucinek_od_s: float = 0.0
    # podmínky při marném pokusu, aby se čekalo na jejich změnu
    # Do kdy couváme po marném pulzu. Dřív se kvůli tomu posouval čas
    # posledního povelu do budoucnosti, takže se couvání tvářilo jako
    # držení stavu a drželo i den po zavření kvůli větru.
    pauza_do_s: float = 0.0
    marne_od_s: float = 0.0
    marne_t_out: float = 0.0
    # co selhalo: "chlazeni" nebo "ohrev". Podle toho platí změna venku
    # jen tím směrem, který by pomohl.
    marne_smer: str = ""
    ucinek_co2: float = 0.0
    ucinek_t_in: float = 0.0
    # kolikátý úsek sledování běží; první čeká na dobu držení, další
    # jsou kratší, aby se obrat poznal včas
    ucinek_kolikaty: int = 0
    # kolik úseků po sobě se nic nezlepšilo; po prvním se dává ještě
    # jedna šance, po druhém se zavírá
    ucinek_bez_zlepseni: int = 0
    # běží právě pulz zkrácený kvůli nárazovému větrání? Spouštěcí
    # podmínka zmizí hned, jak CO2 klesne, ale okno běží dál.
    narazove_pulz: bool = False
    # poslední skutečné rozhodnutí, ať jde dohledat, co se dělo
    posledni_akce: str = ""
    posledni_duvod: str = ""
    posledni_kdy_s: float = 0.0
    # kdy se naposledy poslala obnova. Zvlášť od času povelu, protože
    # obnova není pohyb okna — dřív restartovala dobu držení, takže se
    # při delším držení na jeho konec nikdy nedošlo.
    obnova_kdy_s: float = 0.0
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
    """O kolik v noci posunout cíl. Kladné číslo znamená ubrat.

    Klesá se s předstihem před začátkem noci, aby to nebyl skok —
    hlavice i zdivo reagují pomalu a náhlá změna se stejně nestihne
    projevit. Zapnutý spánek platí hned, bez ohledu na hodinu, a po
    skončení noci se útlum pouští.
    """
    if utlum == 0:
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


def konflikt_mezi(cil: float, otevrit: float, zavrit: float,
                  mez_dolni: float, mez_horni: float) -> list[str]:
    """Nesrovnalosti v nastavení pásma a pojistek.

    Každé nastavení samo o sobě vypadá rozumně, teprve dohromady dají
    chování, které nikdo nechtěl — a není to nikde vidět.
    """
    potize = []
    if otevrit <= 0 and zavrit <= 0:
        potize.append(
            "Obě hodnoty pásma jsou nulové: "
            "okno by se kvůli teplotě otevřelo i zavřelo na cíli a "
            "jezdilo by sem a tam. Zvyš aspoň jedno z nich.")
    if mez_dolni >= cil:
        potize.append(
            f"Pojistka „nevychladit pod“ {mez_dolni:.1f} °C je nad cílem "
            f"{cil:.1f} °C, takže zavře okno dřív, než se dá něco "
            f"vyvětrat. Sniž ji pod cíl.")
    if mez_horni <= cil:
        potize.append(
            f"Pojistka „nepřehřát nad“ {mez_horni:.1f} °C je pod cílem "
            f"{cil:.1f} °C, takže se okno kvůli teplu nikdy neotevře. "
            f"Zvyš ji nad cíl.")
    if mez_dolni > cil - otevrit:
        potize.append(
            f"Pojistka „nevychladit pod“ {mez_dolni:.1f} °C je nad dolní "
            f"hranou pásma {cil - otevrit:.1f} °C, takže se kvůli chladu "
            f"nikdy neotevře — pojistka zasáhne dřív.")
    if mez_horni < cil + otevrit:
        potize.append(
            f"Pojistka „nepřehřát nad“ {mez_horni:.1f} °C je pod horní "
            f"hranou pásma {cil + otevrit:.1f} °C, takže se chlazení "
            f"nikdy nerozjede — pojistka zasáhne dřív.")
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


def _hyst(v: "Vstup", n: "Nastaveni") -> tuple[float, float]:
    """Platné pásmo: v noci noční, jinak denní.

    Vrací odchylku pro otevření a pro zavření. Zavření je za cílem,
    tedy při chlazení pod ním a při ohřevu nad ním — proto se obě
    hodnoty používají souměrně.
    """
    if _je_noc(v.hodina, n, v.spanek):
        return n.hyst_noc_otevrit, n.hyst_noc_zavrit
    return n.hyst_den_otevrit, n.hyst_den_zavrit


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
        if tin <= n.mez_dolni:
            seznam.append(f"pojistka: pod {n.mez_dolni:.1f} °C")
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
    return t_in <= v.cil - _hyst(v, n)[1]


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
        radky.append(f"{p.pulzy_za_sebou}. pulz po sobě bez vyvětrání; "
                     f"u větrání kvůli CO2 se tím prodlužují pauzy")
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
        # Dokud platí ruční zásah, automatika do okna nemluví — další
        # řádky o zavírání by slibovaly něco, co se nestane. Nouzové
        # větrání je jediné, co to obchází, takže patří k tomu.
        return [f"sáhl jsi na okno, čekám na nový podnět "
                f"(ještě {int((p.rucni_do_s - v.cas_s) / 60)} min)",
                f"dřív jen při nouzovém větrání nad "
                f"{n.co2_noc_krize:.0f} ppm (teď {v.co2:.0f})"]

    zbyva = n.min_drzeni_s - (v.cas_s - p.cas_povelu_s)
    if zbyva > 0:
        seznam.append(f"nejdřív za {int(zbyva / 60)} min (držím stav)")
    elif p.pauza_do_s > v.cas_s:
        seznam.append(f"couvám po marném větrání, zkusím za "
                      f"{int((p.pauza_do_s - v.cas_s) / 60)} min")

    if p.otevreno:
        h_otevrit, h_zavrit = _hyst(v, n)
        if p.chladi:
            seznam.append(f"chladím, zavřu na {v.cil - h_zavrit:.1f} °C "
                          f"(teď {t_in:.1f})")
        elif p.ohrivam:
            seznam.append(f"ohřívám, zavřu na {v.cil + h_zavrit:.1f} °C "
                          f"(teď {t_in:.1f})")
        else:
            # Větrání kvůli vzduchu čeká na vyvětrání; o teplotu se
            # starají pojistky, ne hrana pásma.
            seznam.append(f"pojistky {n.mez_dolni:.1f} a "
                          f"{n.mez_horni:.1f} °C (teď {t_in:.1f})")
        # Zavření nebrání jen CO2. „Vyvětráno" znamená všechno naráz,
        # takže se musí vyjmenovat, co zbývá — jinak člověk kouká na
        # nízké CO2 a nechápe, proč je pořád otevřeno.
        chybi = []
        if v.narazove:
            seznam.append("nárazové větrání: zavřu hned, jak důvod "
                          "pomine")
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
        # Couvání po marném pulzu brzdí jen otevírání; zavřít se smí
        # vždycky, jinak by okno zůstalo otevřené kvůli pauze.
        if (chci_otevreno and not hned and p.pauza_do_s > v.cas_s
                and v.co2 <= n.co2_noc_krize and not v.vetrat):
            zbyva_p = int((p.pauza_do_s - v.cas_s) / 60)
            return hotovo(Akce.NIC,
                          f"couvám po marném větrání, zkusím za "
                          f"{zbyva_p} min", kod="pauza")
        if v.cas_s - p.cas_povelu_s < limit:
            zbyva = int(limit - (v.cas_s - p.cas_povelu_s))
            chci = "otevřít" if chci_otevreno else "zavřít"
            if zbyva >= 60:
                kolik = f"{zbyva // 60} min"
            else:
                kolik = f"{zbyva} s"
            return hotovo(Akce.NIC, f"chci {chci}, držím stav ještě {kolik}",
                          kod="drzeni")
        if chci_otevreno and not p.otevreno:
            # od čeho se měří, jestli větrání zabírá
            p.ucinek_od_s = v.cas_s
            p.ucinek_co2 = v.co2
            p.ucinek_t_in = t_in
        elif not chci_otevreno:
            # Pozorování patří k jednomu otevření. Bez nulování se
            # počítalo od prvního otevření v historii a vycházely z toho
            # stovky minut.
            p.ucinek_od_s = 0.0
            p.ucinek_kolikaty = 0
            p.ucinek_bez_zlepseni = 0
            p.chladi = False
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
                and v.cas_s - max(p.cas_povelu_s,
                                  p.obnova_kdy_s) > n.obnova_s):
            p.obnova_kdy_s = v.cas_s
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

    # --- 3b. zabírá to vůbec? ----------------------------------------
    # Marně otevřené okno v zimě stojí teplo a nic za to nevrací.
    # Když se po nastavené době nezlepšilo ani CO2, ani teplota, zavře
    # se a chvíli se to nezkouší. Nouzové větrání a tvoje ruční žádost
    # tím neprochází, ty mají přednost.
    # Účinek se ověří, jakmile uplyne nejkratší doba držení polohy —
    # dřív to nemá smysl, protože zavřít stejně nejde. Dvě různé doby
    # na jednu věc jen pletly.
    # Posuzuje se poslední úsek, ne celé větrání od otevření. Dřív se
    # porovnávalo proti okamžiku otevření, takže větrání, které zabralo
    # na začátku a pak se zastavilo, prošlo navždycky.
    #
    # Zhoršení a zastavení nejsou totéž. Zastavení se pozná až na konci
    # úseku, protože pomalé větrání potřebuje čas. Zhoršení se pozná
    # kdykoli, protože čekat na konec úseku znamená nechat okno dál
    # tahat dovnitř, co nechceme.
    prvni = p.ucinek_kolikaty == 0
    ucinek_po = (n.min_drzeni_s if prvni else
                 max(n.min_drzeni_s / UCINEK_DILU, UCINEK_NEJKRATSI_S))
    if (p.otevreno and n.min_drzeni_s > 0 and p.ucinek_od_s > 0
            and v.co2 <= n.co2_noc_krize
            and not v.vetrat and not v.vynuceno):
        uplynulo = v.cas_s - p.ucinek_od_s
        lepsi_co2 = v.co2 <= p.ucinek_co2 - UCINEK_CO2_PPM
        blize = (abs(t_in - v.cil)
                 <= abs(p.ucinek_t_in - v.cil) - UCINEK_TEPLOTA)
        horsi_co2 = v.co2 >= p.ucinek_co2 + UCINEK_CO2_PPM
        dal = (abs(t_in - v.cil)
               >= abs(p.ucinek_t_in - v.cil) + UCINEK_TEPLOTA)
        zhorseni = horsi_co2 or dal
        konec_useku = uplynulo >= ucinek_po

        if zhorseni and uplynulo >= max(n.min_drzeni_s / UCINEK_DILU,
                                        UCINEK_NEJKRATSI_S):
            p.pulzy_za_sebou += 1
            p.marne_od_s = v.cas_s
            p.marne_t_out = v.t_out
            p.marne_smer = ("chlazeni" if t_in > v.cil
                            else "ohrev" if t_in < v.cil else "")
            # Zavírá se hned, jak se zhoršení pozná — nejkratší doba
            # držení polohy ale platí dál, ta je od toho, aby okno
            # nelítalo, a obcházet ji by znamenalo ji zrušit.
            return zavri(
                f"zhoršuje se to: za {int(uplynulo / 60)} min CO2 "
                f"{p.ucinek_co2:.0f} → {v.co2:.0f}, teplota "
                f"{p.ucinek_t_in:.1f} → {t_in:.1f} °C",
                kod="bez_ucinku")

        if konec_useku and not lepsi_co2 and not blize:
            # První úsek bez zlepšení ještě není důvod zavírat —
            # větrání se může rozjet pomalu. Zavírá se až po druhém
            # v řadě; zhoršení se řeší výš a hned.
            if p.ucinek_bez_zlepseni == 0:
                p.ucinek_bez_zlepseni = 1
                p.ucinek_od_s = v.cas_s
                p.ucinek_co2 = v.co2
                p.ucinek_t_in = t_in
                p.ucinek_kolikaty += 1
                return beze_zmeny(
                    f"zatím se nic nehýbe, dávám tomu ještě jeden úsek "
                    f"(CO2 {v.co2:.0f}, {t_in:.1f} °C)", True)
            p.pulzy_za_sebou += 1
            p.marne_od_s = v.cas_s
            p.marne_t_out = v.t_out
            p.marne_smer = ("chlazeni" if t_in > v.cil
                            else "ohrev" if t_in < v.cil else "")
            return zavri(
                f"nehýbe se to: za {int(uplynulo / 60)} min CO2 "
                f"{p.ucinek_co2:.0f} → {v.co2:.0f}, teplota "
                f"{p.ucinek_t_in:.1f} → {t_in:.1f} °C",
                kod="bez_ucinku")

        if konec_useku:
            # úsek dopadl dobře, další se posuzuje od těchhle hodnot
            p.ucinek_bez_zlepseni = 0
            p.ucinek_od_s = v.cas_s
            p.ucinek_co2 = v.co2
            p.ucinek_t_in = t_in
            p.ucinek_kolikaty += 1

    # --- 3c. absolutní pojistky --------------------------------------
    # Zavřou okno bez ohledu na to, proč je otevřené, a nic jiného
    # neotevřou. Obchází je jen ruční žádost o vyvětrání — v mrazu je
    # vymrzlý pokoj horší problém než dusno.
    if not v.vetrat and v.t_out is not None:
        # Pojistka platí jen proti vzduchu, který tlačí špatným směrem.
        # Zavřít okno, které zrovna chladí přehřátý pokoj, by bylo
        # proti smyslu.
        chladi_nas = v.t_out < t_in
        hreje_nas = v.t_out > t_max
        # Ostré srovnání: na hranici se nic neděje, jinak by se při
        # rovnosti zavřelo a už nikdy neotevřelo.
        if t_in < n.mez_dolni and chladi_nas:
            if p.otevreno:
                return zavri(f"pojistka: kleslo na {t_in:.1f} °C "
                             f"(mez {n.mez_dolni:.1f})", kod="pojistka")
            return beze_zmeny(
                f"pojistka: {t_in:.1f} °C pod mezí {n.mez_dolni:.1f} °C",
                False)
        if t_max > n.mez_horni and hreje_nas:
            if p.otevreno:
                return zavri(f"pojistka: vyšplhalo na {t_max:.1f} °C "
                             f"(mez {n.mez_horni:.1f})", kod="pojistka")
            return beze_zmeny(
                f"pojistka: {t_max:.1f} °C nad mezí {n.mez_horni:.1f} °C",
                False)

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
    # Zapíná se s odstupem, aby se neotvíralo kvůli dvěma desetinám,
    # ale dojede se na cíl. Dřív se tou samou hranicí zapínalo
    # i vypínalo, takže se pokoj zastavil o odstup nad cílem.
    h_otevrit, h_zavrit = _hyst(v, n)
    prah_chlazeni = (v.cil - h_zavrit if (p.otevreno and p.chladi)
                     else v.cil + h_otevrit)
    # Ohřev větráním je zrcadlový obraz chlazení: venku je tepleji než
    # v pokoji a pokoj je pod cílem. Dojede se na cíl, stejně jako
    # u chlazení — proto taky vlastní příznak.
    prah_ohrevu = (v.cil + h_zavrit if (p.otevreno and p.ohrivam)
                   else v.cil - h_otevrit)
    # Venkovní vzduch musí být na správné straně cíle, ne jen lepší než
    # v pokoji. Teplejší vzduch než cíl pokoj na cíl nikdy neochladí,
    # jen ho zastaví o kus výš — a totéž zrcadlově u ohřevu.
    ohrev = ((t_in < prah_ohrevu or v.cizi_ohrev)
             # nikde v pokoji se nesmí přehřívat; dojezd k horní hraně
             # tím zůstává možný
             and t_max < v.cil + h_zavrit
             and v.t_out > v.cil + h_zavrit + n.rezerva_venku
             and not v.smog)
    # Soused bez okna si chladit sám nemůže, tak to udělá tahle
    # místnost za něj — pořád ale podle svých pojistek, aby se kvůli
    # cizímu horku nevymrazila.
    chlazeni = ((t_max > prah_chlazeni or v.cizi_chlazeni)
                and v.t_out < v.cil - h_zavrit - n.rezerva_venku
                and v.t_out > n.chlazeni_min_venku
                and not v.smog)

    # Po marném pokusu se čeká na změnu venkovních podmínek, ne na
    # hodiny. Když se venku nic nezmění, nemá smysl zkoušet totéž —
    # nouzové CO2 a ruční žádost to obchází dál.
    # Nula u změny podmínek vypíná jen čekání na ně, ne celou bránu —
    # strop čekání platí dál. Dřív nula vypnula obojí a zbyla jen doba
    # držení polohy, takže se zkoušelo každých dvacet minut.
    if (p.marne_od_s > 0 and not p.otevreno
            and (n.zmena_podminek > 0 or n.nejdriv_znovu_s > 0)
            and v.co2 <= n.co2_noc_krize and not v.vetrat
            and not v.vynuceno):
        # Stačí jedno z dvojího: venku se posunula teplota správným
        # směrem, nebo uplynul čas. Čas je strop, ne další podmínka —
        # když se ochladí dřív, zkusí se dřív.
        # Pomůže jen posun tím směrem, který by větrání zachránil:
        # chlazení potřebuje chladnější vzduch, ohřev teplejší. Opačný
        # posun situaci nezlepší, jen ji otočí.
        chladneji = v.t_out <= p.marne_t_out - n.zmena_podminek
        tepleji = v.t_out >= p.marne_t_out + n.zmena_podminek
        zmenilo_se = n.zmena_podminek > 0 and (
            chladneji if p.marne_smer == "chlazeni"
            else tepleji if p.marne_smer == "ohrev"
            else chladneji or tepleji)
        cas_vyprsel = v.cas_s - p.marne_od_s >= n.nejdriv_znovu_s
        if not zmenilo_se and not cas_vyprsel:
            # Platí na všechno, ne jen na teplotu. Dřív prošlo větrání
            # kvůli CO2 a za dvacet minut se zkusilo totéž, co minule
            # nezabralo. Krize a ruční žádost to obchází dál.
            zbyva = int((n.nejdriv_znovu_s
                         - (v.cas_s - p.marne_od_s)) / 60)
            cim = (f"na změnu venku o {n.zmena_podminek:.1f} °C, "
                   f"nejpozději {zbyva} min" if n.zmena_podminek > 0
                   else f"ještě {zbyva} min")
            return beze_zmeny(f"minule to nepomohlo, čekám {cim}", False)
        else:
            p.marne_od_s = 0.0        # zkusíme to znovu

    # daleko od cíle: venkovní vzduch se od cílové teploty liší tak,
    # že se větrá jen z důvodu
    daleko_venku = (v.t_out is not None
                    and abs(v.t_out - v.cil) > n.narazove_odstup)

    brani = ""
    if v.smog:
        brani = "smog venku"
    elif dew > t_in - 2:
        brani = f"rosný bod {dew:.1f}"
    elif not chlazeni and not ohrev and daleko_venku:
        # Za prahem je venku tak jiný vzduch, že „venku je příjemně"
        # neplatí ani zdaleka — otevírá se jen z důvodu, ne pro pohodu.
        brani = (f"venku {v.t_out:.1f} °C, mimo pásmo kolem cíle "
                 f"— pro pohodu neotvírám")
    elif not chlazeni and (noc or _v_pasmu(v.hodina, n.noc_od, n.noc_do)):
        # Nočních hodin se to drží i tam, kde se klid neřeší. Že je
        # venku příjemně, není ve tři ráno důvod nechat okno otevřené —
        # tím se probudí dům, ne místnost. Chlazení je výjimka, kvůli
        # němu se v létě otevírá právě v noci.
        brani = "noční hodiny"
    elif p.ohrivam and t_max > v.cil + h_zavrit:
        # Teplejší vzduch zvenčí byl důvod, proč se otevíralo. Zavírá
        # se proto, že už je dost teplo, ne proto, že je venku tepleji.
        brani = "dost teplo, jsme na horní hraně pásma"
    elif (not ohrev and t_max > v.cil + h_otevrit
            and v.t_out >= v.cil - h_zavrit):
        # V pokoji je nad cílem, ale venkovní vzduch nedosáhne tam, kam
        # chlazení dojede. Otevřením se k cíli nepřiblížíme, jen se
        # zastavíme o kus výš. Cíl se v létě sám zvedá, takže se tím
        # chlazení v horku neblokuje.
        brani = (f"venku {v.t_out:.1f} °C, na chlazení k "
                 f"{v.cil - h_zavrit:.1f} °C nestačí")
    elif (not chlazeni and t_in < v.cil - h_otevrit
            and v.t_out <= v.cil + h_zavrit):
        # zrcadlově pro ohřev
        brani = (f"venku {v.t_out:.1f} °C, na ohřev k "
                 f"{v.cil + h_zavrit:.1f} °C nestačí")
    elif not chlazeni and not ohrev and v.t_out < t_in \
            and _pod_cilem(v, n, t_in):
        # když se zároveň někde přehřívá, chlazení má přednost
        brani = f"uvnitř {t_in:.1f} °C, pod cílem"
    elif not chlazeni and not ohrev and not n.pro_pohodu:
        # Otevírání bez důvodu se dá vypnout: pak se okno hýbe jen
        # kvůli CO2, prachu, chlazení nebo ohřevu.
        brani = "pro pohodu se neotvírá"
    elif (not chlazeni and not ohrev
            and abs(v.t_out - v.cil) > h_otevrit):
        # „Venku je příjemně" musí znamenat, že venkovní teplota je
        # blízko cíle. Jinak by se pro pohodu otevřelo i při
        # devětadvaceti venku, jen proto, že pokoj je v pásmu.
        brani = (f"venku {v.t_out:.1f} °C, mimo pásmo kolem cíle "
                 f"— pro pohodu neotvírám")

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
            # ať je poznat, že za tím nestojí prach, CO2 ani teplota
            popis_bezi = "nic nevadí, venku je příjemně"
            popis_nove = "nic nevadí, venku je příjemně — nechávám otevřeno"
        if p.otevreno:
            return beze_zmeny(popis_bezi, True)
        return otevri(popis_nove, None)

    # Venkovní vzduch přestal pomáhat: chladili jsme a venku se
    # oteplilo, nebo jsme ohřívali a venku se ochladilo. Držet okno
    # otevřené pak nemá smysl, jen se tahá dovnitř, co nechceme.
    if p.otevreno and p.chladi and not chlazeni and t_max > v.cil:
        p.chladi = False
        return zavri(f"venku {v.t_out:.1f} °C už nechladí", kod="teplota")
    if p.otevreno and p.ohrivam and not ohrev and t_in < v.cil:
        p.ohrivam = False
        return zavri(f"venku {v.t_out:.1f} °C už neohřívá", kod="teplota")

    p.chladi = chlazeni
    p.ohrivam = ohrev and not chlazeni

    if p.rezim == "komfort":
        p.rezim = "pulz"
        p.komfort_start = None
        if not potreba:
            # Zavření kvůli teplotě se pozná podle kódu: koordinátor
            # na něj nasadí pauzu, aby se okno hned neotevřelo znovu.
            # Bez toho lítalo tam a sem i ve dne, protože malý pokoj
            # se vrátí na teplotu za dvacet minut.
            # Jen teplota v pokoji. Zavření kvůli venkovní teplotě
            # s rozkyvem uvnitř nemá co dělat a nasazovat na něj
            # smyčku znamenalo čekat na nesmyslné hodnoty.
            kvuli_teplote = ("uvnitř" in brani or "pod cílem" in brani
                             or "nestačí" in brani)
            return zavri(f"zavírám, {brani}",
                         kod="teplota" if kvuli_teplote else "")

    # --- 6. noc a spánek: rozhoduje CO2 ------------------------------
    # Teplotu v noci řeší noční pásmo výš a pojistky; tady už jde jen
    # o vzduch. Dřív tu byla vlastní noční mez, vlastní hystereze
    # a vlastní pojistka ve spánku — tři pojmy pro totéž, co dnes umí
    # pásmo s pojistkami.
    if noc:
        # Když za nás větrá soused, sami se otevřeme až při krizi.
        # Lepší pomalejší výměna přes dveře než průvan nad postelí.
        # Ve spánku to platí vždycky: rámus okna vzbudí spolehlivěji
        # než oxid uhličitý.
        prah = (n.co2_noc_krize if (v.spanek or v.zastupce)
                else n.co2_noc)

        if p.otevreno:
            # Jedna hladina pro zavření, tatáž jako ve dne. Dřív se ve
            # spánku zavíralo na nočním prahu, takže se jedna hodnota
            # používala na otevírání i zavírání a nebylo poznat, co dělá.
            if (v.co2 < n.co2_zavrit and not pm_spatne
                    and not v.vetrat and not v.vynuceno):
                return zavri(f"noc: vyvětráno, CO2 {v.co2:.0f}",
                             hned=bool(v.narazove), kod="noc_hotovo")
            return beze_zmeny(
                f"noc: větrá {t_in:.1f} °C, CO2 {v.co2:.0f}", True)

        if v.co2 > prah or pm_spatne or v.vetrat:
            return otevri(f"noc: otevírám, CO2 {v.co2:.0f}", 4 * 3600,
                          kod="noc_otevri")
        return beze_zmeny(f"noc: klid, CO2 {v.co2:.0f}", False)

    # --- 7. spánek nebo vyvětráno ------------------------------------
    if cisto:
        if not p.otevreno:
            return beze_zmeny(f"čisto, CO2 {v.co2:.0f}", False)
        p.narazove_pulz = False
        p.pulzy_za_sebou = 0          # povedlo se, couvání se ruší
        # V nárazovém režimu se zavírá okamžitě, bez čekání na nejkratší
        # dobu držení. Bez toho by nárazové větrání nedělalo nic jiného
        # než běžné — a v mrazu je každá minuta navíc drahá.
        return zavri(f"vyvětráno, CO2 {v.co2:.0f}", hned=bool(v.narazove),
                     kod="cisto")


    # --- 8. pulzní větrání -------------------------------------------
    if potreba:
        if p.otevreno:
            # Větrání kvůli vzduchu čeká na vyvětrání; o prochladnutí
            # se stará pojistka výš, ne hrana pásma. Dřív se zavíralo
            # na dolní hraně i s dusnem a hned se otevíralo znovu.
            return beze_zmeny(f"větrá se, CO2 {v.co2:.0f}", True)

        dt = max(t_in - v.t_out, 1.0)
        if v.t_out >= v.cil - 1:
            minuty = 90.0
        else:
            minuty = max(5.0, min(45.0, n.rozpocet_stupnominut / dt))
        if noc:
            minuty *= 1.5
        zkraceno = False
        # Nárazové větrání běží jako běžné, jen se zavře hned, jakmile
        # důvod pomine — v mrazu i v horku je každá minuta navíc drahá.
        zkraceno = bool(v.narazove)

        p.rezim = "pulz"
        duvod = f"CO2 {v.co2:.0f}"
        if pm_spatne:
            duvod = f"PM2.5 {v.pm25:.0f}" + ("" if v.pm_platny else " (bez ventilátoru)")
        dolni = 30
        p.narazove_pulz = zkraceno
        if zkraceno:
            duvod += ", nárazově — zavřu, jakmile důvod pomine"
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
        "Od jaké venkovní teploty se vůbec chladí a o kolik musí být "
        "vzduch za dojezdem pásma, se nastavuje u místnosti.",
        "Když venkovní vzduch přestane pomáhat — chladili jsme a venku "
        "se oteplilo, nebo naopak — okno se zavře.",
        "V noci se kvůli teplotě otevírá jen pro chlazení. Ohřev "
        "venkovním vzduchem čeká do rána — ticho je v noci cennější "
        "než pár stupňů.",
        f"Účinek větrání se posuzuje po úsecích: první trvá nejkratší "
        f"dobu držení polohy, další {1 / UCINEK_DILU:.0%} z ní, nejméně "
        f"{UCINEK_NEJKRATSI_S // 60:.0f} min. Zhoršení zavře okno hned, "
        f"zastavení až na konci úseku.",
        f"Otevřené okno ověřím: když se za nastavenou dobu CO2 "
        f"nesnížilo aspoň o {UCINEK_CO2_PPM:.0f} ppm ani teplota "
        f"nepřiblížila k cíli o {UCINEK_TEPLOTA:.1f} °C, zavřu — "
        f"nad krizovým prahem a při ruční žádosti ne.",
        f"Bez funkčního ventilátoru v čidle prachu se práh zvedá na "
        f"{Nastaveni.pm_prah_bez_ventilatoru:.0f} µg/m³, protože měření "
        f"bez nasávání podhodnocuje.",
        f"Náhlý skok prachu o {Nastaveni.pm_skok:.0f} µg/m³ během "
        f"{Nastaveni.pm_skok_min:.0f} min se bere jako kouř nebo vaření "
        f"a větrá se i pod běžným prahem.",
        f"Prach z venku musí být aspoň o {Nastaveni.pm_rozdil:.0f} "
        f"µg/m³ lepší, aby mělo smysl kvůli němu otevřít. Bez "
        f"venkovního čidla se to učí z toho, jak prach reaguje na "
        f"otevřené okno: měří se {Nastaveni.pm_uceni_s / 60:.0f} min "
        f"a poznatek platí {Nastaveni.pm_poznatek_s / 3600:.0f} h.",
        "Teplotu při každém větrání drží dvě absolutní pojistky "
        "u místnosti; obchází je jen ruční žádost o vyvětrání.",
        f"Povel se po {Nastaveni.obnova_s / 60:.0f} min pošle znovu, "
        f"protože pohon ho občas ztratí. V noci a ve spánku ne.",
        f"Délka pulzu vychází z rozpočtu "
        f"{Nastaveni.rozpocet_stupnominut:.0f} stupňominut: čím větší "
        f"rozdíl teplot, tím kratší větrání, nejvýš 45 a nejméně 5 min.",
        f"Prach se vyhlazuje, aby jeden náraz nerozhodoval: každé měření "
        f"posune průměr o {PM_VYHLAZENI * 100:.0f} %.",
        f"Když větrání nezabírá na CO2, další pulz zkusím až za "
        f"{PAUZA_PO_PULZU_S // 60:.0f} min a pauza se s každým dalším "
        f"zdvojnásobí, nejvýš na hodinu. Po marném větrání kvůli teplotě "
        f"se místo toho čeká na změnu venkovních podmínek.",
    ]


def pevna_pravidla(spanek: bool, noc: bool, co2_noc: float,
                   co2_krize: float, co2_zavrit: float) -> list[str]:
    """Pravidla bez nastavení, která závisí na stavu místnosti."""
    if spanek:
        return [
            f"Ve spánku rozhoduje jen CO2: otevře nad {co2_krize:.0f}, "
            f"zavře pod {co2_zavrit:.0f} ppm. Teplota okno neotvírá ani "
            f"nezavírá, drží ji jen pojistky.",
        ]
    if noc:
        return [f"V noci otevře CO2 nad {co2_noc:.0f} ppm a zavře "
                f"vyvětrání pod {co2_zavrit:.0f} ppm; teplotu řeší "
                f"noční pásmo a pojistky."]
    return []


def proc_neotevira(v: "Vstup", n: "Nastaveni", t_in: float,
                   t_max: float) -> str:
    """Proč se kvůli teplotě neotvírá, i když je pokoj mimo pásmo.

    Bez toho stupnice ukazuje teplotu nad horní hranou a zavřené okno
    a není poznat, co tomu brání — nejčastěji venkovní vzduch, který
    by nepomohl.
    """
    if v.t_out is None:
        return "venkovní teplotu neznám"

    nad_pasmem = t_max > v.cil + n.hyst_den_otevrit
    pod_pasmem = t_in < v.cil - n.hyst_den_otevrit
    chladit_lze = (v.t_out < v.cil - n.hyst_den_zavrit - n.rezerva_venku
                   and v.t_out > n.chlazeni_min_venku)
    ohrat_lze = v.t_out > v.cil + n.hyst_den_zavrit + n.rezerva_venku

    if nad_pasmem and chladit_lze:
        return ""           # chladit jde, nic nebrání
    if pod_pasmem and ohrat_lze:
        return ""           # ohřát jde
    if nad_pasmem:
        if v.t_out <= n.chlazeni_min_venku:
            return (f"venku {v.t_out:.1f} °C, pro chlazení chceme "
                    f"aspoň {n.chlazeni_min_venku:.1f} °C")
        return f"venku {v.t_out:.1f} °C, chladnější vzduch nemáme"
    if pod_pasmem:
        return f"venku {v.t_out:.1f} °C, teplejší vzduch na ohřev nemáme"
    # Nárazový režim teplotnímu větrání nebrání, zakazuje jen otevírání
    # pro pohodu — takže mezi překážky toho, co ta věta popisuje,
    # nepatří. Dřív tu stál a tvrdil, že chlazení ani ohřev nejdou.
    return ""
    return ""


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


def pasmo_text(cil: float, t_in: float, otevrit: float, zavrit: float,
               mez_dolni: float, mez_horni: float, otevreno: bool,
               spanek: bool = False, noc: bool = False,
               t_max: float | None = None,
               chladi: bool = False, ohrivam: bool = False,
               duvod: str = "", brani_teplote: str = "",
               rucni_min: int | None = None,
               trend: int = 0, t_out: float | None = None) -> list[str]:
    """Stupnice: pojistky, pásmo a kde je teplota právě teď.

    U každé hrany je napsané, které nastavení ji určuje — bez toho se
    v číslech kolem cíle nikdo nevyzná.
    """
    t_max = t_max if t_max is not None else t_in
    horni = cil + otevrit
    dolni = cil - otevrit
    # U každé hrany je v závorce šoupátko, které ji určuje — bez toho
    # se v číslech kolem cíle nikdo nevyzná. Ukazuje se ale jen to, co
    # právě platí: dojezdy jen v odpovídajícím režimu a pojistky jen
    # tehdy, když jsou hned za teplotou. Jinak je v tom sedm čísel,
    # z nichž šest nic neznamená.
    znacka_t = t_max if (chladi or t_max > horni) else t_in
    # Chladit jde jen chladnějším vzduchem a ohřívat jen teplejším,
    # takže v zimě nemá smysl ukazovat hranu ohřevu a v létě hranu
    # chlazení — ten stav stejně nenastane.
    lze_chladit = t_out is None or t_out < cil or chladi
    lze_ohrat = t_out is None or t_out > cil or ohrivam
    body = [(cil, "cíl")]
    if lze_chladit:
        body.append((horni, "začnu chladit"))
    if lze_ohrat:
        body.append((dolni, "začnu ohřívat"))
    if chladi:
        body.append((cil - zavrit, "chlazení dojede"))
    if ohrivam:
        body.append((cil + zavrit, "ohřev dojede"))
    # pojistka patří do obrázku, až když je nejbližší hranou
    nad = [h for h, _ in body if h > znacka_t]
    pod = [h for h, _ in body if h < znacka_t]
    if not nad or mez_horni < min(nad):
        body.append((mez_horni, "pojistka: tady zavřu"))
    if not pod or mez_dolni > max(pod):
        body.append((mez_dolni, "pojistka: tady zavřu"))
    znacka = znacka_t
    cidlo = ("nejteplejší čidlo" if znacka == t_max and t_max != t_in
             else "nejchladnější čidlo")

    radky = []
    for hodnota, popis in sorted(set(body), key=lambda x: -x[0]):
        radky.append(f"{hodnota:5.1f} \u2524 {popis}")
    kde = sorted(set(body) | {(znacka, "")},
                 key=lambda x: -x[0]).index((znacka, ""))
    sipka = {1: " \u2191", -1: " \u2193"}.get(trend, "")
    radky.insert(kde, f"{znacka:5.1f} \u25cf{sipka} teď, {cidlo}, "
                      + ("otevřeno" if otevreno else "zavřeno"))

    if rucni_min:
        radky.append(f"Sáhl jsi na okno, automatika mlčí ještě "
                     f"{rucni_min} min. Teplota do toho teď nemluví.")
    elif otevreno and chladi:
        radky.append(f"Otevřeno: {duvod}. " if duvod else "Otevřeno. "
                     + f"Chladím, zavřu na {cil - zavrit:.1f} °C.")
    elif otevreno and ohrivam:
        radky.append((f"Otevřeno: {duvod}. " if duvod else "Otevřeno. ")
                     + f"Ohřívám, zavřu na {cil + zavrit:.1f} °C.")
    elif otevreno and (spanek or noc):
        radky.append(f"Ve spánku rozhoduje jen CO2; teplotu drží "
                     f"pojistky {mez_dolni:.1f} a {mez_horni:.1f} °C.")
    elif otevreno:
        radky.append(f"Větrá se kvůli vzduchu; teplotu drží pojistky "
                     f"{mez_dolni:.1f} a {mez_horni:.1f} °C.")
    else:
        veta = (f"Kvůli teplotě bych otevřel nad {horni:.1f} °C "
                f"(chlazení), nebo pod {dolni:.1f} °C (ohřev).")
        if brani_teplote:
            veta += f" Teď brání: {brani_teplote}."
        radky.append(veta)
    return radky
