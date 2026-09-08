"""Testy zastupování mezi zónami."""

from sousedstvi import Uprava, ZonaStav, prerozdel


def byt(loznice_co2=1100, loznice_klid=True, kuchyn_co2=600,
        kuchyn_klid=False, dvere=True, kuchyn_muze=True):
    """Tvoje sestava: ložnice se spí, kuchyň větrá i za obývák."""
    return [
        ZonaStav("l", "Ložnice", co2=loznice_co2, klid=loznice_klid,
                 sousedi=["k"], dvere_otevrene=dvere),
        ZonaStav("k", "Kuchyně", co2=kuchyn_co2, klid=kuchyn_klid,
                 muze_vetrat=kuchyn_muze, sousedi=["l"], dvere_otevrene=dvere),
    ]


def test_v_noci_vetra_kuchyn_za_loznici():
    u = prerozdel(byt())
    assert u["l"].zastupce == "Kuchyně"
    assert u["k"].prevzate_co2 == 1100
    assert u["k"].za_koho == ["Ložnice"]


def test_bez_spanku_se_nezastupuje():
    u = prerozdel(byt(loznice_klid=False))
    assert u["l"].zastupce is None
    assert u["k"].prevzate_co2 == 0


def test_zavrene_dvere_nepomohou():
    u = prerozdel(byt(dvere=False))
    assert u["l"].zastupce is None


def test_kdyz_se_spi_i_v_kuchyni_nepomuze():
    u = prerozdel(byt(kuchyn_klid=True))
    assert u["l"].zastupce is None


def test_kdyz_soused_nemuze_vetrat():
    """Vítr nebo zima blokuje kuchyň, ložnice si musí poradit sama."""
    u = prerozdel(byt(kuchyn_muze=False))
    assert u["l"].zastupce is None


def test_cisty_vzduch_nikoho_neobtezuje():
    u = prerozdel(byt(loznice_co2=600))
    assert u["l"].zastupce is None
    assert u["k"].prevzate_co2 == 0


def test_kuchyn_bere_vyssi_z_obou():
    u = prerozdel(byt(loznice_co2=1100, kuchyn_co2=1400))
    # sama má hůř, ale cizí hodnotu si stejně zapamatuje
    assert u["k"].prevzate_co2 == 1100
    assert u["l"].zastupce == "Kuchyně"


def test_jeden_zastupce_staci():
    zony = [
        ZonaStav("l", "Ložnice", co2=1200, klid=True, sousedi=["k", "o"]),
        ZonaStav("k", "Kuchyně", co2=600, sousedi=["l"]),
        ZonaStav("o", "Obývák", co2=600, sousedi=["l"]),
    ]
    u = prerozdel(zony)
    zastupci = [z for z in ("k", "o") if u[z].za_koho]
    assert len(zastupci) == 1


def test_vzajemne_zastoupeni_nevznikne():
    """Dvě zóny, obě potřebují větrat, ani v jedné se nespí."""
    zony = [
        ZonaStav("a", "A", co2=1200, sousedi=["b"]),
        ZonaStav("b", "B", co2=1200, sousedi=["a"]),
    ]
    u = prerozdel(zony)
    assert u["a"].zastupce is None and u["b"].zastupce is None


def test_zona_nezastoupi_sama_sebe():
    zony = [ZonaStav("a", "A", co2=1200, klid=True, sousedi=["a"])]
    assert prerozdel(zony)["a"].zastupce is None
