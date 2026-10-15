"""Testy zakládání událostí plánu z dashboardu."""

from datetime import datetime, timedelta

from planovac import DRUHY, nabidka, nazev, pravidlo, rozbal, nejblizsi, zkontroluj


def test_nabidka_ma_vsechny_varianty_kazde_mistnosti():
    """Zapisuje se do vlastního kalendáře, takže není kam se netrefit
    a nabídku nemá smysl zkracovat podle toho, co je kde přiřazené."""
    v = nabidka(["Ložnice", "Kuchyně"])
    assert [x.popis for x in v] == [
        "nikdo doma", "víc lidí",
        "Ložnice: je tu někdo", "Ložnice: nikdo tu nebude",
        "Ložnice: cílová teplota",
        "Kuchyně: je tu někdo", "Kuchyně: nikdo tu nebude",
        "Kuchyně: cílová teplota"]
    assert {x.druh for x in v} <= set(DRUHY)


def test_prohozene_casy_se_nezalozi():
    """Kalendář by to přijal a vznikla by událost, která nikdy
    neplatí — a hledá se to špatně."""
    od = datetime(2026, 10, 15, 18, 0)
    assert zkontroluj(od, od + timedelta(hours=2)) is None
    assert zkontroluj(od, od) is not None
    assert zkontroluj(od, od - timedelta(hours=1)) is not None
    assert zkontroluj(None, od) is not None


def test_pravidlo_opakovani():
    """Akce calendar.create_event opakování neumí, entita kalendáře
    ano — a tohle je přesně to, co jí posílá webové rozhraní."""
    assert pravidlo("jednou", 8) is None
    assert pravidlo("tydne", 8) == "FREQ=WEEKLY;COUNT=8"
    assert pravidlo("vsedni_dny", 0) == "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"


def test_nazev_nese_i_cilovou_teplotu():
    assert nazev("nikdo") == "NaPohodu: nikdo doma"
    assert nazev("obsazeno", "Ložnice") == "Ložnice: je tu někdo"
    assert nazev("cil", "Ložnice", 22.5) == "Ložnice: cíl 22,5 °C"


def test_rozbaleni_opakovane_udalosti():
    """Kalendář musí vracet výskyty, ne jeden záznam s pravidlem."""
    from dateutil.rrule import rrulestr

    z = {"od": datetime(2026, 10, 20, 8, 0),
         "do": datetime(2026, 10, 20, 15, 0),
         "rrule": pravidlo("tydne", 4)}
    v = rozbal(z, datetime(2026, 10, 1), datetime(2026, 12, 1), rrulestr)
    assert len(v) == 4
    assert [a.day for a, _ in v] == [20, 27, 3, 10]


def test_bez_dateutilu_zbyde_aspon_prvni_vyskyt():
    """Bez knihovny se plán nerozpadne, jen přestane opakovat."""
    z = {"od": datetime(2026, 10, 20, 8, 0),
         "do": datetime(2026, 10, 20, 15, 0),
         "rrule": "FREQ=WEEKLY"}
    assert len(rozbal(z, datetime(2026, 10, 1),
                      datetime(2026, 12, 1), None)) == 1


def test_bezici_vyskyt_ma_prednost_pred_budoucim():
    v = [(datetime(2026, 10, 20, 8, 0), datetime(2026, 10, 20, 15, 0)),
         (datetime(2026, 10, 27, 8, 0), datetime(2026, 10, 27, 15, 0))]
    assert nejblizsi(v, datetime(2026, 10, 20, 9, 0))[0].day == 20
    assert nejblizsi(v, datetime(2026, 10, 21, 9, 0))[0].day == 27
    assert nejblizsi(v, datetime(2026, 11, 1)) is None
