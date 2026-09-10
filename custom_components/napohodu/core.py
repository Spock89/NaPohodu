"""Rozhodovací jádro chytrého větrání.

Čistý Python bez závislosti na Home Assistantu, aby šlo testovat samostatně.
Logika je přenesená z odladěného Node-RED flow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------- konstanty

KVALITA_STUPNE = [
    "extremely_poor",
    "very_poor",
    "poor",
    "moderate",
    "fair",
    "good",
]

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

    denni_pokles: float = 1.5
    nocni_pokles_zaklad: float = 3.0
    nocni_pokles: float = 3.0
    nocni_rezerva: float = 1.0
    nocni_min: float = 18.0
    krize_pod_mez: float = 1.5

    noc_od: float = 22.0
    noc_do: float = 6.5

    korekce_k: float = 0.08
    korekce_max: float = 1.5

    rozpocet_stupnominut: float = 200.0


@dataclass
class Vstup:
    """Naměřený stav v jednom okamžiku."""

    co2: float = 500.0
    pm25: float = 0.0
    pm10: float = 0.0
    pm_platny: bool = True
    kvalita: str | None = None

    t_in: float = 21.0          # nejchladnější místo — kondenzace, topení
    t_in_max: float | None = None   # nejteplejší místo — přehřívání, chlazení
    t_out: float = 15.0
    rh_out: float = 50.0
    cil: float = 22.0

    dest: float = 0.0
    vitr_blokuje: bool = False
    smog: bool = False
    doma: bool = True
    spanek: bool = False
    vetrat: bool = False
    vynuceno: bool = False

    hodina: float = 12.0
    cas_s: float = 0.0

    # větrá za nás jiná zóna, takže se sami otevřeme až při krizi
    zastupce: bool = False


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
    den_mez: float | None = None
    pohyby: int = 0


@dataclass
class Rozhodnuti:
    akce: Akce
    duvod: str
    limit_s: float | None = None
    t_in_korig: float = 0.0
    korekce: float = 0.0
    rosny_bod: float = 0.0
    co2: float = 0.0


# ---------------------------------------------------------------- pomocné


def rosny_bod(t: float, rh: float) -> float:
    """Magnusův vzorec. Vlhkost se ořízne, aby logaritmus nespadl."""
    rh = min(100.0, max(1.0, rh))
    g = (MAGNUS_A * t) / (MAGNUS_B + t) + math.log(rh / 100.0)
    return (MAGNUS_B * g) / (MAGNUS_A - g)


def cil_adaptivni(prumer_venku: float, posun: float = 0.0,
                  dolni: float = 20.0, horni: float = 27.0) -> float:
    """Adaptivní komfortní teplota podle EN 16798-1."""
    return round(min(max(0.33 * prumer_venku + 18.8 + posun, dolni), horni), 1)


def _kvalita_rank(kvalita: str | None) -> int | None:
    if not kvalita:
        return None
    k = str(kvalita).strip().lower().replace(" ", "_")
    return KVALITA_STUPNE.index(k) if k in KVALITA_STUPNE else None


def _je_noc(hodina: float, n: Nastaveni, spanek: bool) -> bool:
    if spanek:
        return True
    if n.noc_od > n.noc_do:          # přes půlnoc
        return hodina >= n.noc_od or hodina < n.noc_do
    return n.noc_od <= hodina < n.noc_do


# ---------------------------------------------------------------- jádro


def z_priority(priorita: float) -> tuple[float, float]:
    """Jeden posuvník místo dvou čísel.

    Nula znamená držet teplo za každou cenu, deset vyvětrat za každou
    cenu. Pětka odpovídá výchozím hodnotám, se kterými jsme to ladili.
    Vrací povolený denní a noční pokles teploty ve stupních.
    """
    p = max(0.0, min(10.0, priorita))
    return (0.5 + p * 0.25, 1.0 + p * 0.4)


def duvody(v: Vstup, p: Pamet, n: Nastaveni = Nastaveni()) -> list[str]:
    """Vyjmenuje všechno, co právě brání větrání.

    Popisek pod rozhodnutím ukáže jen ten první důvod, takže se snadno
    stane, že člověk jednu překážku odstraní a nic se nezmění. Tohle
    ukáže celý seznam.
    """
    seznam = []
    if v.vitr_blokuje:
        seznam.append("vítr")
    if v.dest > n.dest_prah:
        seznam.append(f"déšť {v.dest:.1f}")
    if not v.doma:
        seznam.append("nikdo doma")

    korekce = 0.0
    if p.otevreno:
        korekce = max(-n.korekce_max,
                      min(n.korekce_max, n.korekce_k * (v.t_in - v.t_out)))
    tin = v.t_in + korekce
    noc = _je_noc(v.hodina, n, v.spanek)

    if noc:
        seznam.append("noční klid")
        if v.zastupce:
            seznam.append("větrá za nás soused")
        if tin <= n.nocni_min + n.nocni_rezerva:
            seznam.append(f"pod noční mezí {n.nocni_min:.1f} °C")
        if n.noc_do <= v.hodina < 9:
            seznam.append("ranní klid")
        prah = n.co2_noc
    else:
        prah = n.co2_zavrit if p.vetra_se else n.co2_otevrit

    if v.co2 <= prah:
        seznam.append(f"CO2 {v.co2:.0f} pod prahem {prah:.0f}")
    if rosny_bod(v.t_out, v.rh_out) > tin - 2:
        seznam.append("rosný bod")
    if v.smog:
        seznam.append("smog venku")
    if v.cas_s - p.cas_povelu_s < n.min_drzeni_s:
        zbyva = int((n.min_drzeni_s - (v.cas_s - p.cas_povelu_s)) / 60)
        seznam.append(f"drží se stav ještě {zbyva} min")

    return seznam


def rozhodni(v: Vstup, p: Pamet, n: Nastaveni = Nastaveni()) -> Rozhodnuti:
    """Vrátí, co se má s oknem stát. Paměť se upravuje na místě."""

    # korekce čidla: při otevřeném okně táhne k venkovní teplotě
    korekce = 0.0
    if p.otevreno:
        korekce = max(-n.korekce_max,
                      min(n.korekce_max, n.korekce_k * (v.t_in - v.t_out)))
    t_in = v.t_in + korekce
    # V zimě rozhoduje nejchladnější čidlo (kondenzace, topení), v horku
    # naopak nejteplejší — nechceme pouštět vedro do přehřáté místnosti.
    t_max = (v.t_in_max if v.t_in_max is not None else v.t_in) + korekce
    dew = rosny_bod(v.t_out, v.rh_out)

    def hotovo(akce: Akce, duvod: str, limit_s: float | None = None) -> Rozhodnuti:
        return Rozhodnuti(akce, duvod, limit_s, round(t_in, 2),
                          round(korekce, 2), round(dew, 1), v.co2)

    def otevri(duvod: str, limit_s: float | None, *, hned: bool = False) -> Rozhodnuti:
        return _povel(True, duvod, limit_s, hned)

    def zavri(duvod: str, *, hned: bool = False) -> Rozhodnuti:
        return _povel(False, duvod, None, hned)

    def _povel(chci_otevreno: bool, duvod: str,
               limit_s: float | None, hned: bool) -> Rozhodnuti:
        limit = n.projezd_s if hned else max(n.projezd_s, n.min_drzeni_s)
        if v.cas_s - p.cas_povelu_s < limit:
            zbyva = int(limit - (v.cas_s - p.cas_povelu_s))
            chci = "otevřít" if chci_otevreno else "zavřít"
            if zbyva >= 60:
                kolik = f"{zbyva // 60} min"
            else:
                kolik = f"{zbyva} s"
            return hotovo(Akce.NIC, f"chci {chci}, držím stav ještě {kolik}")
        p.otevreno = chci_otevreno
        p.cas_povelu_s = v.cas_s
        p.pohyby += 1
        return hotovo(Akce.OTEVRIT if chci_otevreno else Akce.ZAVRIT,
                      duvod, limit_s)

    def beze_zmeny(duvod: str, chci_otevreno: bool | None = None) -> Rozhodnuti:
        # obnova povelu, kdyby se stav rozešel se skutečností (ne v noci)
        if (chci_otevreno is not None
                and not _je_noc(v.hodina, n, v.spanek)
                and v.cas_s - p.cas_povelu_s > n.obnova_s):
            p.cas_povelu_s = v.cas_s
            return hotovo(Akce.OTEVRIT if chci_otevreno else Akce.ZAVRIT,
                          "obnova povelu")
        return hotovo(Akce.NIC, duvod)

    # --- 1. vítr ---------------------------------------------------
    if v.vitr_blokuje:
        if not p.otevreno:
            return beze_zmeny("vítr, zavřeno", False)
        p.rezim = "pulz"
        return zavri("zavírám kvůli větru", hned=True)

    # --- 1b. déšť ---------------------------------------------------
    # Ochrana bytu stojí nad ručním rozhodnutím stejně jako vítr.
    if v.dest > n.dest_prah:
        if not p.otevreno:
            return beze_zmeny("prší, zavřeno", False)
        p.rezim = "pulz"
        return zavri(f"zavírám kvůli dešti ({v.dest:.1f})", hned=True)

    # --- 2. nikdo doma ---------------------------------------------
    if not v.doma:
        if not p.otevreno:
            return beze_zmeny("nikdo doma")
        p.rezim = "pulz"
        return zavri("nikdo není doma", hned=True)

    # --- 3. ruční otevření -----------------------------------------
    if v.vynuceno:
        if p.otevreno:
            return beze_zmeny("ručně otevřeno", True)
        return otevri("ručně otevřeno", None, hned=True)

    # --- 4. vzduch --------------------------------------------------
    rank = _kvalita_rank(v.kvalita)
    kvalita_spatna = rank is not None and rank <= 2
    kvalita_ok = rank is None or rank >= 4

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

    pm_cisto = (not pm_spatne
                and (not v.pm_platny
                     or (v.pm25 < n.pm_prah_cisto and v.pm10 < 30)))

    if v.co2 > n.co2_otevrit:
        p.vetra_se = True
    if v.co2 < n.co2_zavrit:
        p.vetra_se = False
    prah_startu = n.co2_zavrit if p.vetra_se else n.co2_otevrit

    potreba = (v.co2 > prah_startu or v.vetrat or kvalita_spatna or pm_spatne)
    cisto = (v.co2 < n.co2_zavrit and not v.vetrat and kvalita_ok and pm_cisto)

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
    elif not chlazeni and noc:
        brani = "noční klid"
    elif t_max > v.cil and v.t_out > t_max:
        brani = "venku tepleji než uvnitř"
    elif not chlazeni and t_in < v.cil - 0.5 and v.t_out < t_in:
        # když se zároveň někde přehřívá, chlazení má přednost
        brani = f"uvnitř {t_in:.1f} °C, pod cílem"

    if not brani:
        p.rezim = "komfort"
        if p.otevreno:
            return beze_zmeny("chladím" if chlazeni else "komfort", True)
        return otevri("chlazení větráním" if chlazeni else "komfortní režim", None)

    if p.rezim == "komfort":
        p.rezim = "pulz"
        if not potreba:
            return zavri(f"konec komfortu: {brani}")

    # --- 6. noční režim ---------------------------------------------
    if noc:
        rano = n.noc_do <= v.hodina < 9
        krize = v.co2 > n.co2_noc_krize
        # Když za nás větrá soused, sami se v noci otevřeme až při krizi.
        # Lepší pomalejší výměna přes dveře než průvan nad postelí.
        prah_noc = n.co2_noc_krize if v.zastupce else n.co2_noc
        mez = (p.noc_mez if p.noc_mez is not None
               else max(n.nocni_min, t_in - n.nocni_pokles))

        if p.otevreno:
            if t_in <= mez:
                return zavri(f"noc: kleslo na {t_in:.1f} °C")
            return beze_zmeny(f"noc: větrá {t_in:.1f} °C, CO2 {v.co2:.0f}", True)

        if v.co2 > prah_noc or pm_spatne or kvalita_spatna or v.vetrat:
            if krize and t_in > n.nocni_min - n.krize_pod_mez:
                p.noc_mez = n.nocni_min - n.krize_pod_mez
                p.noc_krize = True
                return otevri("noc: nouzové větrání", 12 * 60)
            if rano:
                return beze_zmeny(f"noc: ranní ruch, neotvírám (CO2 {v.co2:.0f})")
            if t_in <= n.nocni_min + n.nocni_rezerva:
                return beze_zmeny(f"noc: dusno, ale jen {t_in:.1f} °C")
            p.noc_mez = max(n.nocni_min, t_in - n.nocni_pokles)
            p.noc_krize = False
            return otevri(f"noc: otevírám do {p.noc_mez:.1f} °C", 4 * 3600)
        return beze_zmeny(f"noc: klid, CO2 {v.co2:.0f}", False)

    p.noc_mez = None

    # --- 7. spánek nebo vyvětráno ------------------------------------
    if cisto:
        if not p.otevreno:
            return beze_zmeny(f"čisto, CO2 {v.co2:.0f}", False)
        p.den_mez = None
        return zavri(f"vyvětráno, CO2 {v.co2:.0f}")

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

        p.rezim = "pulz"
        p.den_mez = max(n.nocni_min + 1, t_in - n.denni_pokles)
        duvod = f"CO2 {v.co2:.0f}"
        if kvalita_spatna:
            duvod = f"kvalita {v.kvalita}"
        if pm_spatne:
            duvod = f"PM2.5 {v.pm25:.0f}" + ("" if v.pm_platny else " (bez ventilátoru)")
        return otevri(duvod, min(max(minuty, 30), 120) * 60)

    return beze_zmeny(f"mrtvá zóna, CO2 {v.co2:.0f}")
