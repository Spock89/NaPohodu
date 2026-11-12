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
    def __init__(self, typ, title, data):
        self.subentry_type, self.title, self.data = typ, title, data


class _Zapis:
    def __init__(self, podentity):
        self.subentries = {str(i): p for i, p in enumerate(podentity)}


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
