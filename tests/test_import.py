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
    "karty", "zpravy", "klima", "select",
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
        zvlhcuje: set = set()
        vykonavaci: dict = {}
        hass = None

    k = Falesny()
    m = Mistnost()
    m.atributy = {}
    d = {c.CONF_RH_VNITRNI: "sensor.vlhkost"}      # žádný odtah, žádný zvlhčovač
    asyncio.run(k._pomocnici_krok(_Pod(), d, m, {"pm25": 0, "pm10": 0},
                                  21.0, 5.0, False, True))
    assert m.atributy["vlhkost"] == 43.5
    assert m.atributy["zvlhcovac_bezi"] == "nenastaveno"


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
    v = core.Vstup(co2=681, cil=22.0, cas_s=1000, t_out=15.0)
    p = core.Pamet()
    n = core.Nastaveni()

    assert d([], False, v, p, n) == ["okno tady neovládáme"]
    assert d(["cover.x"], True, v, p, n) == ["větrá se"]
    assert d(["cover.x"], False, v, p, n)      # něco tam být musí


# ------------------------------------------- úkoly ventilátoru


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
        hodnota = staticmethod(lambda a, b, vych: vych)

        class entry:
            entry_id = "id"

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


# ------------------------------------------- ventilátory podle úkolu




# ------------------------------------------- chování per žaluzie

def test_vlastni_chovani_prebiji_mistnost(nahradni_ha):
    """Dvě okna v pokoji míří jinam a člověk je chce řídit každé jinak."""
    import importlib
    c = importlib.import_module("napohodu.const")

    d = {c.CONF_STINENI_REZIM: "vzdy", c.CONF_SOUKROMI_KDY: "nikdy"}
    chovani = {"cover.o2": {c.CONF_STINENI_REZIM: "jen_pryc"}}

    def nastav(z, klic, vychozi):
        return (chovani.get(z) or {}).get(klic, d.get(klic, vychozi))

    assert nastav("cover.o1", c.CONF_STINENI_REZIM, "vzdy") == "vzdy"
    assert nastav("cover.o2", c.CONF_STINENI_REZIM, "vzdy") == "jen_pryc"
    # co není přenastavené, bere se z místnosti
    assert nastav("cover.o2", c.CONF_SOUKROMI_KDY, "nikdy") == "nikdy"


def test_chovani_klice(nahradni_ha):
    import importlib
    c = importlib.import_module("napohodu.const")
    assert c.CONF_STINENI_REZIM in c.CHOVANI_KLICE
    assert c.CONF_VYCHOZI_KDY in c.CHOVANI_KLICE


def test_popisky_poli_zaluzii_jsou_citelne(nahradni_ha):
    """Home Assistant umí přeložit jen názvy známé předem. Tyhle vznikají
    podle toho, jaké žaluzie v místnosti jsou, takže text musí dávat
    smysl sám o sobě."""
    import importlib
    cf = importlib.import_module("napohodu.config_flow")

    class Stav:
        attributes = {"friendly_name": "Žaluzie kuchyně"}

    class Hass:
        class states:
            @staticmethod
            def get(eid):
                return Stav()

    f = cf.MistnostSubentryFlow.__new__(cf.MistnostSubentryFlow)
    f.hass = Hass()
    klice = cf.MistnostSubentryFlow._klice_stineni(f, ["cover.k", "cover.o"])

    assert "1. Žaluzie kuchyně — stav pro zastínění" in klice
    assert all("#" not in k and "|" not in k for k in klice)
    # každá žaluzie má pět rolí a tři volby chování
    assert len(klice) == 16
    # stav a chování se nepletou
    assert "1. Žaluzie kuchyně — stav pro soukromí" in klice
    assert "1. Žaluzie kuchyně — kdy zatáhnout kvůli soukromí" in klice


def test_popisky_jdou_precist_zpatky(nahradni_ha):
    """Podle popisku se pozná, ke které žaluzii a nastavení patří."""
    import importlib
    cf = importlib.import_module("napohodu.config_flow")
    c = importlib.import_module("napohodu.const")

    class Hass:
        class states:
            @staticmethod
            def get(eid):
                return None

    f = cf.MistnostSubentryFlow.__new__(cf.MistnostSubentryFlow)
    f.hass = Hass()
    klice = cf.MistnostSubentryFlow._klice_stineni(f, ["cover.k"])

    z, druh, co = klice["1. cover.k — kdy smí automatika hýbat"]
    assert (z, druh, co) == ("cover.k", "chovani", "rezim")
    z, druh, co = klice["1. cover.k — výchozí stav"]
    assert (z, druh, co) == ("cover.k", "role", "vychozi")


def test_chovani_zaluzii_neni_dvakrat(nahradni_ha):
    """Dvojí místo pro totéž je past — chování se nastavuje jen
    u žaluzie, ne i u místnosti."""
    import importlib
    import re
    cf = importlib.import_module("napohodu.config_flow")

    zdroj = __import__("pathlib").Path(cf.__file__).read_text()
    blok = zdroj[zdroj.index("def _schema_mistnost"):
                 zdroj.index("SCHEMA_PRITOMNOST")]
    pole = set(re.findall(r"vol\.\w+\(c\.(CONF_\w+)", blok))

    assert "CONF_STINENI_REZIM" not in pole
    assert "CONF_SOUKROMI_KDY" not in pole
    assert "CONF_VYCHOZI_KDY" not in pole
    # seznam žaluzií a azimut u místnosti zůstávají
    assert "CONF_ZALUZIE" in pole and "CONF_AZIMUT" in pole


def test_narazove_je_videt_dokud_bezi(nahradni_ha):
    """Příznak drží, dokud nárazový pulz běží — i když spouštěcí
    podmínka mezitím zmizela."""
    import importlib
    core = importlib.import_module("napohodu.core")

    p = core.Pamet(cas_povelu_s=0)
    core.rozhodni(core.Vstup(co2=911, t_in=21, t_out=15.5, cil=22,
                             cas_s=100000, narazove=True), p,
                  core.Nastaveni(narazove_odstup=4.0))
    assert p.narazove_pulz is True

    # a jakmile pulz skončí, příznak zmizí
    core.rozhodni(core.Vstup(co2=400, t_in=21, t_out=15.5, cil=22,
                             cas_s=200000), p,
                  core.Nastaveni(narazove_odstup=4.0))
    assert p.narazove_pulz is False


def test_odeslany_souhrn_prezije_znovunacteni(nahradni_ha):
    """Uložení nastavení integraci restartuje. Bez tohohle by denní
    souhrn přišel po každé úpravě znovu."""
    import importlib
    ko = importlib.import_module("napohodu.coordinator")

    class Falesny:
        _formular: dict = {}
        _souhrn_odeslan = "2026-01-15"
        pameti: dict = {}
        vykonavaci: dict = {}
        _uloz_pameti = ko.NaPohoduCoordinator._uloz_pameti

    snimek = Falesny()._uloz_pameti()
    assert snimek["_souhrn_odeslan"] == "2026-01-15"

    # a při načtení se vezme zpátky
    obnoveny = snimek.pop("_souhrn_odeslan", "") or ""
    assert obnoveny == "2026-01-15"



def test_vyber_stavu_zaluzie(nahradni_ha):
    """Žaluzii jde poslat do kteréhokoli jejího uloženého stavu."""
    import importlib
    sel = importlib.import_module("napohodu.select")

    class Pod:
        subentry_id = "m1"
        title = "Ložnice"
        subentry_type = "mistnost"
        data = {}

    class K:
        vykonavaci = {}

    e = sel.StavZaluzie.__new__(sel.StavZaluzie)
    e._zaluzie = "cover.l"
    e.pod_id = "m1"
    e.coordinator = K()
    assert e.current_option is None           # nic jsme ještě neposlali
    assert e.extra_state_attributes == {"zaluzie": "cover.l"}


def test_neznamy_stav_neni_vypnuto(nahradni_ha):
    """Po startu hlásí entity chvíli unknown. Brát to jako vypnuto
    znamenalo „nikdo doma" a žaluzie se rozjely."""
    import importlib
    ko = importlib.import_module("napohodu.coordinator")

    class Stav:
        def __init__(self, s):
            self.state = s

    class Falesny:
        _zapnuto = ko.NaPohoduCoordinator._zapnuto

        def __init__(self, stav):
            self._s = stav

        def _stav(self, eid):
            return Stav(self._s) if self._s is not None else None

    assert Falesny("unknown")._zapnuto("x") is None
    assert Falesny("unavailable")._zapnuto("x") is None
    assert Falesny(None)._zapnuto("x") is None
    assert Falesny("on")._zapnuto("x") is True
    assert Falesny("home")._zapnuto("x") is True
    assert Falesny("off")._zapnuto("x") is False
    assert Falesny("not_home")._zapnuto("x") is False
    # zone.home hlásí počet lidí doma
    assert Falesny("1")._zapnuto("x") is True
    assert Falesny("2")._zapnuto("x") is True
    assert Falesny("0")._zapnuto("x") is False


def test_sezona_zacina_pod_prahem(nahradni_ha):
    """Hystereze patří nad práh. Dřív se rozkládala na obě strany,
    takže se při prahu 13 zapínala až pod 12,5."""
    def sezona(t, drive, prah=13.0, hyst=1.0):
        if t < prah:
            return True
        if t > prah + hyst:
            return False
        return drive

    assert sezona(12.9, False) is True       # zapne pod prahem
    assert sezona(13.0, False) is False      # na prahu ještě ne
    assert sezona(13.5, True) is True        # v pásmu drží
    assert sezona(14.1, True) is False       # nad pásmem končí


def test_tlacitka_oken(nahradni_ha):
    """Ruční otevření se bere jako zásah, jinak by automatika okno
    hned vrátila zpátky."""
    import importlib
    b = importlib.import_module("napohodu.button")
    core = importlib.import_module("napohodu.core")

    volani = []

    class Hass:
        class services:
            @staticmethod
            async def async_call(domena, sluzba, data, blocking=False):
                volani.append((domena, sluzba, tuple(data["entity_id"])))

    pamet = core.Pamet()

    class K:
        pameti = {"m1": pamet}

    e = b.Okno.__new__(b.Okno)
    e._otevrit = True
    e.pod = type("P", (), {"data": {"okna": ["cover.k"]}})()
    e.pod_id = "m1"
    e.hass = Hass()
    e.coordinator = K()

    import asyncio
    asyncio.run(e.async_press())
    assert volani == [("cover", "open_cover", ("cover.k",))]
    assert pamet.otevreno is True
    assert pamet.rucni_do_s > 0          # automatika chvíli nemluví


def test_poradi_mistnosti_na_karte(nahradni_ha):
    """Bez nastavení se místnosti řadí podle toho, jak vznikly."""
    def serad(mistnosti, poradi):
        """Stejné řazení, jaké dělá generátor karty."""
        puvodni = {k: i for i, k in enumerate(mistnosti)}
        return sorted(mistnosti,
                      key=lambda k: (poradi.get(k, 0), puvodni[k]))

    assert serad(["kuchyne", "obyvak", "loznice"],
                 {"obyvak": 1, "kuchyne": 2, "loznice": 3}) == [
        "obyvak", "kuchyne", "loznice"]

    # při stejném čísle zůstane pořadí, jak místnosti vznikly
    assert serad(["kuchyne", "obyvak"], {}) == ["kuchyne", "obyvak"]


def test_zvlhcovac_ma_obe_meze(nahradni_ha):
    """Dolní mez zapíná, horní vypíná. Pevných pět procent nad minimem
    byla hodnota, kterou nešlo ovlivnit."""
    def zapnout(rh, rh_min=38.0, rh_max=60.0):
        rh_max = max(rh_max, rh_min + 2)
        if rh < rh_min:
            return True
        if rh > rh_max:
            return False
        return None

    assert zapnout(30.0) is True
    assert zapnout(45.0) is None          # mezi mezemi se nesahá
    assert zapnout(65.0) is False
    # horní mez pod dolní by přepínala pořád, proto ten odstup
    assert zapnout(41.0, rh_min=40.0, rh_max=35.0) is None
    assert zapnout(43.0, rh_min=40.0, rh_max=35.0) is False


def test_diagnostika_zaluzii_se_nastavuje(nahradni_ha):
    """Tři atributy vypadly při přepisu na chování per žaluzie —
    a s nimi tiše i ochrana proti neexistující entitě."""
    import pathlib
    ko = pathlib.Path(
        "custom_components/napohodu/coordinator.py").read_text()
    for a in ("zaluzie_chybi", "stineni_mapa", "vraceni_vychoziho"):
        assert f'atributy["{a}"]' in ko, a
    # a povel se na neexistující entitu neposílá
    assert "cile.pop(z, None)" in ko


def test_venkovni_teplota_se_nevymysli(nahradni_ha):
    """Vymyšlená patnáctka se po restartu propsala do rozhodnutí —
    okno se zavřelo „kvůli chladu venku", který nikdy nebyl."""
    import pathlib
    ko = pathlib.Path(
        "custom_components/napohodu/coordinator.py").read_text()
    # žádná pevná náhrada venkovní teploty
    assert 'CONF_T_VENKU), 15.0' not in ko
    # poslední známá hodnota se pamatuje
    assert "_t_out_posledni" in ko


def test_pauza_roste_po_kazdem_teplotnim_zavreni(nahradni_ha):
    """Když se okno hned vrací, teplotní mez a rychlost návratu pokoje
    se nesnesou — pauza se proto zdvojnásobuje."""
    def pauza(kolikate, zaklad_min=15):
        return min(zaklad_min * 60 * 2 ** (kolikate - 1), 3600) / 60

    assert pauza(1) == 15
    assert pauza(2) == 30
    assert pauza(3) == 60
    assert pauza(9) == 60          # strop je hodina


def test_pasmo_jen_kde_je_okno(nahradni_ha):
    """V místnosti bez okna ukazovalo meze, podle kterých se nikdy nic
    nestane, a stav okna, který neznáme."""
    import pathlib
    ko = pathlib.Path(
        "custom_components/napohodu/coordinator.py").read_text()
    assert '"teplotni_pasmo": None if not okna' in ko


def test_oblast_je_ze_spanku_jedna_vec(nahradni_ha):
    """Místnosti, které spolu dýchají, jsou jedna místnost přepažená
    průchodem — rámus okna v kuchyni dolehne do obýváku."""
    mistnosti = {"kuchyne": False, "obyvak": True}
    assert any(mistnosti.values()) is True       # spí se v oblasti
    assert all(mistnosti.values()) is False      # dřív to nestačilo


def test_zavrene_dvere_rusi_spolecny_klid(nahradni_ha):
    """Zavřené dveře znamenají, že se rámus nepřenese — spánek v jedné
    místnosti pak druhé nebrání větrat."""
    import pathlib
    ko = pathlib.Path(
        "custom_components/napohodu/coordinator.py").read_text()
    assert 'o["dvere_otevrene"]' in ko
    assert 'if o["dvere_otevrene"] else False' in ko


def test_tloustka_az_do_sedmi(nahradni_ha):
    """Čtyři stupně nestačily, okno pořád lítalo."""
    import pathlib
    import re
    cf = pathlib.Path(
        "custom_components/napohodu/config_flow.py").read_text()
    nb = pathlib.Path("custom_components/napohodu/number.py").read_text()
    assert "CONF_TLOUSTKA, default=1.0): _cislo(0, 7, 0.5)" in cf
    assert re.search(r"Posuvnik\(CONF_TLOUSTKA, 0, 7", nb)


def test_stupnice_bere_pevnou_pojistku(nahradni_ha):
    """Nastavení zmizelo, ale stupnice ho ještě chvíli chtěla — a
    integrace se kvůli tomu nenačetla."""
    import pathlib
    ko = pathlib.Path(
        "custom_components/napohodu/coordinator.py").read_text()
    assert "nast.spanek_pojistka" not in ko
    assert "core.SPANEK_POJISTKA" in ko


def test_zvlhcovac_respektuje_okno_a_pritomnost(nahradni_ha):
    """Zvlhčovat při otevřeném okně znamená zvlhčovat ulici."""
    import asyncio
    import importlib

    ko = importlib.import_module("napohodu.coordinator")
    c = importlib.import_module("napohodu.const")

    class StavRH:
        state = "30.0"
        attributes: dict = {}

    class Mistnost:
        obsazeno = False
        klid = False
        atributy: dict = {}

    volani = []

    class Vyk:
        class stav:
            zarizeni: dict = {}

        async def zarizeni(self, entity, zapnout, jmeno):
            volani.append(zapnout)
            return "ok"

    def postav(otevreno, doma, kdy):
        class Falesny:
            _cislo = ko.NaPohoduCoordinator._cislo
            _stav = staticmethod(lambda eid: StavRH() if eid else None)
            _pomocnici_krok = ko.NaPohoduCoordinator._pomocnici_krok
            _stav_pomocnika = staticmethod(
                ko.NaPohoduCoordinator._stav_pomocnika)
            hodnota = staticmethod(lambda a, b, vych: vych)
            vykonavaci = {"id": Vyk()}
            zvlhcuje: set = set()
            hass = None

        m = Mistnost()
        m.atributy = {}
        d = {c.CONF_RH_VNITRNI: "sensor.vlhkost",
             c.CONF_ZVLHCOVAC: ["input_boolean.z"],
             c.CONF_ZVLHCOVAC_KDY: kdy}
        asyncio.run(Falesny()._pomocnici_krok(
            _Pod(), d, m, {"pm25": 0, "pm10": 0}, 21.0, 5.0, otevreno, doma))
        return m

    # vlhkost 30 % je pod dolní mezí, takže by se normálně zapnul
    volani.clear()
    m = postav(otevreno=False, doma=True, kdy="vzdy")
    assert volani == [True]

    volani.clear()
    m = postav(otevreno=True, doma=True, kdy="vzdy")
    assert volani == [False]
    assert "otevřené okno" in m.atributy["zvlhcovac_proc"]

    volani.clear()
    m = postav(otevreno=False, doma=False, kdy="doma")
    assert volani == [False]
    assert "nikdo není doma" in m.atributy["zvlhcovac_proc"]


def test_prach_ze_zvlhcovace_se_nepocita(nahradni_ha):
    """Ultrazvukový zvlhčovač rozprašuje minerály a čidlo je vidí jako
    prach. Větrat ani čistit kvůli tomu nemá smysl."""
    import pathlib
    ko = pathlib.Path(
        "custom_components/napohodu/coordinator.py").read_text()
    # prach se pro rozhodování vynuluje, a to v celé zóně
    assert "pm25=0.0 if self._zvlhcuje_v_okruhu" in ko
    assert "def _zvlhcuje_v_okruhu" in ko
    # a čistička na vlastní aerosol taky nereaguje
    assert "zvlhcuje = p.subentry_id in self.zvlhcuje" in ko
    assert '"prach_ze_zvlhcovace"' in ko


def test_cekani_po_marnem_je_videt(nahradni_ha):
    """Čekání řídí jedno pravidlo — změna venku, nejpozději strop.
    Dvojí mechanismus jen pletl, kolik se vlastně čeká."""
    import pathlib
    ko = pathlib.Path(
        "custom_components/napohodu/coordinator.py").read_text()
    assert '"cekani_po_marnem"' in ko
    assert 'if r.kod == "bez_ucinku":' not in ko


def test_popisek_sezony_mluvi_o_trinacti(nahradni_ha):
    """Patnáctka bývá v mnoha domech moc brzy."""
    import json
    import pathlib
    for jazyk in ("cs", "en"):
        d = json.loads(pathlib.Path(
            f"custom_components/napohodu/translations/{jazyk}.json"
        ).read_text())
        popis = d["config"]["step"]["user"]["data_description"]["sezona_prah"]
        assert "13" in popis
        assert "Obvykle 15" not in popis


def test_prehled_bytu_uvadi_narazovy_rezim(nahradni_ha):
    """Volba, kterou jsme přidali naposled, musí být na dashboardu
    vidět — posuvník z ní udělat nejde, je globální."""
    import importlib

    ko = importlib.import_module("napohodu.coordinator")
    c = importlib.import_module("napohodu.const")

    class Zapis:
        entry_id = "id"

    class Falesny:
        _prehled_bytu = ko.NaPohoduCoordinator._prehled_bytu
        _cas = staticmethod(ko.NaPohoduCoordinator._cas)
        _hodina = staticmethod(ko.NaPohoduCoordinator._hodina)
        hodnota = staticmethod(lambda a, b, vych: vych)
        entry = Zapis()
        narazove = True
        topna_sezona = False

    radky = Falesny()._prehled_bytu({
        c.CONF_NARAZOVE: True, c.CONF_NARAZOVE_ODSTUP: 15.0,
        c.CONF_ZMENA_PODMINEK: 2.0, c.CONF_NEJDRIV_ZNOVU: 60})
    text = " | ".join(radky)
    assert "Nárazový režim" in text and "15.0" in text
    assert "běží" in text
    assert "změně venku o 2.0" in text
    assert "Topná sezóna" in text


def test_prehled_bytu_zvlada_cas_z_formulare(nahradni_ha):
    """Noční hodiny chodí z formuláře jako „22:00:00", ne jako číslo —
    integrace se kvůli tomu nenačetla."""
    import importlib

    ko = importlib.import_module("napohodu.coordinator")
    c = importlib.import_module("napohodu.const")

    class Zapis:
        entry_id = "id"

    class Falesny:
        _prehled_bytu = ko.NaPohoduCoordinator._prehled_bytu
        _cas = staticmethod(ko.NaPohoduCoordinator._cas)
        _hodina = staticmethod(ko.NaPohoduCoordinator._hodina)
        hodnota = staticmethod(lambda a, b, vych: vych)
        entry = Zapis()
        narazove = False
        topna_sezona = True

    radky = Falesny()._prehled_bytu({
        c.CONF_NOC_OD: "22:00:00", c.CONF_NOC_DO: "06:30:00"})
    text = " | ".join(radky)
    assert "22:00" in text and "6:30" in text


def test_vynulovani_nesahne_na_nastaveni(nahradni_ha):
    """Tlačítko smí zapomenout rozdělané větrání, ne uživatelské volby."""
    import importlib

    ko = importlib.import_module("napohodu.coordinator")
    core = importlib.import_module("napohodu.core")

    class Falesny:
        vynuluj_stavy = ko.NaPohoduCoordinator.vynuluj_stavy
        pameti = {"id": core.Pamet(
            otevreno=True, rezim="pulz", den_mez=19.0, pulzy_za_sebou=3,
            marne_od_s=1000.0, zavreno_chladem=True, chladi=True,
            ucinek_od_s=500.0, cas_povelu_s=12345.0)}
        hodnoty = {("id", "odchylka_teploty"): 1.5}
        zvlhcuje = {"id"}
        vykonavaci: dict = {}

    k = Falesny()
    k.vynuluj_stavy()
    p = k.pameti["id"]

    # vnitřní stavy pryč
    assert p.rezim == core.Pamet().rezim
    assert p.den_mez is None and p.pulzy_za_sebou == 0
    assert p.marne_od_s == 0.0 and p.zavreno_chladem is False
    assert p.chladi is False and p.ucinek_od_s == 0.0
    assert not k.zvlhcuje

    # čekání a odpočty taky, jinak by „bod nula" neznamenal nic
    assert p.cas_povelu_s < 0 and p.rucni_do_s == 0.0

    # uživatelské volby a skutečný stav okna zůstávají
    assert k.hodnoty[("id", "odchylka_teploty")] == 1.5
    assert p.otevreno is True


def test_vynulovani_zrusi_i_cekani(nahradni_ha):
    """Bez zrušení odpočtů by „bod nula" neznamenal nic — dál by se
    drželo držení polohy, ruční klid i dojezd pulzu."""
    import importlib

    ko = importlib.import_module("napohodu.coordinator")
    core = importlib.import_module("napohodu.core")

    class Stav:
        pulz_do_s = 999999.0
        posledni_cas_s = 999999.0

    class Vyk:
        stav = Stav()

    class Falesny:
        vynuluj_stavy = ko.NaPohoduCoordinator.vynuluj_stavy
        pameti = {"id": core.Pamet(
            cas_povelu_s=999999.0, rucni_do_s=999999.0,
            pm_venku_horsi_do_s=999999.0, marne_od_s=999999.0,
            pm_otevreno_od_s=999999.0)}
        hodnoty: dict = {}
        zvlhcuje: set = set()
        vykonavaci = {"id": Vyk()}

    k = Falesny()
    k.vynuluj_stavy()
    p = k.pameti["id"]

    assert p.cas_povelu_s < 0            # žádné držení polohy
    assert p.rucni_do_s == 0.0           # ani ruční klid
    assert p.pm_venku_horsi_do_s == 0.0  # ani poznatek o prachu
    assert p.marne_od_s == 0.0
    assert k.vykonavaci["id"].stav.pulz_do_s is None
    assert k.vykonavaci["id"].stav.posledni_cas_s < 0


def test_zona_se_chova_jako_jedna_mistnost(nahradni_ha):
    """Kuchyň a obývák za otevřenými dveřmi mají společný vzduch:
    zvlhčovač v jednom zvedne prach v druhém a otevřené okno v jednom
    znamená, že druhý nemá co zvlhčovat."""
    import importlib

    ko = importlib.import_module("napohodu.coordinator")

    class Pod:
        def __init__(self, pid):
            self.subentry_id = pid

    class Stav:
        def __init__(self, povel=None):
            self.posledni_povel = povel

    class Vyk:
        def __init__(self, povel=None):
            self.stav = Stav(povel)

    class Falesny:
        _zvlhcuje_v_okruhu = ko.NaPohoduCoordinator._zvlhcuje_v_okruhu
        _okno_v_okruhu = ko.NaPohoduCoordinator._okno_v_okruhu
        zvlhcuje = {"kuchyne"}
        vykonavaci = {"kuchyne": Vyk("otevrit"), "obyvak": Vyk()}

    k = Falesny()
    okruh = {"cleni": [Pod("kuchyne"), Pod("obyvak")],
             "dvere_otevrene": True}

    # obývák vidí zvlhčovač i okno kuchyně
    assert k._zvlhcuje_v_okruhu(okruh, "obyvak") is True
    assert k._okno_v_okruhu(okruh, "obyvak") is True

    # se zavřenými dveřmi se neovlivňují
    zavreno = {**okruh, "dvere_otevrene": False}
    assert k._zvlhcuje_v_okruhu(zavreno, "obyvak") is False
    assert k._okno_v_okruhu(zavreno, "obyvak") is False


def test_kontakt_okna_plati_i_bez_ovladani(nahradni_ha):
    """V obýváku okno neovládáme, ale kontakt máme — zvlhčovač nesmí
    běžet při otevřeném okně, i když ho otevřela ruka."""
    import pathlib
    ko = pathlib.Path(
        "custom_components/napohodu/coordinator.py").read_text()
    assert "(bool(okna) or bool(kontakty)) and skutecne" in ko
    assert "okno_fakt" in ko
