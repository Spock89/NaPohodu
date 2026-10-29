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
    """Na dlaždici se čte zkratka dne a datum, nic víc.

    Dlaždice je úzká: „NaPohodu zítra" se do ní nevejde a zbude
    „aPohod". Mezera mezi zkratkou a datem je jediné místo, kde se
    text zalomí, takže každá dlaždice vypadá stejně — proto tu nejsou
    ani slova „dnes" a „zítra".
    """
    dn, _ = modul
    dnes = datetime.date(2026, 10, 26)       # pondělí, tedy první dlaždice
    assert (dn.popis(0, dnes), dn.datum_popis(0, dnes)) == ("dnes", "26.")
    assert dn.popis(1, dnes) == "zítra"
    assert dn.datum_popis(2, dnes) == "28.★"        # Vznik Československa
    assert (dn.popis(3, dnes), dn.datum_popis(3, dnes)) == ("čt", "29.")
    assert (dn.popis(5, dnes), dn.datum_popis(5, dnes)) == ("so", "31.")
    # měsíc se píše jen prvního, jak je v kalendáři zvykem
    assert dn.datum_popis(6, dnes) == "1.11."
    # Horní řádek je vždycky dvě písmena, spodní datum — jen tak
    # vypadá každá dlaždice stejně a nic se neořízne.
    for i in range(2, dn.DNU_DOPREDU):
        assert len(dn.popis(i, dnes)) == 2, dn.popis(i, dnes)
        x = dn.datum_popis(i, dnes)
        assert " " not in x and len(x) <= 6, x
    # mřížka musí dosáhnout za hranici měsíce, jinak se první dny
    # příštího zadávají až na poslední chvíli
    assert (dn.popis(dn.DNU_DOPREDU - 1, dnes),
            dn.datum_popis(dn.DNU_DOPREDU - 1, dnes)) == ("ne", "29.")


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


def test_svatky_a_vikendy_jsou_volno(modul):
    """Barvu dlaždice určuje entita, ne pozice v mřížce — který
    sloupec je víkend, se každým dnem posune."""
    dn, _ = modul
    d = datetime.date
    assert dn.typ_dne(d(2026, 10, 31)) == "volno"       # sobota
    assert dn.typ_dne(d(2026, 11, 1)) == "volno"        # neděle
    assert dn.typ_dne(d(2026, 10, 30)) == "pracovní"    # pátek
    # státní svátek ve všední den je taky volno a je pojmenovaný
    assert dn.typ_dne(d(2026, 10, 28)) == "volno"       # středa
    assert dn.svatek(d(2026, 10, 28)) == "Vznik Československa"
    assert dn.svatek(d(2026, 10, 30)) is None


def test_velikonoce_se_pocitaji(modul):
    """Jediné dva svátky, které se stěhují — v tabulce být nemůžou."""
    dn, _ = modul
    d = datetime.date
    for rok, nedele in ((2026, d(2026, 4, 5)), (2027, d(2027, 3, 28)),
                        (2030, d(2030, 4, 21))):
        assert dn.velikonoce(rok) == nedele, rok
        assert dn.svatek(nedele - datetime.timedelta(days=2)) == "Velký pátek"
        assert dn.svatek(
            nedele + datetime.timedelta(days=1)) == "Velikonoční pondělí"


def test_popis_je_zkratka_dne_a_datum(modul):
    """Dlaždice je široká sedminu karty: „NaPohodu út 27. 10." se do ní
    nevešlo a zbylo z toho „aPohod". Zkratka dne a datum se vejdou."""
    dn, _ = modul
    # v úterý sedí dnešek na druhé dlaždici, protože mřížka začíná
    # pondělím — svislice jsou pevně dny v týdnu
    utery = datetime.date(2026, 10, 27)
    assert dn.popis(1, utery) == "dnes"
    assert dn.popis(0, utery) == "po" and dn.stav_dlazdice(0, utery) == "minulost"
    assert dn.popis(3, utery) == "čt"
    assert dn.datum_popis(1, utery) == "27."
    assert dn.datum_popis(5, utery) == "31."
    # víkend je poznat ze zkratky, a to i bez barvy
    assert dn.typ_dne(datetime.date(2026, 10, 31)) == "volno"
    assert dn.typ_dne(datetime.date(2026, 10, 27)) == "pracovní"


def test_statni_svatky(modul):
    """Pevné i pohyblivé. Velikonoce se počítají, ať to platí i za
    deset let a nic se nemusí doplňovat."""
    dn, _ = modul
    assert dn.svatek(datetime.date(2026, 11, 17)) == "Den boje za svobodu"
    assert dn.svatek(datetime.date(2026, 7, 5)) == "Cyril a Metoděj"
    assert dn.svatek(datetime.date(2026, 10, 27)) is None
    assert dn.typ_dne(datetime.date(2026, 11, 17)) == "volno"

    # velikonoční neděle podle tabulek
    for rok, den in ((2024, (3, 31)), (2025, (4, 20)),
                     (2026, (4, 5)), (2027, (3, 28))):
        assert dn.velikonoce(rok) == datetime.date(rok, *den), rok
    assert dn.svatek(datetime.date(2026, 4, 3)) == "Velký pátek"
    assert dn.svatek(datetime.date(2026, 4, 6)) == "Velikonoční pondělí"
    # a svátek je na dlaždici vidět
    # velikonoční pondělí 2026 je 6. dubna, tedy první dlaždice týdne
    assert "★" in dn.datum_popis(0, datetime.date(2026, 4, 6))


def test_vikend_je_vzdycky_na_konci_radku(modul):
    """Svislice mřížky musí být pevně dny v týdnu.

    Kdyby se počítalo ode dneška, posouval by se víkend mřížkou každý
    den o jedno políčko a z kalendáře by zbyl jen pás dlaždic.
    """
    dn, _ = modul
    for dnes in (datetime.date(2026, 10, 26),   # pondělí
                 datetime.date(2026, 10, 29),   # čtvrtek
                 datetime.date(2026, 11, 1)):   # neděle
        for i in range(dn.DNU_DOPREDU):
            volno_podle_sloupce = i % 7 >= 5
            assert dn.vikend(dn.datum(i, dnes)) == volno_podle_sloupce, (dnes, i)


def test_minule_dny_se_nedaji_zaskrtnout(modul):
    """Mřížka začíná pondělím, takže dny před dneškem padnou na začátek
    prvního řádku. Karta je nechává prázdné."""
    dn, _ = modul
    ctvrtek = datetime.date(2026, 10, 29)
    stavy = [dn.stav_dlazdice(i, ctvrtek) for i in range(7)]
    assert stavy[:3] == ["minulost"] * 3, stavy
    assert "minulost" not in stavy[3:]

    # v pondělí nezbyde prázdné ani jedno
    pondeli = datetime.date(2026, 10, 26)
    assert all(dn.stav_dlazdice(i, pondeli) != "minulost" for i in range(7))
