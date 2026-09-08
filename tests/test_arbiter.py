"""Testy arbitra místnosti."""

import core
import slunce as sl
from arbiter import (Chlazeni, NastaveniMistnosti, PametMistnosti, Stineni,
                     StavMistnosti, Topeni, Vybava, Zamer, rozhodni_mistnost)

NV = core.Nastaveni()
NM = NastaveniMistnosti()

VSE = Vybava(okno=True, topeni=True, chlazeni=True, stineni=True)
BEZ_KLIMY = Vybava(okno=True, topeni=True, chlazeni=False, stineni=True)


def sit(**kw):
    """Připraví situaci. Vrací záměr a obě paměti."""
    cas = kw.pop("cas_s", 100000)
    otevreno = kw.pop("otevreno", False)
    vybava = kw.pop("vybava", VSE)
    pm = kw.pop("pm", PametMistnosti())
    slunce = kw.pop("slunce", 0.0)
    azimut = kw.pop("azimut", 180.0)
    obsazeno = kw.pop("obsazeno", True)

    t_in = kw.pop("t_in", 21.0)
    cil = kw.pop("cil", 22.0)

    v = core.Vstup(t_in=t_in, cil=cil, cas_s=cas, **kw)
    # slunce se zadává jako požadovaný zisk; převedeme na jižní okno
    okna = [sl.Okno("jih", azimut=180)] if slunce > 0 else []
    elevace = 40.0 if slunce > 0 else -10.0
    jasno = min(1.0, slunce / 300.0) if slunce > 0 else 0.0
    s = StavMistnosti(t_in=t_in, cil=cil, obsazeno=obsazeno, cas_s=cas,
                      okna=okna, azimut_slunce=azimut, elevace_slunce=elevace,
                      jasno=jasno)
    pv = core.Pamet(otevreno=otevreno,
                    cas_povelu_s=cas - NV.min_drzeni_s - 60)
    return rozhodni_mistnost(v, s, pv, pm, vybava, NV, NM), pv, pm


# ------------------------------------------------------- tvrdá pravidla

def test_otevrene_okno_vypina_topeni():
    z, _, _ = sit(otevreno=True, t_in=19, cil=22, co2=1500, t_out=10)
    assert z.topeni is Topeni.VYPNOUT
    assert z.topeni_cil == NM.utlum


def test_otevrene_okno_vypina_chlazeni():
    z, _, _ = sit(otevreno=True, t_in=27, cil=23, co2=1500, t_out=25)
    assert z.chlazeni is Chlazeni.VYPNOUT


def test_zavrene_okno_topi_na_cil():
    z, _, _ = sit(t_in=20, cil=22.5, co2=500, t_out=5)
    assert z.topeni is Topeni.TOPIT
    assert z.topeni_cil == 22.5


# ------------------------------------------------------- pořadí prostředků

def test_v_zime_se_nejdriv_odcloni():
    z, _, _ = sit(t_in=20, cil=22, slunce=400, co2=500, t_out=5)
    assert z.stineni is Stineni.OTEVRIT
    assert z.topeni is Topeni.TOPIT       # topí se zároveň, slunce nestačí


def test_bez_slunce_se_stinenim_nehybe():
    z, _, _ = sit(t_in=20, cil=22, slunce=0, co2=500, t_out=5)
    assert z.stineni is Stineni.NIC


def test_v_horku_se_nejdriv_zastini():
    z, _, _ = sit(t_in=26, cil=23, slunce=600, co2=500, t_out=30)
    assert z.stineni is Stineni.ZASTINIT


def test_chlazeni_ustoupi_vetrani_kdyz_je_venku_chladneji():
    """Volné chlazení oknem je zadarmo, klimatizace se nezapne."""
    z, _, _ = sit(t_in=27, cil=23, co2=500, t_out=19, slunce=0)
    assert z.okno is core.Akce.OTEVRIT
    assert z.chlazeni is Chlazeni.VYPNOUT


def test_chlazeni_ustoupi_i_bez_otevreneho_okna():
    """Venku je chladněji, ale okno je blokované větrem – klima přesto čeká
    jen tehdy, když má okno šanci. Když ne, zapne se."""
    z, _, _ = sit(t_in=27, cil=23, co2=500, t_out=19, slunce=0,
                  vitr_blokuje=True)
    assert z.okno is not core.Akce.OTEVRIT


def test_chlazeni_nastoupi_kdyz_venku_nepomuze():
    z, _, _ = sit(t_in=27, cil=23, co2=500, t_out=31, slunce=0)
    assert z.chlazeni is Chlazeni.CHLADIT


def test_chlazeni_ma_klid_po_topeni():
    pm = PametMistnosti(topilo_do_s=100000 - 300)
    z, _, _ = sit(t_in=27, cil=23, co2=500, t_out=31, pm=pm)
    assert z.chlazeni is Chlazeni.NIC


# ------------------------------------------------------- vzduch má přednost

def test_dusno_otevre_okno_i_kdyz_je_zima():
    z, _, _ = sit(t_in=20, cil=22, co2=1200, t_out=2)
    assert z.okno is core.Akce.OTEVRIT
    assert z.topeni is Topeni.VYPNOUT     # topení hned ustoupí


def test_cisty_vzduch_okno_neotevre():
    z, _, _ = sit(t_in=20, cil=22, co2=500, t_out=2)
    assert z.okno is not core.Akce.OTEVRIT


# ------------------------------------------------------- vybavení

def test_mistnost_bez_klimy_ji_neresi():
    z, _, _ = sit(vybava=BEZ_KLIMY, t_in=28, cil=23, co2=500, t_out=32)
    assert z.chlazeni is Chlazeni.NIC


def test_mistnost_bez_okna_resi_jen_teplotu():
    z, _, _ = sit(vybava=Vybava(topeni=True), t_in=19, cil=22, co2=1500, t_out=5)
    assert z.okno is core.Akce.NIC
    assert z.topeni is Topeni.TOPIT


def test_prazdna_mistnost_se_netopi_na_cil():
    z, _, _ = sit(obsazeno=False, t_in=19, cil=22, co2=500, t_out=5)
    assert z.topeni is Topeni.NIC


# ------------------------------------------------------- srozumitelnost

def test_zamer_vysvetli_co_dela():
    z, _, _ = sit(otevreno=True, t_in=19, cil=22, co2=1500, t_out=10)
    assert len(z.poradi) >= 2
    assert all(":" in radek for radek in z.poradi)


# ------------------------------------------------------- okna po směrech

def test_stini_se_jen_osvicene_okno():
    """Místnost má okna na východ, jih a západ. Ráno se stíní jen východ."""
    okna = [sl.Okno("východ", azimut=90), sl.Okno("jih", azimut=180),
            sl.Okno("západ", azimut=270)]
    cas = 100000
    v = core.Vstup(t_in=26, cil=23, co2=500, t_out=28, cas_s=cas)
    s = StavMistnosti(t_in=26, cil=23, cas_s=cas, okna=okna,
                      azimut_slunce=95, elevace_slunce=30)
    pv = core.Pamet(cas_povelu_s=cas - 2000)
    z = rozhodni_mistnost(v, s, pv, PametMistnosti(), VSE)
    assert z.stineni is Stineni.ZASTINIT
    assert z.stinit_okna == ["východ"]


def test_vecer_se_stini_zapad():
    okna = [sl.Okno("východ", azimut=90), sl.Okno("západ", azimut=270)]
    cas = 100000
    v = core.Vstup(t_in=26, cil=23, co2=500, t_out=28, cas_s=cas)
    s = StavMistnosti(t_in=26, cil=23, cas_s=cas, okna=okna,
                      azimut_slunce=265, elevace_slunce=15)
    pv = core.Pamet(cas_povelu_s=cas - 2000)
    z = rozhodni_mistnost(v, s, pv, PametMistnosti(), VSE)
    assert z.stinit_okna == ["západ"]


def test_v_noci_se_nestini():
    okna = [sl.Okno("jih", azimut=180)]
    cas = 100000
    v = core.Vstup(t_in=26, cil=23, co2=500, t_out=20, cas_s=cas)
    s = StavMistnosti(t_in=26, cil=23, cas_s=cas, okna=okna,
                      azimut_slunce=0, elevace_slunce=-20)
    pv = core.Pamet(cas_povelu_s=cas - 2000)
    z = rozhodni_mistnost(v, s, pv, PametMistnosti(), VSE)
    assert z.stineni is Stineni.NIC
    assert z.stinit_okna == []


def test_prazdny_byt_roztahne_zaluzie():
    import pritomnost as pr
    nm = NastaveniMistnosti(stineni_pryc=pr.StineniPryc.ROZTAHNOUT)
    cas = 100000
    v = core.Vstup(t_in=26, cil=23, co2=500, t_out=30, doma=False, cas_s=cas)
    # prázdný byt znamená i neobsazenou místnost, to řeší pritomnost.obsazeno()
    s = StavMistnosti(t_in=26, cil=23, cas_s=cas, doma=False, obsazeno=False,
                      okna=[sl.Okno("jih", azimut=180)],
                      azimut_slunce=180, elevace_slunce=45)
    pv = core.Pamet(cas_povelu_s=cas - 2000)
    z = rozhodni_mistnost(v, s, pv, PametMistnosti(), VSE, core.Nastaveni(), nm)
    assert z.stineni is Stineni.OTEVRIT
    assert any("nikdo doma" in r for r in z.poradi)
    # v prázdném bytě se nechladí, i když je nad cílem
    assert z.chlazeni is not Chlazeni.CHLADIT


# ------------------------------------------------------- čistička a odtah

import arbiter as ab

PLNA = ab.Vybava(okno=True, topeni=True, chlazeni=True, stineni=True,
                 cisticka=True, odtah=True)


def _situace(vybava=PLNA, rh=None, **kw):
    cas = 100000
    t_in = kw.pop("t_in", 21.0)
    cil = kw.pop("cil", 22.0)
    v = core.Vstup(t_in=t_in, cil=cil, cas_s=cas, **kw)
    s = StavMistnosti(t_in=t_in, cil=cil, cas_s=cas, rh_in=rh)
    pv = core.Pamet(cas_povelu_s=cas - 2000)
    return rozhodni_mistnost(v, s, pv, PametMistnosti(), vybava)


def test_cisticka_resi_prach():
    z = _situace(pm25=80, co2=500, t_out=2)
    assert z.cisticka is ab.Cisticka.ZAPNOUT


def test_cisticka_se_vypne_kdyz_je_cisto():
    z = _situace(pm25=8, co2=500, t_out=2)
    assert z.cisticka is ab.Cisticka.VYPNOUT


def test_cisticka_neresi_co2():
    """Prach umí, vydýchaný vzduch ne — na ten je potřeba okno."""
    z = _situace(pm25=8, co2=1200, t_out=2)
    assert z.cisticka is ab.Cisticka.VYPNOUT
    assert z.okno is core.Akce.OTEVRIT


def test_odtah_pri_vysoke_vlhkosti():
    z = _situace(rh=72, co2=500, t_out=2)
    assert z.odtah is ab.Odtah.ZAPNOUT


def test_odtah_ma_hysterezi():
    assert _situace(rh=58, co2=500, t_out=2).odtah is ab.Odtah.NIC
    assert _situace(rh=50, co2=500, t_out=2).odtah is ab.Odtah.VYPNOUT


def test_bez_cidla_vlhkosti_se_odtah_neresi():
    z = _situace(rh=None, co2=500, t_out=2)
    assert z.odtah is ab.Odtah.NIC


def test_mistnost_bez_cisticky_ji_nezapne():
    z = _situace(vybava=ab.Vybava(okno=True), pm25=80, co2=500, t_out=2)
    assert z.cisticka is ab.Cisticka.NIC
