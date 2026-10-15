"""Testy zakládání událostí plánu z dashboardu."""

from datetime import datetime, timedelta

from planovac import kam, nabidka, zkontroluj

NIKDO, VIC = "plan_nikdo_doma", "plan_vic_lidi"
JE, NENI = "plan_obsazeno", "plan_prazdno"


def volby(byt, mistnosti):
    return nabidka(byt, mistnosti, NIKDO, VIC, JE, NENI)


def test_nabidka_jen_z_toho_co_ma_kam_zapsat():
    """Volba bez přiřazeného kalendáře by skončila chybou až po
    stisku tlačítka — do nabídky se proto vůbec nedostane."""
    byt = {NIKDO: ["calendar.prazdno"]}
    v = volby(byt, [("Ložnice", {JE: ["calendar.loznice"]}),
                    ("Kuchyně", {})])
    assert [x.popis for x in v] == ["nikdo doma", "Ložnice: je tu někdo"]


def test_do_rozvrhu_se_zapsat_neda():
    """Týdenní rozvrh se naklikává v Home Assistantu, událost do něj
    založit nejde."""
    assert volby({NIKDO: ["schedule.vsedni_dny"]}, []) == []


def test_kam_to_patri():
    byt = {NIKDO: ["calendar.prazdno"], VIC: ["calendar.navsteva"]}
    mistnosti = {"Ložnice": {JE: ["calendar.loznice"]}}
    v = volby(byt, [("Ložnice", mistnosti["Ložnice"])])
    podle = {x.popis: x for x in v}
    assert kam(podle["nikdo doma"], byt, mistnosti) == "calendar.prazdno"
    assert kam(podle["Ložnice: je tu někdo"], byt,
               mistnosti) == "calendar.loznice"


def test_prohozene_casy_se_nezaloží():
    """Kalendář by to přijal a vznikla by událost, která nikdy
    neplatí — a hledá se to špatně."""
    od = datetime(2026, 10, 15, 18, 0)
    assert zkontroluj(od, od + timedelta(hours=2)) is None
    assert zkontroluj(od, od) is not None
    assert zkontroluj(od, od - timedelta(hours=1)) is not None
    assert zkontroluj(None, od) is not None
