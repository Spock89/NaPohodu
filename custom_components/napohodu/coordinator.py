"""Koordinátor — přečte čidla, spočítá rozhodnutí, nabídne výsledek entitám.

Zatím nic neovládá. Povel na okno se pošle až po zapnutí přepínače
„Ovládat okno", který je ve výchozím stavu vypnutý. Do té doby integrace
jen ukazuje, co by udělala.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field, replace
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import (core, pritomnost as pr, prumery as pm, slunce as sl,
               sousedstvi as so, vykon as vy, zpravy as zp,
               klima as kl)
from .const import (
    CONF_AZIMUT, CONF_CIL_MAX, CONF_CIL_MIN, CONF_CISTICKA, CONF_CO2,
    CONF_CO2_NOC, CONF_CO2_NOC_KRIZE, CONF_CO2_OTEVRIT, CONF_CO2_ZAVRIT,
    CONF_DEST, CONF_DEST_PRAH, CONF_DOBEH, CONF_DOMA, CONF_DVERE,
    CONF_INDICIE_DOBEH, CONF_INDICIE_STAV, CONF_INDICIE_VYKON,
    CONF_I_KDYZ_NIKDO, CONF_KLID_STINENI_MIN, CONF_KLIMA_CHLADIT_OD,
    CONF_KLIMA_DLOUHA, CONF_KLIMA_DLOUHA_H, CONF_KLIMA_ENTITA,
    CONF_KLIMA_POKOJE, CONF_KLIMA_SUSIT_OD, CONF_KLIMA_TOPIT_OD,
    CONF_KLIMA_UMI, CONF_KLIMA_UTLUM_CHLAZENI, CONF_KLIMA_UTLUM_TOPENI,
    CONF_KLIMA_V_POKOJI, CONF_KOMFORT_ODSTUP, CONF_KVALITA, CONF_MAX_STARI,
    CONF_MISTNOSTI, CONF_NARAZ, CONF_NARAZ_PRAH, CONF_NAZEV, CONF_NOC_DO,
    CONF_NOC_MIN, CONF_NOC_OD, CONF_ODCHYLKA, CONF_ODTAH, CONF_OKNA,
    CONF_PLOCHA, CONF_PM10, CONF_PM25, CONF_PM_PLATNY, CONF_PRAH_VYKONU,
    CONF_PRIORITA, CONF_PRITOMNOST, CONF_PROJEZD_M, CONF_RH_MAX,
    CONF_RH_VENKU, CONF_RH_VENKU_M, CONF_RH_VNITRNI, CONF_SEZONA_HYSTEREZE,
    CONF_SEZONA_PRAH, CONF_SOUHRN_CAS, CONF_SOUKROMI_KDY, CONF_SOUSEDI,
    CONF_SPANEK, CONF_STINENI_MAPA, CONF_STINENI_PRYC, CONF_STINENI_REZIM,
    CONF_TEPLOTY, CONF_T_PRUMER, CONF_T_SEZONA, CONF_T_VENKU,
    CONF_T_VENKU_M, CONF_VITR, CONF_VITR_KLID, CONF_VITR_PRAH,
    CONF_VYNUCENO_M, CONF_ZALUZIE, CONF_ZALUZIE_STARE, CONF_ZARENI,
    CONF_ZDROJ_KLIDU, CONF_ZDROJ_OBSAZENOSTI, CONF_ZPRAVY,
    CONF_ZPRAVY_DRUHY, DOMAIN, INTERVAL_S, PODENTITA_KLIMA,
    PODENTITA_MISTNOST, PODENTITA_ZONA,
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
        # denní souhrn: podle něj se pozná, jestli jsou prahy dobře
        self.souhrn: dict[str, dict] = {}
        self._souhrn_den: str = ""
        self.hlasic = zp.Hlasic()
        self._souhrn_odeslan: str = ""
        self.vitr_blokuje: bool = False
        # hodnoty, které blokaci spustily — zpráva má říkat pravdu,
        # ne aktuální stav, který už může být jiný
        self.vitr_pricina: dict = {}
        self.vitr_stav: dict = {}
        self.klimy: dict[str, dict] = {}
        self._klima_pamet: dict[str, kl.Pamet] = {}
        self._prazdno_od: float | None = None
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
        self.mistnosti: dict[str, VysledekMistnosti] = {}

    def srovnej(self, pod_id: str | None = None) -> None:
        """Zapomene poslední povely, takže se v dalším cyklu pošlou znovu.

        Bez pod_id platí pro všechno. Skutečné povely se pošlou jen tam,
        kde je zapnuté ovládání — tlačítko nic neobchází.
        """
        for klic, vyk in self.vykonavaci.items():
            if pod_id is None or klic == pod_id:
                vyk.zapomen()

    async def async_nacti(self) -> None:
        """Obnoví průměry i polohy žaluzií, ať se nezačíná od nuly."""
        self.prumery = pm.Prumery.ze_slovniku(await self._uloziste.async_load())
        ulozene = await self._uloziste_stineni.async_load() or {}
        for pod_id, polohy in ulozene.items():
            vyk = self.vykonavaci.setdefault(
                pod_id, vy.Vykonavac(self.hass, pod_id))
            vyk.stav.posledni_stineni.update(polohy)
            # polohy známe z disku, ochrana po startu už netřeba
            vyk.stav.prvni_beh = False

    def _uloz_stineni(self) -> dict:
        return {k: dict(v.stav.posledni_stineni)
                for k, v in self.vykonavaci.items()
                if v.stav.posledni_stineni}

    # ------------------------------------------------------------ čtení

    def _stav(self, eid: str | None) -> State | None:
        if not eid:
            return None
        st = self.hass.states.get(eid)
        if st is None or str(st.state).lower() in NEPLATNE:
            return None
        return st

    def _cislo(self, eid: str | None, nahrada: float | None = None):
        st = self._stav(eid)
        if st is None:
            return nahrada
        try:
            return float(st.state)
        except (TypeError, ValueError):
            return nahrada

    def _zapnuto(self, eid: str | None) -> bool | None:
        st = self._stav(eid)
        if st is None:
            return None
        return str(st.state).lower() in ("on", "true", "home", "open", "playing")

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
            prumer, zdroj = self._cislo(g.get(CONF_T_VENKU), 15.0), "nahrada"
        self.pouzity["tyden"] = (prumer, zdroj)
        posun = self.hodnoty.get((self.entry.entry_id, "posun"), 0.0)
        return core.cil_adaptivni(
            prumer, posun,
            float(g.get(CONF_CIL_MIN, 20.0)),
            float(g.get(CONF_CIL_MAX, 27.0)),
        )

    # ------------------------------------------------------------ hlavní

    def _vitr(self, g: dict, vitr: float, naraz: float) -> bool:
        """Nárazy mají vlastní práh, protože pohon poškodí dřív než průměr.

        Blokace povolí, až když obě hodnoty klesnou pod uklidňovací mez —
        jinak by se to na hraně překlápělo.
        """
        prah_v = float(g.get(CONF_VITR_PRAH, 7.0))
        prah_n = float(g.get(CONF_NARAZ_PRAH, 11.0))
        klid_v = float(g.get(CONF_VITR_KLID, 5.0))

        if vitr > prah_v or naraz > prah_n:
            if not self.vitr_blokuje:
                self.vitr_pricina = {
                    "prumer": round(vitr, 1), "naraz": round(naraz, 1),
                    "co_prekrocilo": "nárazy" if naraz > prah_n else "průměr",
                    "prah": prah_n if naraz > prah_n else prah_v,
                }
                _LOGGER.info("NaPohodu: vítr blokuje — %s %.1f m/s nad "
                             "prahem %.1f", self.vitr_pricina["co_prekrocilo"],
                             max(vitr, naraz), self.vitr_pricina["prah"])
            self.vitr_blokuje = True
        elif vitr < klid_v and naraz < klid_v:
            if self.vitr_blokuje:
                _LOGGER.info("NaPohodu: vítr povolil (průměr %.1f, náraz "
                             "%.1f pod %.1f)", vitr, naraz, klid_v)
            self.vitr_blokuje = False
            self.vitr_pricina = {}
        self.vitr_stav = {
            "prumer": round(vitr, 1), "naraz": round(naraz, 1),
            "blokuje": self.vitr_blokuje,
            "prahy": {"prumer": prah_v, "naraz": prah_n, "povoli_pod": klid_v},
            "pricina": self.vitr_pricina or None,
        }
        return self.vitr_blokuje

    def _sezona(self, g: dict) -> bool:
        """Topná sezóna podle třídenního průměru, s hysterezí kolem prahu.

        Bez vlastní entity se použije počítaný průměr.
        """
        prah = float(g.get(CONF_SEZONA_PRAH, 15.0))
        hyst = float(g.get(CONF_SEZONA_HYSTEREZE, 1.0))
        t = self._cislo(g.get(CONF_T_SEZONA))
        zdroj = "cidlo"
        if t is None:
            t, zdroj = self.prumery.tri_dny, "pocitano"
        self.pouzity["tri_dny"] = (t, zdroj)
        if t is None:
            return self.topna_sezona
        if t < prah - hyst / 2:
            return True
        if t > prah + hyst / 2:
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
        t_out = self._cislo(g.get(CONF_T_VENKU), 15.0)
        self.prumery.aktualizuj(self._cislo(g.get(CONF_T_VENKU)),
                                dt_util.utcnow().timestamp())
        self._uloziste.async_delay_save(self.prumery.jako_slovnik, 300)
        rh_out = self._cislo(g.get(CONF_RH_VENKU), 50.0)
        dest = self._cislo(g.get(CONF_DEST), 0.0) or 0.0
        doma = self._zapnuto(g.get(CONF_DOMA))
        doma = True if doma is None else doma

        vitr = self._cislo(g.get(CONF_VITR), 0.0) or 0.0
        naraz = self._cislo(g.get(CONF_NARAZ), vitr) or 0.0
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
        cil_zakl = self._cil_zakladni(g)
        self.topna_sezona = self._sezona(g)
        noc_od = self._hodina(g.get(CONF_NOC_OD), 22.0)
        noc_do = self._hodina(g.get(CONF_NOC_DO), 6.5)
        je_noc = ((hodina >= noc_od or hodina < noc_do) if noc_od > noc_do
                  else (noc_od <= hodina < noc_do))

        # ---------- 1. základ každé místnosti ----------
        self.mistnosti = {}
        podklady: dict[str, dict] = {}
        for p in self._podentity(PODENTITA_MISTNOST):
            d = dict(p.data)
            if not d.get(CONF_ZALUZIE) and d.get(CONF_ZALUZIE_STARE):
                d[CONF_ZALUZIE] = d[CONF_ZALUZIE_STARE]

            jmeno = d.get(CONF_NAZEV, p.title)
            odchylka = self.hodnota(p.subentry_id, CONF_ODCHYLKA,
                                    float(d.get(CONF_ODCHYLKA, 0.0)))
            sig = self._signaly(d, doma, hodina, noc_od, noc_do)
            nast_pr = self._nastaveni_pritomnosti(d)

            m = VysledekMistnosti(
                nazev=jmeno,
                cil=round(cil_zakl + odchylka, 1),
                obsazeno=pr.obsazeno(sig, nast_pr),
                klid=pr.klid(sig, nast_pr),
            )
            okno_m = sl.Okno(nazev=p.title,
                             azimut=float(d.get(CONF_AZIMUT, 180)),
                             plocha=float(d.get(CONF_PLOCHA, 1.0)))
            m.slunce = round(sl.dopad(okno_m, slunce_az, slunce_el, jasno))
            m.atributy = {
                "teplota_min": self._min(d.get(CONF_TEPLOTY)),
                "teplota_max": self._max(d.get(CONF_TEPLOTY)),
                "co2_vlastni": self._max(d.get(CONF_CO2)),
                "indicie": pr.indicie_aktivni(sig, nast_pr),
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
        for o in okruhy:
            co2, pm25, pm10, kvalita, pm_platny, spanek = [], [], [], None, None, False
            for mp in o["cleni"]:
                md = podklady[mp.subentry_id]["d"]
                co2 += list(md.get(CONF_CO2) or [])
                pm25 += list(md.get(CONF_PM25) or [])
                pm10 += list(md.get(CONF_PM10) or [])
                spanek = spanek or bool(self._zapnuto(md.get(CONF_SPANEK)))
                if md.get(CONF_PM_PLATNY) and pm_platny is None:
                    pm_platny = self._zapnuto(md.get(CONF_PM_PLATNY))
                if md.get(CONF_KVALITA) and kvalita is None:
                    st = self._stav(md.get(CONF_KVALITA))
                    kvalita = st.state if st else None
            o["co2"] = self._max(co2, 450.0)
            o["pm25"] = self._max(pm25, 0.0)
            o["pm10"] = self._max(pm10, 0.0)
            o["kvalita"] = kvalita
            o["pm_platny"] = True if pm_platny is None else pm_platny
            o["spanek"] = spanek
            o["klid"] = any(self.mistnosti[x.subentry_id].klid
                            for x in o["cleni"])

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
            }

        # ---------- 3. zastupování mezi oblastmi ----------
        stavy = []
        for o in okruhy:
            data = o["pod"].data if o["pod"] else {}
            dvere = [self._zapnuto(e) for e in (data.get(CONF_DVERE) or [])]
            sousedi = [q["id"] for q in okruhy
                       if q["pod"] is not None
                       and q["pod"].subentry_id in (data.get(CONF_SOUSEDI) or [])]
            stavy.append(so.ZonaStav(
                id=o["id"], nazev=o["nazev"], co2=o["co2"], klid=o["klid"],
                muze_vetrat=not vitr_blokuje and doma, sousedi=sousedi,
                dvere_otevrene=all(x is not False for x in dvere)))
        upravy = so.prerozdel(stavy)

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
        await self._klima_krok(g, t_out, doma, cas_s)

        # ---------- 6. denní souhrn ----------
        cas_souhrnu = self._hodina(g.get(CONF_SOUHRN_CAS), 21.0)
        if (hodina >= cas_souhrnu and self._souhrn_odeslan != dnes
                and self.souhrn):
            self._souhrn_odeslan = dnes
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
                "co2": o["co2"], "pm25": o["pm25"], "kvalita": o["kvalita"],
                "spi_se": o["spanek"], "klid": o["klid"],
                "zastupce": uprava.zastupce, "vetra_i_za": uprava.za_koho,
                "mistnosti": z.mistnosti,
            }
            self.zony[o["id"]] = z

        return {"zony": self.zony, "mistnosti": self.mistnosti}

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

    async def _klima_krok(self, g: dict, t_out: float, doma: bool,
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

    async def _mistnost_krok(self, p, u, okruh, uprava, t_out, rh_out, dest,
                             doma, vitr_blokuje, je_noc, hodina, cas_s,
                             noc_od, noc_do, slunce_el):
        """Rozhodne o oknech jedné místnosti a případně je ovládne."""
        d = u["d"]
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
            co2=max(okruh["co2"], uprava.prevzate_co2),
            pm25=okruh["pm25"], pm10=okruh["pm10"],
            pm_platny=okruh["pm_platny"], kvalita=okruh["kvalita"],
            t_in=self._min(d.get(CONF_TEPLOTY), 21.0),
            t_in_max=self._max(d.get(CONF_TEPLOTY), None),
            t_out=t_ven, rh_out=rh_ven, cil=m.cil,
            dest=dest, vitr_blokuje=vitr_blokuje,
            doma=doma or i_kdyz_nikdo,
            spanek=okruh["spanek"], vynuceno=vynuceno,
            hodina=hodina, cas_s=cas_s,
            zastupce=uprava.zastupce is not None,
        )
        nast = core.Nastaveni(
            # prahy z oblasti, ať se místnosti nepřetahují
            co2_otevrit=okruh["prahy"][CONF_CO2_OTEVRIT],
            co2_zavrit=okruh["prahy"][CONF_CO2_ZAVRIT],
            co2_noc=okruh["prahy"][CONF_CO2_NOC],
            co2_noc_krize=okruh["prahy"][CONF_CO2_NOC_KRIZE],
            dest_prah=prah_deste,
            projezd_s=float(d.get(CONF_PROJEZD_M, 120)),
            nocni_min=self.hodnota(p.subentry_id, CONF_NOC_MIN,
                                   float(d.get(CONF_NOC_MIN, 18))),
            komfort_odstup=float(d.get(CONF_KOMFORT_ODSTUP, 4.0)),
            noc_od=noc_od, noc_do=noc_do,
        )
        den_pokles, noc_pokles = core.z_priority(
            self.hodnota(p.subentry_id, CONF_PRIORITA, 5.0))
        nast = replace(nast, denni_pokles=den_pokles, nocni_pokles=noc_pokles)

        vyk = self.vykonavaci.setdefault(
            p.subentry_id, vy.Vykonavac(self.hass, p.subentry_id))
        ovladat = self.hodnoty.get((p.subentry_id, "ovladat"), 0.0) > 0
        pamet = self.pameti.setdefault(p.subentry_id, core.Pamet())

        prvni_okno = okna[0] if okna else None
        projezd = float(d.get(CONF_PROJEZD_M, 120))
        skutecne = self._okno_otevreno(prvni_okno, pamet, cas_s, projezd)
        pamet.otevreno = skutecne

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

        provedeno = None
        if ovladat and okna:
            for okno in okna:
                vysledek = await vyk.okno(okno, r, cas_s, skutecne)
                provedeno = vysledek or provedeno

            g = {**self.entry.data, **self.entry.options}
            if r.akce is core.Akce.ZAVRIT and "větr" in r.duvod:
                await self._posli(g, "vitr", m.nazev, cas_s,
                                  **(self.vitr_pricina or {}))
            elif r.akce is core.Akce.ZAVRIT and "dešt" in r.duvod:
                await self._posli(g, "dest", m.nazev, cas_s, dest=dest)
            elif r.akce is core.Akce.OTEVRIT and "nouzov" in r.duvod:
                await self._posli(g, "nouzove", m.nazev, cas_s, co2=v.co2)
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
        if r.akce is not core.Akce.NIC:
            sh["pohyby"] += 1
        if skutecne:
            sh["minut_otevreno"] += INTERVAL_S / 60
        sh["co2_max"] = max(sh["co2_max"], int(v.co2))
        if r.t_in_korig:
            sh["nejnizsi_teplota"] = min(
                sh["nejnizsi_teplota"] or 99, round(r.t_in_korig, 1))
        if "nouzov" in (r.duvod or ""):
            sh["nouzove"] += 1

        m.rozhodnuti = r
        m.okno_otevreno = skutecne
        m.atributy.update({
            "co2": v.co2, "uvnitr": r.t_in_korig, "korekce": r.korekce,
            "venku": t_ven, "rosny_bod": r.rosny_bod, "rezim": pamet.rezim,
            "navrh": r.akce.value, "provedeno": provedeno,
            "ovladani": "zapnuto" if ovladat else "jen sleduje",
            "oblast": okruh["nazev"] if okruh["pod"] else None,
            "prahy_z_oblasti": {
                "otevrit": okruh["prahy"][CONF_CO2_OTEVRIT],
                "zavrit": okruh["prahy"][CONF_CO2_ZAVRIT],
                "noc": okruh["prahy"][CONF_CO2_NOC],
            },
            "zastupce": uprava.zastupce,
            "okna": okna,
            "duvody": core.duvody(v, pamet, nast),
            "nocni_klid": f"{self._cas(noc_od)} – {self._cas(noc_do)}",
            "rano_neotvirat_od": self._cas(noc_do),
            "je_noc": je_noc,
            "vitr": self.vitr_stav,
            "dnes": {
                "pohyby": sh["pohyby"],
                "otevreno_min": round(sh["minut_otevreno"]),
                "co2_max": sh["co2_max"],
                "nejnizsi_teplota": sh["nejnizsi_teplota"],
                "nouzove_vetrani": sh["nouzove"],
            },
        })

        await self._stineni_krok(p, d, u, m, doma, slunce_el, cas_s)
        await self._pomocnici_krok(p, d, m, okruh)

    async def _pomocnici_krok(self, p, d, m, okruh) -> None:
        """Čistička řeší prach, odtah vlhkost. Okno na to nemusí."""
        vyk = self.vykonavaci.setdefault(
            p.subentry_id, vy.Vykonavac(self.hass, p.subentry_id))

        cisticka = d.get(CONF_CISTICKA) or []
        if cisticka:
            pm = okruh["pm25"] or 0
            pm10 = okruh["pm10"] or 0
            zapnout = None
            if (pm > 35 or pm10 > 50) and m.obsazeno:
                zapnout = True
            elif pm < 20 and pm10 < 30:
                zapnout = False
            m.atributy["cisticka"] = await vyk.zarizeni(
                cisticka, zapnout, "čistička")
        m.atributy["cisticka_bezi"] = vyk.stav.zarizeni.get("čistička")

        odtah = d.get(CONF_ODTAH) or []
        rh_in = self._cislo(d.get(CONF_RH_VNITRNI))
        if odtah and rh_in is not None:
            rh_max = float(d.get(CONF_RH_MAX, 60.0))
            zapnout = None
            if rh_in > rh_max:
                zapnout = True
            elif rh_in < rh_max - 5:
                zapnout = False
            m.atributy["odtah"] = await vyk.zarizeni(odtah, zapnout, "odtah")
            m.atributy["vlhkost"] = rh_in
        m.atributy["odtah_bezi"] = vyk.stav.zarizeni.get("odtah")

    async def _stineni_krok(self, p, d, u, m, doma, slunce_el, cas_s):
        """Rozhodne o žaluziích místnosti. Slunce svítí do pokoje, ne do oblasti."""
        vyk_m = self.vykonavaci.setdefault(
            p.subentry_id, vy.Vykonavac(self.hass, p.subentry_id))
        if self.hodnoty.get((p.subentry_id, "ovladat_stineni"), 0.0) > 0:
            t_max = m.atributy.get("teplota_max")
            t_min = m.atributy.get("teplota_min")
            role = vy.role_stineni(
                m.slunce, 150.0,
                t_max is not None and t_max > m.cil + 0.5,
                t_min is not None and t_min < m.cil - 0.5,
                doma,
                rezim=d.get(CONF_STINENI_REZIM, "vzdy"),
                po_zapadu=slunce_el < 0,
                pohyb=bool(u["sig"].cidlo)
                or bool(pr.indicie_aktivni(u["sig"], u["nast"])),
                soukromi_kdy=d.get(CONF_SOUKROMI_KDY, "nikdy"))
            cile = vy.cile_zaluzii(role, d.get(CONF_STINENI_MAPA) or {})
            stin = await vyk_m.stineni(
                cile, cas_s, float(d.get(CONF_KLID_STINENI_MIN, 15)))
            m.atributy["stineni"] = stin
            m.atributy["role_stineni"] = role
            if stin:
                self._uloziste_stineni.async_delay_save(self._uloz_stineni, 10)
        m.atributy["stineni_stav"] = dict(vyk_m.stav.posledni_stineni)

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
            kl = pr.ZdrojKlidu(d.get(CONF_ZDROJ_KLIDU, "spanek"))
        except ValueError:
            kl = pr.ZdrojKlidu.SPANEK
        try:
            st = pr.StineniPryc(d.get(CONF_STINENI_PRYC, "nic"))
        except ValueError:
            st = pr.StineniPryc.NIC
        return pr.NastaveniPritomnosti(
            obsazenost=obs, klid=kl,
            dobeh_s=float(d.get(CONF_DOBEH, 30)) * 60,
            max_stari_s=float(d.get(CONF_MAX_STARI, 6)) * 3600,
            stineni_pryc=st, indicie=indicie,
        )

    def _poloha_slunce(self) -> tuple[float, float]:
        st = self.hass.states.get("sun.sun")
        if st is None:
            return (180.0, -10.0)
        return (float(st.attributes.get("azimuth", 180.0)),
                float(st.attributes.get("elevation", -10.0)))
