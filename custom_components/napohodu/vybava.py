"""Co má v místnosti smysl — jedno místo, kam se chodí ptát.

Tutéž otázku si kladou tři různá místa: nastavení (na které pole se
vůbec ptát), platformy (kterou entitu zakládat) a úklid registru
(kterou entitu smazat, když už tam být nemá). Dokud měla každá svoje
vlastní podmínky, rozcházely se — šoupátko útlumu se zakládalo jen
s hlavicí, ale nastavení se na něj ptalo vždycky, a úklid o něm
nevěděl vůbec.

Pravidlo je jedno: **co v místnosti nemá význam, to nevzniká.** Ne
proto, že by to škodilo, ale protože prázdné šoupátko na dashboardu
i pole ve formuláři tvrdí, že se tím něco ovládá.

Pole pro přiřazení zařízení sem nepatří — ta musí být vidět vždycky,
jinak by nebylo jak zařízení přidat.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from . import const as c

# --- Vlastnosti místnosti ---------------------------------------------
#
# Jména jsou klíče slovníku, který vrací `vlastnosti()`. Používají se
# v tabulce níž i přímo v nastavení.

OKNA = "okna"            # řízené okno, kterým se dá hýbat
SKLO = "sklo"            # vůbec nějaké okno — stačí kontakt nebo žaluzie
ZALUZIE = "zaluzie"
ZVLHCOVAC = "zvlhcovac"
PRACH = "prach"
TOPENI = "topeni"
VETRA_SE = "vetra_se"    # vlastním oknem, nebo žádostí sousedovi


def vlastnosti(data: Mapping[str, Any] | None, v_zone: bool = False,
               vse: bool = False) -> dict[str, bool]:
    """Co místnost má. `vse` je pro zakládání, kdy ještě nemá nic.

    Při zakládání se musí ukázat všechno: data teprve vznikají, takže
    podle nich by se nezobrazilo nic a místnost by se nedala nastavit.
    """
    d = data or {}
    okna = vse or bool(d.get(c.CONF_OKNA))
    # Rozhoduje přiřazená žaluzie, ne mapa rolí: ta vzniká až o krok
    # dál, takže by se při zakládání nikdy nestihla.
    zaluzie = vse or bool(d.get(c.CONF_ZALUZIE))
    return {
        OKNA: okna,
        SKLO: okna or zaluzie or vse or bool(d.get(c.CONF_KONTAKT_M)),
        ZALUZIE: zaluzie,
        ZVLHCOVAC: vse or bool(d.get(c.CONF_ZVLHCOVAC)),
        PRACH: vse or bool(d.get(c.CONF_CISTICKA) or d.get(c.CONF_PM25)
                           or d.get(c.CONF_PM10)),
        TOPENI: vse or bool(d.get(c.CONF_CLIMATE)),
        # Místnost bez vlastního okna, ale v oblasti, si o vyvětrání
        # říká sousedovi — a kdy, to určují právě prahy CO2 a pásmo
        # kolem cíle. Vzít jí je by znamenalo vzít jí jediný způsob,
        # jak se vyjádřit.
        VETRA_SE: okna or v_zone or vse,
    }


def je_v_zone(podentity: Iterable[Any], pod_id: str | None) -> bool:
    """Patří místnost do nějaké oblasti? Hledá se podle identifikátoru,
    aby přejmenování místnosti odkaz nerozbilo."""
    if not pod_id:
        return False
    for pod in podentity:
        if pod.subentry_type != c.PODENTITA_ZONA:
            continue
        if pod_id in (pod.data.get(c.CONF_MISTNOSTI) or []):
            return True
    return False


def pro_mistnost(entry: Any, pod: Any) -> dict[str, bool]:
    """Vlastnosti místnosti tak, jak je vidí platforma."""
    return vlastnosti(pod.data,
                      je_v_zone(entry.subentries.values(), pod.subentry_id))


# --- Co na čem závisí -------------------------------------------------
#
# Klíč je zároveň identifikátor entity (u šoupátek je to klíč
# nastavení, entita z něj vzniká) a zároveň jméno pole v nastavení.
# Co v tabulce není, platí všude — stav místnosti, cíl, obsazenost.

POTREBUJE: dict[str, str] = {
    # Okna: časování pohonu a ruční klid patří k oknu, kterým se hýbe.
    c.CONF_PROJEZD_M: OKNA,
    c.CONF_MIN_DRZENI: OKNA,
    c.CONF_RUCNI_KLID: OKNA,
    "ovladat_okno": OKNA,
    "otevirat_i_pro_pohodu": OKNA,
    "otevrit_okno": OKNA,
    "zavrit_okno": OKNA,
    "srovnat_okno": OKNA,
    # Čidlo okna stačí ke kontaktu, ovládat okno netřeba.
    "okno": SKLO,
    "okno_otevreno": SKLO,
    # Dopad slunce na okna místnosti bez jediného okna nic neznamená.
    "slunce": SKLO,
    # Vzduch: prahy CO2 a pásmo kolem cíle platí i tam, kde se větrá
    # jen žádostí sousedovi.
    c.CONF_CO2_OTEVRIT: VETRA_SE,
    c.CONF_CO2_ZAVRIT: VETRA_SE,
    c.CONF_CO2_NOC: VETRA_SE,
    c.CONF_CO2_NOC_KRIZE: VETRA_SE,
    c.CONF_HYST_DEN_OTEVRIT: VETRA_SE,
    c.CONF_HYST_DEN_ZAVRIT: VETRA_SE,
    c.CONF_HYST_NOC_OTEVRIT: VETRA_SE,
    c.CONF_HYST_NOC_ZAVRIT: VETRA_SE,
    c.CONF_REZERVA_VENKU: VETRA_SE,
    c.CONF_CHLAZENI_MIN_VENKU: VETRA_SE,
    c.CONF_MEZ_DOLNI: VETRA_SE,
    c.CONF_MEZ_HORNI: VETRA_SE,
    # Prach: čistička nebo čidlo prachu.
    c.CONF_PM_SPATNE: PRACH,
    c.CONF_PM_CISTO: PRACH,
    c.CONF_CISTICKA_OD: PRACH,
    # Stínění.
    c.CONF_RUCNI_KLID_ZALUZIE: ZALUZIE,
    c.CONF_KLID_STINENI_MIN: ZALUZIE,
    c.CONF_STINENI_PREDSTIH: ZALUZIE,
    "ovladat_stineni": ZALUZIE,
    "srovnat_stineni": ZALUZIE,
    "stineni": ZALUZIE,
    # Zvlhčovač.
    c.CONF_RH_MIN: ZVLHCOVAC,
    c.CONF_RH_MAX: ZVLHCOVAC,
    "zvlhcovat_i_ve_spanku": ZVLHCOVAC,
    # Topení: bez hlavice je útlum šoupátko, kterým se nic nestane.
    c.CONF_UTLUM: TOPENI,
    c.CONF_NOC_POSUN: TOPENI,
    c.CONF_PRYC_UTLUM: TOPENI,
    c.CONF_PRYC_PO: TOPENI,
    "ovladat_topeni": TOPENI,
    "srovnat_topeni": TOPENI,
    "termostat": TOPENI,
}

# Tlačítka stínění nevznikají podle přiřazeného zařízení, ale podle
# toho, jestli role v mapě stínění vůbec na nějakou žaluzii míří.
PODLE_ROLE: dict[str, str] = {
    "zastinit": "zastinit",
    "odstinit": "odstinit",
    "soukromi": "soukromi",
    "stineni_pryc": "pryc",
    "stineni_vychozi": "vychozi",
}


def ma_vitr(g: Mapping[str, Any] | None) -> bool:
    """Je odkud brát vítr? Jiný zdroj než tahle dvě čidla není, takže
    bez nich nemá co hlásit čidlo přepočtené rychlosti ani co
    porovnávat prahy ve společném nastavení."""
    g = g or {}
    return bool(g.get(c.CONF_VITR) or g.get(c.CONF_NARAZ))


def ma_smysl(klic: str, v: dict[str, bool]) -> bool:
    """Má entita (nebo pole nastavení) toho klíče v místnosti význam?

    Co v tabulce není, platí všude — tím se nová entita nikdy
    nezatluče omylem, jen se na ni musí pamatovat při úklidu.
    """
    potreba = POTREBUJE.get(klic)
    return potreba is None or v.get(potreba, False)
