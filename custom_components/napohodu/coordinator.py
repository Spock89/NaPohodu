"""Koordinátor — přečte čidla, spočítá rozhodnutí, nabídne výsledek entitám.

Zatím nic neovládá. Povel na okno se pošle až po zapnutí přepínače
„Ovládat okno", který je ve výchozím stavu vypnutý. Do té doby integrace
jen ukazuje, co by udělala.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import (core, pritomnost as pr, prumery as pm, slunce as sl,
               sousedstvi as so, vykon as vy)
from .const import (
    CONF_AZIMUT, CONF_CIL_MAX, CONF_CIL_MIN, CONF_CO2, CONF_CO2_OTEVRIT,
    CONF_CO2_ZAVRIT, CONF_DEST, CONF_DOBEH, CONF_DOMA, CONF_INDICIE_DOBEH,
    CONF_INDICIE_STAV, CONF_INDICIE_VYKON, CONF_KOMFORT_ODSTUP, CONF_KVALITA,
    CONF_DVERE, CONF_MAX_STARI, CONF_MISTNOSTI, CONF_SOUSEDI, CONF_NARAZ, CONF_NAZEV, CONF_NOC_DO,
    CONF_NOC_MIN, CONF_NOC_OD, CONF_ODCHYLKA, CONF_OKNO, CONF_PLOCHA,
    CONF_PM10, CONF_PM25, CONF_PRIORITA, CONF_PM_PLATNY, CONF_PRAH_VYKONU, CONF_PRITOMNOST,
    CONF_PROJEZD, CONF_RH_VENKU, CONF_SPANEK, CONF_STINENI_PRYC,
    CONF_KLID_STINENI_MIN, CONF_SEZONA_HYSTEREZE, CONF_STAV_ODSTINIT,
    CONF_STAV_PRYC, CONF_STAV_ZASTINIT, CONF_ZALUZIE_ZONY, CONF_SEZONA_PRAH, CONF_T_PRUMER,
    CONF_T_SEZONA, CONF_T_VENKU, CONF_TEPLOTY, CONF_UTLUM, CONF_VITR, CONF_VITR_KLID,
    CONF_VITR_PRAH, CONF_VYNUCENO, CONF_ZARENI, CONF_ZDROJ_KLIDU,
    CONF_ZDROJ_OBSAZENOSTI, DOMAIN, INTERVAL_S, PODENTITA_MISTNOST,
    PODENTITA_ZONA,
)

_LOGGER = logging.getLogger(__name__)

NEPLATNE = ("unknown", "unavailable", "none", "")


@dataclass
class VysledekZony:
    """Co koordinátor spočítal pro jednu zónu."""

    nazev: str
    rozhodnuti: core.Rozhodnuti | None = None
    otevreno: bool = False
    mistnosti: list[str] = field(default_factory=list)
    atributy: dict = field(default_factory=dict)


@dataclass
class VysledekMistnosti:
    nazev: str
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
        # průměry si počítáme sami, ať uživatel nemusí zakládat statistiky
        self.prumery = pm.Prumery()
        self.vykonavaci: dict[str, vy.Vykonavac] = {}
        self._uloziste = Store(hass, 1, f"{DOMAIN}.prumery")
        self.mistnosti: dict[str, VysledekMistnosti] = {}

    async def async_nacti(self) -> None:
        """Obnoví průměry po restartu, ať se nezačíná od nuly."""
        self.prumery = pm.Prumery.ze_slovniku(await self._uloziste.async_load())

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
        if prumer is None:
            prumer = self.prumery.tyden
        if prumer is None:
            prumer = self._cislo(g.get(CONF_T_VENKU), 15.0)
        posun = self.hodnoty.get((self.entry.entry_id, "posun"), 0.0)
        return core.cil_adaptivni(
            prumer, posun,
            float(g.get(CONF_CIL_MIN, 20.0)),
            float(g.get(CONF_CIL_MAX, 27.0)),
        )

    # ------------------------------------------------------------ hlavní

    async def _async_update_data(self):
        g = {**self.entry.data, **self.entry.options}

        t_out = self._cislo(g.get(CONF_T_VENKU), 15.0)
        self.prumery.aktualizuj(self._cislo(g.get(CONF_T_VENKU)),
                                dt_util.utcnow().timestamp())
        self._uloziste.async_delay_save(self.prumery.jako_slovnik, 300)
        rh_out = self._cislo(g.get(CONF_RH_VENKU), 50.0)
        dest = self._cislo(g.get(CONF_DEST), 0.0)
        doma = self._zapnuto(g.get(CONF_DOMA))
        doma = True if doma is None else doma

        vitr = self._cislo(g.get(CONF_VITR), 0.0)
        naraz = self._cislo(g.get(CONF_NARAZ), vitr)
        vitr_blokuje = max(vitr or 0, naraz or 0) > float(g.get(CONF_VITR_PRAH, 14))

        slunce_az, slunce_el = self._poloha_slunce()
        jasno = pr.oblacnost(self._cislo(g.get(CONF_ZARENI)), slunce_el)

        ted = dt_util.now()
        hodina = ted.hour + ted.minute / 60
        cas_s = dt_util.utcnow().timestamp()
        cil_zakl = self._cil_zakladni(g)
        self.topna_sezona = self._sezona(g)

        noc_od = self._hodina(g.get(CONF_NOC_OD), 22.0)
        noc_do = self._hodina(g.get(CONF_NOC_DO), 6.5)

        # ---------- místnosti ----------
        self.mistnosti = {}
        for p in self._podentity(PODENTITA_MISTNOST):
            d = p.data
            jmeno = d.get(CONF_NAZEV, p.title)
            odchylka = self.hodnota(p.subentry_id, CONF_ODCHYLKA,
                                    float(d.get(CONF_ODCHYLKA, 0.0)))
            sig = self._signaly(d, doma, hodina, noc_od, noc_do)
            nast = self._nastaveni_pritomnosti(d)

            m = VysledekMistnosti(
                nazev=jmeno,
                cil=round(cil_zakl + odchylka, 1),
                obsazeno=pr.obsazeno(sig, nast),
                klid=pr.klid(sig, nast),
            )
            m.atributy = {
                "teplota_min": self._min(d.get(CONF_TEPLOTY)),
                "teplota_max": self._max(d.get(CONF_TEPLOTY)),
                "co2": self._max(d.get(CONF_CO2)),
                "indicie": pr.indicie_aktivni(sig, nast),
                "zdroj_obsazenosti": d.get(CONF_ZDROJ_OBSAZENOSTI, "vzdy"),
            }
            self.mistnosti[p.subentry_id] = m

        # ---------- zóny: nejdřív posbírat, pak přerozdělit ----------
        priprava = {}
        for p in self._podentity(PODENTITA_ZONA):
            podentity = [self._mistnost(j)
                         for j in (p.data.get(CONF_MISTNOSTI) or [])]
            podentity = [x for x in podentity if x]
            co2 = []
            for mp in podentity:
                co2 += list(mp.data.get(CONF_CO2) or [])
            klid = any(self.mistnosti[mp.subentry_id].klid for mp in podentity)
            dvere = [self._zapnuto(e) for e in (p.data.get(CONF_DVERE) or [])]
            priprava[p.subentry_id] = so.ZonaStav(
                id=p.subentry_id, nazev=p.title,
                co2=self._max(co2, 450.0), klid=klid,
                muze_vetrat=not vitr_blokuje and doma,
                sousedi=[q.subentry_id for q in self._podentity(PODENTITA_ZONA)
                         if q.subentry_id in (p.data.get(CONF_SOUSEDI) or [])
                         or q.title in (p.data.get(CONF_SOUSEDI) or [])],
                dvere_otevrene=all(d is not False for d in dvere),
            )
        upravy = so.prerozdel(list(priprava.values()))

        self.zony = {}
        for p in self._podentity(PODENTITA_ZONA):
            d = p.data
            jmena = d.get(CONF_MISTNOSTI) or []
            podentity = [self._mistnost(j) for j in jmena]
            podentity = [x for x in podentity if x]

            teploty, co2, pm25, pm10 = [], [], [], []
            spanek = False
            pm_platny, kvalita = None, None
            for mp in podentity:
                md = mp.data
                teploty += list(md.get(CONF_TEPLOTY) or [])
                co2 += list(md.get(CONF_CO2) or [])
                pm25 += list(md.get(CONF_PM25) or [])
                pm10 += list(md.get(CONF_PM10) or [])
                spanek = spanek or bool(self._zapnuto(md.get(CONF_SPANEK)))
                if md.get(CONF_PM_PLATNY) and pm_platny is None:
                    pm_platny = self._zapnuto(md.get(CONF_PM_PLATNY))
                if md.get(CONF_KVALITA) and kvalita is None:
                    st = self._stav(md.get(CONF_KVALITA))
                    kvalita = st.state if st else None

            cil = min((self.mistnosti[mp.subentry_id].cil for mp in podentity),
                      default=cil_zakl)
            noc_min = min((self.hodnota(mp.subentry_id, CONF_NOC_MIN,
                                        float(mp.data.get(CONF_NOC_MIN, 18)))
                           for mp in podentity), default=18.0)
            odstup = min((float(mp.data.get(CONF_KOMFORT_ODSTUP, 4.0))
                          for mp in podentity), default=4.0)
            # nejnižší priorita v zóně rozhoduje: kdo chce teplo, ten vyhrává
            priorita = min((self.hodnota(mp.subentry_id, CONF_PRIORITA, 5.0)
                            for mp in podentity), default=5.0)
            den_pokles, noc_pokles = core.z_priority(priorita)

            vynuceno = any(self._zapnuto(e)
                           for e in (d.get(CONF_VYNUCENO) or []))
            uprava = upravy.get(p.subentry_id, so.Uprava())

            v = core.Vstup(
                co2=max(self._max(co2, 450.0), uprava.prevzate_co2),
                pm25=self._max(pm25, 0.0),
                pm10=self._max(pm10, 0.0),
                pm_platny=True if pm_platny is None else pm_platny,
                kvalita=kvalita,
                t_in=self._min(teploty, 21.0),
                t_in_max=self._max(teploty, None),
                t_out=t_out, rh_out=rh_out, cil=cil,
                dest=dest, vitr_blokuje=vitr_blokuje,
                doma=doma, spanek=spanek, vynuceno=vynuceno,
                hodina=hodina, cas_s=cas_s,
                zastupce=uprava.zastupce is not None,
            )
            nast = core.Nastaveni(
                co2_otevrit=self.hodnota(p.subentry_id, CONF_CO2_OTEVRIT,
                                         float(d.get(CONF_CO2_OTEVRIT, 800))),
                co2_zavrit=self.hodnota(p.subentry_id, CONF_CO2_ZAVRIT,
                                        float(d.get(CONF_CO2_ZAVRIT, 700))),
                projezd_s=float(d.get(CONF_PROJEZD, 120)),
                nocni_min=noc_min,
                denni_pokles=den_pokles,
                nocni_pokles=noc_pokles,
                komfort_odstup=odstup,
                noc_od=noc_od, noc_do=noc_do,
            )

            ovladat = self.hodnoty.get((p.subentry_id, "ovladat"), 0.0) > 0
            pamet = self.pameti.setdefault(p.subentry_id, core.Pamet())
            skutecne = self._okno_otevreno(d.get(CONF_OKNO), pamet)
            pamet.otevreno = skutecne

            if ovladat:
                r = core.rozhodni(v, pamet, nast)
            else:
                # Bez ovládání se paměť měnit nesmí. Jádro si jinak zapíše,
                # že okno otevřelo, další cyklus přečte skutečnost a stav
                # se překlápí sem a tam.
                zaloha = copy.deepcopy(pamet)
                r = core.rozhodni(v, pamet, nast)
                naucene = pamet.pm_prumer
                self.pameti[p.subentry_id] = zaloha
                zaloha.pm_prumer = naucene
                zaloha.otevreno = skutecne
                pamet = zaloha

            okno = sl.Okno(
                nazev=p.title,
                azimut=float(d.get(CONF_AZIMUT, 180)),
                plocha=float(d.get(CONF_PLOCHA, 1.0)),
            )
            zisk = sl.dopad(okno, slunce_az, slunce_el, jasno)

            z = VysledekZony(
                nazev=d.get(CONF_NAZEV, p.title),
                rozhodnuti=r,
                otevreno=skutecne,
                mistnosti=[mp.title for mp in podentity],
            )
            # ---------- vykonání ----------
            vyk = self.vykonavaci.setdefault(
                p.subentry_id, vy.Vykonavac(self.hass, p.subentry_id))
            provedeno = None
            if ovladat:
                provedeno = await vyk.okno(d.get(CONF_OKNO), r, cas_s, skutecne)

            stineni = None
            if self.hodnoty.get((p.subentry_id, "ovladat_stineni"), 0.0) > 0:
                teploty_zony = [self.mistnosti[mp.subentry_id]
                                for mp in podentity]
                horko = any(m.atributy.get("teplota_max") is not None
                            and m.atributy["teplota_max"] > m.cil + 0.5
                            for m in teploty_zony)
                zima = all(m.atributy.get("teplota_min") is not None
                           and m.atributy["teplota_min"] < m.cil - 0.5
                           for m in teploty_zony) if teploty_zony else False
                jmena = {
                    "zastinit": d.get(CONF_STAV_ZASTINIT),
                    "odstinit": d.get(CONF_STAV_ODSTINIT),
                    "pryc": d.get(CONF_STAV_PRYC),
                }
                cil_stav = vy.stav_stineni(zisk, 150.0, horko, zima, doma, jmena)
                stineni = await vyk.stineni(
                    d.get(CONF_ZALUZIE_ZONY) or [],
                    cil_stav, cas_s, float(d.get(CONF_KLID_STINENI_MIN, 15)))

            z.atributy = {
                "co2": v.co2,
                "provedeno": provedeno,
                "stineni": stineni,
                "stineni_stav": dict(vyk.stav.posledni_stineni),
                "uvnitr": r.t_in_korig,
                "uvnitr_max": v.t_in_max,
                "korekce": r.korekce,
                "venku": t_out,
                "cil": cil,
                "rosny_bod": r.rosny_bod,
                "rezim": pamet.rezim,
                "vetra_se": skutecne,
                "ovladani": "zapnuto" if ovladat else "jen sleduje",
                "slunce": round(zisk),
                "jasno": round(jasno, 2),
                "vynuceno": vynuceno,
                "vitr_blokuje": vitr_blokuje,
                "mistnosti": z.mistnosti,
                "navrh": r.akce.value,
                "zastupce": uprava.zastupce,
                "vetra_i_za": uprava.za_koho,
                "topna_sezona": self.topna_sezona,
            }
            self.zony[p.subentry_id] = z

            for mp in podentity:
                self.mistnosti[mp.subentry_id].okno_otevreno = skutecne
                self.mistnosti[mp.subentry_id].slunce = round(zisk)

        return {"zony": self.zony, "mistnosti": self.mistnosti}

    def _sezona(self, g: dict) -> bool:
        """Topná sezóna podle třídenního průměru, s hysterezí kolem prahu.

        Bez vlastní entity se použije týdenní průměr, který stejně máme.
        """
        prah = float(g.get(CONF_SEZONA_PRAH, 15.0))
        hyst = float(g.get(CONF_SEZONA_HYSTEREZE, 1.0))
        t = self._cislo(g.get(CONF_T_SEZONA))
        if t is None:
            t = self.prumery.tri_dny
        if t is None:
            return self.topna_sezona
        if t < prah - hyst / 2:
            return True
        if t > prah + hyst / 2:
            return False
        return self.topna_sezona          # v pásmu se nemění

    # ------------------------------------------------------------ detaily

    def _okno_otevreno(self, eid: str | None, pamet: core.Pamet) -> bool:
        """Skutečný stav okna má přednost před tím, co si pamatujeme."""
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
