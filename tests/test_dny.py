"""Zaškrtávací mřížka dnů scény.

Den se v kalendáři zadával po jedné události, takže čtrnáct dní
v měsíci znamenalo čtrnáct dialogů. Mřížka dělá totéž kliknutím —
a musí se potkat s plánem, který už existuje.
"""

import asyncio
import datetime
import pathlib
import sys

import pytest

KOREN = pathlib.Path(__file__).parent.parent


@pytest.fixture
def modul():
    sys.path.insert(0, str(KOREN / "tests" / "stub_ha"))
    sys.path.insert(0, str(KOREN / "custom_components"))
    import importlib

    yield (importlib.import_module("napohodu.dny"),
           importlib.import_module("napohodu.planovac"))
    for jmeno in list(sys.modules):
        if jmeno.startswith(("napohodu", "homeassistant")):
            del sys.modules[jmeno]
    sys.path.remove(str(KOREN / "custom_components"))
    sys.path.remove(str(KOREN / "tests" / "stub_ha"))


SCENA = {"nazev": "Home Office", "okno": ["07:00", "18:00"],
         "prazdno": ["Ložnice"], "zavreno": [], "cil": {"obyvak": 22.0}}


def _rozbal(pz):
    """Rozbalování jako v koordinátoru, tedy včetně opakování."""
    from dateutil.rrule import rrulestr

    def f(zaznam, od, do):
        return pz.rozbal(zaznam, od, do, rrulestr)
    return f


def test_popis_dlazdice_nese_datum(modul):
    """Na dlaždici se čte datum, ne číslo — mřížka je kalendář."""
    dn, _ = modul
    dnes = datetime.date(2026, 10, 26)       # pondělí
    assert dn.popis(0, dnes) == "dnes"
    assert dn.popis(1, dnes) == "zítra"
    assert dn.popis(2, dnes) == "st 28. 10."
    assert dn.popis(5, dnes) == "so 31. 10."
    # mřížka musí dosáhnout za hranici měsíce, jinak se první dny
    # příštího zadávají až na poslední chvíli
    assert dn.popis(dn.DNU_DOPREDU - 1, dnes) == "ne 29. 11."


def test_zaskrtnuti_vypada_jako_celodenni_udalost(modul):
    """Záznam z dlaždice musí být k nerozeznání od toho z kalendáře,
    aby fungovalo rozbalení na denní okna i opis po smazané scéně."""
    dn, pz = modul
    z = dn.novy_zaznam("id_ho", SCENA, datetime.date(2026, 11, 3))
    assert z["druh"] == "scena" and z["scena"] == "id_ho"
    assert z["celodenni"] is True
    assert z["okno"] == ["07:00", "18:00"]
    assert z["opis"]["prazdno"] == ["Ložnice"]
    assert z["do"] - z["od"] == datetime.timedelta(days=1)

    # celodenní záznam se rozpadne na okno dne, ne na celou noc
    vyskyty = pz.rozbal(z, z["od"] - datetime.timedelta(days=1),
                        z["od"] + datetime.timedelta(days=2), None)
    assert len(vyskyty) == 1
    a, b = vyskyty[0]
    assert (a.hour, b.hour) == (7, 18)


def test_den_pozna_i_opakovanou_udalost(modul):
    """Dlaždice musí vidět i den, který drží vzorec — jinak by tvrdila,
    že scéna ten den není, a přidala by zaškrtnutí navíc."""
    dn, pz = modul
    pondeli = datetime.date(2026, 11, 2)
    zaznam = dn.novy_zaznam("id_ho", SCENA, pondeli)
    zaznam["rrule"] = "FREQ=WEEKLY;BYDAY=MO"

    for den, ceka in ((pondeli, True),
                      (pondeli + datetime.timedelta(days=7), True),
                      (pondeli + datetime.timedelta(days=1), False)):
        stav = dn.pro_den([zaznam], "id_ho", den, _rozbal(pz))
        assert stav["plati"] is ceka, den
        if ceka:
            # a odškrtnout se nedá: smazalo by to i ostatní pondělky
            assert stav["vlastni"] == []
            assert stav["odjinud"] is True


def test_vicedenni_oznaceni_se_odskrtnout_neda(modul):
    """Týden v kuse je jedna věc, kterou člověk zadal jako celek."""
    dn, pz = modul
    z = dn.novy_zaznam("id_ho", SCENA, datetime.date(2026, 11, 2))
    z["do"] = z["od"] + datetime.timedelta(days=5)
    stav = dn.pro_den([z], "id_ho", datetime.date(2026, 11, 4), _rozbal(pz))
    assert stav["plati"] and stav["odjinud"] and stav["vlastni"] == []


def test_jedno_zaskrtnuti_se_odskrtnout_da(modul):
    dn, pz = modul
    den = datetime.date(2026, 11, 3)
    z = dn.novy_zaznam("id_ho", SCENA, den)
    stav = dn.pro_den([z], "id_ho", den, _rozbal(pz))
    assert stav["plati"] and not stav["odjinud"]
    assert [x["uid"] for x in stav["vlastni"]] == [z["uid"]]

    # cizí scéna se do toho nemíchá
    jina = dn.pro_den([z], "id_jina", den, _rozbal(pz))
    assert not jina["plati"]
