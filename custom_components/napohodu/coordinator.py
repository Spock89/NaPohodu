"""Koordinátor — přečte čidla, spočítá rozhodnutí, nabídne výsledek entitám.

Zatím nic neovládá. Povel na okno se pošle až po zapnutí přepínače
„Ovládat okno", který je ve výchozím stavu vypnutý. Do té doby integrace
jen ukazuje, co by udělala.
"""

from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

try:      # dateutil je v Home Assistantu běžně k dispozici
    from dateutil.rrule import rrulestr
except ImportError:      # pragma: no cover - bez něj se jen neopakuje
    rrulestr = None

from .number import MISTNOST as POSUVNIKY_MISTNOSTI
from . import (core, plan as pl, planovac as pz, pritomnost as pr,
               prumery as pm, slunce as sl, sousedstvi as so,
               vykon as vy, zpravy as zp, klima as kl)
from .const import (
    CONF_AZIMUT, CONF_CHLAZENI_MIN_VENKU, CONF_CIL_MAX, CONF_CIL_MIN,
    CONF_CISTICKA, CONF_CISTICKA_OD, CONF_CLIMATE, CONF_CO2, CONF_CO2_NOC,
    CONF_CO2_NOC_KRIZE, CONF_CO2_OTEVRIT, CONF_CO2_ZAVRIT, CONF_DEST,
    CONF_DEST_PRAH, CONF_DOBEH, CONF_DOMA, CONF_DVERE,
    CONF_HYST_DEN_OTEVRIT, CONF_HYST_DEN_ZAVRIT, CONF_HYST_NOC_OTEVRIT,
    CONF_HYST_NOC_ZAVRIT, CONF_INDICIE_DOBEH, CONF_INDICIE_STAV,
    CONF_INDICIE_VYKON, CONF_I_KDYZ_NIKDO, CONF_KLID_STINENI_MIN,
    CONF_KLIMA_CHLADIT_OD, CONF_KLIMA_DLOUHA, CONF_KLIMA_DLOUHA_H,
    CONF_KLIMA_ENTITA, CONF_KLIMA_POKOJE, CONF_KLIMA_SUSIT_OD,
    CONF_KLIMA_TOPIT_OD, CONF_KLIMA_UMI, CONF_KLIMA_UTLUM_CHLAZENI,
    CONF_KLIMA_UTLUM_TOPENI, CONF_KLIMA_V_POKOJI, CONF_KONTAKT_M,
    CONF_MAX_STARI, CONF_MEZ_DOLNI, CONF_MEZ_HORNI, CONF_MIN_DRZENI,
    CONF_MISTNOSTI, CONF_NARAZ, CONF_NARAZOVE, CONF_NARAZOVE_ODSTUP,
    CONF_NARAZ_PRAH, CONF_NAZEV, CONF_NEJDRIV_ZNOVU, CONF_NOC_DO,
    CONF_NOC_OD, CONF_NOC_POSUN, CONF_NOC_PREDSTIH,
    CONF_OCHOTA, CONF_ODCHYLKA, CONF_ODVZDUSNENI_H, CONF_ODVZDUSNENI_T,
    CONF_OKNA, CONF_PM10, CONF_PM10_VENKU, CONF_PM25, CONF_PM25_VENKU,
    CONF_PLAN_NIKDO, CONF_PLAN_OBSAZENO, CONF_PLAN_PRAZDNO,
    CONF_PLAN_VIC, CONF_PM_CISTO, CONF_PM_PLATNY, CONF_PM_SPATNE,
    CONF_PLAN_CIL, CONF_PLAN_KOLIKRAT,
    CONF_PRACH_DOSAH, CONF_PREDVETRAT,
    CONF_PRACH_MISTNOSTI, CONF_PRAH_VYKONU, CONF_PRITOMNOST,
    CONF_PROJEZD_M, CONF_PRO_POHODU, CONF_PRYC_PO, CONF_PRYC_UTLUM,
    CONF_REZERVA_VENKU, CONF_RH_MAX, CONF_RH_MIN, CONF_RH_VENKU,
    CONF_RH_VENKU_M, CONF_RH_VNITRNI, CONF_RUCNI_KLID,
    CONF_RUCNI_KLID_ZALUZIE,
    CONF_SEZONA_HYSTEREZE, CONF_SEZONA_PRAH, CONF_SEZONA_REZIM,
    CONF_SEZONU_RIDI_HLAVICE, CONF_SMOG, CONF_SOUHRN_CAS,
    CONF_SKUPINA_MISTNOSTI, CONF_SOUKROMI_KDY, CONF_SOUSEDI, CONF_SPANEK,
    CONF_STINENI_CHOVANI,
    CONF_STINENI_MAPA, CONF_STINENI_PREDSTIH, CONF_STINENI_PRYC,
    CONF_STINENI_REZIM, CONF_TEPLOTY, CONF_TOPENI_OBNOVA,
    CONF_TOPIT_PRI_OKNU, CONF_T_PRUMER, CONF_T_SEZONA, CONF_T_VENKU,
    CONF_T_VENKU_M, CONF_UTLUM, CONF_VETRAT, CONF_VITR, CONF_VITR_KLID,
    CONF_VITR_PRAH, CONF_VLHKOST_DOSAH, CONF_VLHKOST_MISTNOSTI,
    CONF_VYCHOZI_KDY, CONF_VYNUCENO_M, CONF_ZALUZIE,
    CONF_ZARENI, CONF_ZASKLENI, CONF_ZDROJ_OBSAZENOSTI, CONF_ZIMA_NAJEZD,
    CONF_ZIMA_O_KOLIK, CONF_ZIMA_PRAH, CONF_ZMENA_PODMINEK,
    CONF_ZNACKA_MIMO, CONF_ZNACKA_OKNO, CONF_ZPRAVY, CONF_ZPRAVY_DRUHY,
    CONF_ZVLHCOVAC, CONF_ZVLHCOVAC_KDY, CONF_ZVLHCOVAC_VE_SPANKU, DOMAIN,
    INTERVAL_S, PODENTITA_KLIMA, PODENTITA_MISTNOST,
    PODENTITA_SKUPINA, PODENTITA_ZONA, ZASKLENI_PODIL,
)

_LOGGER = logging.getLogger(__name__)

NEPLATNE = ("unknown", "unavailable", "none", "")


@dataclass
class VysledekZony:
    """Co koordinátor spočítal pro jednu oblast.

    Oblast sama nic neovládá. Jen sdílí vzduch mezi místnostmi a řeší
    zastupování v noci, aby se v ložnici nemuselo otevírat.
    """

    nazev: str
    mistnosti: list[str] = field(default_factory=list)
    atributy: dict = field(default_factory=dict)


@dataclass
class VysledekMistnosti:
    nazev: str
    rozhodnuti: core.Rozhodnuti | None = None
    cil: float = 22.0
    obsazeno: bool = True
    klid: bool = False
    okno_otevreno: bool = False
    slunce: float = 0.0
    # dva samostatné povely z plánu: držet okno zavřené a utlumit
    plan_zavreno: bool = False
    plan_prazdno: bool = False
    plan_prazdno_do_s: float | None = None
    atributy: dict = field(default_factory=dict)


class NaPohoduCoordinator(DataUpdateCoordinator):
    """Jediné místo, které čte stav Home Assistantu."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(seconds=INTERVAL_S),
        )
        self.entry = entry
        # ladicí hodnoty z posuvníků; klíč je (id_podentity, jméno)
        self.hodnoty: dict[tuple[str, str], float] = {}
        # paměť rozhodovacího jádra, jedna na zónu
        self.pameti: dict[str, core.Pamet] = {}
        self.zony: dict[str, VysledekZony] = {}
        self.topna_sezona: bool = True
        self.vitr_blokuje: bool = False
        # hodnoty, které blokaci spustily — zpráva má říkat pravdu,
        # ne aktuální stav, který už může být jiný
        self.vitr_pricina: dict = {}
        self.vitr_stav: dict = {}
        self.klimy: dict[str, dict] = {}
        self._klima_pamet: dict[str, kl.Pamet] = {}
        self._prazdno_od: float | None = None
        self._sezona_od: float | None = None
        self._overene_jednotky: set[str] = set()
        self.narazove: bool = False
        self.narazove_bezi: bool = False
        # jak daleko je venku od cíle a která místnost o tom rozhodla
        self.narazove_rozdil: float = 0.0
        self.narazove_kdo: str = ""
        self.narazove_co2: float = 0.0
        self.narazove_pm: float = 0.0
        # co říká plán obsazenosti; přepočítává se každý cyklus
        self.plan_nikdo = pl.Udalost()
        self.plan_vic = pl.Udalost()
        self.plan_popis: str | None = None
        self.predvetrat: bool = False
        self.plan_pryc: bool = False
        self.plan_zavrit_byt: bool = False
        # co z plánu platilo při poslední obnově, ať se hlásí
        # jen změny, a na které záznamy se už chyba hlásila
        self._plan_bezelo: dict[str, list[str]] = {}
        self._plan_chyby: set[str] = set()
        self._plan_zpravy_prvni: bool = True
        # výsledek posledního stisku tlačítka Naplánovat
        self.plan_vysledek: str = "zatím nic"
        # co je navolené na dashboardu pro tlačítko Naplánovat
        self.plan_volba: str | None = None
        self.plan_od = None
        self.plan_do = None
        self.plan_opakovani: str = "jednou"
        # Vlastní kalendář plánu. Význam události je v záznamu, ne
        # v názvu, takže ho nejde pokazit překlepem.
        self._vlastni_plan: list[dict] = []
        # Poslední viděné hodnoty z formuláře. Musí přežít znovunačtení
        # integrace, protože uložení formuláře ho spustí — jinak by se
        # změna nikdy nepoznala a šoupátko by po restartu vyhrálo.
        self._formular: dict[tuple, float] = {}
        # klíče, které formulář v tomhle běhu přepsal
        self._prepsano: set[tuple] = set()
        self._posledni_snimek: dict | None = None
        # kdy integrace naběhla — hned po startu se nic neohlašuje
        self._start_s: float = dt_util.utcnow().timestamp()
        self.doma_popis: str = ""
        self.cil_rozpad: list[str] = []
        self._konflikt_hlasen: dict = {}
        self._t_out_posledni: float | None = None
        # místnosti, kde právě běží zvlhčovač a prach z něj se nemá
        # brát jako prach ve vzduchu
        self.zvlhcuje: set = set()
        # skutečný stav okna v každé místnosti; None znamená, že o něm
        # nevíme nic — ani kontakt, ani ovládané okno
        self.okna_stav: dict[str, bool | None] = {}
        # Teplota místnosti před pěti minutami, ať je ve stupnici vidět,
        # kam se hýbe. Kratší odstup by blikal, protože menší posun než
        # desetina je šum čidla.
        self._t_in_drive: dict[str, tuple[float, float]] = {}
        # popis okruhů z posledního cyklu, kvůli dosahu „v jeho zóně"
        self._okruhy_popis: list[dict] = []
        # žádosti o chlazení a ohřev od místností bez vlastního okna;
        # drží se mezi cykly, aby měly hysterezi jako každé jiné větrání
        self._cizi_zadost: dict[str, str] = {}
        # doznívání aerosolu po vypnutí zvlhčovače: kdy přestal
        self._dozvuk: dict[str, float] = {}
        # kdy někdo naposledy přestavil žaluzie rukou. Po tu dobu se
        # s nimi nehýbe, stejně jako u okna po ručním zásahu.
        self._zaluzie_rukou: dict[str, float] = {}
        # poslední naměřený prach místnosti, kvůli ukončení doznívání
        self._pm_syrovy: dict[str, float] = {}
        self._je_noc_ted: bool = False
        self._rh_out_posledni: float | None = None
        self._hodina_ted: float = 12.0
        self._noc_od: float = 22.0
        self._noc_do: float = 6.5
        # denní souhrn: podle něj se pozná, jestli jsou prahy dobře
        self.souhrn: dict[str, dict] = {}
        self._souhrn_den: str = ""
        self.hlasic = zp.Hlasic()
        self._souhrn_odeslan: str = ""
        # průměry si počítáme sami, ať uživatel nemusí zakládat statistiky
        self.prumery = pm.Prumery()
        # hodnoty, se kterými se opravdu počítá, a odkud pocházejí
        self.pouzity: dict[str, tuple[float | None, str]] = {
            "tyden": (None, "pocitano"), "tri_dny": (None, "pocitano")}
        self.vykonavaci: dict[str, vy.Vykonavac] = {}
        self._uloziste = Store(hass, 1, f"{DOMAIN}.prumery")
        # Bez tohohle by se po každém znovunačtení integrace žaluzie
        # rozjely znovu do stejné polohy. Zarachotí a nikdo neví proč.
        self._uloziste_stineni = Store(hass, 1, f"{DOMAIN}.stineni_pamet")
        # Bez tohohle se po restartu zapomene rozdělané větrání, doba
        # držení stavu i běžící pulz — okno by se mohlo hned rozjet.
        self._uloziste_pameti = Store(hass, 1, f"{DOMAIN}.pameti")
        self._uloziste_planu = Store(hass, 1, f"{DOMAIN}.plan")
        self.mistnosti: dict[str, VysledekMistnosti] = {}

    def vynuluj_stavy(self) -> None:
        """Zapomene vnitřní stavy rozhodování, nic uživatelského.

        Mění se jen to, co si jádro pamatuje mezi cykly: rozdělané
        větrání, čekání po marném pokusu, zapamatované meze a počítadla.
        Nastavení, posuvníky ani naučené průměry se nedotkne, jinak by
        tlačítko bylo nebezpečné.
        """
        for pamet in self.pameti.values():
            cista = core.Pamet()
            # Všechno kromě skutečného stavu okna. Čekání a odpočty
            # patří mezi vnitřní stavy — bez nich by „bod nula"
            # neznamenal nic, protože by se dál drželo držení polohy,
            # ruční klid i dojezd pulzu.
            for pole in vars(cista):
                if pole != "otevreno":
                    setattr(pamet, pole, getattr(cista, pole))
            # cas_povelu_s daleko v minulosti znamená, že žádné držení
            # neběží a další povel se smí poslat hned
            pamet.cas_povelu_s = -1e9
        # Stavy, které si koordinátor vede mimo paměť místností.
        # Žádost souseda i trend teploty patří mezi vnitřní stavy, takže
        # bez nich by „bod nula" nebyl nula.
        self._cizi_zadost.clear()
        self._t_in_drive.clear()
        self._zaluzie_rukou.clear()      # i ruční klid žaluzií
        # Nárazové větrání se drží mezi prahy, takže je to taky stav.
        self.narazove_bezi = False
        # Doznívání aerosolu je odpočet jako každý jiný. Mazal se jen
        # seznam běžících zvlhčovačů, takže po „bodu nula" zůstal pokoj
        # dál označený za zaprášený od zvlhčovače, který už neběžel.
        self._dozvuk.clear()
        self._pm_syrovy.clear()
        # Odpočet dlouhé nepřítomnosti a odstup mezi povely klimatizaci
        # jsou taky jen rozdělané mezičasy.
        self._prazdno_od = None
        self._klima_pamet.clear()
        for vyk in self.vykonavaci.values():
            vyk.stav.pulz_do_s = None          # dojezd pulzu
            vyk.stav.posledni_okna.clear()     # a odstup mezi povely
        self.zvlhcuje.clear()

    def srovnej(self, pod_id: str | None = None) -> None:
        """Zapomene poslední povely, takže se v dalším cyklu pošlou znovu.

        Bez pod_id platí pro všechno. Skutečné povely se pošlou jen tam,
        kde je zapnuté ovládání — tlačítko nic neobchází.
        """
        for klic, vyk in self.vykonavaci.items():
            if pod_id is None or klic == pod_id:
                vyk.zapomen()
                # Tlačítko je výslovný pokyn, takže ruší i ruční klid
                # žaluzií. Bez toho by stisk nic neudělal a nebylo by
                # poznat proč.
                self._zaluzie_rukou.pop(klic, None)

    def zaluzie_rukou(self, pod_id: str, cas_s: float) -> None:
        """Od teď se žaluziím místnosti chvíli nesahá.

        Používá to kontrola polohy i tlačítka rolí. Tlačítko je stejně
        vědomá volba jako ruka na ovladači, takže se po něm automatika
        drží zpátky úplně stejně — a hlavně se tím nespoléhá na to, že
        se stisk náhodou pozná jako ruční přestavení.
        """
        self._zaluzie_rukou[pod_id] = cas_s
        self._uloziste_stineni.async_delay_save(self._uloz_stineni, 10)

    async def async_nacti(self) -> None:
        """Obnoví průměry i polohy žaluzií, ať se nezačíná od nuly."""
        self.prumery = pm.Prumery.ze_slovniku(await self._uloziste.async_load())
        await self._nacti_pameti()
        await self._nacti_plan()
        ulozene = await self._uloziste_stineni.async_load() or {}
        for pod_id, data in ulozene.items():
            vyk = self.vykonavaci.setdefault(
                pod_id, vy.Vykonavac(self.hass, pod_id))
            vyk.stav.posledni_stineni.update(data.get("stavy") or {})
            vyk.stav.stineni_poloha.update(
                {k: float(x) for k, x in (data.get("polohy") or {}).items()})
            vyk.stav.stineni_tilt.update(
                {k: float(x)
                 for k, x in (data.get("naklopeni") or {}).items()})
            # Ruční klid žaluzií přežije restart. Člověk si polohu
            # nastavil pět minut předtím a restart není důvod mu do ní
            # sáhnout.
            if isinstance(data, dict) and data.get("rukou_s") is not None:
                self._zaluzie_rukou[pod_id] = float(data["rukou_s"])
            # polohy známe z disku, ochrana po startu už netřeba
            vyk.stav.prvni_beh = False

    def _uloz_pameti(self) -> dict:
        """Stav rozhodování, aby restart nezačínal od nuly."""
        out = {"_formular": {f"{a}|{b}": v
                             for (a, b), v in self._formular.items()},
               # Odeslaný souhrn musí přežít znovunačtení. Uložení
               # nastavení integraci restartuje a souhrn by přišel znovu.
               "_souhrn_odeslan": self._souhrn_odeslan}
        for pid, pamet in self.pameti.items():
            zaznam = asdict(pamet)
            vyk = self.vykonavaci.get(pid)
            if vyk is not None:
                zaznam["_pulz_do_s"] = vyk.stav.pulz_do_s
                zaznam["_topeni_cil"] = vyk.stav.topeni_cil
                zaznam["_topeni_rezim"] = vyk.stav.topeni_rezim
            out[pid] = zaznam
        # Běžící zvlhčovač a doznívání jeho aerosolu. Bez nich se po
        # restartu vzal prach za vzduch a okno se otevřelo kvůli tomu,
        # co se vyvětrat nedá.
        out["_zvlhcuje"] = sorted(self.zvlhcuje)
        out["_dozvuk"] = dict(self._dozvuk)
        return out

    async def _nacti_pameti(self) -> None:
        ulozene = await self._uloziste_pameti.async_load() or {}
        self._souhrn_odeslan = ulozene.pop("_souhrn_odeslan", "") or ""
        self.zvlhcuje = set(ulozene.pop("_zvlhcuje", None) or [])
        self._dozvuk = dict(ulozene.pop("_dozvuk", None) or {})
        # Restart je pro aerosol totéž co vypnutí: dokud prach neklesne
        # do čistého pásma, bere se pořád za zvlhčovačův. Skutečný stav
        # zařízení se doplní v prvním cyklu.
        ted = dt_util.utcnow().timestamp()
        for pid in self.zvlhcuje:
            self._dozvuk.setdefault(pid, ted)
        for klic, v in (ulozene.pop("_formular", None) or {}).items():
            a, _, b = klic.partition("|")
            self._formular[(a, b)] = v
        pole = {f.name for f in fields(core.Pamet)}
        for pid, zaznam in ulozene.items():
            pamet = core.Pamet(**{k: v for k, v in zaznam.items()
                                  if k in pole})
            self.pameti[pid] = pamet
            vyk = self.vykonavaci.setdefault(
                pid, vy.Vykonavac(self.hass, pid))
            vyk.stav.pulz_do_s = zaznam.get("_pulz_do_s")
            vyk.stav.topeni_cil = zaznam.get("_topeni_cil")
            vyk.stav.topeni_rezim = zaznam.get("_topeni_rezim")
        if ulozene:
            _LOGGER.debug("NaPohodu: obnoveno %d pamětí", len(ulozene))

    def _uloz_stineni(self) -> dict:
        # Ruční klid se ukládá taky, a proto se záznam zakládá i tam,
        # kde pojmenovaný stav není: ruční přestavení ten stav právě
        # zapomene, takže by se po restartu klid ztratil a žaluzie by
        # se hned po něm rozjely.
        out = {}
        for k, v in self.vykonavaci.items():
            rukou = self._zaluzie_rukou.get(k)
            if not v.stav.posledni_stineni and rukou is None:
                continue
            out[k] = {"stavy": dict(v.stav.posledni_stineni),
                      "polohy": dict(v.stav.stineni_poloha),
                      "naklopeni": dict(v.stav.stineni_tilt)}
            if rukou is not None:
                out[k]["rukou_s"] = rukou
        return out

    # ------------------------------------------------------------ čtení

    def _stav(self, eid: str | None) -> State | None:
        if not eid:
            return None
        st = self.hass.states.get(eid)
        if st is None or str(st.state).lower() in NEPLATNE:
            return None
        return st

    # na metry za sekundu; Home Assistant může senzor zobrazovat jinak,
    # než v čem hlásí hodnotu, a prahy jsou v m/s
    NA_MS = {
        "m/s": 1.0, "km/h": 1 / 3.6, "kph": 1 / 3.6, "mph": 0.44704,
        "kn": 0.514444, "kt": 0.514444, "ft/s": 0.3048,
    }

    def _zkontroluj_jednotku(self, eid: str | None, ocekavane: tuple,
                             popis: str) -> None:
        """Upozorní, když čidlo hlásí v jednotce, se kterou nepočítáme.

        Prahy jsou v konkrétních jednotkách a Home Assistant může senzor
        zobrazovat v jiné, než v jaké drží hodnotu. Tichý přepočet by byl
        hádání, takže se to aspoň napíše do protokolu.
        """
        if not eid or eid in self._overene_jednotky:
            return
        st = self._stav(eid)
        if st is None:
            return
        jednotka = (st.attributes.get("unit_of_measurement") or "").strip()
        self._overene_jednotky.add(eid)
        if jednotka and jednotka not in ocekavane:
            _LOGGER.warning(
                "NaPohodu: %s (%s) hlásí v %r, ale prahy jsou v %s — "
                "hodnoty nebudou odpovídat",
                popis, eid, jednotka, " nebo ".join(ocekavane))

    def _v_registru(self, eid: str) -> bool:
        """Existuje entita, i když zrovna nehlásí stav?

        Entita, která je v registru, existuje — jen ještě není
        načtená, nebo je dočasně nedostupná. Rozdíl mezi „není" a
        „zatím mlčí" se bez tohohle nedá udělat a upozornění na
        nenačtenou entitu je planý poplach.
        """
        try:
            return er.async_get(self.hass).async_get(eid) is not None
        except Exception:      # pragma: no cover - registr při startu
            return False

    def _rychlost(self, eid: str | None, nahrada: float = 0.0) -> float:
        """Rychlost větru v metrech za sekundu, ať čidlo hlásí cokoli."""
        st = self._stav(eid)
        if st is None:
            return nahrada
        try:
            hodnota = float(st.state)
        except (TypeError, ValueError):
            return nahrada
        jednotka = (st.attributes.get("unit_of_measurement") or "").strip()
        prevod = self.NA_MS.get(jednotka)
        if prevod is None:
            if jednotka:
                _LOGGER.warning(
                    "NaPohodu: neznámá jednotka rychlosti %r u %s, beru ji "
                    "jako m/s", jednotka, eid)
            return hodnota
        return hodnota * prevod

    def _cislo(self, eid: str | None, nahrada: float | None = None):
        st = self._stav(eid)
        if st is None:
            return nahrada
        try:
            return float(st.state)
        except (TypeError, ValueError):
            return nahrada

    def _zapnuto(self, eid: str | None) -> bool | None:
        """Je entita zapnutá? Nevím znamená None, ne vypnuto.

        Po startu hlásí spousta entit chvíli unknown nebo unavailable.
        Brát to jako vypnuto znamenalo třeba „nikdo doma" hned po
        restartu, a žaluzie se rozjely do polohy pro prázdný byt.
        """
        st = self._stav(eid)
        if st is None:
            return None
        stav = str(st.state).lower()
        if stav in ("unknown", "unavailable", "none", ""):
            return None
        # zone.home a podobné hlásí počet lidí, ne zapnuto
        try:
            return float(stav) > 0
        except ValueError:
            pass
        return stav in ("on", "true", "home", "open", "playing")

    def _stari_s(self, eid: str | None) -> tuple[float, float]:
        """Jak dlouho je entita v současném stavu a kdy se naposledy ozvala."""
        st = self.hass.states.get(eid) if eid else None
        if st is None:
            return (0.0, 0.0)
        ted = dt_util.utcnow()
        return ((ted - st.last_changed).total_seconds(),
                (ted - st.last_updated).total_seconds())

    def _max(self, eidy, nahrada=None):
        h = [self._cislo(e) for e in (eidy or [])]
        h = [x for x in h if x is not None]
        return max(h) if h else nahrada

    def _min(self, eidy, nahrada=None):
        h = [self._cislo(e) for e in (eidy or [])]
        h = [x for x in h if x is not None]
        return min(h) if h else nahrada

    # ------------------------------------------------------------ pomocné

    def _srovnej_posuvniky(self, pod_id: str, d: dict) -> None:
        """Změnu v nastavení místnosti přenese na šoupátka."""
        for p2 in POSUVNIKY_MISTNOSTI:
            if p2.klic not in d:
                continue
            hodnota = float(d[p2.klic])
            if self.formular_zmenen((pod_id, p2.klic), hodnota):
                self.hodnoty[(pod_id, p2.klic)] = hodnota
                self._prepsano.add((pod_id, p2.klic))
                _LOGGER.info("NaPohodu: %s.%s z nastavení -> %s",
                             pod_id, p2.klic, hodnota)
                self._posledni_snimek = None      # vynutí zápis

    def prepsano_formularem(self, klic: tuple) -> bool:
        """Přepsal tenhle klíč formulář? Pak má přednost před uloženou
        hodnotou šoupátka, kterou by obnova jinak vrátila."""
        return klic in self._prepsano

    def formular_zmenen(self, klic: tuple, hodnota: float) -> bool:
        """Změnil se od minula údaj ve formuláři?

        Když ano, má přednost před hodnotou šoupátka — uživatel ji právě
        vědomě přepsal. Když ne, platí šoupátko, protože s ním se ladí.
        """
        # Klíč, který vidíme poprvé, není přepsání — jen jsme o něm
        # dosud nevěděli. Dřív se po přidání nového posuvníku bralo
        # první spuštění jako změnu ve formuláři a přepsalo hodnotu,
        # kterou měl uživatel nastavenou na dashboardu.
        prvni = klic not in self._formular
        zmena = not prvni and self._formular[klic] != hodnota
        self._formular[klic] = hodnota
        return zmena

    def hodnota(self, pod_id: str, klic: str, vychozi: float) -> float:
        """Hodnota z posuvníku, jinak z konfigurace."""
        return self.hodnoty.get((pod_id, klic), vychozi)

    def _podentity(self, typ: str) -> list[ConfigSubentry]:
        return [p for p in self.entry.subentries.values()
                if p.subentry_type == typ]

    def _mistnost(self, odkaz: str) -> ConfigSubentry | None:
        """Odkaz je identifikátor. Starší konfigurace mají jméno, proto
        se zkusí obojí — po přeuložení zóny se to samo srovná."""
        for p in self._podentity(PODENTITA_MISTNOST):
            if p.subentry_id == odkaz:
                return p
        for p in self._podentity(PODENTITA_MISTNOST):
            if p.title == odkaz or p.data.get(CONF_NAZEV) == odkaz:
                return p
        return None

    @staticmethod
    def _cas(hodina: float) -> str:
        """Desetinná hodina na čitelný čas."""
        h = int(hodina)
        return f"{h:02d}:{int(round((hodina - h) * 60)):02d}"

    @staticmethod
    def _hodina(text, nahrada: float) -> float:
        """Čas z formuláře, tedy '22:00:00', na desetinnou hodinu."""
        if isinstance(text, (int, float)):
            return float(text)
        try:
            h, m, *_ = str(text).split(":")
            return int(h) + int(m) / 60
        except (ValueError, AttributeError):
            return nahrada

    # ------------------------------------------------------------ cíl

    def _cil_zakladni(self, g: dict) -> float:
        """Adaptivní cíl. Bez týdenního průměru se použije aktuální teplota."""
        # týdenní průměr je jádrem adaptivního modelu; bez něj by se cíl
        # měnil s každým odpolednem, proto raději samostatná entita
        # vlastní entita má přednost, jinak počítaný průměr
        prumer = self._cislo(g.get(CONF_T_PRUMER))
        zdroj = "cidlo"
        if prumer is None:
            prumer, zdroj = self.prumery.tyden, "pocitano"
        if prumer is None:
            # Poslední známá hodnota, ne vymyšlená patnáctka. Cíl se
            # z ní počítá a vymyšlené číslo by ho po restartu posunulo.
            prumer = self._cislo(g.get(CONF_T_VENKU), self._t_out_posledni)
            zdroj = "posledni_znama"
        dolni = float(g.get(CONF_CIL_MIN, 20.0))
        if prumer is None:
            # Nikdy jsme venkovní teplotu neviděli. Adaptivní cíl z ní
            # vychází, takže bez ní platí dolní hranice — poctivější než
            # dopočítat cokoli z vymyšleného čísla.
            self.pouzity["tyden"] = (None, "nevime")
            self.cil_rozpad = [
                f"venkovní teplotu ještě neznáme, platí dolní hranice "
                f"{dolni:.1f} °C"]
            return dolni
        self.pouzity["tyden"] = (prumer, zdroj)
        posun = self.hodnoty.get((self.entry.entry_id, "posun"), 0.0)
        zaklad = core.cil_adaptivni(
            prumer, posun,
            float(g.get(CONF_CIL_MIN, 20.0)),
            float(g.get(CONF_CIL_MAX, 27.0)),
        )
        # Přitápění se přičítá až po dolní hranici — jinak by ho hranice
        # spolkla právě v mrazu, kde má smysl.
        pritop = core.zimni_pritapeni(
            prumer,
            float(g.get(CONF_ZIMA_PRAH, 7.0)),
            float(g.get(CONF_ZIMA_O_KOLIK, 1.0)),
            float(g.get(CONF_ZIMA_NAJEZD, 2.5)))
        self.cil_rozpad = [
            f"základ z křivky {zaklad:.1f} °C (venku ⌀ {prumer:.1f} °C)"]
        if pritop:
            self.cil_rozpad.append(
                f"zimní přitápění +{pritop:.2f} °C "
                f"(venku ⌀ {prumer:.1f}, práh {g.get(CONF_ZIMA_PRAH, 7.0)} °C)")
        if posun:
            self.cil_rozpad.append(f"společný posun {posun:+.1f} °C")
        return round(zaklad + pritop, 2)

    # ------------------------------------------------------------ hlavní

    def _vitr(self, g: dict, vitr: float, naraz: float) -> bool:
        """Nárazy mají vlastní práh, protože pohon poškodí dřív než
        ustálená rychlost.

        Blokace povolí, až když obě hodnoty klesnou pod uklidňovací mez —
        jinak by se to na hraně překlápělo.
        """
        prah_v = float(g.get(CONF_VITR_PRAH, 7.0))
        prah_n = float(g.get(CONF_NARAZ_PRAH, 11.0))
        klid_v = float(g.get(CONF_VITR_KLID, 5.0))

        drive = self.vitr_blokuje
        if vitr > prah_v or naraz > prah_n:
            self.vitr_blokuje = True
            co = "nárazy" if naraz > prah_n else "rychlost"
            prah = prah_n if naraz > prah_n else prah_v
        elif vitr < klid_v and naraz < klid_v:
            self.vitr_blokuje = False
            co, prah = None, None
        else:
            # mezi prahem a uklidněním se stav nemění
            co, prah = ("hystereze", klid_v) if self.vitr_blokuje else (None, None)

        # příčina se přepisuje každý cyklus, aby zpráva nikdy nebyla prázdná
        self.vitr_pricina = {
            "rychlost": round(vitr, 1), "naraz": round(naraz, 1),
            "co_prekrocilo": co, "prah": prah,
            "prahy": {"rychlost": prah_v, "naraz": prah_n,
                      "povoli_pod": klid_v},
        } if self.vitr_blokuje else {}

        if drive != self.vitr_blokuje:
            _LOGGER.info(
                "NaPohodu: vítr %s — rychlost %.1f (práh %.1f), náraz %.1f "
                "(práh %.1f), povolí pod %.1f",
                "blokuje" if self.vitr_blokuje else "povolil",
                vitr, prah_v, naraz, prah_n, klid_v)
        else:
            _LOGGER.debug("NaPohodu: vítr rychlost %.1f náraz %.1f blokuje %s",
                          vitr, naraz, self.vitr_blokuje)
        self.vitr_stav = {
            "jednotka": "m/s (přepočteno z čidla)",
            "rychlost": round(vitr, 1), "naraz": round(naraz, 1),
            "blokuje": self.vitr_blokuje,
            "prahy": {"rychlost": prah_v, "naraz": prah_n,
                      "povoli_pod": klid_v},
            "pricina": self.vitr_pricina or None,
        }
        return self.vitr_blokuje

    def _pasmo(self, nast, m, v, pamet, otevreno: bool,
               cas_s: float = 0.0, pod_id: str = "") -> list[str]:
        """Stupnice teplotního pásma pro kartu."""
        noc = core._je_noc(self._hodina_ted, nast, bool(m.klid))
        otevrit, zavrit = ((nast.hyst_noc_otevrit, nast.hyst_noc_zavrit)
                           if noc or m.klid
                           else (nast.hyst_den_otevrit,
                                 nast.hyst_den_zavrit))
        return core.pasmo_text(
            m.cil, v.t_in, otevrit, zavrit, nast.mez_dolni, nast.mez_horni,
            otevreno, bool(m.klid), noc,
            m.atributy.get("teplota_max"), pamet.chladi, pamet.ohrivam,
            pamet.posledni_duvod or "",
            core.proc_neotevira(v, nast, v.t_in,
                                m.atributy.get("teplota_max") or v.t_in),
            int(max(0, pamet.rucni_do_s - cas_s) / 60) or None,
            self._trend(pod_id, v, cas_s), v.t_out)

    @staticmethod
    def _cislo_z(hodnota) -> float | None:
        """Číslo z atributu entity, nebo nic."""
        try:
            return float(hodnota)
        except (TypeError, ValueError):
            return None

    TREND_ODSTUP_S = 5 * 60

    def _trend(self, pod_id: str, v, cas_s: float) -> int:
        """Kam se teplota hýbe: +1 nahoru, -1 dolů, 0 stojí."""
        drive = self._t_in_drive.get(pod_id)
        if drive is None:
            self._t_in_drive[pod_id] = (v.t_in, cas_s)
            return 0
        teplota, kdy = drive
        if cas_s - kdy >= self.TREND_ODSTUP_S:
            self._t_in_drive[pod_id] = (v.t_in, cas_s)
        if abs(v.t_in - teplota) < 0.1:
            return 0
        return 1 if v.t_in > teplota else -1

    def _vetra_se_za(self, pod_id: str) -> bool:
        """Větrá za tuhle místnost soused v zóně?

        Platí jen tam, kde okno neovládáme — kdo má vlastní, ten o svém
        větrání ví sám.
        """
        pod = self.entry.subentries.get(pod_id)
        if pod is not None and (pod.data.get(CONF_OKNA) or []):
            return False
        if not self._cizi_zadost.get(pod_id):
            return False
        for o in self._okruhy_popis:
            cleni = {x.subentry_id for x in o.get("cleni", [])}
            if pod_id not in cleni or not o.get("dvere_otevrene", True):
                continue
            if any(self.okna_stav.get(x) is True
                   for x in cleni if x != pod_id):
                return True
        return False

    def _zadost_bez_okna(self, pod_id: str, d: dict) -> str:
        """Chce místnost bez okna chladit, ohřát, nebo nic?

        Hranice jsou její vlastní, včetně hystereze: začne se při
        odchylce od cíle a skončí až na protější hraně pásma, aby
        žádost nepodléhala každému zakolísání. Teploty jsou z minulého
        kola, protože zóna se počítá dřív než místnosti — minuta
        zpoždění u teploty nevadí.
        """
        m = self.mistnosti.get(pod_id)
        if m is None or m.cil is None:
            return ""
        # Výsledek místnosti se každý cyklus staví znovu a v době, kdy
        # se počítá zóna, má teprve čerstvě načtená čidla. „uvnitr" se
        # doplní až v kroku místnosti, takže se bere přímo z nich —
        # dřív tu bylo None a žádost nevznikla nikdy.
        t_min = m.atributy.get("teplota_min")
        t_max = m.atributy.get("teplota_max")
        t_in = t_min if t_min is not None else t_max
        if t_in is None:
            return ""
        t_max = t_max if t_max is not None else t_in
        noc = bool(m.klid) or self._je_noc_ted
        otevrit = self.hodnota(
            pod_id, CONF_HYST_NOC_OTEVRIT if noc else CONF_HYST_DEN_OTEVRIT,
            float(d.get(CONF_HYST_NOC_OTEVRIT if noc
                        else CONF_HYST_DEN_OTEVRIT, 2.5)))

        # Končí se na cíli, ne na protější hraně pásma. Hlavice v téhle
        # místnosti míří na cíl, takže přetah pod něj by znamenal topit
        # proti otevřenému oknu vedle.
        bezi = self._cizi_zadost.get(pod_id, "")
        if bezi == "chlazeni" and t_max > m.cil:
            return "chlazeni"
        if bezi == "ohrev" and t_in < m.cil:
            return "ohrev"
        jak = ""
        if t_max > m.cil + otevrit:
            jak = "chlazeni"
        elif t_in < m.cil - otevrit:
            jak = "ohrev"
        self._cizi_zadost[pod_id] = jak
        return jak

    def _dosah(self, zdroj: str, klic_volby: str, klic_seznamu: str,
               vychozi: str) -> set[str]:
        """Kam až sahá vliv zvlhčovače z místnosti „zdroj".

        Zóna je definovaná sdílením vzduchu kvůli CO2, jenže jemný
        aerosol ani vlhkost se jí nedrží — proto se dosah nastavuje
        zvlášť a zóna je jen jedna z možností.
        """
        pod = self.entry.subentries.get(zdroj)
        data = pod.data if pod else {}
        jak = data.get(klic_volby, vychozi)
        if jak == "mistnost":
            return {zdroj}
        if jak == "vybrane":
            return {zdroj, *(data.get(klic_seznamu) or [])}
        if jak == "zona":
            return self._zona_mistnosti(zdroj)
        return set(self.mistnosti)          # celý byt

    def _zona_mistnosti(self, pod_id: str) -> set[str]:
        """Místnosti, se kterými tahle dýchá za otevřenými dveřmi."""
        for o in self._okruhy_popis:
            cleni = {x.subentry_id for x in o.get("cleni", [])}
            if pod_id in cleni and o.get("dvere_otevrene", True):
                return cleni
        return {pod_id}

    # Jak dlouho se nejdéle čeká, než prach po zvlhčovači klesne.
    # Bez stropu by stačilo zaseknuté čidlo a prach by se neřešil nikdy.
    DOZVUK_NEJDELE_S = 2 * 3600

    def _zvlhcuje_na(self, pod_id: str) -> bool:
        """Dosáhne sem aerosol z běžícího nebo doznívajícího zvlhčovače?"""
        zdroje = set(self.zvlhcuje) | set(self._dozvuk)
        return any(pod_id in self._dosah(zdroj, CONF_PRACH_DOSAH,
                                         CONF_PRACH_MISTNOSTI, "byt")
                   for zdroj in zdroje)

    def _uklid_dozvuku(self, cas_s: float) -> None:
        """Doznívání končí, až prach spadne do čistého pásma.

        Teprve pak se prachu zase věří. Strop je od toho, aby jedno
        zaseknuté čidlo neumlčelo reakci na prach napořád.
        """
        for zdroj, od in list(self._dozvuk.items()):
            if cas_s - od > self.DOZVUK_NEJDELE_S:
                del self._dozvuk[zdroj]
                continue
            dosah = self._dosah(zdroj, CONF_PRACH_DOSAH,
                                CONF_PRACH_MISTNOSTI, "byt")
            mereno = [self._pm_syrovy[x] for x in dosah
                      if x in self._pm_syrovy]
            if mereno and max(mereno) < self.hodnota(
                    zdroj, CONF_PM_CISTO,
                    float((self.entry.subentries[zdroj].data
                           if zdroj in self.entry.subentries else {})
                          .get(CONF_PM_CISTO, 20.0))):
                del self._dozvuk[zdroj]

    def _okno_brani_zvlhcovani(self, pod_id: str) -> bool:
        """Je otevřené okno tam, odkud to na vlhkost tady dosáhne?"""
        dosah = self._dosah(pod_id, CONF_VLHKOST_DOSAH,
                            CONF_VLHKOST_MISTNOSTI, "byt")
        return any(self.okna_stav.get(x) is True
                   for x in dosah if x != pod_id)

    def _prehled_bytu(self, g: dict) -> list[str]:
        """Globální nastavení, ať je na dashboardu vidět, co platí."""
        naraz = bool(g.get(CONF_NARAZOVE, False))
        odstup_naraz = self.hodnota(
            self.entry.entry_id, CONF_NARAZOVE_ODSTUP,
            float(g.get(CONF_NARAZOVE_ODSTUP, 15.0)))
        radky = [
            "Nárazový režim: "
            + (f"od rozdílu {odstup_naraz:.1f} "
               f"°C mezi venkem a cílem" if naraz else "vypnutý")
            + f" (teď {'běží' if self.narazove else 'neběží'}"
            + (f", rozdíl {self.narazove_rozdil:.1f} °C"
               + (f" — rozhoduje {self.narazove_kdo}"
                  if self.narazove_kdo else "") if naraz else "")
            + ")",
            f"Další pokus po marném větrání: po změně venku o "
            f"{float(g.get(CONF_ZMENA_PODMINEK, 2.0)):.1f} °C, "
            f"nejpozději za {int(g.get(CONF_NEJDRIV_ZNOVU, 60))} min",
            f"Topná sezóna pod {float(g.get(CONF_SEZONA_PRAH, 13.0)):.1f} "
            f"°C třídenního průměru (teď "
            f"{'běží' if self.topna_sezona else 'neběží'})",
            # čas z formuláře chodí jako „22:00:00", ne jako číslo
            f"Noční hodiny "
            f"{self._cas(self._hodina(g.get(CONF_NOC_OD), 22.0))} – "
            f"{self._cas(self._hodina(g.get(CONF_NOC_DO), 6.5))}",
        ]
        return radky

    def _sezona(self, g: dict) -> bool:
        rezim = g.get(CONF_SEZONA_REZIM, "podle_prumeru")
        if rezim == "vzdy":
            self.pouzity["tri_dny"] = (None, "nastaveno natvrdo")
            return True
        if rezim == "nikdy":
            self.pouzity["tri_dny"] = (None, "nastaveno natvrdo")
            return False
        return self._sezona_podle_prumeru(g)

    def _sezona_podle_prumeru(self, g: dict) -> bool:
        """Topná sezóna podle třídenního průměru, s hysterezí kolem prahu.

        Bez vlastní entity se použije počítaný průměr.
        """
        prah = self.hodnota(self.entry.entry_id, CONF_SEZONA_PRAH,
                            float(g.get(CONF_SEZONA_PRAH, 13.0)))
        hyst = float(g.get(CONF_SEZONA_HYSTEREZE, 1.0))
        t = self._cislo(g.get(CONF_T_SEZONA))
        zdroj = "cidlo"
        if t is None:
            t, zdroj = self.prumery.tri_dny, "pocitano"
        self.pouzity["tri_dny"] = (t, zdroj)
        if t is None:
            return self.topna_sezona
        # Sezóna začíná pod prahem a končí, až teplota vyleze nad práh
        # o hysterezi. Dřív se pásmo rozkládalo na obě strany, takže
        # se při prahu 13 zapínala až pod 12,5 — a to nikdo neočekává.
        if t < prah:
            return True
        if t > prah + hyst:
            return False
        return self.topna_sezona          # v pásmu se nemění

    async def _async_update_data(self):
        """Jeden cyklus: přečti stav, rozhodni za každou místnost, vykonej.

        Rozhoduje se za místnost, protože okna patří místnosti. Oblast
        do toho vstupuje jen tím, že sdílí vzduch mezi místnostmi, které
        spolu dýchají, a řeší noční zastupování.
        """
        g = {**self.entry.data, **self.entry.options}

        # ---------- společné venku ----------
        # Po restartu čidlo chvíli nehlásí. Vymyslet si teplotu znamená
        # rozhodovat podle vymyšleného čísla — okno se pak zavře „kvůli
        # chladu venku", kterého patnáct stupňů nikdy nebylo. Bere se
        # poslední známá hodnota, a když žádná není, nerozhoduje se
        # podle teploty vůbec.
        namerene = self._cislo(g.get(CONF_T_VENKU))
        if namerene is not None:
            self._t_out_posledni = namerene
        t_out = namerene if namerene is not None else self._t_out_posledni
        self.prumery.aktualizuj(self._cislo(g.get(CONF_T_VENKU)),
                                dt_util.utcnow().timestamp())
        self._uloziste.async_delay_save(self.prumery.jako_slovnik, 300)
        # Vlhkost se používá na rosný bod, takže vymyšlená padesátka
        # umí kondenzaci buď zatajit, nebo vyrobit. Poslední známá, a
        # když žádná není, rosný bod se prostě nepočítá.
        namerena_rh = self._cislo(g.get(CONF_RH_VENKU))
        if namerena_rh is not None:
            self._rh_out_posledni = namerena_rh
        rh_out = (namerena_rh if namerena_rh is not None
                  else self._rh_out_posledni)
        dest = self._cislo(g.get(CONF_DEST), 0.0) or 0.0
        self._zkontroluj_jednotku(g.get(CONF_T_VENKU), ("°C",), "teplota")
        self._zkontroluj_jednotku(g.get(CONF_DEST),
                                  ("mm/h", "in/h"), "déšť")
        doma = self._zapnuto(g.get(CONF_DOMA))
        zdroj_doma = g.get(CONF_DOMA)
        st_doma = self._stav(zdroj_doma)
        self.doma_popis = (
            f"{zdroj_doma} = {st_doma.state}" if st_doma is not None
            else "přítomnost nenastavena, beru jako doma")
        doma = True if doma is None else doma

        vitr = self._rychlost(g.get(CONF_VITR), 0.0)
        naraz = self._rychlost(g.get(CONF_NARAZ), vitr)
        vitr_blokuje = self._vitr(g, vitr, naraz)

        slunce_az, slunce_el = self._poloha_slunce()
        jasno = pr.oblacnost(self._cislo(g.get(CONF_ZARENI)), slunce_el)

        ted = dt_util.now()
        hodina = ted.hour + ted.minute / 60
        dnes = ted.strftime("%Y-%m-%d")
        if dnes != self._souhrn_den:
            self._souhrn_den = dnes
            self.souhrn = {}          # nový den, počítadla od nuly
        cas_s = dt_util.utcnow().timestamp()
        # Plán obsazenosti. Skutečnost smí přítomnost jen přidat, nikdy
        # ubrat: kdyby plán uměl „nikdo doma" přebít čidlo, stačil by
        # jeden zapomenutý záznam v kalendáři a člověk sedí ve studeném
        # bytě. Proto se plán „nikdo" uplatní, jen když ani přítomnost
        # nikoho nevidí.
        self.plan_nikdo = pl.slouc(
            [await self._plan(g.get(CONF_PLAN_NIKDO), cas_s),
             self.plan_vlastni("nikdo", None, cas_s)])
        self.plan_vic = pl.slouc(
            [await self._plan(g.get(CONF_PLAN_VIC), cas_s),
             self.plan_vlastni("vic", None, cas_s)])
        if self.plan_vic.bezi:
            doma = True
            # Ať je v kartě poznat, proč se byt bere za obsazený,
            # když přítomnost hlásí opak.
            self.doma_popis += " (plán: víc lidí)"
        self.plan_popis = self._plan_popis(
            pl.BYT, g.get(CONF_PLAN_NIKDO), g.get(CONF_PLAN_VIC),
            self.plan_nikdo, self.plan_vic, cas_s)
        predstih = self.hodnota(self.entry.entry_id, CONF_PREDVETRAT,
                                float(g.get(CONF_PREDVETRAT, 60)))
        self.predvetrat = pl.predvetrat(self.plan_vic, cas_s, predstih)
        # Plánovaná nepřítomnost se počítá za dlouhou hned, bez čekání
        # na hodiny — a končí s předstihem, aby se stihlo nahřát zpátky.
        self.plan_pryc = (
            self.plan_nikdo.bezi and not doma
            and not pl.konci_do(self.plan_nikdo, cas_s,
                                float(g.get(CONF_NOC_PREDSTIH, 60))))
        # Povel „zavřená okna" pro celý byt. Nekončí s předstihem jako
        # útlum: nahřát se musí dopředu, ale okno nemá proč otevírat
        # dřív, než se někdo vrátí. Přepínač přítomnosti ho ruší —
        # když jsi doma, plán ustupuje.
        self.plan_zavrit_byt = bool(self.plan_nikdo.bezi and not doma)

        cil_zakl = self._cil_zakladni(g)
        drive_sezona = self.topna_sezona
        self.topna_sezona = self._sezona(g)
        if self.topna_sezona and not drive_sezona:
            self._sezona_od = cas_s      # začátek sezóny, čas na odvzdušnění
        elif not self.topna_sezona:
            self._sezona_od = None
        noc_od = self._hodina(g.get(CONF_NOC_OD), 22.0)
        noc_do = self._hodina(g.get(CONF_NOC_DO), 6.5)
        # ostatní kroky je potřebují a dostávají jen čas v sekundách
        self._hodina_ted, self._noc_od, self._noc_do = hodina, noc_od, noc_do
        je_noc = ((hodina >= noc_od or hodina < noc_do) if noc_od > noc_do
                  else (noc_od <= hodina < noc_do))

        # ---------- 1. základ každé místnosti ----------
        self.mistnosti = {}
        podklady: dict[str, dict] = {}
        for p in self._podentity(PODENTITA_MISTNOST):
            d = dict(p.data)

            jmeno = d.get(CONF_NAZEV, p.title)
            self._srovnej_posuvniky(p.subentry_id, d)
            odchylka = self.hodnota(p.subentry_id, CONF_ODCHYLKA,
                                    float(d.get(CONF_ODCHYLKA, 0.0)))
            sig = self._signaly(d, doma, hodina, noc_od, noc_do)
            nast_pr = self._nastaveni_pritomnosti(d)

            # Plán místnosti. Obsazenost smí jen přidat: když čidlo
            # vidí pohyb, je obsazeno, ať plán říká co chce. „Nikdo tu
            # nebude" proto platí jen tam, kde to čidlo nevyvrací.
            plan_je = pl.slouc(
                [await self._plan(d.get(CONF_PLAN_OBSAZENO), cas_s),
                 self.plan_vlastni("obsazeno", p.title, cas_s)])
            plan_neni = pl.slouc(
                [await self._plan(d.get(CONF_PLAN_PRAZDNO), cas_s),
                 self.plan_vlastni("prazdno", p.title, cas_s)])
            obsazeno = pr.obsazeno(sig, nast_pr)
            if plan_je.bezi:
                obsazeno = True
            elif plan_neni.bezi and not pr.indicie_aktivni(sig, nast_pr):
                obsazeno = False

            # „Zavřená okna" je druhý, samostatný povel. Není to
            # informace o obsazenosti: platí i tehdy, když je zbytek
            # bytu plný lidí, a naopak „nikdo tu nebude" samo o sobě
            # okno nezavírá — jinak by jedna utlumená místnost
            # ochromila větrání celého bytu. Pohyb v místnosti povel
            # ruší, protože pak se plán mýlí.
            plan_zavreno = self.plan_vlastni("zavreno", p.title, cas_s)
            zavreno = bool(
                plan_zavreno.bezi
                and not pr.indicie_aktivni(sig, nast_pr))

            # Naplánovaná cílová teplota je konečná: přebíjí adaptivní
            # normu i posun místnosti, protože přesně proto se zadává.
            plan_cil = self.plan_cil_mistnosti(p.title)
            m = VysledekMistnosti(
                nazev=jmeno,
                cil=(round(plan_cil, 1) if plan_cil is not None
                     else round(cil_zakl + odchylka, 1)),
                obsazeno=obsazeno,
                klid=pr.klid(sig),
                plan_zavreno=zavreno,
                plan_prazdno=bool(plan_neni.bezi and not obsazeno),
                plan_prazdno_do_s=plan_neni.do_s,
            )
            okno_m = sl.Okno(nazev=p.title,
                             azimut=float(d.get(CONF_AZIMUT, 180)))
            m.slunce = round(sl.dopad(okno_m, slunce_az, slunce_el, jasno))
            m.atributy = {
                "teplota_min": self._min(d.get(CONF_TEPLOTY)),
                "teplota_max": self._max(d.get(CONF_TEPLOTY)),
                "co2_vlastni": self._max(d.get(CONF_CO2)),
                "indicie": pr.indicie_aktivni(sig, nast_pr),
                # Proč je místnost brána za obsazenou, když tam není
                # čidlo — bez toho by se nedalo zjistit, odkud se to
                # vzalo.
                "plan": self._plan_popis(
                    pl.MISTNOST, d.get(CONF_PLAN_PRAZDNO),
                    d.get(CONF_PLAN_OBSAZENO), plan_neni, plan_je, cas_s),
                # Povel se ukazuje zvlášť, ať je poznat, že okno drží
                # zavřené plán, a ne že se zrovna nemá proč otevřít.
                "plan_okna": "zavřená okna podle plánu" if zavreno else None,
            }
            self.mistnosti[p.subentry_id] = m
            podklady[p.subentry_id] = {"pod": p, "d": d, "sig": sig,
                                       "nast": nast_pr}

        # ---------- 2. okruhy: oblasti plus samostatné místnosti ----------
        okruhy = []
        v_oblasti = set()
        for z in self._podentity(PODENTITA_ZONA):
            cleni = [self._mistnost(j) for j in (z.data.get(CONF_MISTNOSTI) or [])]
            cleni = [x for x in cleni if x and x.subentry_id in podklady]
            if not cleni:
                continue
            v_oblasti.update(x.subentry_id for x in cleni)
            okruhy.append({"id": z.subentry_id, "nazev": z.title,
                           "pod": z, "cleni": cleni})
        for pid, u in podklady.items():
            if pid not in v_oblasti:
                okruhy.append({"id": pid, "nazev": u["pod"].title,
                               "pod": None, "cleni": [u["pod"]]})

        # sdílený vzduch: rozhoduje nejhorší hodnota v okruhu
        # popis okruhů si schováme, dosah „v jeho zóně" ho potřebuje
        self._okruhy_popis = okruhy
        for o in okruhy:
            co2, pm25, pm10, pm_platny, spanek = [], [], [], None, False
            for mp in o["cleni"]:
                md = podklady[mp.subentry_id]["d"]
                co2 += list(md.get(CONF_CO2) or [])
                pm25 += list(md.get(CONF_PM25) or [])
                pm10 += list(md.get(CONF_PM10) or [])
                spanek = spanek or bool(self._zapnuto(md.get(CONF_SPANEK)))
                if md.get(CONF_PM_PLATNY) and pm_platny is None:
                    pm_platny = self._zapnuto(md.get(CONF_PM_PLATNY))
            o["co2"] = self._max(co2, 450.0)
            o["pm25"] = self._max(pm25, 0.0)
            o["pm10"] = self._max(pm10, 0.0)
            o["pm_platny"] = True if pm_platny is None else pm_platny
            o["spanek"] = spanek
            # Spánek je věc celé oblasti: místnosti, které spolu dýchají,
            # jsou jedna místnost přepažená průchodem a rámus okna
            # v kuchyni dolehne do obýváku, kde se spí. Dřív tu bylo
            # „klid platí, jen když ho vyžadují všechny místnosti
            # s oknem" a kuchyň v noci jezdila oknem, přestože vedle
            # někdo spal.
            #
            # Zavřené dveře to ale ruší — pak se rámus nepřenáší a není
            # důvod kvůli vedlejší místnosti nevětrat. Totéž platí pro
            # vzduch, který se zavřenými dveřmi taky nevymění.
            data_o = o["pod"].data if o["pod"] else {}
            dvere_m = [self._zapnuto(e)
                       for e in (data_o.get(CONF_DVERE) or [])]
            o["dvere_otevrene"] = all(x is not False for x in dvere_m)
            o["klid"] = (any(self.mistnosti[x.subentry_id].klid
                             for x in o["cleni"])
                         if o["dvere_otevrene"] else False)
            s_okny = [x for x in o["cleni"]
                      if podklady[x.subentry_id]["d"].get(CONF_OKNA)]

            # Místnost bez ovládaného okna si chladit ani ohřívat sama
            # nemůže. Zóna sdílí vzduch, a tím pádem i teplo, takže
            # žádost předá sousedům s oknem.
            o["cizi_chlazeni"] = o["cizi_ohrev"] = False
            o["cizi_za"] = []
            for x in o["cleni"]:
                # Vyvětrat si sama neumí ani místnost, která okno má,
                # ale má vypnutý přepínač Ovládat okno — dřív se dívalo
                # jen na seznam oken a taková místnost o nic nepožádala.
                if (podklady[x.subentry_id]["d"].get(CONF_OKNA)
                        and self.hodnoty.get(
                            (x.subentry_id, "ovladat_okno"), 1.0) > 0):
                    continue
                jak = self._zadost_bez_okna(
                    x.subentry_id, podklady[x.subentry_id]["d"])
                if jak:
                    o[f"cizi_{jak}"] = True
                    o["cizi_za"].append(x.title)

            # Drahé je větrání tam, kde se otevírá — místnost bez okna
            # k tomu nemá co říct. Bez oken se bere celá oblast.
            def pod(x):
                m2 = self.mistnosti[x.subentry_id]
                return (m2.atributy.get("teplota_min") or 99) < m2.cil

            o["pod_cilem"] = (all(pod(x) for x in s_okny) if s_okny
                              else any(pod(x) for x in o["cleni"]))

            # ochota větrat: od kuchyňského okna táhne, kdežto v ložnici
            # může být otevřeno celý den a nikomu to nevadí
            def ochota(x, jaka):
                return (podklady[x.subentry_id]["d"]
                        .get(CONF_OCHOTA, "normalne") == jaka)

            o["nerada"] = any(ochota(x, "nerada") for x in s_okny)
            o["ochotna"] = bool(s_okny) and all(
                ochota(x, "ochotna") for x in s_okny)

            # Vzduch je společný, takže o něm nemůžou dvě místnosti
            # rozhodovat jinak — jinak by jedna otevírala a druhá zavírala.
            # Bere se nejcitlivější nastavení: stačí jedna místnost,
            # které je dusno, a větrá celá oblast.
            def nej(klic, vychozi):
                return min(self.hodnota(x.subentry_id, klic,
                                        float(podklady[x.subentry_id]["d"]
                                              .get(klic, vychozi)))
                           for x in o["cleni"])

            o["prahy"] = {
                CONF_CO2_OTEVRIT: nej(CONF_CO2_OTEVRIT, 800),
                CONF_CO2_ZAVRIT: nej(CONF_CO2_ZAVRIT, 700),
                CONF_CO2_NOC: nej(CONF_CO2_NOC, 1000),
                CONF_CO2_NOC_KRIZE: nej(CONF_CO2_NOC_KRIZE, 1250),
                # Prach má nárazové větrání spouštět stejně jako CO2,
                # takže se jeho prahy berou po okruhu týmž pravidlem.
                CONF_PM_SPATNE: nej(CONF_PM_SPATNE, 35.0),
                CONF_PM_CISTO: nej(CONF_PM_CISTO, 20.0),
            }
            # Ultrazvukový zvlhčovač rozprašuje minerály a čidlo je
            # vidí jako prach. Okruh, kam jeho aerosol dosáhne, se do
            # nárazového větrání nepočítá — jinak by zvlhčovač
            # v obýváku otevřel okno v ložnici kvůli prachu, který se
            # vyvětrat nedá.
            o["pm_od_zvlhcovace"] = any(
                self._zvlhcuje_na(x.subentry_id) for x in o["cleni"])

        # ---------- 3. zastupování mezi oblastmi ----------
        stavy = []
        for o in okruhy:
            data = o["pod"].data if o["pod"] else {}
            dvere = [self._zapnuto(e) for e in (data.get(CONF_DVERE) or [])]
            # Sousedem může být oblast i samostatná místnost — ta má
            # okruh pod svým vlastním identifikátorem. Bez tohohle by
            # ložnice, která oblast nepotřebuje, nemohla nikoho zastoupit.
            jmenovani = set(data.get(CONF_SOUSEDI) or [])
            sousedi = [q["id"] for q in okruhy if q["id"] in jmenovani]
            stavy.append(so.ZonaStav(
                id=o["id"], nazev=o["nazev"], co2=o["co2"], klid=o["klid"],
                pod_cilem=o["pod_cilem"],
                nerada=o["nerada"], ochotna=o["ochotna"],
                obsazeno=any(self.mistnosti[x.subentry_id].obsazeno
                             for x in o["cleni"]),
                muze_vetrat=not vitr_blokuje and doma, sousedi=sousedi,
                dvere_otevrene=all(x is not False for x in dvere)))
        # Zastupování musí sáhnout po stejném prahu, od kterého by se
        # zóna sama otevřela. Jinak se zástupce přiřadí dřív, než je
        # vůbec potřeba větrat.
        prah_zastoupeni = min(
            (o["prahy"][CONF_CO2_NOC] for o in okruhy if o.get("prahy")),
            default=1000.0)
        # Sousedství platí v obou směrech. Když oblast jmenuje ložnici,
        # ložnice má za souseda ji — jinak by zastupování fungovalo
        # jen jednou stranou a to nikdo nečeká.
        podle_id = {z.id: z for z in stavy}
        for z in stavy:
            for sid in list(z.sousedi):
                soused = podle_id.get(sid)
                if soused is not None and z.id not in soused.sousedi:
                    soused.sousedi.append(z.id)

        upravy = so.prerozdel(stavy, prah_zastoupeni)

        # Společné nárazové větrání: když je venku zima a některá zóna
        # potřebuje vzduch, otevře se všude naráz a krátce. Průvan vymění
        # vzduch rychleji než dlouhé větrání jedním oknem a stěny se
        # nestihnou vychladit. Kde tomu něco brání, se prostě neotevře.
        # Rozhoduje, jestli větrání stojí teplo — tedy jestli je venku
        # chladněji než cíl. Pevná venkovní teplota by v lednu a v květnu
        # znamenala něco jiného.
        # Nárazový režim platí na obě strany: v mrazu i v horku je
        # venkovní vzduch tak jiný, že dlouhé větrání škodí. Hystereze
        # půl stupně brání přepínání, když se teplota motá kolem prahu.
        odstup = self.hodnota(self.entry.entry_id, CONF_NARAZOVE_ODSTUP,
                              float(g.get(CONF_NARAZOVE_ODSTUP, 15.0)))
        rozdil, kdo = self._narazove_rozdil(
            t_out, {m.nazev: m.cil for m in self.mistnosti.values()})
        self.narazove_rozdil, self.narazove_kdo = rozdil, kdo
        prah = odstup - 0.5 if self.narazove else odstup
        self.narazove = bool(g.get(CONF_NARAZOVE, False)) and rozdil > prah
        if self.narazove:
            nejhorsi = max((o["co2"] for o in okruhy), default=0.0)
            self.narazove_bezi = self._narazove_pokracuje(
                self._narazove_vzduch(okruhy), self.narazove_bezi)
            self.narazove_co2 = nejhorsi
            # Nejhorší prach jen z okruhů bez aerosolu ze zvlhčovače;
            # ten se vyvětrat nedá a posílat ho po bytě by otevíralo
            # okna kvůli ničemu.
            self.narazove_pm = max(
                (o.get("pm25") or 0.0 for o in okruhy
                 if not o.get("pm_od_zvlhcovace")), default=0.0)
        else:
            self.narazove_bezi = False
            self.narazove_co2 = 0.0
            self.narazove_pm = 0.0

        # ---------- 4. rozhodnutí a vykonání za místnost ----------
        for o in okruhy:
            uprava = upravy.get(o["id"], so.Uprava())
            for mp in o["cleni"]:
                await self._mistnost_krok(
                    mp, podklady[mp.subentry_id], o, uprava,
                    t_out, rh_out, dest, doma, vitr_blokuje, je_noc,
                    hodina, cas_s, noc_od, noc_do, slunce_el)

        # ---------- 5. sdílená klimatizace ----------
        if doma:
            self._prazdno_od = None
        elif self._prazdno_od is None:
            self._prazdno_od = cas_s
        await self._klima_krok(t_out, cas_s)

        # ---------- 5b. zprávy o plánu ----------
        # Až tady, protože dopad na místnosti je známý teprve po
        # jejich rozhodnutí — zpráva má říkat, co se stalo.
        await self._plan_zpravy(g, cas_s)

        # ---------- 6. denní souhrn ----------
        cas_souhrnu = self._hodina(g.get(CONF_SOUHRN_CAS), 21.0)
        if (hodina >= cas_souhrnu and self._souhrn_odeslan != dnes
                and self.souhrn):
            self._souhrn_odeslan = dnes
            self._posledni_snimek = None      # vynutí zápis
            for pid, sh in self.souhrn.items():
                m = self.mistnosti.get(pid)
                if m:
                    await self._posli(g, "souhrn", m.nazev, cas_s,
                                      dnes=m.atributy.get("dnes", {}))

        # ---------- 7. přehled oblasti ----------
        self.zony = {}
        for o in okruhy:
            if o["pod"] is None:
                continue
            uprava = upravy.get(o["id"], so.Uprava())
            z = VysledekZony(nazev=o["nazev"],
                             mistnosti=[x.title for x in o["cleni"]])
            z.atributy = {
                "co2": o["co2"], "pm25": o["pm25"],
                "spi_se": o["spanek"], "klid": o["klid"],
                "zastupce": uprava.zastupce, "vetra_i_za": uprava.za_koho,
                "teplo_za": o.get("cizi_za") or None,
                "mistnosti": z.mistnosti,
            }
            self.zony[o["id"]] = z

        # Zápis jen při skutečné změně. Ukládat každou minutu celý stav
        # znamená čtrnáct set zápisů denně a na paměťové kartě to není
        # zdravé.
        snimek = self._uloz_pameti()
        if snimek != self._posledni_snimek:
            self._posledni_snimek = snimek
            self._uloziste_pameti.async_delay_save(lambda: snimek, 30)

        return {"zony": self.zony, "mistnosti": self.mistnosti}

    async def _plan_zpravy(self, g: dict, cas_s: float) -> None:
        """Zprávy o plánu: začátky, konce a chyby v zadání.

        Hlásí se **dopad**, ne záznam: co se právě na koho vztahuje.
        Tím se pokryjí i cizí kalendáře a rozvrhy, u kterých žádný
        záznam nemáme, a složený povel pošle jednu zprávu místo dvou.
        """
        ted = dt_util.now()
        stav: dict[str, list[str]] = {}

        def pridej(kdo: str, popis: str, bezi: bool) -> None:
            if bezi:
                stav.setdefault(kdo, []).append(popis)

        pridej("Byt", "nikdo doma", self.plan_nikdo.bezi)
        pridej("Byt", "víc lidí", self.plan_vic.bezi)
        for m in self.mistnosti.values():
            pridej(m.nazev, "nikdo tu nebude", m.plan_prazdno)
            pridej(m.nazev, "zavřená okna", m.plan_zavreno)

        do_kdy = {"Byt": self.plan_nikdo.do_s or self.plan_vic.do_s}
        for m in self.mistnosti.values():
            do_kdy[m.nazev] = m.plan_prazdno_do_s

        if self._plan_zpravy_prvni:
            # Po restartu se jen zapamatuje, co platí. Hlásí se změny,
            # a restart změna není — jinak by každé přenačtení
            # integrace poslalo všechno, co zrovna běží.
            self._plan_zpravy_prvni = False
            self._plan_bezelo = {k: v for k, v in stav.items() if v}
            return

        for kdo in set(stav) | set(self._plan_bezelo):
            nove = stav.get(kdo, [])
            if nove == self._plan_bezelo.get(kdo, []):
                continue
            if nove:
                kdy = do_kdy.get(kdo)
                await self._posli(
                    g, "plan", kdo, cas_s,
                    co=f"{kdo} — {', '.join(nove)}",
                    do_kdy=(self._cas_text(kdy, cas_s, ted) if kdy else None),
                    dopad=pz.dopad(self._druhy_popisu(nove)))
            else:
                await self._posli(g, "plan", kdo, cas_s,
                                  co=kdo, konec=True)
        self._plan_bezelo = {k: v for k, v in stav.items() if v}

        # Chyby v zadání. Hlásí se jednou na záznam, ne každou minutu:
        # nepochopená událost v kalendáři vydrží týdny.
        skupiny = self._skupiny()
        jmena = {p.title for p in self._podentity(PODENTITA_MISTNOST)}
        radky = []
        for z in self._vlastni_plan:
            vyskyty = pz.rozbal(z, ted - timedelta(hours=1),
                                ted + timedelta(days=1), rrulestr)
            if not vyskyty:
                continue          # až se přiblíží, ozveme se
            potize = pz.chyby(z, skupiny, jmena)
            if z.get("rrule") and rrulestr is None:
                potize.append("chybí knihovna python-dateutil, "
                              "opakování se neuplatní")
            for x in potize:
                klic = f"{z.get('uid')}|{x}"
                if klic in self._plan_chyby:
                    continue
                self._plan_chyby.add(klic)
                radky.append(x)
        if radky:
            await self._posli(g, "plan", "Plán", cas_s,
                              chyba="; ".join(radky))

    def _druhy_popisu(self, popisy: list[str]) -> list[str]:
        """Z popisů zpátky na druhy, ať se dopad skládá na jednom místě."""
        obracene = {v: k for k, v in pz.DRUHY.items()}
        return [obracene[x] for x in popisy if x in obracene]

    @staticmethod
    def _cas_text(do_s: float, cas_s: float, ted) -> str:
        """Kdy to skončí, řečeno hodinami, ne sekundami."""
        kdy = ted + timedelta(seconds=do_s - cas_s)
        if kdy.date() == ted.date():
            return kdy.strftime("%H:%M")
        return kdy.strftime("%-d.%-m. %H:%M")

    async def _posli(self, g: dict, druh: str, mistnost: str,
                     cas_s: float, **udaje) -> None:
        """Sestaví zprávu a pošle ji na vybrané notify entity."""
        kam = g.get(CONF_ZPRAVY) or []
        if not kam:
            return
        self.hlasic.druhy = tuple(g.get(CONF_ZPRAVY_DRUHY) or zp.VYCHOZI)
        text = self.hlasic.zprava(druh, mistnost, cas_s, **udaje)
        if not text:
            return
        try:
            await self.hass.services.async_call(
                "notify", "send_message",
                {"entity_id": kam, "message": text}, blocking=False)
        except Exception as e:  # pragma: no cover - výpadek notifikací
            _LOGGER.warning("NaPohodu: zprávu se nepodařilo poslat: %s", e)

    async def _klima_krok(self, t_out: float,
                          cas_s: float) -> None:
        """Sdílená jednotka obsluhuje víc místností, tak se musí rozhodnout.

        Vnitřní jednotka v jedné místnosti se sem neplete — tu má
        místnost u sebe a řídí se sama.
        """
        self.klimy = {}
        for pod in self._podentity(PODENTITA_KLIMA):
            d = pod.data
            entita = d.get(CONF_KLIMA_ENTITA)
            if not entita:
                continue

            vybrane = d.get(CONF_KLIMA_POKOJE) or list(self.mistnosti)
            v_pokoji_id = d.get(CONF_KLIMA_V_POKOJI)
            pokoje = []
            for pid, m in self.mistnosti.items():
                pokoje.append(kl.Pokoj(
                    nazev=m.nazev,
                    t_in=m.atributy.get("teplota_max"),
                    cil=m.cil, obsazeno=m.obsazeno,
                    pocita_se=pid in vybrane,
                    rh_in=m.atributy.get("vlhkost"),
                    okno_otevreno=m.okno_otevreno,
                ))
            v_pokoji = self.mistnosti.get(v_pokoji_id)

            dlouho = bool(self._zapnuto(d.get(CONF_KLIMA_DLOUHA)))
            # Plánovaná nepřítomnost je dlouhá hned, bez čekání na
            # hodiny — kalendář to ví dopředu.
            dlouho = dlouho or self.plan_pryc
            if not dlouho and self._prazdno_od is not None:
                hodin = float(d.get(CONF_KLIMA_DLOUHA_H, 24))
                dlouho = (cas_s - self._prazdno_od) > hodin * 3600

            susit = float(d.get(CONF_KLIMA_SUSIT_OD, 0)) or None
            nast = kl.Nastaveni(
                umi=d.get(CONF_KLIMA_UMI, "chlazeni"),
                v_pokoji=v_pokoji.nazev if v_pokoji else "",
                chladit_od=float(d.get(CONF_KLIMA_CHLADIT_OD, 1.0)),
                topit_od=float(d.get(CONF_KLIMA_TOPIT_OD, 1.0)),
                utlum_chlazeni=float(d.get(CONF_KLIMA_UTLUM_CHLAZENI, 28.0)),
                utlum_topeni=float(d.get(CONF_KLIMA_UTLUM_TOPENI, 16.0)),
                susit_od=susit, dlouha_nepritomnost=dlouho,
            )
            pamet = self._klima_pamet.setdefault(pod.subentry_id, kl.Pamet())
            r = kl.rozhodni(pokoje, pamet, cas_s, t_out,
                            self.topna_sezona, nast)

            ovladat = self.hodnoty.get((pod.subentry_id, "ovladat"), 0.0) > 0
            if ovladat and r.poslat:
                await self._klima_povel(entita, r)

            self.klimy[pod.subentry_id] = {
                "nazev": pod.title, "stav": r.stav, "cil": r.cil,
                "duvod": r.duvod, "podle": r.podle,
                "ovladani": "zapnuto" if ovladat else "jen sleduje",
                "dlouha_nepritomnost": dlouho,
                "pocita_se": [self.mistnosti[x].nazev
                              for x in vybrane if x in self.mistnosti],
            }

    async def _klima_povel(self, entita: str, r) -> None:
        """Přeloží rozhodnutí na povely climate."""
        rezimy = {kl.STAV_CHLADIT: "cool", kl.STAV_TOPIT: "heat",
                  kl.STAV_SUSIT: "dry", kl.STAV_UTLUM: "cool",
                  kl.STAV_VYP: "off"}
        try:
            await self.hass.services.async_call(
                "climate", "set_hvac_mode",
                {"entity_id": entita, "hvac_mode": rezimy[r.stav]},
                blocking=False)
            if r.cil is not None and r.stav != kl.STAV_VYP:
                await self.hass.services.async_call(
                    "climate", "set_temperature",
                    {"entity_id": entita, "temperature": r.cil},
                    blocking=False)
            _LOGGER.info("NaPohodu: klimatizace %s -> %s %s (%s)",
                         entita, r.stav, r.cil or "", r.duvod)
        except Exception as e:  # pragma: no cover
            _LOGGER.warning("NaPohodu: klimatizace %s selhala: %s", entita, e)

    @staticmethod
    def _bez_okna(okruh) -> list[str]:
        """Co říct místnosti, která okno neovládá."""
        if okruh["pod"] is not None:
            return [f"okno tady neovládáme, vzduch sdílíme s oblastí "
                    f"{okruh['nazev']}"]
        return ["okno tady neovládáme, o vzduch se stará jen čistička "
                "nebo ventilátor"]

    @staticmethod
    def _diagnostika(okna, otevreno, v, pamet, nast) -> list[str]:
        """Co brání větrání. U místnosti bez okna nemá o čem mluvit."""
        if not okna:
            return ["okno tady neovládáme"]
        if otevreno:
            return ["větrá se"]
        return core.duvody(v, pamet, nast) or ["nic nebrání"]

    async def _mistnost_krok(self, p, u, okruh, uprava, t_out, rh_out, dest,
                             doma, vitr_blokuje, je_noc, hodina, cas_s,
                             noc_od, noc_do, slunce_el):
        """Rozhodne o oknech jedné místnosti a případně je ovládne."""
        d = u["d"]
        g = {**self.entry.data, **self.entry.options}
        m = self.mistnosti[p.subentry_id]
        okna = d.get(CONF_OKNA) or []

        # místní čidla přebíjejí fasádu — balkon má jiný vzduch
        t_ven = self._cislo(d.get(CONF_T_VENKU_M), t_out)
        rh_ven = self._cislo(d.get(CONF_RH_VENKU_M), rh_out)

        # déšť: každé okno snese jinak, u některých nevadí vůbec
        prah_deste = float(d.get(CONF_DEST_PRAH, 0.3))
        i_kdyz_nikdo = bool(d.get(CONF_I_KDYZ_NIKDO, False))

        vynuceno = any(self._zapnuto(e) for e in (d.get(CONF_VYNUCENO_M) or []))

        v = core.Vstup(
            co2=max(okruh["co2"], uprava.prevzate_co2,
                    self.narazove_co2 if self.narazove_bezi else 0.0),
            # Prach z vlastního zvlhčovače se nepočítá: ultrazvukový
            # rozprašuje minerály z vody a čidlo je vidí jako PM.
            # Zvlhčovač v jedné místnosti zóny zvedne prach i vedle,
            # pokud jsou dveře otevřené — vzduch je společný, takže
            # i ten vlastní aerosol se musí ignorovat společně.
            #
            # Při nárazovém větrání se sem přidá nejhorší prach z bytu,
            # stejně jako u CO2: o ten průvan jde. Posílá se jen prach
            # z okruhů bez zvlhčovače, takže i místnost, která svůj
            # vlastní aerosol ignoruje, se otevře kvůli skutečnému
            # prachu odjinud.
            pm25=max(0.0 if self._zvlhcuje_na(p.subentry_id)
                     else okruh["pm25"],
                     self.narazove_pm if self.narazove_bezi else 0.0),
            pm10=0.0 if self._zvlhcuje_na(p.subentry_id)
            else okruh["pm10"],
            pm_platny=okruh["pm_platny"],
            # žádost od souseda v zóně, který okno nemá
            cizi_chlazeni=bool(okruh.get("cizi_chlazeni")) and bool(okna),
            cizi_ohrev=bool(okruh.get("cizi_ohrev")) and bool(okna),
            pm25_venku=self._cislo(g.get(CONF_PM25_VENKU)),
            pm10_venku=self._cislo(g.get(CONF_PM10_VENKU)),
            t_in=self._min(d.get(CONF_TEPLOTY), 21.0),
            t_in_max=self._max(d.get(CONF_TEPLOTY), None),
            t_out=t_ven, rh_out=rh_ven, cil=m.cil,
            dest=dest, vitr_blokuje=vitr_blokuje,
            doma=doma or i_kdyz_nikdo,
            # Povel z plánu. Narozdíl od „nikdo není doma" ho
            # zaškrtnutí „Větrat i když nikdo není doma" neobejde:
            # je to povel, ne informace o tom, kdo kde je.
            plan_zavreno=bool(m.plan_zavreno or self.plan_zavrit_byt),
            # Noční režim se řídí klidem TÉHLE místnosti, ne oblasti.
            # Spánek v obýváku nemá kuchyni zavřít okno, když má klid
            # nastavený na spánek a sama se v ní nespí.
            smog=bool(self._zapnuto(g.get(CONF_SMOG))),
            vetrat=any(self._zapnuto(e)
                       for e in (d.get(CONF_VETRAT) or [])),
            spanek=m.klid,
            vynuceno=vynuceno,
            hodina=hodina, cas_s=cas_s,
            zastupce=uprava.zastupce is not None,
            narazove=self.narazove_bezi,
            # Samotné počasí, bez ohledu na vzduch: chlazení a ohřev
            # nárazové větrání nespouští, ale zavřít hned se po nich
            # chce stejně — v mrazu je každá minuta navíc drahá.
            narazove_mozne=self.narazove,
            predvetrat=self.predvetrat,
        )
        nast = core.Nastaveni(
            # prahy z oblasti, ať se místnosti nepřetahují
            co2_otevrit=okruh["prahy"][CONF_CO2_OTEVRIT],
            co2_zavrit=okruh["prahy"][CONF_CO2_ZAVRIT],
            co2_noc=okruh["prahy"][CONF_CO2_NOC],
            co2_noc_krize=okruh["prahy"][CONF_CO2_NOC_KRIZE],
            dest_prah=prah_deste,
            projezd_s=float(d.get(CONF_PROJEZD_M, 120)),
            min_drzeni_s=self.hodnota(
                p.subentry_id, CONF_MIN_DRZENI,
                float(d.get(CONF_MIN_DRZENI, 20))) * 60,
            hyst_den_otevrit=self.hodnota(
                p.subentry_id, CONF_HYST_DEN_OTEVRIT,
                float(d.get(CONF_HYST_DEN_OTEVRIT, 2.5))),
            hyst_den_zavrit=self.hodnota(
                p.subentry_id, CONF_HYST_DEN_ZAVRIT,
                float(d.get(CONF_HYST_DEN_ZAVRIT, 1.0))),
            hyst_noc_otevrit=self.hodnota(
                p.subentry_id, CONF_HYST_NOC_OTEVRIT,
                float(d.get(CONF_HYST_NOC_OTEVRIT, 2.5))),
            hyst_noc_zavrit=self.hodnota(
                p.subentry_id, CONF_HYST_NOC_ZAVRIT,
                float(d.get(CONF_HYST_NOC_ZAVRIT, 1.0))),
            pro_pohodu=bool(self.hodnota(
                p.subentry_id, "pro_pohodu",
                float(bool(d.get(CONF_PRO_POHODU, True))))),
            rezerva_venku=self.hodnota(
                p.subentry_id, CONF_REZERVA_VENKU,
                float(d.get(CONF_REZERVA_VENKU, 2.0))),
            mez_dolni=self.hodnota(p.subentry_id, CONF_MEZ_DOLNI,
                                   float(d.get(CONF_MEZ_DOLNI, 18.0))),
            mez_horni=self.hodnota(p.subentry_id, CONF_MEZ_HORNI,
                                   float(d.get(CONF_MEZ_HORNI, 27.0))),
            noc_od=noc_od, noc_do=noc_do,
            rucni_klid_s=self.hodnota(
                p.subentry_id, CONF_RUCNI_KLID,
                float(d.get(CONF_RUCNI_KLID, 30))) * 60,
        )
        # Dřív to byl posuvník nula až deset, u kterého nebylo poznat,
        # co dělá. Teď se rovnou zadává, o kolik stupňů smí teplota
        # při větrání klesnout.
        nast = replace(
            nast,
            chlazeni_min_venku=self.hodnota(
                p.subentry_id, CONF_CHLAZENI_MIN_VENKU,
                float(d.get(CONF_CHLAZENI_MIN_VENKU, 7.0))),
            narazove_odstup=self.hodnota(
                self.entry.entry_id, CONF_NARAZOVE_ODSTUP,
                float(g.get(CONF_NARAZOVE_ODSTUP, 15.0))),
            zmena_podminek=self.hodnota(
                self.entry.entry_id, CONF_ZMENA_PODMINEK,
                float(g.get(CONF_ZMENA_PODMINEK, 2.0))),
            nejdriv_znovu_s=self.hodnota(
                self.entry.entry_id, CONF_NEJDRIV_ZNOVU,
                float(g.get(CONF_NEJDRIV_ZNOVU, 60))) * 60,
            pm_prah=self.hodnota(p.subentry_id, CONF_PM_SPATNE,
                                 float(d.get(CONF_PM_SPATNE, 35.0))),
            pm_prah_cisto=self.hodnota(
                p.subentry_id, CONF_PM_CISTO,
                float(d.get(CONF_PM_CISTO, 20.0))))

        # Každá mez sama o sobě vypadá rozumně, konflikt s cílem je
        # vidět až dohromady. Bez tohohle by okno jen nefungovalo
        # a nebylo by poznat proč.
        potize = core.konflikt_mezi(
            m.cil, nast.hyst_den_otevrit, nast.hyst_den_zavrit,
            nast.mez_dolni, nast.mez_horni, t_ven,
            nast.rezerva_venku, nast.chlazeni_min_venku)
        m.atributy["konflikt_mezi"] = potize or None
        if potize and self._konflikt_hlasen.get(p.subentry_id) != potize:
            self._konflikt_hlasen[p.subentry_id] = potize
            _LOGGER.warning("NaPohodu: %s — %s", m.nazev, "; ".join(potize))
            await self._posli({**self.entry.data, **self.entry.options},
                              "chyba", m.nazev, cas_s,
                              text="; ".join(potize))
        elif not potize:
            self._konflikt_hlasen.pop(p.subentry_id, None)

        vyk = self.vykonavaci.setdefault(
            p.subentry_id, vy.Vykonavac(self.hass, p.subentry_id))
        ovladat = self.hodnoty.get((p.subentry_id, "ovladat"), 0.0) > 0
        pamet = self.pameti.setdefault(p.subentry_id, core.Pamet())

        prvni_okno = okna[0] if okna else None
        projezd = float(d.get(CONF_PROJEZD_M, 120))
        stav_znamy = prvni_okno is None or self._stav(prvni_okno) is not None
        skutecne = self._okno_otevreno(prvni_okno, pamet, cas_s, projezd)

        # Fyzický kontakt ví o skutečnosti nejlíp — pozná i okno
        # otevřené rukou, o kterém pohon nic neví.
        kontakty = d.get(CONF_KONTAKT_M) or []
        rucne = any(self._zapnuto(e) for e in kontakty)
        if kontakty and not okna:
            # Bez ovládaného okna je kontakt jediná pravda, a to oběma
            # směry. Dřív umíval stav jen zapnout, takže po zavření
            # okna rukou zůstal zaseknutý na „otevřeno".
            skutecne = rucne
            stav_znamy = True
        elif kontakty and rucne and not skutecne:
            skutecne = True
            stav_znamy = True
        elif not okna and not kontakty:
            # Místnost bez ovládaného okna a bez kontaktu o žádném okně
            # neví. Brala se poslední vnitřní hodnota jádra, takže si
            # pokoj myslel, že se u něj větrá: v souhrnu přibývaly
            # minuty otevření a kontrola účinku „zavírala" okno, které
            # neexistuje — a každé takové rozhodnutí se počítalo jako
            # pohyb okna. Odtud ty stovky pohybů v obýváku.
            skutecne = False

        # Po dojezdu se povel a skutečnost musí shodovat. Když ne, sáhl
        # na okno člověk — rozdělaná akce se ruší a čeká se na nový
        # podnět, ať se s ním automatika nepřetahuje. Ochrana proti
        # větru a dešti tím dotčená není, ta je v rozhodování výš.
        # Dřív tu stálo „a jen když ruční klid doběhl". Druhé sáhnutí
        # během klidu se tím nezaznamenalo a odpočet běžel dál z toho
        # prvního — člověk otevřel okno a hned viděl, že mu zbývá
        # o půl hodiny míň, než si nastavil.
        if (ovladat and okna and stav_znamy
                and vyk.stav.posledni_okna
                and cas_s - pamet.cas_povelu_s > projezd * 2
                and pamet.otevreno != skutecne):
            _LOGGER.info(
                "NaPohodu: %s — okno je %s, ale posílal jsem %s. "
                "Ruční zásah, nechávám to na tobě.",
                m.nazev, "otevřené" if skutecne else "zavřené",
                "otevřít" if pamet.otevreno else "zavřít")
            core.rucni_zasah(pamet, nast, cas_s, skutecne)
            # Čísla do protokolu, ať se dá ověřit, s čím se počítalo:
            # odpočet se má rovnat nastavení, jinak je chyba mezi
            # šoupátkem a rozhodováním.
            _LOGGER.info(
                "NaPohodu: %s — ruční klid %.0f min, od %.0f do %.0f "
                "(teď %.0f), šoupátko %s, formulář %s",
                m.nazev, nast.rucni_klid_s / 60, pamet.rucni_od_s,
                pamet.rucni_do_s, cas_s,
                self.hodnoty.get((p.subentry_id, CONF_RUCNI_KLID)),
                d.get(CONF_RUCNI_KLID))
            vyk.stav.pulz_do_s = None

        pamet.otevreno = skutecne
        # syrová hodnota prachu kvůli ukončení doznívání po zvlhčovači
        self._pm_syrovy[p.subentry_id] = float(okruh["pm25"] or 0.0)
        self._uklid_dozvuku(cas_s)
        m.atributy["rucni_zasah"] = cas_s < pamet.rucni_do_s

        if ovladat and okna:
            r = core.rozhodni(v, pamet, nast)
        else:
            zaloha = copy.deepcopy(pamet)
            r = core.rozhodni(v, pamet, nast)
            naucene = pamet.pm_prumer
            self.pameti[p.subentry_id] = zaloha
            zaloha.pm_prumer = naucene
            zaloha.otevreno = skutecne
            pamet = zaloha

        provedeno = vyk.stav.posledni_popis
        if ovladat and okna and not stav_znamy:
            _LOGGER.debug("NaPohodu: %s — okno nehlásí stav, nic neposílám",
                          m.nazev)
        if ovladat and okna and stav_znamy:
            for okno in okna:
                vysledek = await vyk.okno(okno, r, cas_s, skutecne)
                if vysledek:
                    provedeno = vysledek
                    vyk.stav.posledni_popis = vysledek

            # Zavření po dojezdu pulzu musí nastavit i paměť jádra,
            # jinak neplatí minimální doba držení stavu a okno se
            # hned otevře znovu.
            if vyk.stav.pulz_zavrel:
                vyk.stav.pulz_zavrel = False
                pamet.otevreno = False
                pamet.pulzy_za_sebou += 1

                # Když větrání nezabírá, nemá cenu zkoušet to pořád
                # dokola stejně — pauza se s každým dalším pulzem
                # zdvojnásobí, nejvýš na hodinu. Typicky se to stane,
                # když tahle místnost větrá za jinou, jejíž vzduch
                # svým oknem skoro neovlivní.
                zaklad = core.PAUZA_PO_PULZU_S
                pauza = min(zaklad * 2 ** (pamet.pulzy_za_sebou - 1), 3600)
                pamet.pauza_do_s = cas_s + pauza
                m.atributy["pauza_po_pulzu_min"] = round(pauza / 60)

            # Totéž po nočním zavření kvůli chladu. Ložnice se prohřeje
            # za dvacet minut a bez pauzy se okno hned otevře znovu —
            # za noc z toho bylo dvanáct cyklů. Pauza je asymetrická,
            # zdržuje jen otevření, ne zavření, takže se nepřestřelí.
            g = {**self.entry.data, **self.entry.options}
            # routuje se podle strojového kódu, ne podle českého textu
            if r.kod == "vitr":
                await self._posli(g, "vitr", m.nazev, cas_s,
                                  **(self.vitr_pricina or {}))
            elif r.kod == "dest":
                await self._posli(g, "dest", m.nazev, cas_s, dest=dest)
            elif r.kod == "noc_krize":
                await self._posli(g, "nouzove", m.nazev, cas_s, co2=v.co2)
            elif r.kod == "obnova":
                await self._posli(
                    g, "obnova", m.nazev, cas_s,
                    co="otevřít" if r.akce is core.Akce.OTEVRIT
                    else "zavřít")
            elif r.akce is core.Akce.OTEVRIT:
                await self._posli(g, "vetrani", m.nazev, cas_s,
                                  duvod=r.duvod)
            elif r.akce is core.Akce.ZAVRIT:
                await self._posli(g, "zavirani", m.nazev, cas_s,
                                  duvod=r.duvod)
            if vyk.stav.chyby:
                await self._posli(g, "chyba", m.nazev, cas_s,
                                  text=vyk.stav.chyby[-1])
                vyk.stav.chyby.clear()

        # ---------- denní souhrn ----------
        sh = self.souhrn.setdefault(p.subentry_id, {
            "pohyby": 0, "minut_otevreno": 0, "co2_max": 0,
            "nejnizsi_teplota": None, "nouzove": 0})
        # Pohyby a minuty otevření se počítají jen tam, kde je co
        # otevírat. Bez okna i kontaktu jsou to čísla bez opory ve
        # skutečnosti: povel nikam nejde a „otevřeno" je jen vnitřní
        # stav jádra.
        ma_okno = bool(okna or kontakty)
        if ma_okno and r.akce is not core.Akce.NIC:
            sh["pohyby"] += 1
        if ma_okno and skutecne:
            sh["minut_otevreno"] += INTERVAL_S / 60
        sh["co2_max"] = max(sh["co2_max"], int(v.co2))
        if r.t_in_korig:
            sh["nejnizsi_teplota"] = min(
                sh["nejnizsi_teplota"] or 99, round(r.t_in_korig, 1))
        if "nouzov" in (r.duvod or ""):
            sh["nouzove"] += 1

        m.rozhodnuti = r
        m.okno_otevreno = skutecne
        # Která teplota zrovna rozhoduje. Vyjmenuje se jednou: text
        # v kartě, číslo pro ručičku i odchylka od cíle musí ukazovat
        # tutéž hodnotu, jinak si tři řádky protiřečí.
        t_max_cidlo = m.atributy.get("teplota_max") or v.t_in
        nejteplejsi = pamet.chladi or t_max_cidlo > m.cil
        t_rozhodna = t_max_cidlo if nejteplejsi else v.t_in
        popis_rozhodne = "nejteplejší" if nejteplejsi else "nejchladnější"
        m.atributy.update({
            "co2": v.co2, "uvnitr": r.t_in_korig,
            "venku": t_ven, "rosny_bod": r.rosny_bod, "rezim": pamet.rezim,
            "navrh": r.akce.value, "kod": r.kod, "provedeno": provedeno,
            "ovladani": ("zapnuto" if ovladat else "jen sleduje")
            + ("" if stav_znamy else " (okno nehlásí stav)"),
            "oblast": okruh["nazev"] if okruh["pod"] else None,
            "prahy_z_oblasti": {
                "otevrit": okruh["prahy"][CONF_CO2_OTEVRIT],
                "zavrit": okruh["prahy"][CONF_CO2_ZAVRIT],
                "noc": okruh["prahy"][CONF_CO2_NOC],
            },
            "zastupce": uprava.zastupce,
            "okna": okna,
            "kontakt_hlasi": rucne if kontakty else None,
            # Místnost bez ovládaného okna se vzduchu účastní, ale
            # o oknech jí nemá kdo nic říkat — hlášky o mezích poklesu
            # a o tom, co chybí k vyvětrání, by jen mátly.
            "co_dal": (core.ocekavani(v, pamet, nast) if okna
                       else self._bez_okna(okruh)),
            "co_bylo": (core.posledni(pamet, cas_s) if okna
                        else ["tato místnost okno neovládá"]),
            "vetrani_za_sebou": pamet.pulzy_za_sebou,
            "prach_zvenci": cas_s < pamet.pm_venku_horsi_do_s,
            "duvody": self._diagnostika(okna, skutecne, v, pamet, nast),
            "nocni_klid": f"{self._cas(noc_od)} – {self._cas(noc_do)}",
            "je_noc": je_noc,
            # běží zkrácený pulz, ne jestli je zrovna splněná podmínka
            "narazove_vetrani": pamet.narazove_pulz and skutecne,
            "narazove_mozne": self.narazove,
            # jak dlouho je otevřeno a jestli to zabírá
            # jak dlouho se ještě čeká, než se zkusí znovu
            # Jen když se opravdu čeká: u otevřeného okna je ten řádek
            # zbytečný a mátl, protože ukazoval nulu hned po zavření.
            "cekani_po_marnem": None if (skutecne or not pamet.marne_od_s)
            else (
                f"od marného pokusu {int((cas_s - pamet.marne_od_s) / 60)} "
                f"min, zkusím po změně venku o "
                f"{nast.zmena_podminek:.1f} °C, nejpozději za "
                f"{int((nast.nejdriv_znovu_s - (cas_s - pamet.marne_od_s)) / 60)}"
                f" min"),
            # Prach se uvádí jen tehdy, když se kvůli němu větrá —
            # jinak by u každého větrání svítila nula, která nic neříká.
            "ucinek": (
                f"CO2 {pamet.ucinek_co2:.0f} → {v.co2:.0f}, teplota "
                f"{pamet.ucinek_t_in:.1f} → {v.t_in:.1f} °C"
                + (f", PM2.5 {pamet.pm_pri_otevreni:.0f} → {v.pm25:.0f}"
                   if "PM" in (pamet.posledni_duvod or "")
                   and pamet.pm_pri_otevreni is not None else "")
                + f" za {int((cas_s - pamet.ucinek_od_s) / 60)} min"
                if skutecne and pamet.ucinek_od_s else None),
            # pravidla pro celý byt, aby nebyla pod každou místností
            "pevna_pravidla_bytu": core.pevna_pravidla_bytu(),
            # Globální nastavení nejsou posuvníky, protože nepatří
            # místnosti. Bez tohohle výpisu by na dashboardu nebyla
            # vidět vůbec a nikdo by nevěděl, že existují.
            "nastaveni_bytu": self._prehled_bytu(g),
            "doma_podle": self.doma_popis,
            # Co plán říká pro celý byt. Bez plánu nic a řádek se
            # v kartě skryje.
            "plan_bytu": self.plan_popis,
            # jak se dospělo k cílové teplotě, ať to není magie.
            # Odchylka místnosti se sem nepřidává: je vidět na svém
            # posuvníku a výsledek je v cílové teplotě.
            "cil_rozpad": self.cil_rozpad,
            # Stupnice s mezemi, ať je vidět, co nastavení dělají. Jen
            # tam, kde okno ovládáme — jinak ukazuje meze, podle kterých
            # se nikdy nic nestane, a stav okna, který neznáme.
            # Stupnice a předpověď. Argumenty se tu vyjmenovávají
            # jednou a obě funkce z nich berou totéž, aby nemohly
            # tvrdit každá jiné číslo.
            "teplotni_pasmo": None if not okna else core.pasmo_jen_stupnice(
                self._pasmo(nast, m, v, pamet, skutecne, cas_s,
                            p.subentry_id)),
            # věta zvlášť, aby ji karta mohla zalomit
            "teplotni_predpoved": None if not okna else core.pasmo_predpoved(
                self._pasmo(nast, m, v, pamet, skutecne, cas_s,
                            p.subentry_id)),
            "teplota_trend": self._trend(p.subentry_id, v, cas_s),
            # co si tahle místnost vyžádala od sousedů v zóně
            "zadost_sousedum": self._cizi_zadost.get(p.subentry_id) or None,
            # Nejteplejší a nejchladnější čidlo bývá totéž. Ukazuje se
            # to, podle kterého se zrovna rozhoduje: při chlazení a
            # horku nejteplejší, jinak nejchladnější.
            "teplota_rozhodna": f"{t_rozhodna:.1f} °C ({popis_rozhodne})",
            # Totéž jako číslo a vůči cíli. Ručička v kartě potřebuje
            # entitu, ne text, a odchylka se barví pevnými pásmy —
            # v absolutních stupních by se zelené pásmo hýbalo s cílem
            # a v noci by ukazovalo jinde, než kde doopravdy je.
            "odchylka_od_cile": round(t_rozhodna - m.cil, 1),
            # Hrany barevných pásem pro ručičky. Karta je jen přepíše
            # do YAML, počítat se mají tam, kde se podle nich i
            # rozhoduje — jinak by to byla druhá pravda.
            "pasma_ukazatelu": {
                "cil": round(m.cil, 1),
                "mez_dolni": nast.mez_dolni,
                "mez_horni": nast.mez_horni,
                "pasmo_den": nast.hyst_den_otevrit,
                "pasmo_noc": nast.hyst_noc_otevrit,
                "co2_otevrit": nast.co2_otevrit,
                "co2_noc": nast.co2_noc,
                "co2_krize": nast.co2_noc_krize,
                "pm_cisto": nast.pm_prah_cisto,
                "pm_spatne": nast.pm_prah,
            },
            "pevna_pravidla": core.pevna_pravidla(
                bool(m.klid),
                core._je_noc(self._hodina_ted, nast, bool(m.klid)),
                nast.co2_noc, nast.co2_noc_krize, nast.co2_zavrit),
            "vitr": self.vitr_stav,
            # Údaje o oknu se vynechají tam, kde žádné není — zpráva
            # i karta se pak skládají z toho, co doopravdy existuje.
            "dnes": {
                **({"pohyby": sh["pohyby"],
                    "otevreno_min": round(sh["minut_otevreno"])}
                   if ma_okno else {}),
                "co2_max": sh["co2_max"],
                "nejnizsi_teplota": sh["nejnizsi_teplota"],
                "nouzove_vetrani": sh["nouzove"],
            },
        })

        await self._stineni_krok(p, d, u, m, doma, slunce_el, cas_s)
        # O otevřeném okně musí mluvit fakt, ne vnitřní stav jádra:
        # kontakt ví o skutečnosti i tam, kde okno neovládáme, a bez
        # kontaktu i ovládaného okna o ní nevíme nic. K tomu okna
        # v zóně, se kterou místnost dýchá.
        # Skutečný stav si místnost zapíše, aby ho ostatní v zóně mohly
        # přečíst. Dřív se zóna ptala na poslední povel, který zůstane
        # „otevřít" i po ručním zavření nebo dojezdu pulzu — a zvlhčovač
        # pak hlásil otevřené okno, které už bylo zavřené.
        self.okna_stav[p.subentry_id] = (
            ((bool(okna) or bool(kontakty)) and skutecne)
            if (okna or kontakty) else None)
        okno_fakt = (self.okna_stav[p.subentry_id] is True
                     or self._okno_brani_zvlhcovani(p.subentry_id))
        await self._pomocnici_krok(p, d, m, okruh, cas_s, v.t_in, t_out,
                                   okno_fakt, doma)
        await self._topeni_krok(p, d, m, cas_s)

    async def _topeni_krok(self, p, d, m, cas_s: float) -> None:
        """Napíše hlavicím cílovou teplotu.

        Hlavice může být virtuální z Better Thermostatu i skutečná —
        integrace posílá jen cíl a režim, o zbytek se stará ona.
        """
        hlavice = list(d.get(CONF_CLIMATE) or [])
        m.atributy["odvzdusneni"] = False
        if not hlavice:
            m.atributy["topeni"] = "hlavice nenastavená"
            m.atributy["topeni_rezim"] = "nenastaveno"
            m.atributy["topeni_hlavice"] = None
            return
        if self.hodnoty.get((p.subentry_id, "ovladat_topeni"), 0.0) <= 0:
            m.atributy["topeni"] = "neovládám, přepínač je vypnutý"
            return

        odvzdusneni_h = float(d.get(CONF_ODVZDUSNENI_H, 24))
        odvzdusneni = (self._sezona_od is not None and odvzdusneni_h > 0
                       and cas_s - self._sezona_od < odvzdusneni_h * 3600)

        # Hlavice nemá topit proti otevřenému oknu, a to ani tehdy,
        # když větrá soused v zóně za nás — místnost bez vlastního okna
        # by jinak o větrání vůbec nevěděla.
        okno_v_zone = m.okno_otevreno or self._vetra_se_za(p.subentry_id)
        povel = vy.cil_topeni(
            m.cil, okno_v_zone,
            self.hodnota(p.subentry_id, CONF_UTLUM,
                         float(d.get(CONF_UTLUM, 16.0))),
            self.topna_sezona,
            False,
            odvzdusneni, float(d.get(CONF_ODVZDUSNENI_T, 28.0)),
            pri_oknu=d.get(CONF_TOPIT_PRI_OKNU, "nechat"),
            sezonu_ridi_hlavice=bool(
                d.get(CONF_SEZONU_RIDI_HLAVICE, True)),
            znacka_okno=float(d.get(CONF_ZNACKA_OKNO, 5.5)),
            znacka_mimo=float(d.get(CONF_ZNACKA_MIMO, 7.7)))

        vyk = self.vykonavaci.setdefault(
            p.subentry_id, vy.Vykonavac(self.hass, p.subentry_id))
        # Útlumy se odečítají až od povelu pro hlavice, ne od cíle
        # místnosti — jinak by se posunuly i prahy pro větrání
        # a stínění, které s topením nemají co dělat.
        g = {**self.entry.data, **self.entry.options}
        utlum_noc = core.nocni_utlum(
            self._hodina_ted, self._noc_od, self._noc_do,
            # Posun se zadává se znaménkem: mínus topit míň. Jádro
            # bere útlum, tedy kladné číslo, proto se obrací.
            -self.hodnota(p.subentry_id, CONF_NOC_POSUN,
                          float(d.get(CONF_NOC_POSUN, 0.0))),
            float(g.get(CONF_NOC_PREDSTIH, 60)),
            spanek=bool(m.klid))

        utlum_pryc = 0.0
        utlum_plan = 0.0
        pryc = float(g.get(CONF_PRYC_UTLUM, 0.0))
        predstih = float(g.get(CONF_NOC_PREDSTIH, 60))
        if pryc > 0 and self._prazdno_od is not None:
            hodin = float(g.get(CONF_PRYC_PO, 2.0))
            # Plánovaná nepřítomnost se nemusí odsedět: kalendář ví
            # dopředu, že se nikdo nevrátí, a stejně tak ví, kdy
            # skončí — útlum proto včas povolí, aby se stihlo nahřát.
            if cas_s - self._prazdno_od >= hodin * 3600 or self.plan_pryc:
                utlum_pryc = pryc
        # „Nikdo tu nebude" utlumí jednu místnost, i když je byt
        # obsazený. Vlastní číslo pro to nezavádíme: bere se tentýž
        # útlum jako pro prázdný byt, protože víc hodnot na totéž je
        # jen víc míst, kde se dá nastavit něco jiného. Povolí se se
        # stejným předstihem, aby se místnost stihla nahřát.
        if pryc > 0 and not utlum_pryc and m.plan_prazdno:
            do_s = m.plan_prazdno_do_s
            if do_s is None or (do_s - cas_s) > predstih * 60:
                utlum_plan = pryc

        celkem = round(utlum_noc + utlum_pryc + utlum_plan, 2)
        if celkem:
            povel = replace(povel, cil=round(povel.cil - celkem, 1)
                            if povel.cil is not None else None)
        m.atributy["topeni_utlum"] = [
            x for x in (f"noc {-utlum_noc:+.1f} °C" if utlum_noc else "",
                        f"nikdo doma -{utlum_pryc:.1f} °C" if utlum_pryc
                        else "",
                        f"plán: nikdo tu nebude -{utlum_plan:.1f} °C"
                        if utlum_plan else "") if x] or None

        poslano = await vyk.topeni(
            hlavice, povel, cas_s,
            float(g.get(CONF_TOPENI_OBNOVA, 30)) * 60)

        # Co hlásí sama hlavice. Bez toho bychom tvrdili, co jsme poslali,
        # a ona mohla dělat něco jiného — třeba proto, že si sezónu
        # určuje podle venkovní teploty sama.
        skutecnost = []
        for h in hlavice:
            st = self._stav(h)
            if st is None:
                continue
            teplota = st.attributes.get("temperature")
            skutecnost.append(
                f"{st.state}" + (f" na {teplota} °C" if teplota else ""))

        m.atributy["topeni"] = poslano or (
            f"{povel.cil:.1f} °C — {povel.duvod}"
            if povel.cil is not None else None)
        m.atributy["topeni_rezim"] = (
            povel.rezim if povel.rezim else "řídí hlavice sama")
        # Proč se nic neposlalo. Bez tohohle člověk kouká na „řídí
        # hlavice sama" a neví, jestli topí, nebo ne.
        vypnuta = any(str(x).startswith("off") for x in skutecnost)
        if poslano:
            m.atributy["topeni_poslano"] = poslano
        elif vypnuta and povel.rezim is None:
            m.atributy["topeni_poslano"] = (
                "nic — hlavice je vypnutá a rozhodla tak sama; zapnutí "
                "jí necháváme, protože to máš tak nastavené")
        elif povel.cil is None:
            m.atributy["topeni_poslano"] = "nic — teplotu si řídí hlavice"
        else:
            # Rozlišit, jestli hlavice opravdu stojí na našem cíli, nebo
            # jen čekáme — dřív to tvrdilo totéž v obou případech.
            hlasi = None
            for h in hlavice:
                st = self._stav(h)
                if st is not None:
                    hlasi = self._cislo_z(st.attributes.get("temperature"))
                    break
            if (hlasi is not None and povel.cil is not None
                    and abs(hlasi - povel.cil) >= vy.TOPENI_ZMENA_MIN):
                m.atributy["topeni_poslano"] = (
                    f"nic — hlavice hlásí {hlasi:.1f} °C místo "
                    f"{povel.cil:.1f} °C, čekám na klid mezi povely")
            else:
                m.atributy["topeni_poslano"] = "nic — hlavice už na tom stojí"
        m.atributy["topeni_hlavice"] = ", ".join(skutecnost) or None
        m.atributy["odvzdusneni"] = odvzdusneni

    def plan_skupiny(self) -> dict[str, list[str]]:
        """Skupiny pro ostatní moduly. Jen jiné jméno pro totéž."""
        return self._skupiny()

    def _skupiny(self) -> dict[str, list[str]]:
        """Skupiny místností pro plánování: jméno na seznam členů.

        Členství se drží jmény místností, ne jejich identifikátory:
        plán se čte podle jména a tohle je jediná věc, která se
        v kalendáři i v zprávě ukáže člověku.
        """
        return {s.title: list(s.data.get(CONF_SKUPINA_MISTNOSTI) or [])
                for s in self._podentity(PODENTITA_SKUPINA)}

    def plan_vlastni(self, druh: str, mistnost: str | None,
                     cas_s: float) -> pl.Udalost:
        """Co o téhle věci říká vlastní plán.

        Čte se rovnou ze záznamů, ne přes kalendářovou entitu: význam
        je v nich uložený, takže odpadá hádání z názvu i okružní cesta
        přes službu.
        """
        ted = dt_util.now()
        okno_od = ted - timedelta(days=1)
        okno_do = ted + timedelta(days=14)
        skupiny = self._skupiny()
        vyskyty = []
        for z in self._vlastni_plan:
            if not pz.obsahuje(z.get("druh", ""), druh):
                continue
            if not pz.patri(z, mistnost, skupiny):
                continue
            vyskyty += pz.rozbal(z, okno_od, okno_do, rrulestr)
        nejblizsi = pz.nejblizsi(vyskyty, ted)
        if nejblizsi is None:
            return pl.Udalost()
        od, do = nejblizsi
        zdroj = "plán"
        if od <= ted < do:
            return pl.Udalost(bezi=True, zdroj=zdroj,
                              do_s=cas_s + (do - ted).total_seconds())
        return pl.Udalost(bezi=False, zdroj=zdroj,
                          od_s=cas_s + (od - ted).total_seconds())

    def plan_cil_mistnosti(self, mistnost: str) -> float | None:
        """Naplánovaná cílová teplota, pokud zrovna platí.

        Je to konečný cíl: přebíjí adaptivní normu i posun místnosti,
        protože přesně proto se zadává.
        """
        ted = dt_util.now()
        skupiny = self._skupiny()
        for z in self._vlastni_plan:
            if z.get("druh") != "cil" or z.get("cil") is None:
                continue
            if not pz.patri(z, mistnost, skupiny):
                continue
            for od, do in pz.rozbal(z, ted - timedelta(days=1),
                                    ted + timedelta(days=1), rrulestr):
                if od <= ted < do:
                    return float(z["cil"])
        return None

    def plan_zaznamy(self) -> list[dict]:
        """Uložené záznamy plánu i s časy jako datum, ne text."""
        return self._vlastni_plan

    def plan_z_nazvu(self, nazev: str) -> tuple:
        """Co znamená událost založená ručně v panelu Kalendář.

        Panel nic jiného než název nenabízí, takže se tady čte zpátky
        to, co píšeme my. Čemu nerozumíme, zůstane uložené a objeví se
        v kartě — tiše to zahodit by bylo horší.

        Vrací druh, místnost, skupinu a cíl. Jméno před dvojtečkou se
        porovná se skupinami: co není skupina, je místnost.
        """
        text = (nazev or "").strip()
        kdo = None
        if ":" in text:
            pred, _, za = text.partition(":")
            if pred.strip().lower() != "napohodu":
                kdo = pred.strip()
            text = za.strip()
        skupina = kdo if kdo in self._skupiny() else None
        mistnost = None if skupina else kdo
        text = text.lower()
        if text.startswith("cíl"):
            cislo = text.replace("°c", "").replace(",", ".")
            cislo = "".join(z for z in cislo if z.isdigit() or z == ".")
            try:
                return ("cil", mistnost, skupina, float(cislo))
            except ValueError:
                return ("nerozumim", mistnost, skupina, None)
        # Od nejdelšího popisu: „nikdo tu nebude, zavřená okna" začíná
        # textem „nikdo tu nebude", takže od kratšího by se složený
        # povel poznal jen jako jeho první polovina.
        for druh, popis in pz.PODLE_DELKY:
            if text.startswith(popis):
                return (druh, mistnost, skupina, None)
        return ("nerozumim", mistnost, skupina, None)

    async def plan_zapis(self, zaznam: dict) -> None:
        self._vlastni_plan.append(zaznam)
        await self._uloz_plan()
        await self.async_request_refresh()

    async def plan_smaz(self, uid: str) -> None:
        self._vlastni_plan = [z for z in self._vlastni_plan
                              if z.get("uid") != uid]
        await self._uloz_plan()
        await self.async_request_refresh()

    async def _uloz_plan(self) -> None:
        """Časy se ukládají textem, protože datum se do JSONu nevejde."""
        await self._uloziste_planu.async_save(
            [{**z, "od": z["od"].isoformat(), "do": z["do"].isoformat()}
             for z in self._vlastni_plan if z.get("od") and z.get("do")])

    async def _nacti_plan(self) -> None:
        ulozene = await self._uloziste_planu.async_load() or []
        self._vlastni_plan = []
        for z in ulozene:
            od = dt_util.parse_datetime(str(z.get("od")))
            do = dt_util.parse_datetime(str(z.get("do")))
            if od and do:
                self._vlastni_plan.append({**z, "od": od, "do": do})

    def nabidka_planu(self) -> list[pz.Volba]:
        """Co jde naplánovat z dashboardu."""
        return pz.nabidka(
            [p.title for p in self._podentity(PODENTITA_MISTNOST)],
            list(self._skupiny()))

    async def naplanuj(self, popis: str, od, do) -> str:
        """Založí událost ve vlastním kalendáři plánu.

        Vrací větu pro člověka — tlačítko samo o sobě nic neukáže
        a bez zpětné vazby se nedá poznat, jestli se událost založila.

        Včetně opakování: zapisuje se do vlastního záznamu, ne akcí
        `calendar.create_event`, která pole pro opakování nemá.
        """
        volba = next((v for v in self.nabidka_planu() if v.popis == popis),
                     None)
        if volba is None:
            self.plan_vysledek = f"neznámá volba: {popis}"
            return self.plan_vysledek
        potiz = pz.zkontroluj(od, do)
        if potiz:
            self.plan_vysledek = potiz
            return self.plan_vysledek
        # Hodnoty šoupátek se čtou přes hodnota(), stejně jako
        # všechno ostatní — jinak by platil jen formulář.
        kolikrat = self.hodnota(self.entry.entry_id, CONF_PLAN_KOLIKRAT, 8.0)
        cil = self.hodnota(self.entry.entry_id, CONF_PLAN_CIL, 21.0)
        pravidlo = pz.pravidlo(self.plan_opakovani, int(kolikrat or 0))
        await self.plan_zapis({
            "uid": uuid.uuid4().hex,
            "druh": volba.druh,
            "mistnost": volba.mistnost,
            # Skupina se drží jménem, aby platila i pro místnost, která
            # se do ní přidá později. Opis členů je záloha pro případ,
            # že skupinu smažeš — plán pak nespadne.
            "skupina": volba.skupina,
            "clenove": (self._skupiny().get(volba.skupina, [])
                        if volba.skupina else None),
            "cil": round(float(cil), 1) if volba.druh == "cil" else None,
            "od": od, "do": do, "rrule": pravidlo, "popis": "",
            # Lichý a sudý týden se v pravidle vyjádřit nedá, drží se
            # zvlášť a uplatní se při rozbalování.
            "parita": pz.parita(self.plan_opakovani),
            "kolikrat": int(kolikrat or 0),
        })
        kolik = (f", opakovaně: {self.plan_opakovani}"
                 + (f", {int(kolikrat)}×" if kolikrat else "")
                 if pravidlo else "")
        self.plan_vysledek = (
            f"{pz.nazev(volba.druh, volba.mistnost or volba.skupina, cil)}: "
            f"{od:%-d.%-m. %H:%M} – {do:%-d.%-m. %H:%M}{kolik}")
        _LOGGER.info("NaPohodu: %s", self.plan_vysledek)
        return self.plan_vysledek

    def _plan_popis(self, slova, prazdno_ent, plno_ent, prazdno: pl.Udalost,
                    plno: pl.Udalost, cas_s: float) -> str | None:
        """Co plán říká — a když neříká nic, tak aspoň že je nastavený.

        Tiché nic je správné chování, ale při zakládání je to k ničemu:
        člověk vybere kalendář, nic se neukáže a nemá jak poznat, jestli
        se nečte, nebo jen zrovna nic neplatí. Řádek proto vypíše, co je
        nastavené, a zvlášť upozorní na entitu, která neexistuje.
        """
        text = pl.popis(prazdno, plno, cas_s, slova)
        if text:
            return text
        nastavene = list(prazdno_ent or []) + list(plno_ent or [])
        if not nastavene:
            return None
        chybi = [e for e in nastavene if self._stav(e) is None]
        if chybi:
            return "entita chybí: " + ", ".join(chybi)
        return f"nastaveno ({', '.join(nastavene)}), teď nic neplatí"

    async def _plan(self, entity, cas_s: float) -> pl.Udalost:
        """Co říká kalendář nebo rozvrh: platí to teď a kdy se to změní.

        Stav obojího je zapnuto/vypnuto, takže „teď" se čte stejně.
        Pro „kdy" má rozvrh atribut `next_event`, kalendář odpověď
        akce `calendar.get_events`. Když se nic z toho nepovede,
        zůstane jen „teď" — plán se pak neplánuje dopředu, ale ani
        nelže.

        Chybějící nebo smazaná entita se tiše přeskočí: plán prostě
        neplatí a zbytek integrace jede jako bez něj.
        """
        jednotlive = []
        for eid in (entity or []):
            st = self._stav(eid)
            if st is None:
                continue
            bezi = str(st.state).lower() == "on"
            if eid.startswith("calendar."):
                jednotlive.append(await self._plan_kalendar(eid, bezi, cas_s))
                continue
            kdy = self._cas_z(st.attributes.get("next_event"), cas_s)
            jednotlive.append(pl.Udalost(
                bezi=bezi, do_s=kdy if bezi else None,
                od_s=None if bezi else kdy, zdroj=eid))
        return pl.slouc(jednotlive) if jednotlive else pl.Udalost()

    async def _plan_kalendar(self, eid: str, bezi: bool,
                             cas_s: float) -> pl.Udalost:
        """Nejbližší událost kalendáře. Bez ní platí jen „teď"."""
        try:
            odpoved = await self.hass.services.async_call(
                "calendar", "get_events",
                {"entity_id": eid, "duration": {"hours": 48}},
                blocking=True, return_response=True)
        except Exception as e:      # pragma: no cover - cizí integrace
            _LOGGER.debug("NaPohodu: %s neodpověděl na get_events: %s",
                          eid, e)
            return pl.Udalost(bezi=bezi, zdroj=eid)
        udalosti = ((odpoved or {}).get(eid) or {}).get("events") or []
        if not udalosti:
            return pl.Udalost(bezi=bezi, zdroj=eid)
        prvni = udalosti[0]
        if bezi:
            return pl.Udalost(bezi=True, zdroj=eid,
                              do_s=self._cas_z(prvni.get("end"), cas_s))
        return pl.Udalost(bezi=False, zdroj=eid,
                          od_s=self._cas_z(prvni.get("start"), cas_s))

    def _cas_z(self, hodnota, cas_s: float) -> float | None:
        """Čas z entity na tutéž osu, na jaké běží jádro.

        Kalendář vrací text i datetime a celodenní událost jen datum.
        Počítá se rozdíl proti teď, ne absolutní hodnota — jádro měří
        v sekundách od spuštění stroje, ne v kalendářním čase.
        """
        if hodnota in (None, ""):
            return None
        kdy = dt_util.parse_datetime(str(hodnota))
        if kdy is None:
            den = dt_util.parse_date(str(hodnota))
            if den is None:
                return None
            kdy = dt_util.start_of_local_day(den)
        return cas_s + (dt_util.as_utc(kdy) - dt_util.utcnow()).total_seconds()

    @staticmethod
    def _narazove_rozdil(t_out: float | None,
                         cile: dict[str, float]) -> tuple[float, str]:
        """Jak daleko je venku od toho, co byt chce — a kdo rozhoduje.

        Rozhoduje místnost, pro kterou je větrání **nejdražší**: pokoj,
        který chce 22 a má venku 3, platí za otevřené okno plnou cenu
        bez ohledu na to, že dílna vedle chce jen 18 a je jí to skoro
        jedno. Na obě strany to funguje stejně — v zimě vyhraje pokoj
        s nejvyšším cílem, v létě ten s nejnižším.
        """
        if t_out is None:
            return 0.0, ""
        if not cile:
            return abs(t_out - 22.0), ""
        kdo = max(cile, key=lambda x: abs(t_out - cile[x]))
        return abs(t_out - cile[kdo]), kdo

    @staticmethod
    def _narazove_vzduch(okruhy: list[dict]) -> list[tuple]:
        """Co se do nárazového větrání počítá: hodnota a její dva prahy.

        CO2 za každý okruh a prach taky — v mrazu je krátké vyvětrání
        průvanem lepší než půlhodina jedním oknem, a to platí na prach
        stejně jako na vydýchaný vzduch. Okruh, kam dosáhne aerosol ze
        zvlhčovače, se do prachu nepočítá: není co vyvětrat.
        """
        vzduch = []
        for o in okruhy:
            prahy = o.get("prahy")
            if not prahy:
                continue
            vzduch.append((o["co2"], prahy[CONF_CO2_OTEVRIT],
                           prahy[CONF_CO2_ZAVRIT]))
            if not o.get("pm_od_zvlhcovace"):
                # Bez běžícího ventilátoru je měření prachu nejisté,
                # takže platí vyšší práh — stejně jako v rozhodování
                # jedné místnosti. Jinak by nejisté číslo otevřelo
                # okna po celém bytě.
                spatne = prahy[CONF_PM_SPATNE]
                if o.get("pm_platny") is False:
                    spatne = max(spatne, core.Nastaveni.pm_prah_bez_ventilatoru)
                vzduch.append((o.get("pm25") or 0.0, spatne,
                               prahy[CONF_PM_CISTO]))
        return vzduch

    @staticmethod
    def _narazove_pokracuje(vzduch: list[tuple], bezi: bool) -> bool:
        """Běží nárazové větrání? Hystereze jako u všeho ostatního.

        Zapne práh otevření, vypne až práh zavření, mezi tím drží.
        Bez toho injekce nejhoršího vzduchu do všech místností skončila
        už v pásmu mezi prahy: pomocné místnosti spadly na své vlastní
        čisté hodnoty, zavřely jako vyvětrané a iniciátor dojížděl sám
        — bez průvanu, kvůli kterému se otevíralo všude.

        Každý okruh se měří svými prahy, ne nejvyššími v bytě: okruh
        s přísnějším prahem má větrání spustit, i když je jinde práh
        vyšší, a držet ho, dokud není čistý.
        """
        if not vzduch:
            return False
        if any(h > otevrit for h, otevrit, _ in vzduch):
            return True
        if all(h < zavrit for h, _, zavrit in vzduch):
            return False
        return bezi

    @staticmethod
    def _stav_pomocnika(entity, bezi) -> str:
        """Čitelný stav pomocného zařízení.

        Prázdný atribut se v kartě ukáže jako Neznámý a člověk pak neví,
        jestli zařízení nemá, nebo jen ještě nedostalo povel.
        """
        if not entity:
            return "nenastaveno"
        if bezi is None:
            return "zatím bez povelu"
        return "běží" if bezi else "stojí"

    async def _pomocnici_krok(self, p, d, m, okruh, cas_s: float,
                              t_in: float,
                              t_out: float | None, otevreno: bool,
                              doma: bool) -> None:
        """Čistička řeší prach, zvlhčovač vlhkost. Okno na to nemusí.

        Venkovní teplota a stav okna jsou tu kvůli zvlhčovači: podle
        nich se počítá, kdy se orosí sklo, a při otevřeném okně se
        nezvlhčuje vůbec.
        """
        vyk = self.vykonavaci.setdefault(
            p.subentry_id, vy.Vykonavac(self.hass, p.subentry_id))

        cisticka = d.get(CONF_CISTICKA) or []
        if cisticka:
            # Totéž pro čističku: honit aerosol z vlastního zvlhčovače
            # znamená držet ji v jednom kole a nic tím nevyčistit.
            zvlhcuje = self._zvlhcuje_na(p.subentry_id)
            pm = 0 if zvlhcuje else (okruh["pm25"] or 0)
            pm10 = 0 if zvlhcuje else (okruh["pm10"] or 0)
            # Vypíná se níž, než zapíná, aby nepřepínala na hraně.
            # PM10 se odvozuje z téhož prahu, běžně bývá zhruba
            # jedenapůlkrát vyšší.
            od = float(d.get(CONF_CISTICKA_OD, 35))
            do = od * 0.6
            zapnout = None
            if (pm > od or pm10 > od * 1.5) and m.obsazeno:
                zapnout = True
            elif pm < do and pm10 < do * 1.5:
                zapnout = False
            m.atributy["cisticka"] = await vyk.zarizeni(
                cisticka, zapnout, "čistička")
        m.atributy["prach_ze_zvlhcovace"] = (
            self._zvlhcuje_na(p.subentry_id) or None)
        m.atributy["cisticka_bezi"] = self._stav_pomocnika(
            d.get(CONF_CISTICKA), vyk.stav.zarizeni.get("čistička"))

        # vlhkost patří do atributů vždycky, když ji známe — nezávisle
        # na tom, jestli je čím odsávat nebo zvlhčovat
        rh_in = self._cislo(d.get(CONF_RH_VNITRNI))
        m.atributy["vlhkost"] = (
            rh_in if rh_in is not None else "čidlo nenastaveno")

        # zvlhčovač: v zimě vysychají sliznice, v paneláku běžně pod 30 %
        zvlhcovac = d.get(CONF_ZVLHCOVAC) or []
        if zvlhcovac and rh_in is not None:
            # Dolní mez zapíná, horní vypíná. Pevných pět procent
            # nad minimem bylo nastavení, které nešlo ovlivnit, a horní
            # mez přitom v nastavení celou dobu byla — jen ji nikdo
            # nečetl.
            rh_min = self.hodnota(p.subentry_id, CONF_RH_MIN,
                                  float(d.get(CONF_RH_MIN, 38.0)))
            rh_max = max(self.hodnota(p.subentry_id, CONF_RH_MAX,
                                      float(d.get(CONF_RH_MAX, 60.0))),
                         rh_min + 2)

            # Kondenzace na skle: v mrazu je sklo chladné a rosný bod
            # ho dohoní dřív, než vlhkost dojde na nastavenou mez.
            podil = ZASKLENI_PODIL.get(d.get(CONF_ZASKLENI, "dvojsklo"),
                                       0.2)
            strop = (core.max_vlhkost(t_in, t_out, podil)
                     if t_out is not None else 100.0)
            duvod_stropu = ""
            if strop < rh_max:
                duvod_stropu = (f", kvůli orosení okna jen {strop:.0f} %")
                rh_max = max(strop, rh_min + 2)

            # Kdy smí běžet. Zvlhčovat prázdný pokoj je plýtvání
            # a zvlhčovat při otevřeném okně znamená zvlhčovat ulici.
            kdy = d.get(CONF_ZVLHCOVAC_KDY, "vzdy")
            ve_spanku = bool(self.hodnota(
                p.subentry_id, "zvlhcovac_ve_spanku",
                float(bool(d.get(CONF_ZVLHCOVAC_VE_SPANKU, True)))))
            smi = (not otevreno
                   and (ve_spanku or not m.klid)
                   and not (
                (kdy == "doma" and not doma)
                or (kdy == "v_pokoji" and not m.obsazeno)
                or (kdy == "pri_klidu" and not m.klid)))
            m.atributy["zvlhcovac_proc"] = (
                f"zapnu pod {rh_min:.0f} %, vypnu nad {rh_max:.0f} %, "
                f"teď {rh_in:.0f} %")
            zapnout = None
            if not smi:
                zapnout = False
            elif rh_in < rh_min:
                zapnout = True
            elif rh_in > rh_max:
                zapnout = False
            m.atributy["zvlhcovac_proc"] = (
                f"zapnu pod {rh_min:.0f} %, vypnu nad {rh_max:.0f} %"
                f"{duvod_stropu}, teď {rh_in:.0f} %"
                + ("" if smi else "; teď nesmí — " + (
                    "otevřené okno" if otevreno else {
                        "doma": "nikdo není doma",
                        "v_pokoji": "v pokoji nikdo není",
                        "pri_klidu": "nespí se tu"}.get(kdy, ""))))
            m.atributy["zvlhcovac"] = await vyk.zarizeni(
                zvlhcovac, zapnout, "zvlhčovač")
            # Ultrazvukový zvlhčovač rozprašuje minerály z vody a čidlo
            # je vidí jako prach. Větrat ani čistit kvůli tomu nemá
            # smysl — je to jeho vlastní aerosol, ne vzduch zvenčí.
            # Ptát se musíme na stav zařízení, ne na jeho popis:
            # _stav_pomocnika vrací text a ten je pravdivý i tehdy,
            # když zvlhčovač stojí — pak se prach pořád sváděl na něj
            # a kvůli prachu se nikdy neotevřelo okno.
            if vyk.stav.zarizeni.get("zvlhčovač"):
                self.zvlhcuje.add(p.subentry_id)
                self._dozvuk.pop(p.subentry_id, None)
            elif p.subentry_id in self.zvlhcuje:
                # Aerosol v pokoji zůstává i potom, co zvlhčovač vypne.
                # Dokud prach neklesne do čistého pásma, bere se pořád
                # za jeho — jinak se hned po doběhu otevřelo okno kvůli
                # prachu, který se vyvětrat nedá.
                self.zvlhcuje.discard(p.subentry_id)
                self._dozvuk[p.subentry_id] = cas_s
        m.atributy["zvlhcovac_bezi"] = self._stav_pomocnika(
            d.get(CONF_ZVLHCOVAC), vyk.stav.zarizeni.get("zvlhčovač"))

    async def _stineni_krok(self, p, d, u, m, doma, slunce_el, cas_s):
        """Rozhodne o žaluziích místnosti. Slunce svítí do pokoje, ne do oblasti."""
        vyk_m = self.vykonavaci.setdefault(
            p.subentry_id, vy.Vykonavac(self.hass, p.subentry_id))

        # Nejdřív ověřit, kde žaluzie doopravdy jsou. Ruční přestavení
        # jinak zůstane skryté a večer se nic nepošle.
        zaluzie_mistnosti = d.get(CONF_ZALUZIE) or []
        prestaveno = []
        for z in zaluzie_mistnosti:
            st = self._stav(z)
            jede = st is not None and st.state in ("opening", "closing")
            byval = vyk_m.zkontroluj_polohu(
                z, self._poloha_krytu(z), cas_s, jede,
                tilt=self._naklopeni_krytu(z))
            if byval:
                prestaveno.append(f"{z}: bylo {byval}")
        m.atributy["prestaveno_rukou"] = prestaveno or None
        # Rozdíl, který se ještě potvrzuje. Povel se na takovou žaluzii
        # neposílá, ať se ruční zásah nepřebije dřív, než se pozná.
        m.atributy["zaluzie_overuji"] = sorted(vyk_m.stav.rozejiti) or None
        if prestaveno:
            # Polohu si člověk u žaluzií vybírá vědomě, takže se jí
            # chvíli nesahá. Ukládá se okamžik, ne hotový termín: když
            # se šoupátkem pohne, odpočet se přepočítá a neukazuje čas
            # podle hodnoty, která už neplatí.
            self.zaluzie_rukou(p.subentry_id, cas_s)

        klid_rukou = self.hodnota(
            p.subentry_id, CONF_RUCNI_KLID_ZALUZIE,
            float(d.get(CONF_RUCNI_KLID_ZALUZIE, 120))) * 60
        rukou_od = self._zaluzie_rukou.get(p.subentry_id)
        rukou_zbyva = (int((klid_rukou - (cas_s - rukou_od)) / 60) + 1
                       if rukou_od is not None and klid_rukou > 0
                       and cas_s - rukou_od < klid_rukou else 0)
        if rukou_od is not None and not rukou_zbyva:
            # Doběhlo to; záznam se zahodí, aby se na disku nedržel
            # okamžik, který už nic neznamená.
            self._zaluzie_rukou.pop(p.subentry_id, None)
            self._uloziste_stineni.async_delay_save(self._uloz_stineni, 10)
        # V řádku karty stojí za popiskem „ruční klid", takže stačí
        # zbytek času; celá věta je ve stavu stínění.
        m.atributy["zaluzie_rucni_klid"] = (
            f"ještě {rukou_zbyva} min" if rukou_zbyva else None)

        # Role se počítá vždycky, i když se žaluzie neovládají — jinak
        # by karta neměla co ukázat a graf by hlásil neznámo. Povel se
        # posílá až dole, podle přepínače.
        #
        # Každá žaluzie se rozhoduje sama: dvě okna v jednom pokoji míří
        # jinam a člověk je často chce řídit každé jinak.
        if zaluzie_mistnosti:
            t_max = m.atributy.get("teplota_max")
            t_min = m.atributy.get("teplota_min")
            mapa = d.get(CONF_STINENI_MAPA) or {}
            chovani = d.get(CONF_STINENI_CHOVANI) or {}
            st = vyk_m.stav
            pohyb = bool(u["sig"].cidlo) or bool(
                pr.indicie_aktivni(u["sig"], u["nast"]))

            cile, role_vse, duvody, co_dal = {}, {}, {}, {}
            vraceni = {}
            for z in zaluzie_mistnosti:
                vlastni = chovani.get(z) or {}

                def nastav(klic, vychozi):
                    # chování se nastavuje jen u žaluzie, ne u místnosti
                    return vlastni.get(klic, vychozi)

                zisk = m.slunce

                chtene = list(nastav(CONF_VYCHOZI_KDY, []) or [])
                podminky = []
                if "konec_klidu" in chtene:
                    podminky.append(not m.klid)
                if "rozednilo" in chtene:
                    podminky.append(slunce_el >= 0)
                vraceni[z] = chtene
                splneno = bool(podminky) and all(podminky)
                vratit = splneno and st.drive_splneno.get(z) is False
                st.drive_splneno[z] = splneno

                # Chladno má přednost. Jedno čidlo na slunci umí ukázat
                # víc než cíl, přestože je v pokoji o pár stupňů méně —
                # a zastínit kvůli němu znamenalo odříznout teplo, které
                # zrovna chybí. Navíc se tím rozjelo kmitání: po zastínění
                # čidlo vychladlo, žaluzie se odstínila a šlo to znovu.
                zima = t_min is not None and t_min < m.cil - 0.5
                horko = (not zima and t_max is not None
                         and t_max > m.cil - float(
                             d.get(CONF_STINENI_PREDSTIH, 1.0)))
                rezim = nastav(CONF_STINENI_REZIM, "vzdy")
                soukromi = nastav(CONF_SOUKROMI_KDY, "nikdy")

                role = vy.role_stineni(
                    zisk, 150.0, horko, zima, doma,
                    rezim=rezim, po_zapadu=slunce_el < 0, pohyb=pohyb,
                    soukromi_kdy=soukromi, v_pokoji=pohyb, klid=m.klid,
                    role_drive=st.posledni_role.get(z), vratit=vratit)

                st.posledni_role[z] = role
                role_vse[z] = role
                cile.update(vy.cile_zaluzii(role, {z: mapa.get(z, {})}))
                duvody[z] = vy.duvody_stineni(
                    role, zisk, 150.0, doma, slunce_el < 0, m.klid, rezim)
                co_dal[z] = vy.ocekavani_stineni(
                    role, zisk, 150.0, slunce_el < 0, m.klid, horko, zima,
                    soukromi, chtene)

            # Přiřazení může ukazovat na entitu, která neexistuje —
            # po přejmenování žaluzie nebo po poškozeném záznamu.
            # Povel na ni nemá smysl, jen by plnil zprávy. Tohle
            # vypadlo při přepisu na chování per žaluzie.
            chybi = [z for z in cile if self._stav(z) is None]
            for z in chybi:
                cile.pop(z, None)
            # Bez stavu ještě neznamená neexistující. Při startu se
            # integrace načítají postupně a Zigbee bývá hotové později
            # než my — žaluzie, která je v registru, se za chvíli
            # ozve. Hlásí se proto jen ta, kterou nezná ani registr.
            neni = [z for z in chybi if not self._v_registru(z)]
            m.atributy["zaluzie_chybi"] = neni or None
            if neni:
                _LOGGER.warning(
                    "NaPohodu: %s — přiřazení stínění ukazuje na "
                    "neexistující %s, přenastav Stavy žaluzií",
                    m.nazev, ", ".join(neni))

            m.atributy["stineni_mapa"] = mapa or None
            m.atributy["vraceni_vychoziho"] = {
                z: sorted(vraceni[z]) for z in vraceni if vraceni[z]} or None
            m.atributy["role_stineni"] = role_vse
            m.atributy["stineni_duvody"] = duvody
            m.atributy["stineni_co_dal"] = co_dal

        # Pojmenovaný stav známe jen tam, kam jsme sami poslali povel.
        # Skutečná poloha se dá přečíst vždycky, a právě ta člověka
        # zajímá, když je paměť prázdná.
        if not zaluzie_mistnosti:
            m.atributy["stineni"] = "žaluzie nenastavené"
            m.atributy["role_stineni"] = None
            m.atributy["zadana_poloha"] = {}
        elif self.hodnoty.get((p.subentry_id, "ovladat_stineni"), 0.0) <= 0:
            m.atributy["stineni"] = "neovládám, přepínač je vypnutý"
        elif rukou_zbyva:
            # Stejná dohoda jako u okna: po ručním zásahu se automatika
            # nepřetahuje. Tlačítko Srovnat žaluzie to obejde, protože
            # to je výslovný pokyn.
            m.atributy["stineni"] = (
                f"sáhl jsi na žaluzie, nechávám to na tobě "
                f"(ještě {rukou_zbyva} min)")
        elif cas_s - self._start_s < 600:
            # Po startu se žaluziemi deset minut nehýbe. Entity v té době
            # teprve naskakují a některé hlásí nesmysly — přítomnost třeba
            # „nikdo doma", i když je někdo doma. Pohyb by byl na základě
            # hodnot, kterým se ještě nedá věřit.
            zbyva = int((600 - (cas_s - self._start_s)) / 60) + 1
            m.atributy["stineni"] = (
                f"po startu čekám, než se stavy ustálí (ještě {zbyva} min)")
        else:
            stin = await vyk_m.stineni(
                cile, cas_s, float(d.get(CONF_KLID_STINENI_MIN, 15)))
            m.atributy["stineni"] = stin
            if stin:
                self._uloziste_stineni.async_delay_save(self._uloz_stineni, 10)
                # Proč zrovna teď — z diagnostiky těch žaluzií, které se
                # hýbou. Stejné důvody se neopakují.
                proc = []
                for z in cile:
                    for x in duvody.get(z) or []:
                        if x not in proc:
                            proc.append(x)
                await self._posli(
                    {**self.entry.data, **self.entry.options},
                    "zaluzie", m.nazev, cas_s,
                    co=stin.removeprefix("stínění: "),
                    duvod="; ".join(proc) or "změna")

        m.atributy["stineni_stav"] = dict(vyk_m.stav.posledni_stineni)
        m.atributy["zaluzie_poloha"] = {
            z: self._poloha_krytu(z) for z in (d.get(CONF_ZALUZIE) or [])}

    # ------------------------------------------------------------ detaily

    def _okno_otevreno(self, eid: str | None, pamet: core.Pamet,
                       cas_s: float = 0.0, projezd_s: float = 120.0) -> bool:
        """Skutečný stav okna, ale během jízdy se věří vlastnímu povelu.

        Pohon chvíli jede a po tu dobu hlásí starou polohu. Bez téhle
        pojistky by jádro vidělo zavřeno, chtělo otevřít znovu a naráželo
        na minimální dobu držení stavu — přesně to hlásí „čekám 1080 s“.
        """
        if cas_s - pamet.cas_povelu_s < projezd_s:
            return pamet.otevreno

        st = self._stav(eid)
        if st is None:
            return pamet.otevreno
        if st.state == "open":
            return True
        if st.state == "closed":
            return False
        poloha = st.attributes.get("current_position")
        if poloha is not None:
            return float(poloha) > 0
        return pamet.otevreno

    def _signaly(self, d: dict, doma: bool, hodina: float,
                 noc_od: float, noc_do: float) -> pr.Signaly:
        cidlo = self._zapnuto(d.get(CONF_PRITOMNOST))
        od_s, stari_s = self._stari_s(d.get(CONF_PRITOMNOST))
        je_noc = (hodina >= noc_od or hodina < noc_do) if noc_od > noc_do \
            else (noc_od <= hodina < noc_do)

        ind = {}
        for eid in (d.get(CONF_INDICIE_STAV) or []):
            o, s = self._stari_s(eid)
            ind[eid] = pr.StavIndicie(self._zapnuto(eid), o, s)
        prah = float(d.get(CONF_PRAH_VYKONU, 15))
        for eid in (d.get(CONF_INDICIE_VYKON) or []):
            o, s = self._stari_s(eid)
            hodnota = self._cislo(eid)
            ind[eid] = pr.StavIndicie(
                None if hodnota is None else hodnota > prah, o, s)

        return pr.Signaly(
            doma=doma, cidlo=cidlo, spanek=self._zapnuto(d.get(CONF_SPANEK)),
            je_noc=je_noc, cidlo_od_s=od_s, cidlo_stari_s=stari_s,
            indicie=ind,
        )

    def _nastaveni_pritomnosti(self, d: dict) -> pr.NastaveniPritomnosti:
        dobeh = float(d.get(CONF_INDICIE_DOBEH, 10)) * 60
        indicie = tuple(
            pr.Indicie(eid, dobeh_s=dobeh)
            for eid in list(d.get(CONF_INDICIE_STAV) or [])
            + list(d.get(CONF_INDICIE_VYKON) or [])
        )
        try:
            obs = pr.ZdrojObsazenosti(d.get(CONF_ZDROJ_OBSAZENOSTI, "vzdy"))
        except ValueError:
            obs = pr.ZdrojObsazenosti.VZDY
        try:
            st = pr.StineniPryc(d.get(CONF_STINENI_PRYC, "nic"))
        except ValueError:
            st = pr.StineniPryc.NIC
        return pr.NastaveniPritomnosti(
            obsazenost=obs, 
            dobeh_s=float(d.get(CONF_DOBEH, 30)) * 60,
            max_stari_s=float(d.get(CONF_MAX_STARI, 6)) * 3600,
            stineni_pryc=st, indicie=indicie,
        )

    def _poloha_krytu(self, eid: str) -> float | None:
        """Poloha žaluzie v procentech, nebo nic, když ji nehlásí."""
        st = self._stav(eid)
        if st is None:
            return None
        hodnota = st.attributes.get("current_position")
        if hodnota is None:
            return 100.0 if st.state == "open" else (
                0.0 if st.state == "closed" else None)
        try:
            return float(hodnota)
        except (TypeError, ValueError):
            return None

    def _naklopeni_krytu(self, eid: str) -> float | None:
        """Naklopení lamel v procentech, nebo nic, když ho pohon nehlásí.

        U lamelových žaluzií je to jediná osa, která se doopravdy hýbe —
        výška zůstává na sto procentech celý den.
        """
        st = self._stav(eid)
        if st is None:
            return None
        hodnota = st.attributes.get("current_tilt_position")
        if hodnota is None:
            return None
        try:
            return float(hodnota)
        except (TypeError, ValueError):
            return None

    def _poloha_slunce(self) -> tuple[float, float]:
        st = self.hass.states.get("sun.sun")
        if st is None:
            return (180.0, -10.0)
        return (float(st.attributes.get("azimuth", 180.0)),
                float(st.attributes.get("elevation", -10.0)))
