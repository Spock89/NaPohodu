"""Převod uloženého nastavení na to, co umí nová verze.

Měnit výchozí hodnotu nestačí: výchozí platí jen pro nově zakládanou
místnost. Ta stávající má v konfiguraci uloženou starou hodnotu a bez
převodu by se u ní nezměnilo nic — přesně to se stalo u předstihu
stínění, kde šlo o to chování zrušit všude.
"""

import importlib
import pathlib
import sys

import pytest

KOREN = pathlib.Path(__file__).parent.parent


@pytest.fixture(scope="module")
def modul():
    sys.path.insert(0, str(KOREN / "tests" / "stub_ha"))
    sys.path.insert(0, str(KOREN / "custom_components"))
    m = importlib.import_module("napohodu")
    c = importlib.import_module("napohodu.const")
    yield m, c
    for jmeno in list(sys.modules):
        if jmeno.startswith(("napohodu", "homeassistant")):
            del sys.modules[jmeno]
    sys.path.remove(str(KOREN / "custom_components"))
    sys.path.remove(str(KOREN / "tests" / "stub_ha"))


class _Pod:
    def __init__(self, typ, title, data, subentry_id=None):
        self.subentry_type, self.title, self.data = typ, title, data
        self.subentry_id = subentry_id or title.lower()


class _Zapis:
    def __init__(self, podentity, entry_id="zapis"):
        self.subentries = {str(i): p for i, p in enumerate(podentity)}
        self.entry_id = entry_id


class _Spravce:
    def __init__(self):
        self.zapsano = []

    def async_update_subentry(self, zapis, pod, data):
        pod.data = dict(data)
        self.zapsano.append(pod.title)


class _Hass:
    def __init__(self):
        self.config_entries = _Spravce()


def test_predstih_stineni_se_zrusi_i_u_zalozenych_mistnosti(modul):
    m, c = modul
    pokoj = _Pod(c.PODENTITA_MISTNOST, "Obývák",
                 {c.CONF_STINENI_PREDSTIH: 1.0, c.CONF_NAZEV: "Obývák"})
    jiny = _Pod(c.PODENTITA_MISTNOST, "Dílna",
                {c.CONF_STINENI_PREDSTIH: 2.0})
    uz_nula = _Pod(c.PODENTITA_MISTNOST, "Ložnice",
                   {c.CONF_STINENI_PREDSTIH: 0.0})
    bez = _Pod(c.PODENTITA_MISTNOST, "Kuchyně", {})
    zona = _Pod(c.PODENTITA_ZONA, "Oblast",
                {c.CONF_STINENI_PREDSTIH: 1.0})
    zapis = _Zapis([pokoj, jiny, uz_nula, bez, zona])
    hass = _Hass()

    m._preved(hass, zapis)

    assert pokoj.data[c.CONF_STINENI_PREDSTIH] == 0.0
    # i ručně nastavená hodnota: šlo o to chování zrušit všude
    assert jiny.data[c.CONF_STINENI_PREDSTIH] == 0.0
    # ostatní nastavení místnosti převod nesmí shodit pod stůl
    assert pokoj.data[c.CONF_NAZEV] == "Obývák"
    # co už nulu má nebo klíč nemá, se nepřepisuje
    assert uz_nula.data[c.CONF_STINENI_PREDSTIH] == 0.0
    assert c.CONF_STINENI_PREDSTIH not in bez.data
    # a podentita, která není místnost, se nechává být
    assert zona.data[c.CONF_STINENI_PREDSTIH] == 1.0
    assert hass.config_entries.zapsano == ["Obývák", "Dílna"]

    # Podruhé už nesmí sáhnout na nic. Zápis do podentity spouští
    # znovunačtení integrace, které spustí převod — a ten, kdyby
    # zapisoval i beze změny, by se tím točil dokola.
    hass.config_entries.zapsano.clear()
    m._preved(hass, zapis)
    assert hass.config_entries.zapsano == []


def test_uklid_smaze_entity_bez_zarizeni(modul):
    """Přestat entity zakládat nestačí — registr si je drží dál."""
    m, c = modul
    from homeassistant.helpers import entity_registry as er

    bez = _Pod(c.PODENTITA_MISTNOST, "Dílna", {}, "d1")
    s_oknem = _Pod(c.PODENTITA_MISTNOST, "Kuchyně",
                   {c.CONF_OKNA: ["cover.kuchyn"]}, "k1")
    kontakt = _Pod(c.PODENTITA_MISTNOST, "Obývák",
                   {c.CONF_KONTAKT_M: ["binary_sensor.obyvak"]}, "o1")
    zapis = _Zapis([bez, s_oknem, kontakt])
    hass = _Hass()
    hass.registr = er.Registr([
        # Dílna nemá nic: všechny druhy vázané na vybavení jdou pryč.
        er.RegistrZapis("switch.dilna_okno", "d1_ovladat_okno",
                        config_entry_id="zapis"),
        er.RegistrZapis("switch.dilna_pohoda", "d1_otevirat_i_pro_pohodu",
                        config_entry_id="zapis"),
        er.RegistrZapis("switch.dilna_stineni", "d1_ovladat_stineni",
                        config_entry_id="zapis"),
        er.RegistrZapis("switch.dilna_zvlhcovac",
                        "d1_zvlhcovat_i_ve_spanku", config_entry_id="zapis"),
        er.RegistrZapis("switch.dilna_topeni", "d1_ovladat_topeni",
                        config_entry_id="zapis"),
        er.RegistrZapis("climate.dilna", "d1_termostat",
                        config_entry_id="zapis"),
        er.RegistrZapis("binary_sensor.dilna_okno", "d1_okno",
                        config_entry_id="zapis"),
        er.RegistrZapis("binary_sensor.dilna_okno_otevreno",
                        "d1_okno_otevreno", config_entry_id="zapis"),
        # ...ale co s vybavením nesouvisí, zůstává.
        er.RegistrZapis("sensor.dilna_teplota", "d1_teplota",
                        config_entry_id="zapis"),
        er.RegistrZapis("binary_sensor.dilna_obsazeno", "d1_obsazeno",
                        config_entry_id="zapis"),
        # Kuchyně okno má, takže se jí nesmí sáhnout na nic.
        er.RegistrZapis("switch.kuchyn_okno", "k1_ovladat_okno",
                        config_entry_id="zapis"),
        er.RegistrZapis("binary_sensor.kuchyn_okno", "k1_okno",
                        config_entry_id="zapis"),
        # Obývák řízené okno nemá, jen kontakt: vypínač pryč, čidlo ne.
        er.RegistrZapis("switch.obyvak_okno", "o1_ovladat_okno",
                        config_entry_id="zapis"),
        er.RegistrZapis("binary_sensor.obyvak_okno", "o1_okno",
                        config_entry_id="zapis"),
        er.RegistrZapis("binary_sensor.obyvak_okno_otevreno",
                        "o1_okno_otevreno", config_entry_id="zapis"),
    ])

    m._uklid(hass, zapis)

    assert sorted(hass.registr.smazane) == [
        "binary_sensor.dilna_okno",
        "binary_sensor.dilna_okno_otevreno",
        "climate.dilna",
        "switch.dilna_okno",
        "switch.dilna_pohoda",
        "switch.dilna_stineni",
        "switch.dilna_topeni",
        "switch.dilna_zvlhcovac",
        "switch.obyvak_okno",
    ]

    # Podruhé už není co mazat.
    hass.registr.smazane.clear()
    m._uklid(hass, zapis)
    assert hass.registr.smazane == []


def test_uklid_necha_na_pokoji_cizi_entity_a_jine_podentity(modul):
    """Mazat se smí jen vlastní entity místností tohoto zápisu."""
    m, c = modul
    from homeassistant.helpers import entity_registry as er

    zona = _Pod(c.PODENTITA_ZONA, "Oblast", {}, "z1")
    klima = _Pod(c.PODENTITA_KLIMA, "Klima", {}, "c1")
    zapis = _Zapis([zona, klima])
    hass = _Hass()
    hass.registr = er.Registr([
        er.RegistrZapis("switch.zona_okno", "z1_ovladat_okno",
                        config_entry_id="zapis"),
        er.RegistrZapis("switch.klima", "c1_ovladat_klimu",
                        config_entry_id="zapis"),
        # Stejně pojmenovaná entita jiné integrace.
        er.RegistrZapis("switch.cizi_okno", "d1_ovladat_okno",
                        config_entry_id="jiny"),
    ])

    m._uklid(hass, zapis)

    assert hass.registr.smazane == []
