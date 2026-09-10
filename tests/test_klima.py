"""Testy sdílené klimatizace."""

import klima as kl
from klima import (STAV_CHLADIT, STAV_SUSIT, STAV_TOPIT, STAV_UTLUM,
                   STAV_VYP, Nastaveni, Pamet, Pokoj, dotlak, rozhodni)

N = Nastaveni(umi=kl.UMI_CHLADIT, v_pokoji="Obývák")


def byt(obyvak=27.0, loznice=27.0, cil=24.0, **kw):
    return [
        Pokoj("Obývák", t_in=obyvak, cil=cil, **kw),
        Pokoj("Ložnice", t_in=loznice, cil=cil, **kw),
    ]


def r(pokoje, p=None, cas=100000, t_out=30.0, sezona=False, n=N):
    return rozhodni(pokoje, p or Pamet(), cas, t_out, sezona, n)


# ---------------------------------------------------------------- základ

def test_chladi_kdyz_je_horko():
    v = r(byt())
    assert v.stav is not None and v.stav == STAV_CHLADIT
    assert v.poslat


def test_nechladi_kdyz_je_teplota_v_poradku():
    assert r(byt(obyvak=23.5, loznice=23.5)).stav == STAV_VYP


def test_jedna_mistnost_pod_cilem_zastavi_chlazeni():
    """Radši nedochladit než přemrazit místnost, která to nepotřebovala."""
    assert r(byt(obyvak=27.0, loznice=23.0)).stav == STAV_VYP


# ---------------------------------------------------------------- dotlak

def test_cil_je_ve_stupnici_vlastni_mistnosti():
    """Jednotka měří svůj pokoj, takže cíl musí být v jeho stupnici."""
    v = r(byt(obyvak=25.0, loznice=27.0, cil=24.0))
    assert v.cil < 24.0          # ložnice je nad cílem, tlačí se dál


def test_dotlak_je_omezeny():
    """Místnost s jednotkou nesmí zmrznout kvůli zbytku bytu."""
    p = byt(obyvak=25.0, loznice=40.0, cil=24.0)
    assert dotlak(p, p[0]) == kl.DOTLAK_MAX


def test_bez_ostatnich_mistnosti_zadny_dotlak():
    p = [Pokoj("Obývák", t_in=27.0, cil=24.0)]
    assert dotlak(p, p[0]) == 0.0


def test_prazdna_mistnost_cil_netaha():
    p = [Pokoj("Obývák", t_in=25.0, cil=24.0),
         Pokoj("Dílna", t_in=35.0, cil=24.0, obsazeno=False)]
    assert dotlak(p, p[0]) == 0.0


def test_nepocitana_mistnost_cil_netaha():
    p = [Pokoj("Obývák", t_in=25.0, cil=24.0),
         Pokoj("Spíž", t_in=35.0, cil=24.0, pocita_se=False)]
    assert dotlak(p, p[0]) == 0.0


# ---------------------------------------------------------------- okna

def test_otevrene_okno_v_chladu_vypne_jednotku():
    """Okno chladí zadarmo, tak ať chladí."""
    v = r(byt(), t_out=19.0, pokoje_kw=None) if False else \
        r([Pokoj("Obývák", t_in=27, cil=24, okno_otevreno=True),
           Pokoj("Ložnice", t_in=27, cil=24)], t_out=19.0)
    assert v.stav == STAV_VYP and "okno" in v.duvod


def test_otevrene_okno_v_horku_jednotku_nevypne():
    """Okno je otevřené kvůli CO2 a tahá dovnitř teplo — chladit je
    potřeba právě teď."""
    v = r([Pokoj("Obývák", t_in=27, cil=24, okno_otevreno=True),
           Pokoj("Ložnice", t_in=27, cil=24)], t_out=33.0)
    assert v.stav == STAV_CHLADIT


# ---------------------------------------------------------------- nepřítomnost

def test_bez_nikoho_se_drzi_utlum_ne_vypnuto():
    """Rozhoupat byt zpátky je dražší než ho udržet."""
    p = byt(obsazeno=False)
    v = r(p)
    assert v.stav == STAV_UTLUM


def test_dlouha_nepritomnost_prejde_na_utlum():
    n = Nastaveni(umi=kl.UMI_CHLADIT, v_pokoji="Obývák",
                  dlouha_nepritomnost=True)
    v = r(byt(), n=n)
    assert v.stav == STAV_UTLUM and v.cil == n.utlum_chlazeni


# ---------------------------------------------------------------- topení

def test_topi_jen_mimo_sezonu():
    n = Nastaveni(umi=kl.UMI_OBOJI, v_pokoji="Obývák")
    studeno = byt(obyvak=19.0, loznice=19.0, cil=22.0)
    assert r(studeno, n=n, sezona=False).stav == STAV_TOPIT
    assert r(studeno, n=n, sezona=True).stav == STAV_VYP


def test_jednotka_ktera_neumi_topit_netopi():
    studeno = byt(obyvak=19.0, loznice=19.0, cil=22.0)
    assert r(studeno).stav == STAV_VYP


# ---------------------------------------------------------------- sušení

def test_susi_jen_kdyz_je_to_zapnute():
    vlhko = [Pokoj("Obývák", t_in=23.5, cil=24, rh_in=72),
             Pokoj("Ložnice", t_in=23.5, cil=24, rh_in=72)]
    assert r(vlhko).stav == STAV_VYP
    n = Nastaveni(umi=kl.UMI_CHLADIT, v_pokoji="Obývák", susit_od=65)
    assert r(vlhko, n=n).stav == STAV_SUSIT


# ---------------------------------------------------------------- klid

def test_stejny_povel_se_neposila_znovu():
    p = Pamet()
    assert r(byt(), p, cas=1000).poslat
    assert not r(byt(), p, cas=1100).poslat


def test_zmena_stavu_projde_hned():
    p = Pamet()
    r(byt(), p, cas=1000)
    assert r(byt(obyvak=23.5, loznice=23.5), p, cas=1100).poslat


def test_drobna_zmena_cile_se_neposila():
    """Cíl, který se vrtí o desetinu, nikomu nepomůže."""
    p = Pamet()
    r(byt(obyvak=25.0, loznice=27.0), p, cas=1000)
    v = r(byt(obyvak=25.0, loznice=27.2), p, cas=1000 + 20 * 60)
    assert not v.poslat


def test_vetsi_zmena_cile_po_uplynuti_klidu_projde():
    p = Pamet()
    r(byt(obyvak=25.0, loznice=25.5), p, cas=1000)
    v = r(byt(obyvak=25.0, loznice=30.0), p, cas=1000 + 20 * 60)
    assert v.poslat


def test_vysledek_rekne_podle_ceho_se_rozhodl():
    v = r(byt(obyvak=25.0, loznice=27.0))
    assert "Ložnice" in v.podle
