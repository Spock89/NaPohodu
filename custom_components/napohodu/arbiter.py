"""Arbitr místnosti.

Vlastní záměr — cílovou teplotu a kvalitu vzduchu — a rozhoduje, kterým
prostředkem ho naplnit. Prostředky mají různou cenu, takže se sahá po tom
nejlevnějším, který v dané situaci funguje.

    stínění  <  větrání  <  topení / chlazení

Nezná Home Assistant. Neovládá ventily ani nepočítá polohu žaluzií podle
azimutu — to dělají Better Thermostat a Adaptive Cover. Tenhle modul jen
říká, co má kdo dělat, a hlídá, aby si nelezli do cesty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

try:  # uvnitř Home Assistantu je to balíček, v testech samostatné moduly
    from . import core, pritomnost as pr, slunce as sl
except ImportError:  # pragma: no cover
    import core
    import pritomnost as pr
    import slunce as sl


class Stineni(Enum):
    OTEVRIT = "otevrit"      # pustit slunce dovnitř, chceme teplo
    ZASTINIT = "zastinit"    # bránit přehřívání
    NIC = "nic"              # nechat na Adaptive Cover


class Topeni(Enum):
    TOPIT = "topit"
    VYPNOUT = "vypnout"
    NIC = "nic"


class Chlazeni(Enum):
    CHLADIT = "chladit"
    VYPNOUT = "vypnout"
    NIC = "nic"


class Cisticka(Enum):
    ZAPNOUT = "zapnout"
    VYPNOUT = "vypnout"
    NIC = "nic"


class Odtah(Enum):
    ZAPNOUT = "zapnout"
    VYPNOUT = "vypnout"
    NIC = "nic"


@dataclass(frozen=True)
class Vybava:
    """Co místnost fyzicky má."""

    okno: bool = False
    topeni: bool = False
    chlazeni: bool = False
    stineni: bool = False
    cisticka: bool = False       # řeší prach, ne CO2
    odtah: bool = False          # odsává vlhkost


@dataclass(frozen=True)
class NastaveniMistnosti:
    stineni_pryc: pr.StineniPryc = pr.StineniPryc.NIC
    tolerance: float = 0.5        # pásmo kolem cíle, kde se nic nedělá
    utlum: float = 16.0           # teplota při otevřeném okně
    klid_po_topeni_s: float = 20 * 60
    klid_po_vetrani_s: float = 15 * 60
    solarni_zisk_min: float = 150.0   # W/m2, od kdy má odclonění smysl
    chlazeni_od: float = 1.5      # o kolik nad cílem se zapne chlazení
    rh_max: float = 60.0          # nad tím hrozí plíseň
    rh_min: float = 35.0          # pod tím vysychají sliznice


@dataclass
class StavMistnosti:
    """Vstupy nad rámec těch, které potřebuje větrání."""

    t_in: float = 21.0
    cil: float = 22.0
    obsazeno: bool = True
    doma: bool = True
    klid: bool = False           # spí se tu, šetři hlukem
    rh_in: float | None = None   # vnitřní vlhkost
    cas_s: float = 0.0

    # okna místnosti a poloha slunce; zisk se dopočítá
    okna: list[sl.Okno] = field(default_factory=list)
    azimut_slunce: float = 180.0
    elevace_slunce: float = -10.0
    jasno: float = 1.0

    @property
    def slunce_na_okno(self) -> float:
        return sl.zisk_mistnosti(self.okna, self.azimut_slunce,
                                 self.elevace_slunce, self.jasno)

    def osvicena_okna(self, prah: float) -> list[sl.Okno]:
        return sl.okna_na_slunci(self.okna, self.azimut_slunce,
                                 self.elevace_slunce, prah, self.jasno)


@dataclass
class PametMistnosti:
    topilo_do_s: float = -1e9
    vetralo_do_s: float = -1e9


@dataclass
class Zamer:
    """Co se má stát. Každý prostředek zvlášť, aby šly řídit nezávisle."""

    okno: core.Akce = core.Akce.NIC
    okno_duvod: str = ""
    okno_limit_s: float | None = None

    topeni: Topeni = Topeni.NIC
    topeni_cil: float | None = None

    chlazeni: Chlazeni = Chlazeni.NIC
    stineni: Stineni = Stineni.NIC
    cisticka: Cisticka = Cisticka.NIC
    odtah: Odtah = Odtah.NIC

    okno_otevreno: bool = False
    stinit_okna: list[str] = field(default_factory=list)
    duvod: str = ""
    poradi: list[str] = field(default_factory=list)


def rozhodni_mistnost(
    v: core.Vstup,
    s: StavMistnosti,
    pv: core.Pamet,
    pm: PametMistnosti,
    vybava: Vybava,
    nv: core.Nastaveni = core.Nastaveni(),
    nm: NastaveniMistnosti = NastaveniMistnosti(),
) -> Zamer:
    """Vrátí záměr pro všechny prostředky místnosti."""

    z = Zamer()

    # ---------------------------------------------------------- 1. vzduch
    # Kvalita vzduchu má přednost před teplotou. To je rozhodnutí, které
    # jsme udělali hned na začátku a platí i tady.
    if vybava.okno:
        r = core.rozhodni(v, pv, nv)
        z.okno = r.akce
        z.okno_duvod = r.duvod
        z.okno_limit_s = r.limit_s
        if r.akce is core.Akce.OTEVRIT:
            pm.vetralo_do_s = s.cas_s
        z.poradi.append(f"vzduch: {r.duvod}")

    z.okno_otevreno = pv.otevreno

    # ---------------------------------------------------------- 2. topení
    # Otevřené okno vypíná topení vždycky. Tohle je jediné tvrdé pravidlo
    # mezi prostředky a existuje proto, aby se netopilo ven.
    if vybava.topeni:
        if z.okno_otevreno:
            z.topeni = Topeni.VYPNOUT
            z.topeni_cil = nm.utlum
            z.poradi.append("topení: vypnuto, otevřené okno")
        elif not s.obsazeno:
            z.topeni = Topeni.NIC
            z.poradi.append("topení: prázdná místnost, nechávám na útlumu")
        else:
            z.topeni = Topeni.TOPIT
            z.topeni_cil = s.cil
            z.poradi.append(f"topení: cíl {s.cil:.1f} °C")

    odchylka = s.t_in - s.cil
    zima = odchylka < -nm.tolerance
    horko = odchylka > nm.tolerance

    # ---------------------------------------------------------- 3. stínění
    # Nejlevnější prostředek, takže se řeší dřív než topení a chlazení.
    if vybava.stineni and not s.doma:
        # prázdný byt: pevné chování podle nastavení, slunce se neřeší
        if nm.stineni_pryc is pr.StineniPryc.ROZTAHNOUT:
            z.stineni = Stineni.OTEVRIT
            z.poradi.append("stínění: roztáhnout, nikdo doma")
        elif nm.stineni_pryc is pr.StineniPryc.ZATAHNOUT:
            z.stineni = Stineni.ZASTINIT
            z.poradi.append("stínění: zatáhnout, nikdo doma")
        else:
            z.stineni = Stineni.NIC
    elif vybava.stineni:
        osvicena = s.osvicena_okna(nm.solarni_zisk_min)
        z.stinit_okna = [o.nazev for o in osvicena]
        zisk = s.slunce_na_okno
        if not osvicena:
            z.stineni = Stineni.NIC
        elif horko:
            z.stineni = Stineni.ZASTINIT
            z.poradi.append(f"stínění: zastínit {', '.join(z.stinit_okna)}"
                            f" ({zisk:.0f} W/m2)")
        elif zima:
            z.stineni = Stineni.OTEVRIT
            z.poradi.append(f"stínění: odclonit {', '.join(z.stinit_okna)},"
                            f" slunce hřeje zadarmo ({zisk:.0f} W/m2)")
        else:
            z.stineni = Stineni.NIC

    # ---------------------------------------------------------- 4. chlazení
    # Poslední možnost. Nesmí běžet s otevřeným oknem ani hned po topení,
    # a nesmí nastoupit dřív, než se zkusí zastínit a vyvětrat.
    if vybava.chlazeni:
        if z.okno_otevreno:
            z.chlazeni = Chlazeni.VYPNOUT
            z.poradi.append("chlazení: vypnuto, otevřené okno")
        elif s.cas_s - pm.topilo_do_s < nm.klid_po_topeni_s:
            z.chlazeni = Chlazeni.NIC
            z.poradi.append("chlazení: klid po topení")
        elif odchylka > nm.chlazeni_od and s.obsazeno:
            venku_chladneji = v.t_out < s.t_in - 1
            if venku_chladneji and vybava.okno:
                z.chlazeni = Chlazeni.VYPNOUT
                z.poradi.append("chlazení: nechávám na větrání, venku je chladněji")
            else:
                z.chlazeni = Chlazeni.CHLADIT
                z.poradi.append(f"chlazení: {odchylka:+.1f} °C nad cílem")
        else:
            z.chlazeni = Chlazeni.VYPNOUT

    if z.topeni is Topeni.TOPIT and zima:
        pm.topilo_do_s = s.cas_s

    # ---------------------------------------------------------- 5. čistička
    # Prach umí vyřešit bez chladu a bez hluku okna. V zimě a v noci je
    # to jednoznačně lepší volba než otevřít.
    if vybava.cisticka:
        prasi = v.pm25 > 35 or v.pm10 > 50
        if prasi and s.obsazeno:
            z.cisticka = Cisticka.ZAPNOUT
            z.poradi.append(f"čistička: prach {v.pm25:.0f}")
        elif v.pm25 < 20:
            z.cisticka = Cisticka.VYPNOUT

    # ---------------------------------------------------------- 6. odtah
    # Vlhkost se odsává, dokud to venku dává smysl. Když je venku vlhčeji
    # než uvnitř, okno by situaci zhoršilo, ventilátor pomůže vždycky.
    if vybava.odtah and s.rh_in is not None:
        if s.rh_in > nm.rh_max:
            z.odtah = Odtah.ZAPNOUT
            z.poradi.append(f"odtah: vlhkost {s.rh_in:.0f} %")
        elif s.rh_in < nm.rh_max - 5:
            z.odtah = Odtah.VYPNOUT

    z.duvod = z.poradi[0] if z.poradi else "nic k řešení"
    return z
