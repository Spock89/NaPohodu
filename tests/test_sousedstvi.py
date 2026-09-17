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


def test_prah_zastoupeni_jde_zadat():
    """Zastupování má reagovat od stejné hodnoty, od které by se zóna
    sama otevřela — ne od zadrátovaných 800."""
    zony = byt(loznice_co2=900)
    assert prerozdel(zony, prah=800)["l"].zastupce == "Kuchyně"
    assert prerozdel(zony, prah=1000)["l"].zastupce is None


def test_vychozi_prah_odpovida_nocnimu():
    zony = byt(loznice_co2=950)
    assert prerozdel(zony)["l"].zastupce is None
    assert prerozdel(byt(loznice_co2=1100))["l"].zastupce == "Kuchyně"


# ------------------------------------------- obrácené zastupování

def test_pod_cilem_je_vetrani_drahe():
    """Obývák je pod cílem, okno by kmitalo. Ložnice, kde nikdo není,
    to vyvětrá za něj."""
    zony = [
        ZonaStav("o", "Obývák", co2=1200, pod_cilem=True, sousedi=["l"]),
        ZonaStav("l", "Ložnice", co2=600, obsazeno=False, sousedi=["o"]),
    ]
    u = prerozdel(zony)
    assert u["o"].zastupce == "Ložnice"
    assert u["l"].prevzate_co2 == 1200


def test_soused_taky_pod_cilem_nepomuze():
    zony = [
        ZonaStav("o", "Obývák", co2=1200, pod_cilem=True, sousedi=["l"]),
        ZonaStav("l", "Ložnice", co2=600, pod_cilem=True, sousedi=["o"]),
    ]
    assert prerozdel(zony)["o"].zastupce is None


def test_soused_kde_se_spi_nepomuze_ani_v_tomto_smeru():
    zony = [
        ZonaStav("o", "Obývák", co2=1200, pod_cilem=True, sousedi=["l"]),
        ZonaStav("l", "Ložnice", co2=600, klid=True, sousedi=["o"]),
    ]
    assert prerozdel(zony)["o"].zastupce is None


def test_kdyz_je_vetrani_levne_zastupce_netreba():
    zony = [
        ZonaStav("o", "Obývák", co2=1200, sousedi=["l"]),
        ZonaStav("l", "Ložnice", co2=600, sousedi=["o"]),
    ]
    assert prerozdel(zony)["o"].zastupce is None


def test_draho_plati_pro_oba_duvody():
    from sousedstvi import draho
    assert draho(ZonaStav("a", "A", klid=True))
    assert draho(ZonaStav("a", "A", pod_cilem=True))
    assert not draho(ZonaStav("a", "A"))


def test_kvuli_teplu_se_zastupuje_jen_do_prazdne():
    """Otevřít okno tam, kde někdo je, obtěžuje. Ve dne proto pomůže
    jen prázdná místnost."""
    obsazena = [
        ZonaStav("o", "Obývák", co2=1200, pod_cilem=True, sousedi=["l"]),
        ZonaStav("l", "Ložnice", co2=600, obsazeno=True, sousedi=["o"]),
    ]
    assert prerozdel(obsazena)["o"].zastupce is None

    prazdna = [
        ZonaStav("o", "Obývák", co2=1200, pod_cilem=True, sousedi=["l"]),
        ZonaStav("l", "Ložnice", co2=600, obsazeno=False, sousedi=["o"]),
    ]
    assert prerozdel(prazdna)["o"].zastupce == "Ložnice"


def test_v_noci_pomuze_i_obsazena_kuchyne():
    """Kuchyň je obsazená pořád, jinak by v noci nikdy nezastoupila."""
    zony = [
        ZonaStav("l", "Ložnice", co2=1200, klid=True, sousedi=["k"]),
        ZonaStav("k", "Kuchyně", co2=600, obsazeno=True, sousedi=["l"]),
    ]
    assert prerozdel(zony)["l"].zastupce == "Kuchyně"


def test_oblast_s_bdelou_kuchyni_muze_zastoupit():
    """Spánek v obýváku nesmí zabránit kuchyni, aby vyvětrala za
    ložnici. Kuchyň má okno a klid neřeší."""
    zony = [
        ZonaStav("l", "Ložnice", co2=1200, klid=True, sousedi=["k"]),
        ZonaStav("k", "Kuchyň a obývák", co2=600, klid=False,
                 obsazeno=True, sousedi=["l"]),
    ]
    assert prerozdel(zony)["l"].zastupce == "Kuchyň a obývák"


def test_oblast_kde_spi_vsichni_nezastoupi():
    zony = [
        ZonaStav("l", "Ložnice", co2=1200, klid=True, sousedi=["k"]),
        ZonaStav("k", "Kuchyň a obývák", co2=600, klid=True, sousedi=["l"]),
    ]
    assert prerozdel(zony)["l"].zastupce is None


# ------------------------------------------- ochota větrat

def test_nerada_posle_vzduch_sousedovi_i_pres_den():
    """Od kuchyňského okna táhne na člověka u linky. Ložnice, kde je
    otevřeno celý den a nikoho to netrápí, to vyvětrá za ni."""
    zony = [
        ZonaStav("k", "Kuchyň", co2=1200, nerada=True, sousedi=["l"]),
        ZonaStav("l", "Ložnice", co2=600, ochotna=True, obsazeno=False,
                 sousedi=["k"]),
    ]
    u = prerozdel(zony)
    assert u["k"].zastupce == "Ložnice"
    assert u["l"].prevzate_co2 == 1200


def test_ochotna_pomuze_i_kdyz_je_obsazena():
    """V ložnici může být otevřeno, i když tam někdo je — proto ochotná."""
    zony = [
        ZonaStav("k", "Kuchyň", co2=1200, nerada=True, sousedi=["l"]),
        ZonaStav("l", "Ložnice", co2=600, ochotna=True, obsazeno=True,
                 sousedi=["k"]),
    ]
    assert prerozdel(zony)["k"].zastupce == "Ložnice"


def test_ochotna_se_nebere_za_drahou_ani_pod_cilem():
    from sousedstvi import draho
    assert draho(ZonaStav("l", "L", pod_cilem=True)) is True
    assert draho(ZonaStav("l", "L", pod_cilem=True, ochotna=True)) is False


def test_spanek_prebiji_ochotu():
    """V ložnici může být otevřeno celý den — ale ne když se v ní spí."""
    from sousedstvi import draho
    assert draho(ZonaStav("l", "L", klid=True, ochotna=True)) is True
    zony = [
        ZonaStav("k", "Kuchyň", co2=1200, nerada=True, sousedi=["l"]),
        ZonaStav("l", "Ložnice", co2=600, ochotna=True, klid=True,
                 obsazeno=True, sousedi=["k"]),
    ]
    assert prerozdel(zony)["k"].zastupce is None


def test_nerada_bez_souseda_vetra_sama():
    zony = [ZonaStav("k", "Kuchyň", co2=1200, nerada=True)]
    assert prerozdel(zony)["k"].zastupce is None


def test_sousedstvi_plati_v_obou_smerech():
    """Když oblast jmenuje ložnici, ložnice má za souseda ji. Jinak by
    zastupování fungovalo jen jednou stranou."""
    kuchyn = ZonaStav("k", "Kuchyň a obývák", co2=600, sousedi=["l"])
    loznice = ZonaStav("l", "Ložnice", co2=1200, klid=True, sousedi=[])
    # doplnění zpětné vazby dělá koordinátor; tady ho napodobíme
    loznice.sousedi.append("k")
    u = prerozdel([kuchyn, loznice])
    assert u["l"].zastupce == "Kuchyň a obývák"
    assert u["k"].prevzate_co2 == 1200
