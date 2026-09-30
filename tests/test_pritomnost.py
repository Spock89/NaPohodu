"""Testy obsazenosti, klidu a oblačnosti."""

from pritomnost import (NastaveniPritomnosti, Signaly,
                        ZdrojObsazenosti, klid, oblacnost, obsazeno)
from slunce import dni

# tvoje dvě místnosti
OBYVAK = NastaveniPritomnosti(ZdrojObsazenosti.VZDY)
LOZNICE = NastaveniPritomnosti(ZdrojObsazenosti.SPANEK)
DILNA = NastaveniPritomnosti(ZdrojObsazenosti.CIDLO)


# ---------------------------------------------------------- obsazenost

def test_prazdny_byt_prebiji_vse():
    for n in (OBYVAK, LOZNICE, DILNA):
        assert not obsazeno(Signaly(doma=False, spanek=True, cidlo=True), n)


def test_obyvak_je_trvale_obsazeny():
    assert obsazeno(Signaly(), OBYVAK)
    assert obsazeno(Signaly(spanek=False, cidlo=False), OBYVAK)


def test_loznice_jen_kdyz_se_spi():
    assert not obsazeno(Signaly(spanek=False), LOZNICE)
    assert obsazeno(Signaly(spanek=True), LOZNICE)


def test_chybejici_cidlo_mistnost_nevypne():
    """Vybitá baterie v čidle nesmí znamenat, že se o místnost přestaneme
    starat. Chybějící hodnota se bere jako obsazeno."""
    assert obsazeno(Signaly(cidlo=None), DILNA)
    # vypnuté čidlo se počítá až po uplynutí doběhu
    assert not obsazeno(Signaly(cidlo=False, cidlo_od_s=99999), DILNA)


def test_kombinace_cidla_a_spanku():
    n = NastaveniPritomnosti(ZdrojObsazenosti.CIDLO_NEBO_SPANEK)
    assert obsazeno(Signaly(cidlo=True, spanek=False), n)
    assert obsazeno(Signaly(cidlo=False, cidlo_od_s=99999, spanek=True), n)
    assert not obsazeno(Signaly(cidlo=False, cidlo_od_s=99999, spanek=False), n)


# ---------------------------------------------------------- klid





def test_bez_cidla_se_predpoklada_jasno():
    assert oblacnost(None, 40) == 1.0


def test_v_noci_se_nepocita():
    assert oblacnost(0, -5) == 1.0


def test_zatazeno_snizi_faktor():
    """Zataženo: 100 W/m2 při slunci 40° nad obzorem."""
    assert oblacnost(100, 40) < 0.35


def test_lehky_zavoj():
    """360 W/m2 při 40° je skoro jasno — teoretické maximum je ~414."""
    f = oblacnost(360, 40)
    assert 0.8 < f < 0.95, f


def test_jasno_da_faktor_kolem_jedne():
    elevace = 40
    teoreticke = dni(elevace, 1.0) * __import__('math').sin(
        __import__('math').radians(elevace)) * 1.1
    assert oblacnost(teoreticke, elevace) > 0.95


def test_faktor_je_orezany():
    assert oblacnost(5000, 40) == 1.0
    assert oblacnost(0, 40) == 0.0


# ---------------------------------------------------------- PIR

from pritomnost import StineniPryc, _cidlo_verohodne

PIR = NastaveniPritomnosti(ZdrojObsazenosti.CIDLO)


def test_pir_zapnuty_je_spolehlivy():
    assert _cidlo_verohodne(Signaly(cidlo=True), PIR) is True


def test_pir_vypnuty_ma_dobeh():
    """Nehybný člověk PIR nevidí, proto se po pohybu ještě chvíli čeká."""
    cerstve = Signaly(cidlo=False, cidlo_od_s=10 * 60)
    stare = Signaly(cidlo=False, cidlo_od_s=90 * 60)
    assert _cidlo_verohodne(cerstve, PIR) is True
    assert _cidlo_verohodne(stare, PIR) is False


def test_vybite_cidlo_prestaneme_verit():
    """Zamrzlé 'prázdno' by místnost vyplo natrvalo."""
    zamrzle = Signaly(cidlo=False, cidlo_od_s=99999, cidlo_stari_s=10 * 3600)
    assert _cidlo_verohodne(zamrzle, PIR) is None
    assert obsazeno(zamrzle, PIR)          # nevíme -> staráme se


def test_zamrzle_zapnute_taky_neveri():
    zamrzle = Signaly(cidlo=True, cidlo_stari_s=10 * 3600)
    assert _cidlo_verohodne(zamrzle, PIR) is None


def test_dobeh_se_da_nastavit():
    kratky = NastaveniPritomnosti(ZdrojObsazenosti.CIDLO, dobeh_s=5 * 60)
    s = Signaly(cidlo=False, cidlo_od_s=10 * 60)
    assert not obsazeno(s, kratky)
    assert obsazeno(s, PIR)


def test_kuchyne_ignoruje_pir():
    """Přes kuchyň se pobíhá pořád, čidlo tam nemá cenu."""
    kuchyne = NastaveniPritomnosti(ZdrojObsazenosti.VZDY)
    assert obsazeno(Signaly(cidlo=False, cidlo_od_s=99999), kuchyne)


def test_stineni_pri_odchodu_je_volitelne():
    n = NastaveniPritomnosti(stineni_pryc=StineniPryc.ROZTAHNOUT)
    assert n.stineni_pryc is StineniPryc.ROZTAHNOUT
    assert NastaveniPritomnosti().stineni_pryc is StineniPryc.NIC


# ---------------------------------------------------------- indicie

from pritomnost import Indicie, StavIndicie, indicie_aktivni

# obývák: PIR nestačí, ale televize, světla a odběr napovídají
OBYVAK_INDICIE = NastaveniPritomnosti(
    ZdrojObsazenosti.CIDLO,
    indicie=(
        Indicie("televize", dobeh_s=5 * 60),
        Indicie("kodi", dobeh_s=15 * 60),
        Indicie("svetla", dobeh_s=0),
        Indicie("zasuvka", dobeh_s=10 * 60, max_stari_s=3 * 3600),
    ),
)


def _sig(**indicie):
    """PIR mlčí dávno. Vypnuté indicie jsou vypnuté dávno, ne právě teď —
    jinak by u nich ještě běžel doběh."""
    return Signaly(
        cidlo=False, cidlo_od_s=99999,
        indicie={k: StavIndicie(aktivni=v, od_s=0 if v else 99999)
                 for k, v in indicie.items()})


def test_sedici_clovek_u_televize():
    """PIR ho nevidí, ale televize hraje."""
    s = _sig(televize=True, svetla=False)
    assert not _cidlo_verohodne(s, OBYVAK_INDICIE)
    assert obsazeno(s, OBYVAK_INDICIE)


def test_bez_indicii_je_prazdno():
    s = _sig(televize=False, svetla=False, kodi=False, zasuvka=False)
    assert not obsazeno(s, OBYVAK_INDICIE)


def test_staci_jedina_indicie():
    assert obsazeno(_sig(zasuvka=True), OBYVAK_INDICIE)
    assert obsazeno(_sig(kodi=True), OBYVAK_INDICIE)


def test_indicie_ma_vlastni_dobeh():
    """Kodi doznívá 15 minut, světla okamžitě."""
    n = OBYVAK_INDICIE
    s = Signaly(cidlo=False, cidlo_od_s=99999, indicie={
        "kodi": StavIndicie(aktivni=False, od_s=10 * 60),
        "svetla": StavIndicie(aktivni=False, od_s=10 * 60),
    })
    assert indicie_aktivni(s, n) == ["kodi"]


def test_mrtva_indicie_se_ignoruje():
    """Zásuvka se tři hodiny neozvala, nevěříme jí."""
    s = Signaly(cidlo=False, cidlo_od_s=99999, indicie={
        "zasuvka": StavIndicie(aktivni=True, stari_s=4 * 3600),
    })
    assert indicie_aktivni(s, OBYVAK_INDICIE) == []
    assert not obsazeno(s, OBYVAK_INDICIE)


def test_neznama_indicie_neni_dukaz():
    s = Signaly(cidlo=False, cidlo_od_s=99999,
                indicie={"televize": StavIndicie(aktivni=None)})
    assert not obsazeno(s, OBYVAK_INDICIE)


def test_prazdny_byt_prebiji_i_indicie():
    """Zapomenutá televize nesmí přebít informaci, že nikdo není doma."""
    s = Signaly(doma=False, indicie={"televize": StavIndicie(aktivni=True)})
    assert not obsazeno(s, OBYVAK_INDICIE)


def test_vzdy_obsazena_indicie_neresi():
    n = NastaveniPritomnosti(ZdrojObsazenosti.VZDY,
                             indicie=(Indicie("televize"),))
    assert obsazeno(_sig(televize=False), n)


def test_prave_zhasla_televize_jeste_plati():
    """Pětiminutový doběh: kdo právě vypnul televizi, ještě v místnosti je."""
    s = Signaly(cidlo=False, cidlo_od_s=99999,
                indicie={"televize": StavIndicie(aktivni=False, od_s=60)})
    assert obsazeno(s, OBYVAK_INDICIE)
    s2 = Signaly(cidlo=False, cidlo_od_s=99999,
                 indicie={"televize": StavIndicie(aktivni=False, od_s=600)})
    assert not obsazeno(s2, OBYVAK_INDICIE)


def test_klid_je_jen_spanek():
    """Tři zdroje klidu vedly na to, že nikdo nevěděl, který platí.
    Noční hodiny zůstávají zvlášť, ty platí pro celý byt."""
    n = NastaveniPritomnosti()
    assert klid(Signaly(spanek=True)) is True
    assert klid(Signaly(spanek=False, je_noc=True)) is False
    assert klid(Signaly(spanek=None)) is False
