"""Ověří, že se balíček dá naimportovat tak, jak to udělá Home Assistant.

Testy jádra chyby v propojení nechytnou, protože jádro Home Assistant
nepotřebuje. Tenhle test podstrčí náhradní Home Assistant a zkusí každý
modul skutečně naimportovat — odhalí překlepy, chybějící konstanty
i syntaktické chyby v částech, které se jinak nespustí.
"""

import importlib
import pathlib
import sys

import pytest

KOREN = pathlib.Path(__file__).parent.parent
MODULY = [
    "const", "core", "slunce", "pritomnost", "prumery", "sousedstvi",
    "sekvence", "vykon", "entity", "coordinator", "config_flow",
    "services", "sensor", "binary_sensor", "number", "switch", "button",
    "karty", "zpravy", "klima",
]


@pytest.fixture(scope="module", autouse=True)
def nahradni_ha():
    sys.path.insert(0, str(KOREN / "tests" / "stub_ha"))
    sys.path.insert(0, str(KOREN / "custom_components"))
    yield
    for m in list(sys.modules):
        if m.startswith(("napohodu", "homeassistant")):
            del sys.modules[m]


@pytest.mark.parametrize("modul", MODULY)
def test_modul_jde_naimportovat(modul):
    importlib.import_module(f"napohodu.{modul}")


def test_vitr_blokuje_podle_dvou_prahu(nahradni_ha):
    """Koordinátor se dá zavolat, ne jen naimportovat.

    Chyby jako „get() se třemi argumenty" se projeví až za běhu, proto
    se ta funkce zkusí na několika hodnotách.
    """
    import importlib

    ko = importlib.import_module("napohodu.coordinator")
    c = importlib.import_module("napohodu.const")

    class Falesny:
        vitr_blokuje = False
        _vitr = ko.NaPohoduCoordinator._vitr

    f = Falesny()
    g = {c.CONF_VITR_PRAH: 7.0, c.CONF_NARAZ_PRAH: 11.0, c.CONF_VITR_KLID: 5.0}

    assert f._vitr(g, vitr=3.0, naraz=4.0) is False      # klid
    assert f._vitr(g, vitr=8.0, naraz=8.0) is True       # průměr přes práh
    assert f._vitr(g, vitr=6.0, naraz=6.0) is True       # drží, hystereze
    assert f._vitr(g, vitr=2.0, naraz=2.0) is False      # povolilo
    assert f._vitr(g, vitr=3.0, naraz=12.0) is True      # náraz přes práh
    assert f._vitr({}, vitr=20.0, naraz=20.0) is True    # výchozí hodnoty


# ------------------------------------------------- zakládání entit

class FalesnaPodentita:
    def __init__(self, typ, nazev, data=None):
        self.subentry_type = typ
        self.subentry_id = f"id_{nazev}"
        self.title = nazev
        self.data = data or {}


class FalesnyEntry:
    def __init__(self, podentity):
        self.entry_id = "entry"
        self.data = {}
        self.options = {}
        self.subentries = {p.subentry_id: p for p in podentity}


def _entity_platformy(modul, podentity):
    """Spustí zakládání entit a vrátí, co vzniklo."""
    import asyncio
    import importlib

    m = importlib.import_module(f"napohodu.{modul}")
    const = importlib.import_module("napohodu.const")
    entry = FalesnyEntry(podentity)

    class FalesnyHass:
        data = {const.DOMAIN: {"entry": object()}}

    vznikle = []

    def pridat(seznam, config_subentry_id=None):
        vznikle.extend(seznam)

    asyncio.run(m.async_setup_entry(FalesnyHass(), entry, pridat))
    return vznikle


def _klice(entity):
    return sorted(e._attr_translation_key for e in entity)


def test_mistnost_dostane_vsechny_prepinace(nahradni_ha):
    """Přepínače ovládání jsou entity, ne konfigurace. Když jeden chybí,
    uživatel nemá čím automatiku povolit."""
    import importlib
    const = importlib.import_module("napohodu.const")
    pod = FalesnaPodentita(const.PODENTITA_MISTNOST, "Kuchyne")
    assert _klice(_entity_platformy("switch", [pod])) == [
        "ovladat_okno", "ovladat_stineni", "ovladat_topeni"]


def test_klima_dostane_svuj_prepinac(nahradni_ha):
    import importlib
    const = importlib.import_module("napohodu.const")
    pod = FalesnaPodentita(const.PODENTITA_KLIMA, "Klima")
    assert _klice(_entity_platformy("switch", [pod])) == ["ovladat_klimu"]


def test_mistnost_dostane_tlacitka(nahradni_ha):
    import importlib
    const = importlib.import_module("napohodu.const")
    pod = FalesnaPodentita(const.PODENTITA_MISTNOST, "Kuchyne")
    klice = _klice(_entity_platformy("button", [pod]))
    assert "srovnat_okno" in klice and "srovnat_stineni" in klice


def test_tlacitka_stineni_jen_pro_prirazene_role(nahradni_ha):
    """Tlačítko, které nic nedělá, by jen zaplevelilo kartu."""
    import importlib
    const = importlib.import_module("napohodu.const")
    bez = FalesnaPodentita(const.PODENTITA_MISTNOST, "Kuchyne")
    assert "zastinit" not in _klice(_entity_platformy("button", [bez]))

    s = FalesnaPodentita(const.PODENTITA_MISTNOST, "Obyvak", {
        const.CONF_STINENI_MAPA: {"cover.o1|zastinit": "zastíněno",
                                  "cover.o1|soukromi": "dolů"}})
    klice = _klice(_entity_platformy("button", [s]))
    assert "zastinit" in klice and "soukromi" in klice
    assert "odstinit" not in klice


def test_mistnost_dostane_senzory(nahradni_ha):
    import importlib
    const = importlib.import_module("napohodu.const")
    pod = FalesnaPodentita(const.PODENTITA_MISTNOST, "Kuchyne")
    klice = _klice(_entity_platformy("sensor", [pod]))
    for k in ("stav", "cil", "slunce"):
        assert k in klice


def test_oblast_dostane_sdileny_vzduch(nahradni_ha):
    import importlib
    const = importlib.import_module("napohodu.const")
    pod = FalesnaPodentita(const.PODENTITA_ZONA, "Oblast")
    assert "stav_oblasti" in _klice(_entity_platformy("sensor", [pod]))


# ------------------------------------------------- jednotky větru

class FalesnyStav:
    def __init__(self, state, jednotka=None):
        self.state = state
        self.attributes = {"unit_of_measurement": jednotka} if jednotka else {}


def _rychlost(state, jednotka):
    """Zavolá převod bez celého koordinátoru."""
    import importlib
    ko = importlib.import_module("napohodu.coordinator")

    class Falesny:
        NA_MS = ko.NaPohoduCoordinator.NA_MS
        _rychlost = ko.NaPohoduCoordinator._rychlost

        def _stav(self, eid):
            return FalesnyStav(state, jednotka)

    return Falesny()._rychlost("sensor.vitr")


def test_metry_za_sekundu_se_neprepocitavaji(nahradni_ha):
    assert abs(_rychlost("7.0", "m/s") - 7.0) < 0.01


def test_kilometry_za_hodinu_se_prepoctou(nahradni_ha):
    """Ecowitt hlásí km/h, ale prahy jsou v m/s. Bez převodu by 7,2 km/h
    přeteklo práh 7 m/s, což je vánek proti čerstvému větru."""
    assert abs(_rychlost("7.2", "km/h") - 2.0) < 0.05


def test_mile_a_uzly(nahradni_ha):
    assert abs(_rychlost("10", "mph") - 4.47) < 0.05
    assert abs(_rychlost("10", "kn") - 5.14) < 0.05


def test_neznama_jednotka_se_bere_jako_ms(nahradni_ha):
    assert _rychlost("5", "beaufort") == 5.0


def test_chybejici_jednotka_se_bere_jako_ms(nahradni_ha):
    assert _rychlost("5", None) == 5.0


def test_nesmyslna_hodnota_da_nahradu(nahradni_ha):
    assert _rychlost("unavailable", "km/h") == 0.0


# ------------------------------------- atributy nezávislé na vybavení

def test_vlhkost_se_ukazuje_i_bez_zarizeni(nahradni_ha):
    """Hodnotu, kterou známe, má být vidět — i když není čím odsávat."""
    import asyncio
    import importlib

    ko = importlib.import_module("napohodu.coordinator")
    c = importlib.import_module("napohodu.const")

    class FalesnyStavRH:
        state = "43.5"
        attributes: dict = {}

    class Mistnost:
        obsazeno = True
        atributy: dict = {}

    class Falesny:
        _cislo = ko.NaPohoduCoordinator._cislo
        _stav = staticmethod(lambda eid: FalesnyStavRH() if eid else None)
        _pomocnici_krok = ko.NaPohoduCoordinator._pomocnici_krok
        _stav_pomocnika = staticmethod(
            ko.NaPohoduCoordinator._stav_pomocnika)
        _ukoly_ventilatoru = ko.NaPohoduCoordinator._ukoly_ventilatoru
        vykonavaci: dict = {}
        hass = None

    k = Falesny()
    m = Mistnost()
    m.atributy = {}
    d = {c.CONF_RH_VNITRNI: "sensor.vlhkost"}      # žádný odtah, žádný zvlhčovač
    asyncio.run(k._pomocnici_krok(_Pod(), d, m, {"pm25": 0, "pm10": 0}))
    assert m.atributy["vlhkost"] == 43.5
    assert m.atributy["zvlhcovac_bezi"] == "nenastaveno"
    assert m.atributy["ventilatory"] == "nenastaveno"


class _Pod:
    subentry_id = "id"
    title = "Kuchyne"


# ------------------------------------------- kontrola prahů ve formuláři

def _prahy(**kw):
    import importlib
    cf = importlib.import_module("napohodu.config_flow")
    c = importlib.import_module("napohodu.const")
    klice = {"otevrit": c.CONF_CO2_OTEVRIT, "zavrit": c.CONF_CO2_ZAVRIT,
             "noc": c.CONF_CO2_NOC, "krize": c.CONF_CO2_NOC_KRIZE}
    return cf._zkontroluj_prahy({klice[k]: v for k, v in kw.items()})


def test_rozumne_prahy_projdou(nahradni_ha):
    assert _prahy(otevrit=800, zavrit=700, noc=1000, krize=1250) == {}


def test_zaviraci_prah_nad_oteviracim_neprojde(nahradni_ha):
    """Obrácená mrtvá zóna by okno otevřela a hned zavřela."""
    assert _prahy(otevrit=800, zavrit=900)


def test_stejne_prahy_neprojdou(nahradni_ha):
    assert _prahy(otevrit=800, zavrit=800)


def test_nocni_prah_pod_dennim_neprojde(nahradni_ha):
    assert _prahy(otevrit=800, noc=700)


def test_nouzovy_prah_pod_nocnim_neprojde(nahradni_ha):
    assert _prahy(noc=1000, krize=900)


def test_chybejici_hodnoty_nevadi(nahradni_ha):
    assert _prahy(otevrit=800) == {}


# --------------------------------- zdroj okenního senzoru pro topení

def _okno_pro_topeni(zdroj, nase, kontakt):
    """Postaví entitu bez Home Assistantu a zeptá se na stav."""
    import importlib
    bs = importlib.import_module("napohodu.binary_sensor")
    c = importlib.import_module("napohodu.const")

    class Mistnost:
        okno_otevreno = nase
        atributy = {"kontakt_hlasi": kontakt}

    class Falesna:
        pod = type("P", (), {"data": {c.CONF_ZDROJ_OKENNIHO_M: zdroj}})()
        mistnost = Mistnost()
        is_on = bs.OknoOtevreno.is_on

    return Falesna().is_on


def test_zdroj_nase_otevreni(nahradni_ha):
    assert _okno_pro_topeni("nase_otevreni", True, False) is True
    assert _okno_pro_topeni("nase_otevreni", False, True) is False


def test_zdroj_fyzicke(nahradni_ha):
    """Pozná i okno otevřené rukou, o kterém pohon nic neví."""
    assert _okno_pro_topeni("fyzicke", False, True) is True
    assert _okno_pro_topeni("fyzicke", True, False) is False


def test_zdroj_oboji(nahradni_ha):
    assert _okno_pro_topeni("oboji", True, False) is True
    assert _okno_pro_topeni("oboji", False, True) is True
    assert _okno_pro_topeni("oboji", False, False) is False


def test_zdroj_nikdy(nahradni_ha):
    """Pro hlavici, která si otevřené okno pozná sama z poklesu."""
    assert _okno_pro_topeni("nikdy", True, True) is False


# ------------------------------------------- přežití restartu

def test_pamet_jde_ulozit_a_nacist(nahradni_ha):
    """Po restartu se nesmí zapomenout rozdělané větrání ani časovače."""
    import importlib
    from dataclasses import asdict, fields

    core = importlib.import_module("napohodu.core")
    p = core.Pamet(otevreno=True, rezim="pulz", den_mez=20.5,
                   cas_povelu_s=12345.0, vetra_se=True,
                   noc_mez=18.0, komfort_start=24.0,
                   rucni_do_s=99999.0, pm_venku_horsi_do_s=5555.0)

    zaznam = asdict(p)
    pole = {f.name for f in fields(core.Pamet)}
    obnovena = core.Pamet(**{k: v for k, v in zaznam.items() if k in pole})

    assert obnovena == p


def test_ulozena_pamet_snese_neznama_pole(nahradni_ha):
    """Starší uložený stav nesmí shodit načtení."""
    import importlib
    from dataclasses import fields

    core = importlib.import_module("napohodu.core")
    zaznam = {"otevreno": True, "rezim": "pulz", "_pulz_do_s": 500,
              "nezname_pole": 1}
    pole = {f.name for f in fields(core.Pamet)}
    p = core.Pamet(**{k: v for k, v in zaznam.items() if k in pole})
    assert p.otevreno is True and p.rezim == "pulz"


def test_vsechna_pole_pameti_jsou_serializovatelna(nahradni_ha):
    import importlib
    import json
    from dataclasses import asdict

    core = importlib.import_module("napohodu.core")
    json.dumps(asdict(core.Pamet()))


# ------------------------------- šoupátko a formulář ukazují totéž

def _koordinator(nahradni_ha=None):
    import importlib
    ko = importlib.import_module("napohodu.coordinator")

    class FalesneUloziste:
        def async_delay_save(self, *a, **kw):
            pass

    class Falesny:
        formular_zmenen = ko.NaPohoduCoordinator.formular_zmenen
        prepsano_formularem = ko.NaPohoduCoordinator.prepsano_formularem
        _srovnej_posuvniky = ko.NaPohoduCoordinator._srovnej_posuvniky

        def __init__(self):
            self.hodnoty = {}
            self._formular = {}
            self._prepsano = set()
            self._uloziste_pameti = FalesneUloziste()
            self._uloz_pameti = lambda: {}

    return Falesny()


def test_zmena_ve_formulari_prepise_soupatko(nahradni_ha):
    """Dvě místa pro tutéž hodnotu je past. Formulář je výslovný pokyn."""
    import importlib
    c = importlib.import_module("napohodu.const")
    k = _koordinator()

    # první cyklus: hodnota z formuláře se zapamatuje
    k._srovnej_posuvniky("m1", {c.CONF_CO2_OTEVRIT: 800.0})
    assert k.hodnoty[("m1", c.CONF_CO2_OTEVRIT)] == 800.0

    # člověk pohne šoupátkem
    k.hodnoty[("m1", c.CONF_CO2_OTEVRIT)] = 900.0
    k._srovnej_posuvniky("m1", {c.CONF_CO2_OTEVRIT: 800.0})
    assert k.hodnoty[("m1", c.CONF_CO2_OTEVRIT)] == 900.0   # šoupátko platí

    # člověk přepíše pole v nastavení
    k._srovnej_posuvniky("m1", {c.CONF_CO2_OTEVRIT: 750.0})
    assert k.hodnoty[("m1", c.CONF_CO2_OTEVRIT)] == 750.0


def test_nezmenene_pole_soupatkem_nehne(nahradni_ha):
    import importlib
    c = importlib.import_module("napohodu.const")
    k = _koordinator()
    k._srovnej_posuvniky("m1", {c.CONF_NOC_MIN: 18.0})
    k.hodnoty[("m1", c.CONF_NOC_MIN)] = 19.5
    for _ in range(5):
        k._srovnej_posuvniky("m1", {c.CONF_NOC_MIN: 18.0})
    assert k.hodnoty[("m1", c.CONF_NOC_MIN)] == 19.5


def test_prepsane_klice_maji_prednost_pred_obnovou(nahradni_ha):
    """Uložení formuláře znovu načte integraci. Bez tohohle by obnovená
    hodnota šoupátka změnu přepsala zpátky."""
    import importlib
    c = importlib.import_module("napohodu.const")
    k = _koordinator()
    k._srovnej_posuvniky("m1", {c.CONF_CO2_OTEVRIT: 800.0})
    assert k.prepsano_formularem(("m1", c.CONF_CO2_OTEVRIT)) is True
    assert k.prepsano_formularem(("m1", c.CONF_NOC_MIN)) is False


def test_formular_zmenen_hlasi_jen_zmenu(nahradni_ha):
    k = _koordinator()
    assert k.formular_zmenen(("m", "x"), 1.0) is True     # poprvé
    assert k.formular_zmenen(("m", "x"), 1.0) is False
    assert k.formular_zmenen(("m", "x"), 2.0) is True


# ------------------- místnost bez ovládaného okna

def test_diagnostika_bez_okna(nahradni_ha):
    """Hlášky o mezích poklesu a vyvětrání by u místnosti bez okna
    jen mátly."""
    import importlib
    ko = importlib.import_module("napohodu.coordinator")
    core = importlib.import_module("napohodu.core")

    d = ko.NaPohoduCoordinator._diagnostika
    v = core.Vstup(co2=681, cil=22.0, cas_s=1000)
    p = core.Pamet()
    n = core.Nastaveni()

    assert d([], False, v, p, n) == ["okno tady neovládáme"]
    assert d(["cover.x"], True, v, p, n) == ["větrá se"]
    assert d(["cover.x"], False, v, p, n)      # něco tam být musí


# ------------------------------------------- úkoly ventilátoru

def _ukoly(ukoly, rh=None, pm=0, t_max=None, venku=None, cil=22.0,
           dusno=False):
    import importlib
    ko = importlib.import_module("napohodu.coordinator")

    class Mistnost:
        atributy = {"potreba_vzduchu": dusno, "teplota_max": t_max,
                    "venku": venku}

    class Falesny:
        _ukoly_ventilatoru = ko.NaPohoduCoordinator._ukoly_ventilatoru

    m = Mistnost()
    m.cil = cil
    return Falesny()._ukoly_ventilatoru(ukoly, {}, m, rh, {"pm25": pm})


def test_ventilator_na_vlhkost(nahradni_ha):
    """Odtah v koupelně řeší vlhkost, nic jiného."""
    assert _ukoly(["vlhkost"], rh=75) == ["vlhkost 75 %"]
    assert _ukoly(["vlhkost"], rh=45) == []
    assert _ukoly(["vlhkost"], rh=45, dusno=True) == []


def test_ventilator_na_vzduch(nahradni_ha):
    assert _ukoly(["vzduch"], dusno=True) == ["dusno"]
    assert _ukoly(["vzduch"], dusno=False) == []


def test_ventilator_na_chlazeni(nahradni_ha):
    """Venku musí být chladněji, jinak by průvan situaci zhoršil."""
    assert _ukoly(["chlazeni"], t_max=26.0, venku=18.0, cil=22.0)
    assert _ukoly(["chlazeni"], t_max=26.0, venku=28.0, cil=22.0) == []
    assert _ukoly(["chlazeni"], t_max=21.0, venku=15.0, cil=22.0) == []


def test_ventilator_vic_ukolu_naraz(nahradni_ha):
    d = _ukoly(["vzduch", "vlhkost", "prach"], rh=75, pm=60, dusno=True)
    assert len(d) == 3


def test_ventilator_trvaly_provoz(nahradni_ha):
    assert _ukoly(["vzdy"]) == ["trvalý provoz"]


def test_ventilator_bez_ukolu_nebezi(nahradni_ha):
    assert _ukoly([], rh=90, pm=99, dusno=True) == []


# ------------------------------------------- režim topné sezóny

def _sezona(rezim, tri_dny=None):
    import importlib
    ko = importlib.import_module("napohodu.coordinator")
    c = importlib.import_module("napohodu.const")

    class Falesny:
        topna_sezona = False
        pouzity = {"tri_dny": (None, "")}
        _sezona = ko.NaPohoduCoordinator._sezona
        _sezona_podle_prumeru = ko.NaPohoduCoordinator._sezona_podle_prumeru
        _cislo = staticmethod(lambda eid, nahrada=None: tri_dny)

        class prumery:
            tri_dny = None

    return Falesny()._sezona({c.CONF_SEZONA_REZIM: rezim})


def test_sezona_vzdy_topi(nahradni_ha):
    """Když sezónu určuješ sám jinde, tohle ji zapne nastálo."""
    assert _sezona("vzdy") is True


def test_sezona_nikdy_netopi(nahradni_ha):
    assert _sezona("nikdy") is False


def test_sezona_podle_prumeru_rozhoduje_teplota(nahradni_ha):
    assert _sezona("podle_prumeru", tri_dny=8.0) is True
    assert _sezona("podle_prumeru", tri_dny=22.0) is False



def test_stavy_pomocniku_jsou_citelne(nahradni_ha):
    """Prázdný atribut se v kartě ukáže jako Neznámý a člověk neví,
    jestli zařízení nemá, nebo jen ještě nedostalo povel."""
    import importlib
    ko = importlib.import_module("napohodu.coordinator")
    f = ko.NaPohoduCoordinator._stav_pomocnika

    assert f([], None) == "nenastaveno"
    assert f(["switch.x"], None) == "zatím bez povelu"
    assert f(["switch.x"], True) == "běží"
    assert f(["switch.x"], False) == "stojí"


# ------------------------------------------- seznam ventilátorů

def test_starsi_nastaveni_jednoho_ventilatoru(nahradni_ha):
    """Kdo měl ventilátor v původním poli, nesmí o něj přijít."""
    import importlib
    c = importlib.import_module("napohodu.const")
    d = {c.CONF_VENTILATOR: ["fan.x"],
         c.CONF_VENTILATOR_UKOLY: ["vlhkost"]}

    seznam = list(d.get(c.CONF_VENTILATORY) or [])
    if not seznam and d.get(c.CONF_VENTILATOR):
        seznam = [{c.CONF_VENTILATOR: d[c.CONF_VENTILATOR],
                   c.CONF_VENTILATOR_UKOLY: d.get(c.CONF_VENTILATOR_UKOLY)}]
    assert seznam[0][c.CONF_VENTILATOR] == ["fan.x"]
    assert seznam[0][c.CONF_VENTILATOR_UKOLY] == ["vlhkost"]


def test_formular_ukazuje_platne_hodnoty(nahradni_ha):
    """Posuvník zapisuje do běžící paměti, formulář četl uloženou
    konfiguraci — každý ukazoval něco jiného."""
    import importlib
    cf = importlib.import_module("napohodu.config_flow")
    c = importlib.import_module("napohodu.const")

    class FalesnyKoordinator:
        hodnoty = {("m1", c.CONF_NOC_MIN): 19.5}

    class FalesnyFlow:
        _platne = cf.MistnostSubentryFlow._platne

        class hass:
            data = {c.DOMAIN: {"e1": FalesnyKoordinator()}}

        @staticmethod
        def _get_entry():
            return type("E", (), {"entry_id": "e1"})()

    out = FalesnyFlow()._platne("m1", {c.CONF_NOC_MIN: 18.0,
                                       c.CONF_NAZEV: "Ložnice"})
    assert out[c.CONF_NOC_MIN] == 19.5      # platí posuvník
    assert out[c.CONF_NAZEV] == "Ložnice"   # ostatní zůstává
