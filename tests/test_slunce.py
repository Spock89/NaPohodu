"""Testy slunečního zisku."""

from slunce import Okno, dni, dopad, okna_na_slunci, zisk_mistnosti

JIH = Okno("jih", azimut=180)
VYCHOD = Okno("východ", azimut=90)
ZAPAD = Okno("západ", azimut=270)
SEVER = Okno("sever", azimut=0)


def test_slunce_pod_obzorem_nesviti():
    assert dopad(JIH, 180, -5) == 0.0
    assert dni(-1) == 0.0


def test_nizke_slunce_je_slabsi():
    assert dni(60) > dni(30) > dni(10)


def test_mimo_zorne_pole_nesviti():
    """Ráno na východě jižní okno ještě nemá slunce."""
    assert dopad(JIH, 85, 20) == 0.0
    assert dopad(VYCHOD, 85, 20) > 0


def test_severni_okno_v_poledne_nic():
    assert dopad(SEVER, 180, 50) == 0.0


def test_jizni_okno_ma_vic_v_zime_nez_v_lete():
    """Svislé jižní okno dostane v zimě víc než v létě, protože
    v létě je slunce vysoko a paprsky dopadají šikmo. Klasický efekt,
    kvůli kterému se přesklívají zimní zahrady."""
    zima = dopad(JIH, 180, 17)      # Praha, poledne v prosinci
    leto = dopad(JIH, 180, 62)      # Praha, poledne v červnu
    assert zima > leto


def test_den_projde_okny_postupne():
    """Ráno východ, poledne jih, večer západ."""
    rano = (90, 20)      # azimut, elevace
    poledne = (180, 55)
    vecer = (265, 15)

    assert dopad(VYCHOD, *rano) > dopad(JIH, *rano)
    assert dopad(JIH, *poledne) > dopad(VYCHOD, *poledne)
    assert dopad(ZAPAD, *vecer) > dopad(JIH, *vecer)


def test_zapadni_okno_vecer_prihriva():
    """Nízké západní slunce dopadá skoro kolmo. Absolutně už není silné,
    protože prošlo tlustou vrstvou atmosféry, ale na svislé okno dopadne
    skoro všechno, co zbylo — proto letní přehřívání navečer."""
    vecer = dopad(ZAPAD, 265, 12)
    assert vecer > 300
    # ze zbylého záření využije okno přes 95 %
    assert vecer / dni(12) > 0.95


def test_oblacnost_snizuje_zisk():
    jasno = dopad(JIH, 180, 40, jasno=1.0)
    zataz = dopad(JIH, 180, 40, jasno=0.2)
    assert zataz < jasno * 0.3


def test_soucet_pres_okna():
    okna = [VYCHOD, JIH, ZAPAD]
    celkem = zisk_mistnosti(okna, 180, 50)
    assert celkem == sum(dopad(o, 180, 50) for o in okna)


def test_vybere_jen_osvicena_okna():
    okna = [VYCHOD, JIH, ZAPAD, SEVER]
    rano = okna_na_slunci(okna, 95, 25)
    assert [o.nazev for o in rano] == ["východ"]
    vecer = okna_na_slunci(okna, 265, 15)
    assert [o.nazev for o in vecer] == ["západ"]


def test_plocha_skaluje():
    velke = Okno("velké", azimut=180, plocha=2.0)
    assert abs(dopad(velke, 180, 40) - 2 * dopad(JIH, 180, 40)) < 0.01
