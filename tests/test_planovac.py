"""Testy zakládání událostí plánu z dashboardu."""

from datetime import datetime, timedelta

from planovac import (DRUHY, nabidka, nazev, nejblizsi, obsahuje,
                      parita, patri, pravidlo, rozbal, zkontroluj)


def test_nabidka_ma_vsechny_varianty_kazde_mistnosti():
    """Zapisuje se do vlastního kalendáře, takže není kam se netrefit
    a nabídku nemá smysl zkracovat podle toho, co je kde přiřazené."""
    v = nabidka(["Ložnice"], ["1. patro"])
    assert [x.popis for x in v] == [
        "nikdo doma", "víc lidí",
        "Ložnice: je tu někdo", "Ložnice: nikdo tu nebude",
        "Ložnice: zavřená okna",
        "Ložnice: nikdo tu nebude, zavřená okna",
        "Ložnice: cílová teplota",
        "1. patro: je tu někdo", "1. patro: nikdo tu nebude",
        "1. patro: zavřená okna",
        "1. patro: nikdo tu nebude, zavřená okna",
        "1. patro: cílová teplota"]
    assert {x.druh for x in v} <= set(DRUHY)
    # skupina se pozná podle toho, že není místnost
    skupinove = [x for x in v if x.skupina]
    assert all(x.mistnost is None for x in skupinove)
    assert len(skupinove) == 5


def test_slozeny_povel_nese_oba():
    """„Odjíždíme na týden" je jedna věc a mazat se má jednou."""
    assert obsahuje("prazdno_zavreno", "prazdno")
    assert obsahuje("prazdno_zavreno", "zavreno")
    assert obsahuje("prazdno", "prazdno")
    # a samo o sobě prázdno okno nezavírá
    assert not obsahuje("prazdno", "zavreno")
    assert not obsahuje("zavreno", "prazdno")


def test_skupina_se_drzi_jmenem_a_opis_je_zaloha():
    z = {"skupina": "1. patro", "clenove": ["Ložnice", "Dětská"]}
    # přidaná místnost platí taky, protože skupina se drží jménem
    ted = {"1. patro": ["Ložnice", "Dětská", "Pracovna"]}
    assert patri(z, "Pracovna", ted)
    assert not patri(z, "Kuchyně", ted)
    # smazaná skupina plán nerozbije, jede podle opisu
    assert patri(z, "Dětská", {})
    assert not patri(z, "Pracovna", {})
    # bez skupiny se porovnává místnost
    assert patri({"mistnost": "Ložnice"}, "Ložnice", {})
    assert not patri({"mistnost": "Ložnice"}, "Kuchyně", {})


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


def test_lichy_a_sudy_tyden_nejde_do_pravidla_jako_count():
    """COUNT by počítal i týdny, které se pak vyhodí."""
    assert pravidlo("lichy_tyden", 8) == "FREQ=WEEKLY"
    assert pravidlo("vikend_sudy", 8) == "FREQ=WEEKLY;BYDAY=SA,SU"
    assert parita("lichy_tyden") == 1
    assert parita("sudy_tyden") == 0 and parita("tydne") is None


def test_lichy_tyden_padne_jen_do_lichych_tydnu():
    """Ne `INTERVAL=2`: ten se v roce s 53 týdny převrátí."""
    from dateutil.rrule import rrulestr

    # 19. 10. 2026 je pondělí 43. týdne (lichý)
    z = {"od": datetime(2026, 10, 19, 8, 0),
         "do": datetime(2026, 10, 19, 15, 0),
         "rrule": pravidlo("lichy_tyden", 0), "parita": 1}
    v = rozbal(z, datetime(2026, 10, 1), datetime(2026, 12, 1), rrulestr)
    tydny = [a.isocalendar()[1] for a, _ in v]
    assert tydny == [43, 45, 47, 49]
    z["parita"] = 0
    v = rozbal(z, datetime(2026, 10, 1), datetime(2026, 12, 1), rrulestr)
    assert [a.isocalendar()[1] for a, _ in v] == [44, 46, 48]


def test_omezeni_poctu_plati_az_po_filtru():
    """Tři opakování v lichém týdnu jsou tři, ne půldruhého."""
    from dateutil.rrule import rrulestr

    z = {"od": datetime(2026, 10, 19, 8, 0),
         "do": datetime(2026, 10, 19, 15, 0),
         "rrule": pravidlo("lichy_tyden", 3), "parita": 1, "kolikrat": 3}
    v = rozbal(z, datetime(2026, 10, 1), datetime(2027, 3, 1), rrulestr)
    assert [a.isocalendar()[1] for a, _ in v] == [43, 45, 47]


def test_vikend_v_lichem_tydnu_se_nerozdeli():
    """Týden podle ISO začíná v pondělí, sobota a nedělě drží spolu."""
    from dateutil.rrule import rrulestr

    z = {"od": datetime(2026, 10, 24, 20, 0),      # sobota, 43. týden
         "do": datetime(2026, 10, 24, 23, 0),
         "rrule": pravidlo("vikend_lichy", 0), "parita": 1}
    v = rozbal(z, datetime(2026, 10, 20), datetime(2026, 11, 10), rrulestr)
    dny = [(a.day, a.isocalendar()[1]) for a, _ in v]
    assert dny == [(24, 43), (25, 43), (7, 45), (8, 45)]


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
