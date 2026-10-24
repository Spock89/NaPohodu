"""Hlášky proti skutečnému rozhodnutí.

Běžný test se ptá „udělá to tohle?". Tady se ptáme „slibuje to totéž,
co udělá?" — protože na dashboardu se čte text, ne kód. Práh se proto
nebere z nastavení, ale hledá se půlením: při jakém CO2 se okno
doopravdy otevře. Když se čísla rozejdou, chyba je v jednom z nich.
"""

import copy
import dataclasses
import itertools

from core import (Akce, Nastaveni, Pamet, Vstup, duvody, ocekavani,
                  prah_otevreni, rozhodni)

N = Nastaveni()


def vstup(**kw) -> Vstup:
    zakl = dict(cas_s=100000.0, t_out=5.0, rh_out=50.0, t_in=21.0,
                t_in_max=21.0, cil=22.0, co2=500.0, hodina=12.0)
    zakl.update(kw)
    return Vstup(**zakl)


def pamet(**kw) -> Pamet:
    p = Pamet(cas_povelu_s=0.0)
    for k, val in kw.items():
        setattr(p, k, val)
    return p


def kolo(v: Vstup, p: Pamet):
    """Jedno kolo v pořadí koordinátoru: rozhodnutí, pak hlášky.

    Koordinátor staví `duvody` a `ocekavani` z paměti už změněné
    rozhodnutím, takže se v tomhle pořadí musí porovnávat i tady.
    """
    v2, p2 = copy.deepcopy(v), copy.deepcopy(p)
    r = rozhodni(v2, p2, N)
    return r, duvody(v2, p2, N), ocekavani(v2, p2, N)


def skutecny_prah(v: Vstup, p: Pamet) -> float | None:
    """Při jakém CO2 se okno opravdu otevře? None = neotevře nikdy."""
    nizko, vysoko = 400.0, 5000.0

    def otevre(co2: float) -> bool:
        akce = rozhodni(dataclasses.replace(v, co2=co2),
                        copy.deepcopy(p), N).akce
        return akce is Akce.OTEVRIT

    if not otevre(vysoko):
        return None
    if otevre(nizko):
        return nizko
    for _ in range(40):
        stred = (nizko + vysoko) / 2
        if otevre(stred):
            vysoko = stred
        else:
            nizko = stred
    return round(vysoko)


# ---------------------------------------------------- slíbený práh otevření

def test_prah_v_ocekavani_sedi_na_skutecnost():
    """„Otevřu nad CO2 X" musí být to X, při kterém se opravdu otevře.

    Tohle odhalilo, že noc, spánek, zastupování, předvětrání
    i rozdělané větrání práh posouvají v rozhodování, ale text
    o tom nevěděl a sliboval pořád stejné číslo.
    """
    spatne = []
    mrizka = itertools.product((False, True), (False, True), (False, True),
                               (False, True), (False, True))
    for noc, spanek, zastupce, predvetrat, vetra_se in mrizka:
        v = vstup(hodina=3.0 if noc else 12.0, spanek=spanek,
                  zastupce=zastupce, predvetrat=predvetrat)
        p = pamet(vetra_se=vetra_se)
        radky = ocekavani(v, p, N)
        slib = [r for r in radky if "otevřu nad CO2" in r]
        popis = (f"noc={noc} spánek={spanek} zástupce={zastupce} "
                 f"předvětrat={predvetrat} větrá_se={vetra_se}")
        assert slib, popis
        cislo = float(slib[0].split("CO2")[1].split("(")[0])
        prah = skutecny_prah(v, p)
        if prah is None or abs(cislo - prah) > 1:
            spatne.append(f"{popis}: slibuje {cislo:.0f}, skutečně {prah}")
    assert not spatne, spatne


def test_prah_otevreni_je_jediny_zdroj():
    """Rozhodování i hlášky počítají práh jedinou funkcí."""
    for noc, spanek, zastupce in itertools.product((False, True),
                                                   (False, True),
                                                   (False, True)):
        v = vstup(hodina=3.0 if noc else 12.0, spanek=spanek,
                  zastupce=zastupce)
        p = pamet()
        prah = prah_otevreni(v, p, N)
        # právě pod prahem nic, právě nad prahem otevření
        pod = rozhodni(dataclasses.replace(v, co2=prah - 1),
                       copy.deepcopy(p), N)
        nad = rozhodni(dataclasses.replace(v, co2=prah + 1),
                       copy.deepcopy(p), N)
        assert pod.akce is not Akce.OTEVRIT, (noc, spanek, zastupce)
        assert nad.akce is Akce.OTEVRIT, (noc, spanek, zastupce)


# --------------------------------------------------------- pojistky v důvodech

def test_pojistka_je_v_duvodech_i_pres_den():
    """Pod dolní mezí se přes den nevětrá — a musí být vidět proč.

    Dřív se pojistka vypisovala jen v nočním bloku, takže přes den
    stálo okno zavřené a v seznamu překážek nebylo nic.
    """
    v = vstup(hodina=12.0, t_in=16.0, t_in_max=16.0, t_out=-5.0, co2=2000.0)
    p = pamet(otevreno=False)
    seznam = duvody(v, p, N)
    assert any("pojistka" in x for x in seznam), seznam

    v2 = vstup(hodina=12.0, t_in=29.0, t_in_max=29.0, t_out=34.0, co2=2000.0)
    assert any("pojistka" in x for x in duvody(v2, pamet(), N))


def test_pojistka_nevisi_v_duvodech_zbytecne():
    """Když venkovní vzduch tlačí správným směrem, pojistka nebrání."""
    # uvnitř pod mezí, ale venku je tepleji → otevřením se neuškodí
    v = vstup(hodina=12.0, t_in=16.0, t_in_max=16.0, t_out=20.0, co2=2000.0)
    assert not any("pojistka" in x for x in duvody(v, pamet(), N))


def test_duvody_nikdy_nemlci_pri_necinnosti():
    """Nic v seznamu a přitom se neotevře — to člověk nemá jak najít."""
    spatne = []
    for co2, tin, tout, hod, vetrat in itertools.product(
            (400.0, 900.0, 1500.0), (17.0, 21.0, 25.0),
            (-5.0, 5.0, 18.0, 30.0), (3.0, 12.0), (False, True)):
        v = vstup(co2=co2, t_in=tin, t_in_max=tin, t_out=tout, hodina=hod,
                  vetrat=vetrat)
        p = pamet(otevreno=False)
        r = rozhodni(copy.deepcopy(v), copy.deepcopy(p), N)
        if duvody(v, p, N) == [] and r.akce is not Akce.OTEVRIT:
            spatne.append(f"co2={co2:.0f} in={tin} out={tout} hod={hod} "
                          f"ruční={vetrat}: {r.duvod!r}")
    assert not spatne, spatne


# ------------------------------------------------- co drží otevřené okno

def test_pri_chlazeni_se_nepise_dojezd_vetrani():
    """Vzduch hotový, otevřeno drží chlazení — a text to tak říká."""
    v = vstup(co2=400.0, t_in=25.0, t_in_max=25.0, t_out=18.0, cil=22.0)
    p = pamet(otevreno=True, vetra_se=True, chladi=True)
    radky = ocekavani(v, p, N)
    assert any("otevřeno drží už jen chlazení" in x for x in radky), radky
    assert not any("dojezd větrání" in x for x in radky), radky


def test_vyvetrano_nebo_duvod_proc_je_otevreno():
    """U vyvětrané místnosti se buď zavírá, nebo je vidět proč ne."""
    spatne = []
    for co2, tin, tout, hod, naraz in itertools.product(
            (400.0, 650.0), (17.0, 21.0, 25.0), (-5.0, 5.0, 18.0, 30.0),
            (3.0, 12.0), (False, True)):
        v = vstup(co2=co2, t_in=tin, t_in_max=tin, t_out=tout, hodina=hod,
                  narazove_mozne=naraz)
        p = pamet(otevreno=True, vetra_se=False)
        r, _duv, oce = kolo(v, p)
        hotovo = any("vyvětráno, čekám" in x for x in oce)
        drzi = any("otevřeno drží už jen" in x for x in oce)
        if (hotovo and not drzi and r.akce is Akce.NIC
                and "držím" not in r.duvod):
            spatne.append(f"co2={co2:.0f} in={tin} out={tout} hod={hod} "
                          f"náraz={naraz}: {r.duvod!r} | {oce}")
    assert not spatne, spatne


def test_drzeni_rika_ktery_pohyb_drzi():
    """„Nejdřív za 15 minut" musí mít podmět — zavřu, nebo otevřu."""
    spatne = []
    for otevreno, co2, tin, tout in itertools.product(
            (False, True), (400.0, 1500.0), (18.0, 24.0), (-5.0, 15.0, 30.0)):
        v = vstup(co2=co2, t_in=tin, t_in_max=tin, t_out=tout)
        p = pamet(otevreno=otevreno, cas_povelu_s=v.cas_s - 60)
        r, _duv, oce = kolo(v, p)
        slib = [x for x in oce if "držím stav" in x]
        if r.kod == "drzeni":
            if not slib:
                spatne.append(f"drží stav, ale neříká to — {r.duvod!r}")
                continue
            chce = "zavřu" if "chci zavřít" in r.duvod else "otevřu"
            if not slib[0].startswith(chce):
                spatne.append(f"slibuje {slib[0]!r}, ale {r.duvod!r}")
    assert not spatne, spatne


def test_narazove_nevypisuje_drzeni_u_otevreneho():
    """V nárazovém počasí se zavírá hned, držení tam nemá co slibovat."""
    v = vstup(co2=400.0, t_in=24.0, t_in_max=24.0, t_out=5.0,
              narazove_mozne=True)
    p = pamet(otevreno=True, cas_povelu_s=v.cas_s - 60)
    radky = ocekavani(v, p, N)
    assert not any("držím stav" in x for x in radky), radky
    assert any("zavřu hned" in x for x in radky), radky


# ------------------------------------------------- text proti kódu akce

def test_kod_a_text_rozhodnuti_si_neprotireci():
    """Co se jmenuje „plán", musí jít z plánu, a „vítr" z větru."""
    par = (("plan_zavreno", ("plán",)), ("vitr", ("vítr", "větru")),
           ("dest", ("déšť", "dešti")))
    spatne = []
    for co2, tin, tout, plan, doma, vitr in itertools.product(
            (400.0, 1200.0), (15.0, 21.0, 29.0), (-10.0, 10.0, 34.0),
            (False, True), (False, True), (False, True)):
        v = vstup(co2=co2, t_in=tin, t_in_max=tin, t_out=tout,
                  plan_zavreno=plan, doma=doma, vitr_blokuje=vitr)
        r = rozhodni(v, pamet(otevreno=True, vetra_se=True), N)
        for kod, slova in par:
            sedi = any(x in r.duvod for x in slova)
            if r.kod == kod and not sedi:
                spatne.append(f"kód {kod}, ale text {r.duvod!r}")
            if sedi and r.kod != kod:
                spatne.append(f"text {r.duvod!r}, ale kód {r.kod!r}")
    assert not spatne, sorted(set(spatne))


def test_tvrda_prekazka_nikdy_neskonci_otevrenim():
    """Co je v důvodech jako tvrdá překážka, to okno neotevře."""
    tvrde = ("vítr", "déšť", "nikdo není doma", "plán: zavřená okna")
    spatne = []
    for co2, tin, tout, hod, vitr, doma, plan in itertools.product(
            (400.0, 1500.0, 3000.0), (18.0, 24.0), (-5.0, 15.0, 30.0),
            (3.0, 12.0), (False, True), (False, True), (False, True)):
        v = vstup(co2=co2, t_in=tin, t_in_max=tin, t_out=tout, hodina=hod,
                  vitr_blokuje=vitr, doma=doma, plan_zavreno=plan)
        p = pamet(otevreno=False)
        r, duv, _oce = kolo(v, p)
        if r.akce is Akce.OTEVRIT and any(x in d for d in duv
                                         for x in tvrde):
            spatne.append(f"otevírá, přestože {duv}")
    assert not spatne, sorted(set(spatne))


# ------------------------------------ ruční větrání v hlášce, ne CO2

def test_noc_pojmenuje_rucni_vetrani():
    """CO2 pod nočním prahem neotevře; otevřít může ruční žádost.

    Dokud tu stálo „noc: otevírám, CO2 572", vypadalo to, že se
    otevřelo kvůli hodnotě hluboko pod prahem, a nešlo poznat proč.
    """
    v = vstup(hodina=3.9, co2=572.0, t_in=17.4, t_in_max=17.4, t_out=6.7,
              cil=22.5)
    assert rozhodni(v, pamet(), N).akce is Akce.NIC       # samotné CO2 ne

    v2 = dataclasses.replace(v, vetrat=True)
    r = rozhodni(v2, pamet(), N)
    assert r.akce is Akce.OTEVRIT
    assert "ruční větrání" in r.duvod


def test_otevrene_okno_rekne_co_ho_drzi():
    """Při nízkém CO2 je „větrá se, CO2 583" samo o sobě protimluv."""
    for hodina, cekam in ((3.9, "noc: větrá"), (12.0, "větrá se")):
        v = vstup(hodina=hodina, co2=583.0, t_in=17.9, t_in_max=17.9,
                  t_out=6.7, cil=22.5, vetrat=True)
        r = rozhodni(v, pamet(otevreno=True, vetra_se=True), N)
        assert cekam in r.duvod, r.duvod
        assert "drží to ruční větrání" in r.duvod, r.duvod


def test_den_pojmenuje_rucni_vetrani_misto_co2():
    v = vstup(hodina=12.0, co2=450.0, t_in=21.0, t_in_max=21.0, t_out=6.7,
              cil=22.5, vetrat=True)
    r = rozhodni(v, pamet(), N)
    assert r.akce is Akce.OTEVRIT
    assert "ruční větrání" in r.duvod, r.duvod


def test_couvani_se_u_otevreneho_okna_nevypisuje():
    """„Zkusím za 52 min" u okna, které zrovna větrá, je protimluv."""
    v = vstup(hodina=3.9, co2=583.0, t_in=17.9, t_in_max=17.9, t_out=6.7,
              cil=22.5, vetrat=True)
    p = pamet(otevreno=True, vetra_se=True,
              pauza_do_s=v.cas_s + 52 * 60)
    radky = ocekavani(v, p, N)
    assert not any("couvám" in x for x in radky), radky

    # u zavřeného okna ten řádek dál platí
    zavreno = pamet(otevreno=False, pauza_do_s=v.cas_s + 52 * 60)
    assert any("couvám" in x for x in ocekavani(v, zavreno, N))


# ------------------------------- nárazový režim: slib „zavřu hned"

def test_narazove_zavira_hned_na_kazdy_duvod():
    """Když karta slíbí „zavřu hned, jak důvod pomine", musí to platit.

    Marné větrání, pojistka i prach tažený zvenčí dřív čekaly na
    nejkratší dobu držení polohy, zatímco ostatní důvody zavíraly
    hned. Na kartě pak stálo „nárazový režim: zavřu hned" a vedle
    toho „chci zavřít, držím stav ještě 2 min".
    """
    nast = Nastaveni(hyst_den_otevrit=2.0, hyst_den_zavrit=2.0,
                     min_drzeni_s=62 * 60, mez_dolni=18.0, mez_horni=27.0)

    def kolo(chladi=True, **kw):
        zakl = dict(cas_s=100000.0, co2=564.0, t_in=20.5, t_in_max=20.5,
                    t_out=8.7, rh_out=70.0, cil=21.8, hodina=14.0,
                    narazove_mozne=True)
        zakl.update(kw)
        v = Vstup(**zakl)
        p = Pamet(cas_povelu_s=v.cas_s - 30 * 60)   # držení ještě běží
        p.otevreno = True
        p.chladi = chladi
        p.rezim = "komfort" if chladi else "pulz"
        p.komfort_start = 22.0
        p.ucinek_od_s = v.cas_s - 30 * 60
        p.ucinek_co2, p.ucinek_t_in = 564.0, 22.0
        return rozhodni(v, p, nast)

    # marné větrání
    r = kolo(t_in=23.5, t_in_max=23.5)
    assert r.akce is Akce.ZAVRIT and r.kod == "bez_ucinku", r.duvod
    # pojistka
    r = kolo(t_in=17.5, t_in_max=17.5)
    assert r.akce is Akce.ZAVRIT and r.kod == "pojistka", r.duvod
    # a vyvětráno, které hned zavíralo už dřív
    r = kolo(chladi=False, co2=450.0)
    assert r.akce is Akce.ZAVRIT, r.duvod


def test_bez_naraz_rezimu_drzeni_plati():
    """Mimo nárazový režim se nejkratší doba držení neobchází."""
    nast = Nastaveni(hyst_den_otevrit=2.0, hyst_den_zavrit=2.0,
                     min_drzeni_s=62 * 60)
    v = Vstup(cas_s=100000.0, co2=564.0, t_in=23.5, t_in_max=23.5,
              t_out=8.7, rh_out=70.0, cil=21.8, hodina=14.0)
    p = Pamet(cas_povelu_s=v.cas_s - 30 * 60)
    p.otevreno, p.chladi, p.rezim = True, True, "komfort"
    p.komfort_start = 22.0
    p.ucinek_od_s = v.cas_s - 30 * 60
    p.ucinek_co2, p.ucinek_t_in = 564.0, 22.0
    r = rozhodni(v, p, nast)
    assert r.kod == "drzeni", r.duvod
    assert p.pulzy_za_sebou == 0, "drženo, tak se marnost nepočítá"


def test_chlazeni_rika_ze_jede_za_cil():
    """Teplota pod cílem a okno pořád otevřené — musí být vidět proč."""
    v = vstup(co2=450.0, t_in=20.2, t_in_max=20.2, t_out=8.7, cil=21.8)
    p = pamet(otevreno=True, chladi=True, rezim="komfort")
    radky = ocekavani(v, p, Nastaveni(hyst_den_zavrit=2.0))
    chlazeni = [x for x in radky if x.startswith("chladím")]
    assert chlazeni, radky
    assert "za cíl 21.8" in chlazeni[0], chlazeni[0]


def test_pojistka_prizna_prebitou_krizi():
    """Karta slibuje, že se při krizi otevře i ve spánku. Pojistka ten
    slib přebije — a musí to říct, jinak je ta hláška lež."""
    from core import Vstup, Pamet, Nastaveni, Akce, rozhodni

    n = Nastaveni()
    p = Pamet(cas_povelu_s=-1e9)
    v = Vstup(cas_s=200000.0, co2=1600.0, t_in=27.5, t_in_max=27.5,
              t_out=31.0, rh_out=45.0, cil=24.0, hodina=3.0,
              spanek=True, doma=True)
    r = rozhodni(v, p, n)
    assert r.akce is Akce.NIC
    assert "nad mezí" in r.duvod
    assert "krizovým prahem" in r.duvod, r.duvod

    # pod krizovým prahem se nic dodávat nemá
    v2 = Vstup(**{**v.__dict__, "co2": 900.0})
    r2 = rozhodni(v2, Pamet(cas_povelu_s=-1e9), n)
    assert "krizovým" not in r2.duvod, r2.duvod


def test_zprava_o_vetru_rekne_kdy_pusti():
    """Zavřené okno při bezvětří vypadá jako chyba, dokud se neřekne,
    že se čeká, jestli klid vydrží."""
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent
                           / "custom_components" / "napohodu"))
    import zpravy

    u = {"rychlost": 3.0, "naraz": 4.5, "co_prekrocilo": "klid ještě nevydržel",
         "klid_zbyva_min": 7,
         "prahy": {"rychlost": 7.0, "naraz": 11.0, "povoli_pod": 5.0,
                   "klid_min": 10.0}}
    t = zpravy.SKLADBA["vitr"]("Obývák", u)
    assert "vítr spadl, ale zatím nakrátko" in t
    assert "klid 7 min" in t

    # mlčící čidlo se jmenuje
    u2 = {**u, "co_prekrocilo": "čidlo mlčí", "klid_zbyva_min": 0}
    t2 = zpravy.SKLADBA["vitr"]("Obývák", u2)
    assert "čidlo větru nehlásí" in t2
    assert "klid" not in t2.split("povolí pod")[1]
