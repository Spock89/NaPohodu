"""Jeden celý cyklus koordinátoru proti náhradnímu Home Assistantu.

Všechno ostatní testuje kousky. Tohle testuje propojení: že se celý
cyklus vůbec projde a nespadne. Právě tam vznikly chyby, které se
v jednotlivých modulech nedaly vidět — seznam, který zastínil metodu,
nebo chybějící import v nové větvi.
"""

import asyncio
import datetime
import pathlib
import sys

import pytest

KOREN = pathlib.Path(__file__).parent.parent


@pytest.fixture
def ha():
    sys.path.insert(0, str(KOREN / "tests" / "stub_ha"))
    sys.path.insert(0, str(KOREN / "custom_components"))
    import importlib

    storage = importlib.import_module("homeassistant.helpers.storage")
    storage.Store._data = {}
    yield importlib.import_module("napohodu.coordinator")
    for jmeno in list(sys.modules):
        if jmeno.startswith(("napohodu", "homeassistant")):
            del sys.modules[jmeno]
    sys.path.remove(str(KOREN / "custom_components"))
    sys.path.remove(str(KOREN / "tests" / "stub_ha"))


class Stav:
    def __init__(self, stav, atributy=None):
        self.state = stav
        self.attributes = atributy or {}
        self.last_changed = datetime.datetime.now(datetime.timezone.utc)
        self.last_updated = self.last_changed
        self.entity_id = ""


class Sluzby:
    def __init__(self):
        self.volano = []

    def has_service(self, obor, jmeno):
        return True

    async def async_call(self, obor, jmeno, data=None, **kw):
        self.volano.append((obor, jmeno, data))
        return None


class Stavy:
    def __init__(self, hodnoty):
        self._h = dict(hodnoty)

    def get(self, eid):
        return self._h.get(eid)

    def async_all(self, obor=None):
        return []


class Hass:
    def __init__(self, hodnoty):
        self.states = Stavy(hodnoty)
        self.services = Sluzby()
        self.data = {}
        self.config = type("C", (), {"time_zone": "Europe/Prague"})()

    def async_create_task(self, coro):
        return asyncio.ensure_future(coro)

    async def async_add_executor_job(self, f, *a):
        return f(*a)


class Podentita:
    def __init__(self, typ, nazev, data=None):
        self.subentry_type = typ
        self.subentry_id = f"id_{nazev}"
        self.title = nazev
        self.data = data or {}


class Zapis:
    entry_id = "entry"

    def __init__(self, podentity, data=None):
        self.subentries = {p.subentry_id: p for p in podentity}
        self.data = data or {}
        self.options = {}


def _instalace(c):
    """Byt jako ten skutečný: okno, žaluzie, zóna, skupina i scéna."""
    return [
        Podentita(c.PODENTITA_MISTNOST, "Obývák", {
            c.CONF_OKNA: ["cover.obyvak"],
            c.CONF_ZALUZIE: ["cover.zaluzie"],
            c.CONF_STINENI_MAPA: {"cover.zaluzie": {"zastinit": "dolu"}},
            c.CONF_TEPLOTY: ["sensor.t_obyvak"],
            c.CONF_CO2: ["sensor.co2"],
            c.CONF_PRITOMNOST: "binary_sensor.pohyb",
            c.CONF_CLIMATE: "climate.hlavice"}),
        Podentita(c.PODENTITA_MISTNOST, "Dílna", {
            c.CONF_TEPLOTY: ["sensor.t_dilna"]}),
        Podentita(c.PODENTITA_ZONA, "Kuchyň a obývák",
                  {c.CONF_MISTNOSTI: ["Obývák", "Dílna"]}),
        Podentita(c.PODENTITA_SKUPINA, "1. patro", {
            c.CONF_SKUPINA_MISTNOSTI: ["Dílna"],
            c.CONF_SKUPINA_PRITOMNOST: "binary_sensor.patro"}),
        Podentita(c.PODENTITA_SCENA, "Home Office", {
            c.CONF_NAZEV: "Home Office",
            c.CONF_SCENA_OD: "00:00:00", c.CONF_SCENA_DO: "23:59:00",
            c.CONF_SCENA_PRAZDNO: ["Dílna"],
            c.PREFIX_SCENA_CIL + "obyvak": 22.0}),
    ]


def _stavy():
    return {
        "sensor.t_obyvak": Stav("21.5", {"unit_of_measurement": "°C"}),
        "sensor.t_dilna": Stav("19.0", {"unit_of_measurement": "°C"}),
        "sensor.co2": Stav("640", {"unit_of_measurement": "ppm"}),
        "sensor.venku": Stav("6.5", {"unit_of_measurement": "°C"}),
        "binary_sensor.pohyb": Stav("on"),
        "binary_sensor.patro": Stav("off"),
        "binary_sensor.doma": Stav("on"),
        "cover.obyvak": Stav("closed", {"current_position": 0}),
        "cover.zaluzie": Stav("open", {"current_position": 100,
                                       "current_tilt_position": 50}),
        "climate.hlavice": Stav("heat", {"temperature": 21.0,
                                         "current_temperature": 21.4}),
        "sun.sun": Stav("above_horizon", {"azimuth": 180.0,
                                          "elevation": 25.0}),
    }


def _koordinator(ko, c, podentity=None, stavy=None, data=None):
    hass = Hass(stavy if stavy is not None else _stavy())
    entry = Zapis(podentity if podentity is not None else _instalace(c),
                  data or {c.CONF_T_VENKU: "sensor.venku",
                           c.CONF_DOMA: "binary_sensor.doma"})
    k = ko.NaPohoduCoordinator(hass, entry)
    k.hass = hass
    return k, hass


def test_cely_cyklus_projde(ha):
    """Nic víc, než že se celý cyklus projde a nespadne."""
    ko = ha
    from napohodu import const as c

    k, hass = _koordinator(ko, c)
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())

    assert set(k.mistnosti) == {"id_Obývák", "id_Dílna"}
    obyvak = k.mistnosti["id_Obývák"]
    assert obyvak.rozhodnuti is not None
    assert obyvak.atributy["co2"] == 640.0


def test_cyklus_se_scenou_a_skupinou(ha):
    """Scéna i čidlo patra se projeví tam, kde mají."""
    ko = ha
    from napohodu import const as c

    k, hass = _koordinator(ko, c)
    asyncio.run(k.async_nacti())

    ted = ko.dt_util.now()
    den = ted.replace(hour=0, minute=0, second=0, microsecond=0)
    k._vlastni_plan = [{
        "uid": "u1", "druh": "scena", "scena": "id_Home Office",
        "celodenni": True, "okno": ["00:00:00", "23:59:00"],
        "opis": {"prazdno": [], "zavreno": [], "cil": {}},
        "od": den, "do": den + datetime.timedelta(days=1), "rrule": None}]
    asyncio.run(k._async_update_data())

    # scéna nastavuje cíl obýváku
    assert k.mistnosti["id_Obývák"].cil == 22.0
    # scéna i čidlo patra prohlásí dílnu za prázdnou
    dilna = k.mistnosti["id_Dílna"]
    assert dilna.plan_prazdno is True
    assert dilna.skupina_prazdno == "1. patro"
    assert dilna.obsazeno is False


def test_skupina_neprebije_vlastni_cidlo(ha):
    """Co místnost vidí sama, to jí čidlo patra nepřebije."""
    ko = ha
    from napohodu import const as c

    podentity = _instalace(c)
    # dílna dostane vlastní čidlo pohybu, které někoho vidí
    podentity[1].data[c.CONF_PRITOMNOST] = "binary_sensor.pohyb_dilna"
    podentity[1].data[c.CONF_ZDROJ_OBSAZENOSTI] = "cidlo"
    stavy = _stavy()
    stavy["binary_sensor.pohyb_dilna"] = Stav("on")

    k, hass = _koordinator(ko, c, podentity, stavy)
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())

    dilna = k.mistnosti["id_Dílna"]
    assert dilna.skupina_prazdno is None
    assert dilna.obsazeno is True


def test_obracene_cidlo_pritomnosti(ha):
    """Zapnuto znamená „nikdo doma", když se to zaškrtne."""
    ko = ha
    from napohodu import const as c

    k, hass = _koordinator(
        ko, c, data={c.CONF_T_VENKU: "sensor.venku",
                     c.CONF_DOMA: "binary_sensor.doma",
                     c.CONF_DOMA_OBRACENE: True})
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())
    assert "obráceně" in k.doma_popis
    # prázdný byt přebíjí všechno, takže místnost není obsazená
    assert k.mistnosti["id_Obývák"].obsazeno is False

    # a bez zaškrtnutí je to naopak
    k2, _ = _koordinator(ko, c)
    asyncio.run(k2.async_nacti())
    asyncio.run(k2._async_update_data())
    assert "obráceně" not in k2.doma_popis
    assert k2.mistnosti["id_Obývák"].obsazeno is True


def test_zadost_posle_i_mistnost_s_vypnutym_oknem(ha):
    """Vyvětrat si sama neumí ani místnost, která okno má, ale má
    vypnutý přepínač Ovládat okno — požádá tedy souseda v zóně.

    Dřív to hlídal test, který hledal jméno klíče v kódu. Klíč tam
    byl, jenže špatný: hodnota přepínače se vede pod „ovladat", takže
    se četla výchozí jednička a větev byla mrtvá. Proto se to teď
    zkouší během, ne čtením.
    """
    ko = ha
    from napohodu import const as c

    pod = _instalace(c)
    stavy = _stavy()
    # v obýváku je chladno a venku tepleji, takže by si rád ohřál
    stavy["sensor.t_obyvak"] = Stav("18.0", {"unit_of_measurement": "°C"})
    stavy["sensor.venku"] = Stav("24.0", {"unit_of_measurement": "°C"})

    # se zapnutým ovládáním si pomůže sám a nikoho neprosí
    k, _ = _koordinator(ko, c, pod, stavy)
    k.hodnoty[("id_Obývák", "ovladat")] = 1.0
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())
    asyncio.run(k._async_update_data())
    zona = next(iter(k.zony.values()))
    assert "Obývák" not in (zona.atributy.get("teplo_za") or [])

    # s vypnutým ovládáním o to požádá zónu
    k2, _ = _koordinator(ko, c, pod, stavy)
    k2.hodnoty[("id_Obývák", "ovladat")] = 0.0
    asyncio.run(k2.async_nacti())
    asyncio.run(k2._async_update_data())
    asyncio.run(k2._async_update_data())
    zona2 = next(iter(k2.zony.values()))
    assert "Obývák" in (zona2.atributy.get("teplo_za") or [])


def test_prahy_zony_bere_jen_od_toho_kdo_meri(ha):
    """Místnost bez čidla nesmí tiše přetlačit práh celé zóny.

    Prahy se po zóně berou nejcitlivější, aby o společném vzduchu
    nerozhodovaly dvě místnosti jinak. Jenže místnost bez čidla svůj
    práh nikde nevidí — v kartě se jí negeneruje, protože v ní sama
    nic neovlivní — a přesto tudy jeho výchozí hodnota přebíjela
    nastavení těch, které čidlo mají.
    """
    ko = ha
    from napohodu import const as c

    k, _ = _koordinator(ko, c)
    # obývák má čidlo CO2 a chce větrat až od 1200, dílna nemá nic
    k.hodnoty[("id_Obývák", c.CONF_CO2_OTEVRIT)] = 1200.0
    k.hodnoty[("id_Dílna", c.CONF_CO2_OTEVRIT)] = 700.0
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())

    prahy = k.mistnosti["id_Obývák"].atributy["prahy_z_oblasti"]
    assert prahy["otevrit"] == 1200.0

    # jakmile čidlo dostane i dílna, mluví do toho zas
    pod = _instalace(c)
    pod[1].data[c.CONF_CO2] = ["sensor.co2_dilna"]
    stavy = _stavy()
    stavy["sensor.co2_dilna"] = Stav("500", {"unit_of_measurement": "ppm"})
    k2, _ = _koordinator(ko, c, pod, stavy)
    k2.hodnoty[("id_Obývák", c.CONF_CO2_OTEVRIT)] = 1200.0
    k2.hodnoty[("id_Dílna", c.CONF_CO2_OTEVRIT)] = 700.0
    asyncio.run(k2.async_nacti())
    asyncio.run(k2._async_update_data())
    prahy2 = k2.mistnosti["id_Obývák"].atributy["prahy_z_oblasti"]
    assert prahy2["otevrit"] == 700.0


def test_bez_okna_zadna_rada_k_pojistkam(ha):
    """Rada na nastavení, které člověk v kartě nevidí, je horší než
    žádná: místnosti bez okna se pojistky negenerují."""
    ko = ha
    from napohodu import const as c

    k, _ = _koordinator(ko, c)
    # pojistka nad cílem — klasický konflikt
    k.hodnoty[("id_Dílna", c.CONF_MEZ_DOLNI)] = 24.0
    k.hodnoty[("id_Obývák", c.CONF_MEZ_DOLNI)] = 24.0
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())

    assert k.mistnosti["id_Dílna"].atributy["konflikt_mezi"] is None
    assert k.mistnosti["id_Obývák"].atributy["konflikt_mezi"]


def test_pravidlo_bez_okna_je_videt(ha):
    """Nenastavitelné chování musí být někde napsané.

    Místnost bez okna žádá o vyvětrání sousedy a dojede na cíl, ne za
    něj — proto se jí „zavřít až za cílem" negeneruje. Bez téhle věty
    v kartě není jak přijít na to proč, a hledá se to znovu a znovu.
    """
    ko = ha
    from napohodu import const as c

    k, _ = _koordinator(ko, c)
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())

    pravidla = k.mistnosti["id_Dílna"].atributy["pevna_pravidla"]
    assert any("žádám sousedy" in x for x in pravidla), pravidla
    assert any("dojede se na cíl" in x for x in pravidla), pravidla

    # místnosti s vlastním oknem se to neplete
    assert not any("žádám sousedy" in x for x in
                   k.mistnosti["id_Obývák"].atributy["pevna_pravidla"])


def test_zadost_bez_okna_konci_na_cili(ha):
    """A opravdu na cíli skončí, ne o kus dál."""
    ko = ha
    from napohodu import const as c

    stavy = _stavy()
    stavy["sensor.venku"] = Stav("26.0", {"unit_of_measurement": "°C"})
    stavy["sensor.t_obyvak"] = Stav("22.0", {"unit_of_measurement": "°C"})
    stavy["sensor.t_dilna"] = Stav("17.0", {"unit_of_measurement": "°C"})
    k, _ = _koordinator(ko, c, _instalace(c), stavy)
    k.hodnoty[("id_Dílna", c.CONF_HYST_DEN_ZAVRIT)] = 2.0
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())
    dilna = k.mistnosti["id_Dílna"]
    assert dilna.atributy["zadost_sousedum"] == "ohrev"

    # těsně nad cílem už žádost končí, i když je pásmo nastavené široké
    stavy["sensor.t_dilna"] = Stav(f"{dilna.cil + 0.2:.1f}",
                                   {"unit_of_measurement": "°C"})
    k.hass.states._h.update(stavy)
    asyncio.run(k._async_update_data())
    assert k.mistnosti["id_Dílna"].atributy.get("zadost_sousedum") is None


def test_nocni_pasmo_rozhoduje_o_nocnim_chlazeni(ha):
    """V noci se kvůli teplotě otevírá jen pro chlazení — a rozhoduje
    o tom noční pásmo, ne denní.

    Zkouší se to na samotné místnosti s oknem. Když je horko i vedle,
    otevře okno její žádost a vlastní pásmo se ke slovu nedostane —
    na to se dá snadno naletět a prohlásit nastavení za zbytečné.
    """
    ko = ha
    from napohodu import const as c

    puvodni = ko.dt_util.now
    ko.dt_util.now = lambda: puvodni().replace(hour=2, minute=0)
    try:
        vysledky = {}
        for pasmo in (0.0, 8.0):
            stavy = _stavy()
            stavy["sensor.t_obyvak"] = Stav(
                "31.0", {"unit_of_measurement": "°C"})
            stavy["sensor.venku"] = Stav(
                "20.0", {"unit_of_measurement": "°C"})
            k, hass = _koordinator(ko, c, _instalace(c), stavy)
            k.hodnoty[("id_Obývák", "ovladat")] = 1.0
            k.hodnoty[("id_Obývák", c.CONF_HYST_NOC_OTEVRIT)] = pasmo
            asyncio.run(k.async_nacti())
            asyncio.run(k._async_update_data())
            vysledky[pasmo] = [x for x in hass.services.volano
                               if x[0] == "cover"]
    finally:
        ko.dt_util.now = puvodni

    # úzké pásmo otevře, široké ne
    assert vysledky[0.0], "s nulovým nočním pásmem se mělo otevřít"
    assert not vysledky[8.0], "s osmistupňovým pásmem se otevřít nemělo"


def _byt_jako_doopravdy(c):
    """Obývák bez ovládaného okna (jen kontakt) v zóně s kuchyní,
    dílna úplně mimo zónu."""
    obyvak = Podentita(c.PODENTITA_MISTNOST, "Obývák", {
        c.CONF_TEPLOTY: ["sensor.t_obyvak"], c.CONF_CO2: ["sensor.co2"],
        c.CONF_KONTAKT_M: ["binary_sensor.kontakt"],
        c.CONF_CLIMATE: "climate.hlavice"})
    kuchyne = Podentita(c.PODENTITA_MISTNOST, "Kuchyně", {
        c.CONF_OKNA: ["cover.kuchyne"],
        c.CONF_TEPLOTY: ["sensor.t_kuchyne"]})
    dilna = Podentita(c.PODENTITA_MISTNOST, "Dílna",
                      {c.CONF_TEPLOTY: ["sensor.t_dilna"]})
    zona = Podentita(c.PODENTITA_ZONA, "Kuchyň a obývák",
                     {c.CONF_MISTNOSTI: [obyvak.subentry_id,
                                         kuchyne.subentry_id]})
    return [obyvak, kuchyne, dilna, zona]


def test_nezada_tam_kde_neni_koho_prosit(ha):
    """Místnost mimo zónu nemá koho požádat o vyvětrání.

    Zapisovala si žádost i tak a v kartě pak stálo „žádám sousedy
    o ohřev", přestože žádní sousedé s oknem neexistují.
    """
    ko = ha
    from napohodu import const as c

    stavy = _stavy()
    stavy["sensor.t_kuchyne"] = Stav("22.0", {"unit_of_measurement": "°C"})
    stavy["sensor.t_obyvak"] = Stav("17.0", {"unit_of_measurement": "°C"})
    stavy["sensor.t_dilna"] = Stav("17.0", {"unit_of_measurement": "°C"})
    stavy["sensor.venku"] = Stav("24.0", {"unit_of_measurement": "°C"})
    stavy["cover.kuchyne"] = Stav("closed", {"current_position": 0})
    stavy["binary_sensor.kontakt"] = Stav("off")

    k, _ = _koordinator(ko, c, _byt_jako_doopravdy(c), stavy)
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())

    # obývák v zóně s kuchyní požádá
    obyvak = k.mistnosti["id_Obývák"]
    assert obyvak.atributy["zadost_sousedum"] == "ohrev"
    assert "žádám sousedy" in obyvak.rozhodnuti.duvod

    # dílna mimo zónu nemá koho, takže mlčí
    dilna = k.mistnosti["id_Dílna"]
    assert dilna.atributy.get("zadost_sousedum") is None
    assert dilna.rozhodnuti.duvod == "okno tady neovládáme"
    assert not any("žádám sousedy" in x for x in
                   (dilna.atributy.get("pevna_pravidla") or []))


def _pripravena_obnova(ko, c, posledni_povel):
    """Byt, kde jádro drží zavřeno, vítr fouká a povel je pět hodin starý."""
    import homeassistant.util.dt as dt_util

    stavy = _stavy()
    stavy["sensor.co2"] = Stav("1100", {"unit_of_measurement": "ppm"})
    stavy["sensor.vitr"] = Stav("12.0", {"unit_of_measurement": "m/s"})
    k, hass = _koordinator(
        ko, c,
        podentity=[p for p in _instalace(c) if p.title in ("Obývák", "Dílna")],
        stavy=stavy,
        data={c.CONF_T_VENKU: "sensor.venku", c.CONF_DOMA: "binary_sensor.doma",
              c.CONF_VITR: "sensor.vitr", c.CONF_VITR_KLID_MIN: 0.0})
    asyncio.run(k.async_nacti())
    k.hodnoty[("id_Obývák", "ovladat")] = 1.0
    k.hodnoty[("id_Obývák", c.CONF_MIN_DRZENI)] = 62.0
    asyncio.run(k._async_update_data())

    cas = dt_util.utcnow().timestamp()
    pamet = k.pameti["id_Obývák"]
    pamet.otevreno = False
    pamet.cas_povelu_s = cas - 5 * 3600
    pamet.obnova_kdy_s = 0.0
    k.vykonavaci["id_Obývák"].stav.posledni_okna["cover.obyvak"] = (
        posledni_povel, cas - 5 * 3600)
    return k, hass, pamet


def _kolo(k, hass, vitr):
    hass.states._h["sensor.vitr"] = Stav(str(vitr),
                                         {"unit_of_measurement": "m/s"})
    hass.services.volano.clear()
    asyncio.run(k._async_update_data())
    povely = [s for o, s, d in hass.services.volano if o == "cover"]
    return k.mistnosti["id_Obývák"].rozhodnuti, povely


def test_obnova_ktera_okno_prestavi_nastartuje_drzeni(ha):
    """Obnova povelu je taky pohyb, když se stav rozešel se skutečností.

    Dřív se do nejkratší doby držení nepočítala vůbec, takže po ní
    směl hned následovat pohyb opačným směrem: okno se zavřelo
    (obnovou, s důvodem větru) a za dvě minuty otevřelo, protože
    držení se měřilo od povelu několik hodin starého.
    """
    ko = ha
    from napohodu import const as c

    # naposled se posílalo otevřít, obnova tedy okno doopravdy zavře
    k, hass, pamet = _pripravena_obnova(ko, c, "open_cover")
    r, povely = _kolo(k, hass, 12.0)
    assert r.kod == "obnova" and "zavřít" in r.duvod, r.duvod
    assert "close_cover" in povely

    # vítr pustí, ale otevřít se nesmí — od přestavení platí držení
    r2, povely2 = _kolo(k, hass, 1.0)
    assert r2.kod == "drzeni", r2.duvod
    assert "držím stav" in r2.duvod
    assert not povely2, povely2


def test_obnova_stejnym_smerem_drzeni_nerestartuje(ha):
    """Jinak by se stav nesměl změnit nikdy: obnova chodí každých
    třicet minut a doba držení je u mě hodina."""
    ko = ha
    from napohodu import const as c

    # naposled se posílalo zavřít, obnova tedy jen potvrzuje stav
    k, hass, pamet = _pripravena_obnova(ko, c, "close_cover")
    r, _ = _kolo(k, hass, 12.0)
    assert r.kod == "obnova", r.duvod

    # vítr pustí a otevřít se smí hned, držení je dávno za námi
    r2, povely2 = _kolo(k, hass, 1.0)
    assert r2.akce.value == "otevrit", r2.duvod
    assert "open_cover" in povely2


def test_mrizka_dnu_sceny_zapina_a_vypina(ha):
    """Celý řetězec: naklikat dny → jeden stisk → záznamy v plánu.

    Zaškrtnutí samo nic nezapisuje, aby se dalo naklikat víc dní
    a uložit je najednou.
    """
    ko = ha
    from napohodu import const as c
    from napohodu.switch import DenSceny

    k, hass = _koordinator(ko, c)
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())

    scena = next(p for p in k.entry.subentries.values()
                 if p.subentry_type == c.PODENTITA_SCENA)
    dlazdice = [DenSceny(k, k.entry, i) for i in range(3)]
    for d in dlazdice:
        d.hass = hass
        d.async_write_ha_state = lambda: None
    dnes, zitra, pozitri = dlazdice

    assert not any(d.is_on for d in dlazdice)
    assert dnes.name == "dnes" and zitra.name == "zítra"

    # naklikání dvou dnů: mřížka je ukazuje, do kalendáře nic nejde
    asyncio.run(zitra.async_turn_on())
    asyncio.run(pozitri.async_turn_on())
    assert zitra.is_on and pozitri.is_on and not dnes.is_on
    assert zitra.icon == "mdi:calendar-plus", "čeká na uložení"
    assert not [z for z in k.plan_zaznamy() if z.get("druh") == "scena"]
    assert k.scena_kolik_ceka() == (2, 0)

    # jeden stisk uloží oba
    vysledek = asyncio.run(k.scena_uloz())
    assert "přidáno 2" in vysledek
    zaznamy = [z for z in k.plan_zaznamy() if z.get("druh") == "scena"]
    assert len(zaznamy) == 2
    assert {z["scena"] for z in zaznamy} == {scena.subentry_id}
    assert all(z["celodenni"] is True for z in zaznamy)
    assert k.scena_kolik_ceka() == (0, 0)
    assert pozitri.icon == "mdi:calendar-check", "uložené"
    assert pozitri.extra_state_attributes["v_kalendari"] is True

    # druhý stisk nemá co dělat a nic nepřidá
    assert asyncio.run(k.scena_uloz()) == "nic k uložení"
    assert len([z for z in k.plan_zaznamy()
                if z.get("druh") == "scena"]) == 2

    # odškrtnutí taky čeká na uložení
    asyncio.run(pozitri.async_turn_off())
    assert not pozitri.is_on
    assert pozitri.icon == "mdi:calendar-remove"
    assert len([z for z in k.plan_zaznamy()
                if z.get("druh") == "scena"]) == 2
    asyncio.run(k.scena_uloz())
    assert len([z for z in k.plan_zaznamy()
                if z.get("druh") == "scena"]) == 1

    # a zahození výběr zruší, kalendář nechá být
    asyncio.run(dnes.async_turn_on())
    assert dnes.is_on and k.scena_kolik_ceka() == (1, 0)
    k.scena_zahod()
    assert not dnes.is_on and k.scena_kolik_ceka() == (0, 0)
    assert len([z for z in k.plan_zaznamy()
                if z.get("druh") == "scena"]) == 1


def test_dlazdice_a_kalendar_sceny_vidi_totez(ha):
    """Den označený v kalendáři scény musí být na mřížce zaškrtnutý —
    jsou to dvě cesty k jedné věci, ne dva seznamy."""
    ko = ha
    import datetime as dt

    from homeassistant.util import dt as dt_util
    from napohodu import const as c
    from napohodu.switch import DenSceny

    k, hass = _koordinator(ko, c)
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())
    scena = next(p for p in k.entry.subentries.values()
                 if p.subentry_type == c.PODENTITA_SCENA)

    # tak, jak to ukládá kalendář scény: celodenní událost na zítřek
    zitra = dt_util.now().date() + dt.timedelta(days=1)
    asyncio.run(k.plan_zapis({
        "uid": "z_kalendare", "druh": "scena",
        "scena": scena.subentry_id, "nazev_sceny": "Home Office",
        "celodenni": True, "okno": ["07:00", "18:00"],
        "od": dt_util.start_of_local_day(
            dt.datetime(zitra.year, zitra.month, zitra.day)),
        "do": dt_util.start_of_local_day(
            dt.datetime(zitra.year, zitra.month, zitra.day))
        + dt.timedelta(days=1),
        "opis": {"prazdno": [], "zavreno": [], "cil": {}}}))

    d = DenSceny(k, k.entry, 1)
    d.hass = hass
    d.async_write_ha_state = lambda: None
    assert d.is_on, "den z kalendáře musí být na mřížce vidět"
    assert d.extra_state_attributes["da_se_odskrtnout"] is True


def _dve_sceny(c):
    return [p for p in _instalace(c)] + [
        Podentita(c.PODENTITA_SCENA, "Hlídání", {
            c.CONF_NAZEV: "Hlídání",
            c.CONF_SCENA_OD: "08:00:00", c.CONF_SCENA_DO: "20:00:00",
            c.CONF_SCENA_POPIS: "babička u dětí",
            c.PREFIX_SCENA_CIL + "obyvak": 23.0}),
    ]


def test_mrizka_patri_vybrane_scene(ha):
    """Rolovátko rozhoduje, které scény dny mřížka zaškrtává.

    Dřív měla mřížku i kalendář každá scéna, takže karta s každou
    novou narostla a musela se generovat znovu.
    """
    ko = ha
    from napohodu import const as c
    from napohodu.select import KteraScena
    from napohodu.switch import DenSceny

    k, hass = _koordinator(ko, c, podentity=_dve_sceny(c))
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())

    vyber = KteraScena(k, k.entry)
    vyber.hass = hass
    vyber.async_write_ha_state = lambda: None
    assert vyber.options == ["Home Office", "Hlídání"]
    # bez vybrání platí první — prázdná mřížka by vypadala rozbitě
    assert vyber.current_option == "Home Office"

    d = DenSceny(k, k.entry, 3)
    d.hass = hass
    d.async_write_ha_state = lambda: None

    asyncio.run(d.async_turn_on())
    asyncio.run(k.scena_uloz())
    zaznamy = [z for z in k.plan_zaznamy() if z.get("druh") == "scena"]
    assert len(zaznamy) == 1
    ho = next(p for p in k.entry.subentries.values()
              if p.title == "Home Office")
    assert zaznamy[0]["scena"] == ho.subentry_id

    # přepnu scénu: tatáž dlaždice teď patří jiné a je prázdná
    asyncio.run(vyber.async_select_option("Hlídání"))
    assert not d.is_on
    asyncio.run(d.async_turn_on())
    asyncio.run(k.scena_uloz())
    zaznamy = [z for z in k.plan_zaznamy() if z.get("druh") == "scena"]
    assert len(zaznamy) == 2
    hl = next(p for p in k.entry.subentries.values() if p.title == "Hlídání")
    assert {z["scena"] for z in zaznamy} == {ho.subentry_id, hl.subentry_id}
    # popis scény se opíše do dne
    novy = next(z for z in zaznamy if z["scena"] == hl.subentry_id)
    assert novy["popis"] == "babička u dětí"
    assert novy["okno"] == ["08:00:00", "20:00:00"]

    # a zpátky u první scény zůstalo, co bylo zaškrtnuté
    asyncio.run(vyber.async_select_option("Home Office"))
    assert d.is_on


def test_scena_jde_naplanovat_i_opakovane(ha):
    """Mřížka umí jeden den kliknutím, vzorec ne — na ten je nabídka.

    A ta se čte živě, takže nová scéna se v ní objeví bez generování
    dashboardu.
    """
    ko = ha
    import datetime as dt

    from homeassistant.util import dt as dt_util
    from napohodu import const as c

    k, hass = _koordinator(ko, c, podentity=_dve_sceny(c))
    asyncio.run(k.async_nacti())
    asyncio.run(k._async_update_data())

    popisy = [v.popis for v in k.nabidka_planu()]
    assert "scéna: Home Office" in popisy
    assert "scéna: Hlídání" in popisy

    k.plan_opakovani = "vsedni_dny"
    od = dt_util.now().replace(hour=9, minute=0, second=0, microsecond=0)
    vysledek = asyncio.run(k.naplanuj("scéna: Hlídání", od,
                                      od + dt.timedelta(hours=8)))
    assert "Hlídání" in vysledek and "vsedni_dny" in vysledek

    z = next(x for x in k.plan_zaznamy() if x.get("druh") == "scena")
    assert z["rrule"] and "BYDAY=MO,TU,WE,TH,FR" in z["rrule"]
    # a nese okno dne i opis, takže neplatí celou noc
    assert z["okno"] == ["08:00:00", "20:00:00"]
    assert z["opis"]["cil"] == {"Obývák": 23.0}


def test_dlazdice_maji_identifikator_ktery_karta_hleda(ha):
    """Jméno dlaždice je datum, takže by z něj Home Assistant odvodil
    `switch.dnes` a karta by mřížku nenašla — a negenerovala by ji
    vůbec. Identifikátor se proto nastavuje napevno."""
    ko = ha
    import karty
    from napohodu import const as c
    from napohodu.switch import DenSceny

    k, hass = _koordinator(ko, c)
    asyncio.run(k.async_nacti())

    d = DenSceny(k, k.entry, 0)
    assert d.entity_id == "switch.napohodu_den_00"
    assert d.name == "dnes", "na dlaždici se čte datum"
    assert DenSceny(k, k.entry, 12).entity_id == "switch.napohodu_den_12"

    # a karta hledá přesně tohle
    text = karty.dashboard(["obyvak"], [], lambda e: True,
                           sceny=["Home Office"])
    for i in range(karty.DNU_MRIZKY):
        assert DenSceny(k, k.entry, i).entity_id in text


def test_dlazdice_ze_starsiho_vydani_se_prejmenuji(ha):
    """Registr si první jméno pamatuje, takže by oprava sama na
    stávající instalaci nedosáhla a mřížka by zůstala prázdná."""
    ko = ha
    from homeassistant.helpers import entity_registry as er
    from napohodu import const as c
    from napohodu.switch import async_setup_entry

    k, hass = _koordinator(ko, c)
    asyncio.run(k.async_nacti())
    hass.data = {c.DOMAIN: {k.entry.entry_id: k}}

    registr = er.Registr([
        er.RegistrZapis("switch.dnes", f"{k.entry.entry_id}_den_00",
                        "switch"),
        er.RegistrZapis("switch.st_28_10", f"{k.entry.entry_id}_den_02",
                        "switch"),
    ])
    hass.registr = registr
    asyncio.run(async_setup_entry(hass, k.entry, lambda *a, **kw: None))

    assert ("switch.dnes", "switch.napohodu_den_00") in registr.prejmenovane
    assert ("switch.st_28_10",
            "switch.napohodu_den_02") in registr.prejmenovane
    # a co už správně je, se nepřejmenovává
    assert len(registr.prejmenovane) == 2
