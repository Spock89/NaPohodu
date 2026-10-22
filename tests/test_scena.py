"""Scéna: pojmenovaná sada dopadů, dny se jen označí v kalendáři."""

from datetime import datetime, timedelta

from dateutil.rrule import rrulestr

import planovac as pz

HOME_OFFICE = {
    "nazev": "Home Office",
    "okno": ["07:00", "18:00"],
    "prazdno": ["Ložnice", "Kuchyně"],
    "zavreno": ["Ložnice"],
    "cil": {"Dílna": 22.0},
}


def zaznam(**kw) -> dict:
    zakl = dict(uid="u1", druh="scena", scena="id_ho",
                nazev_sceny="Home Office",
                opis={"prazdno": ["Ložnice"], "zavreno": [], "cil": {}},
                celodenni=True, okno=["07:00", "18:00"],
                od=datetime(2026, 10, 26), do=datetime(2026, 10, 27),
                rrule=None)
    zakl.update(kw)
    return zakl


# ------------------------------------------------- rozpad na povely

def test_scena_rozpadne_se_na_bezne_druhy():
    """Scéna nemá vlastní chování — mluví druhy, které plán už umí."""
    d = pz.dopad_sceny(HOME_OFFICE)
    assert d["prazdno"] == ["Ložnice", "Kuchyně"]
    assert d["zavreno"] == ["Ložnice"]
    assert d["cil"] == {"Dílna": 22.0}


def test_plati_jen_tam_kde_scena_rika():
    z = zaznam()
    assert pz.scena_plati(z, HOME_OFFICE, "prazdno", "Ložnice")
    assert pz.scena_plati(z, HOME_OFFICE, "prazdno", "Kuchyně")
    assert not pz.scena_plati(z, HOME_OFFICE, "prazdno", "Dílna")
    assert pz.scena_plati(z, HOME_OFFICE, "zavreno", "Ložnice")
    assert not pz.scena_plati(z, HOME_OFFICE, "zavreno", "Kuchyně")
    assert pz.scena_plati(z, HOME_OFFICE, "cil", "Dílna")
    assert pz.scena_cil(z, HOME_OFFICE, "Dílna") == 22.0
    assert pz.scena_cil(z, HOME_OFFICE, "Ložnice") is None


def test_smazana_scena_jede_podle_opisu():
    """Smazání scény nesmí shodit naplánované dny."""
    z = zaznam()
    assert pz.scena_plati(z, None, "prazdno", "Ložnice")
    assert not pz.scena_plati(z, None, "prazdno", "Kuchyně")  # v opisu není


def test_zivá_definice_prebije_opis():
    """Úprava scény se promítne do všech naplánovaných dní."""
    z = zaznam()
    assert pz.scena_plati(z, HOME_OFFICE, "prazdno", "Kuchyně")


def test_scena_se_neváže_na_mistnost_jmenem():
    assert pz.patri(zaznam(), "Ložnice", {}) is False


# ------------------------------------------------- celodenní událost

def test_celodenni_den_dostane_okno_sceny():
    """Klik na den znamená „použij okno dne", ne celých 24 hodin."""
    vyskyty = pz.rozbal(zaznam(), datetime(2026, 10, 20),
                        datetime(2026, 11, 5), rrulestr)
    assert vyskyty == [(datetime(2026, 10, 26, 7, 0),
                        datetime(2026, 10, 26, 18, 0))]


def test_celodenni_vic_dni_je_vic_oken():
    """Tři dny v kuse nesmí znamenat i obě noci mezi nimi."""
    vyskyty = pz.rozbal(
        zaznam(od=datetime(2026, 10, 26), do=datetime(2026, 10, 29)),
        datetime(2026, 10, 20), datetime(2026, 11, 5), rrulestr)
    assert len(vyskyty) == 3
    assert [a.day for a, _ in vyskyty] == [26, 27, 28]
    assert all(b - a == timedelta(hours=11) for a, b in vyskyty)


def test_celodenni_s_opakovanim():
    """Každé pondělí: jeden den, jedno okno, jednou týdně."""
    vyskyty = pz.rozbal(
        zaznam(rrule="FREQ=WEEKLY;COUNT=3"),
        datetime(2026, 10, 20), datetime(2026, 11, 20), rrulestr)
    assert [a.date().isoformat() for a, _ in vyskyty] == [
        "2026-10-26", "2026-11-02", "2026-11-09"]
    assert all(a.hour == 7 and b.hour == 18 for a, b in vyskyty)


def test_okno_pres_pulnoc():
    """Noční scéna: konec je dřív než začátek, patří na další den."""
    vyskyty = pz.rozbal(
        zaznam(okno=["22:00", "06:00"]),
        datetime(2026, 10, 20), datetime(2026, 11, 5), rrulestr)
    (a, b), = vyskyty
    assert a == datetime(2026, 10, 26, 22, 0)
    assert b == datetime(2026, 10, 27, 6, 0)


def test_udalost_s_casem_si_okno_neprebiji():
    """Když čas zadáš, platí tvůj, ne okno scény."""
    z = zaznam(celodenni=False,
               od=datetime(2026, 10, 26, 9, 30),
               do=datetime(2026, 10, 26, 12, 0))
    vyskyty = pz.rozbal(z, datetime(2026, 10, 20),
                        datetime(2026, 11, 5), rrulestr)
    assert vyskyty == [(datetime(2026, 10, 26, 9, 30),
                        datetime(2026, 10, 26, 12, 0))]


def test_bez_okna_se_nic_nerozpada():
    """Poškozený záznam bez okna se nesmí pokusit o nemožné."""
    z = zaznam(okno=None)
    vyskyty = pz.rozbal(z, datetime(2026, 10, 20),
                        datetime(2026, 11, 5), rrulestr)
    assert vyskyty == [(datetime(2026, 10, 26), datetime(2026, 10, 27))]
