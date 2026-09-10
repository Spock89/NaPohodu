"""Testy vykonávání povelů."""

import asyncio

import core
from vykon import MIN_ODSTUP_S, Vykonavac, cile_zaluzii, role_stineni


class FalesnyHass:
    def __init__(self):
        self.volani = []
        self.services = self
        self.data = {}

    async def async_call(self, domena, sluzba, data, blocking=False):
        self.volani.append((domena, sluzba, data["entity_id"]))


def vyk(po_startu=True):
    """Výchozí je běžící systém. po_startu=True simuluje čerstvý start."""
    h = FalesnyHass()
    v = Vykonavac(h, "z1")
    v.stav.prvni_beh = po_startu
    return h, v


def r(akce, duvod="test", limit=None):
    return core.Rozhodnuti(akce, duvod, limit)


def bez(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- okno

def test_otevreni_posle_povel():
    h, v = vyk()
    bez(v.okno("cover.okno", r(core.Akce.OTEVRIT, "CO2 900"), 1000, False))
    assert h.volani == [("cover", "open_cover", "cover.okno")]


def test_nic_neposila_nic():
    h, v = vyk()
    bez(v.okno("cover.okno", r(core.Akce.NIC), 1000, False))
    assert h.volani == []


def test_bez_okna_se_nic_nestane():
    h, v = vyk()
    bez(v.okno(None, r(core.Akce.OTEVRIT), 1000, False))
    assert h.volani == []


def test_stejny_povel_se_neopakuje():
    """Otevřít dvakrát za sebou nemá smysl a jen zatěžuje síť."""
    h, v = vyk()
    bez(v.okno("cover.okno", r(core.Akce.OTEVRIT), 1000, False))
    bez(v.okno("cover.okno", r(core.Akce.OTEVRIT), 1010, True))
    assert len(h.volani) == 1


def test_po_odstupu_se_povel_zopakuje():
    """Obnova povelu pro případ, že ho pohon zahodil."""
    h, v = vyk()
    bez(v.okno("cover.okno", r(core.Akce.OTEVRIT), 1000, False))
    bez(v.okno("cover.okno", r(core.Akce.OTEVRIT), 1000 + MIN_ODSTUP_S + 1, True))
    assert len(h.volani) == 2


def test_opacny_povel_projde_hned():
    h, v = vyk()
    bez(v.okno("cover.okno", r(core.Akce.OTEVRIT), 1000, False))
    bez(v.okno("cover.okno", r(core.Akce.ZAVRIT), 1005, True))
    assert [x[1] for x in h.volani] == ["open_cover", "close_cover"]


def test_pulz_dojede_a_zavre():
    h, v = vyk()
    bez(v.okno("cover.okno", r(core.Akce.OTEVRIT, limit=600), 1000, False))
    bez(v.okno("cover.okno", r(core.Akce.NIC), 1300, True))      # ještě běží
    assert len(h.volani) == 1
    bez(v.okno("cover.okno", r(core.Akce.NIC), 1700, True))      # dojel
    assert [x[1] for x in h.volani] == ["open_cover", "close_cover"]


def test_pulz_bez_limitu_nezavira():
    h, v = vyk()
    bez(v.okno("cover.okno", r(core.Akce.OTEVRIT, limit=None), 1000, False))
    bez(v.okno("cover.okno", r(core.Akce.NIC), 99999, True))
    assert len(h.volani) == 1


# ---------------------------------------------------------------- stínění

def test_vybere_zastineni_kdyz_je_horko():
    assert role_stineni(400, 150, True, False, True) == "zastinit"


def test_vybere_odstineni_kdyz_je_zima():
    assert role_stineni(400, 150, False, True, True) == "odstinit"


def test_bez_slunce_se_nehybe():
    assert role_stineni(50, 150, True, False, True) is None


def test_nikdo_doma_prebiji():
    assert role_stineni(400, 150, True, False, False) == "pryc"


def test_vlazno_se_nestini():
    """Ani horko, ani zima — žaluzie se nechá být."""
    assert role_stineni(400, 150, False, False, True) is None



# ---------------------------------------------------- víc žaluzií na zónu

def _naparuj_stineni(monkeypatch, selhavajici=()):
    """Podstrčí vykonavači falešné provádění stavů."""
    import sys, types
    provedeno = []

    async def proved(hass, entita, nazev):
        provedeno.append((entita, nazev))
        if entita in selhavajici:
            return {"povedlo_se": False, "chyba": "pohon mlčí"}
        return {"povedlo_se": True}

    modul = types.ModuleType("napohodu.services")
    modul.proved_stav_stineni = proved
    sys.modules["napohodu.services"] = modul
    sys.modules["services"] = modul
    return provedeno


def test_stineni_projede_vsechny_zaluzie(monkeypatch):
    p = _naparuj_stineni(monkeypatch)
    h, v = vyk(po_startu=False)
    bez(v.stineni({"cover.o1": "zastíněno", "cover.o2": "zastíněno"}, 1000, 15))
    assert p == [("cover.o1", "zastíněno"), ("cover.o2", "zastíněno")]


def test_uz_nastavena_zaluzie_se_prekcaci(monkeypatch):
    p = _naparuj_stineni(monkeypatch)
    h, v = vyk(po_startu=False)
    bez(v.stineni({"cover.o1": "zastíněno", "cover.o2": "zastíněno"}, 1000, 15))
    p.clear()
    bez(v.stineni({"cover.o1": "zastíněno", "cover.o2": "zastíněno"}, 9000, 15))
    assert p == []


def test_kazda_zaluzie_ma_vlastni_pamet(monkeypatch):
    """Ruční přestavení jedné nesmí rozjet ostatní."""
    p = _naparuj_stineni(monkeypatch)
    h, v = vyk(po_startu=False)
    bez(v.stineni({"cover.o1": "zastíněno", "cover.o2": "zastíněno"}, 1000, 15))
    v.stav.posledni_stineni.pop("cover.o2")
    p.clear()
    bez(v.stineni({"cover.o1": "zastíněno", "cover.o2": "zastíněno"}, 9000, 15))
    assert p == [("cover.o2", "zastíněno")]


def test_selhani_jedne_nezastavi_ostatni(monkeypatch):
    p = _naparuj_stineni(monkeypatch, selhavajici={"cover.o1"})
    h, v = vyk(po_startu=False)
    vysledek = bez(v.stineni({"cover.o1": "zastíněno", "cover.o2": "zastíněno"}, 1000, 15))
    assert len(p) == 2
    assert "cover.o2" in v.stav.posledni_stineni
    assert "cover.o1" not in v.stav.posledni_stineni
    assert v.stav.chyby


def test_odstup_mezi_pohyby(monkeypatch):
    p = _naparuj_stineni(monkeypatch)
    h, v = vyk(po_startu=False)
    bez(v.stineni({"cover.o1": "zastíněno"}, 1000, 15))
    p.clear()
    bez(v.stineni({"cover.o1": "odstíněno"}, 1100, 15))   # za 100 s
    assert p == []
    bez(v.stineni({"cover.o1": "odstíněno"}, 1000 + 16 * 60, 15))
    assert p == [("cover.o1", "odstíněno")]


def test_ruzna_jmena_pro_stejnou_roli(monkeypatch):
    """O1 má „zastíněno", O2 „zataženo" — obě se nastaví správně."""
    p = _naparuj_stineni(monkeypatch)
    h, v = vyk(po_startu=False)
    bez(v.stineni({"cover.o1": "zastíněno", "cover.o2": "zataženo"}, 1000, 15))
    assert p == [("cover.o1", "zastíněno"), ("cover.o2", "zataženo")]



# ------------------------------------------------- pravidla, kdy hýbat

from vykon import (REZIM_JEN_PRYC, REZIM_NIKDY, REZIM_VZDY, SOUKROMI_HNED,
                   SOUKROMI_NIKDY, SOUKROMI_POHYB)


def st(**kw):
    """Zkratka: výchozí je doma, den, slunce svítí."""
    a = dict(zisk=400, prah=150, horko=False, zima=False, doma=True,
             rezim=REZIM_VZDY, po_zapadu=False, pohyb=False,
             soukromi_kdy=SOUKROMI_NIKDY, v_pokoji=False)
    a.update(kw)
    return role_stineni(**a)


def test_doma_se_nesaha_kdyz_je_rezim_jen_pryc():
    """Ložnice a obývák: co si nastavíme ručně, to zůstane."""
    assert st(rezim=REZIM_JEN_PRYC, horko=True) is None
    assert st(rezim=REZIM_JEN_PRYC, zima=True) is None


def test_ale_prazdny_byt_prebiji_i_ten_rezim():
    assert st(rezim=REZIM_JEN_PRYC, doma=False) == "pryc"


def test_rezim_nikdy_nesaha_ani_kdyz_odejdeme():
    assert st(rezim=REZIM_NIKDY, doma=True, horko=True) is None


def test_kuchyne_se_stini_i_kdyz_jsme_doma():
    """Kuchyň: roztaženo pořád, kromě horka od slunce."""
    assert st(rezim=REZIM_VZDY, horko=True) == "zastinit"
    assert st(rezim=REZIM_VZDY) is None


def test_soukromi_po_zapadu_hned():
    """Obývák: po setmění zatáhnout, ať není vidět dovnitř."""
    assert st(po_zapadu=True, soukromi_kdy=SOUKROMI_HNED,
              rezim=REZIM_JEN_PRYC) == "soukromi"


def test_soukromi_az_pri_pohybu():
    """Ložnice: zatáhne se, teprve když tam někdo přijde."""
    a = dict(po_zapadu=True, soukromi_kdy=SOUKROMI_POHYB,
             rezim=REZIM_JEN_PRYC)
    assert st(**a, pohyb=False) is None
    assert st(**a, pohyb=True) == "soukromi"


def test_soukromi_neplati_pres_den():
    assert st(po_zapadu=False, soukromi_kdy=SOUKROMI_HNED, pohyb=True) is None


def test_soukromi_prebiji_rezim_jen_pryc():
    """Zatáhnout po setmění chceme i tam, kde si jinak žaluzie řídíme sami."""
    assert st(po_zapadu=True, soukromi_kdy=SOUKROMI_HNED,
              rezim=REZIM_JEN_PRYC) == "soukromi"


def test_puvodni_volani_bez_pravidel_funguje_dal():
    assert role_stineni(400, 150, True, False, True) == "zastinit"


# ------------------------------------- přiřazení stavů jednotlivým žaluziím

MAPA = {
    "cover.o1|zastinit": "zastíněno",
    "cover.o1|soukromi": "dolů",
    "cover.o2|zastinit": "zataženo",     # jinak pojmenovaný stav
    "cover.o2|soukromi": "dolů",
    "cover.o2|odstinit": "odstíněno",
}


def test_kazda_zaluzie_dostane_svoje_jmeno():
    """Dvě žaluzie v pokoji můžou mít stavy pojmenované jinak."""
    assert cile_zaluzii("zastinit", MAPA) == {
        "cover.o1": "zastíněno", "cover.o2": "zataženo"}


def test_zaluzie_bez_prirazeni_se_nehne():
    assert cile_zaluzii("odstinit", MAPA) == {"cover.o2": "odstíněno"}


def test_role_bez_prirazeni_nic_nedela():
    assert cile_zaluzii("pryc", MAPA) == {}


def test_zadna_role_znamena_klid():
    assert cile_zaluzii(None, MAPA) == {}


def test_prazdna_mapa():
    assert cile_zaluzii("zastinit", {}) == {}
    assert cile_zaluzii("zastinit", None) == {}


# --------------------------------------------- žaluzie po startu neruší

def test_po_startu_se_zaluziemi_nehybe(monkeypatch):
    """Restart Home Assistanta nesmí zarachotit žaluziemi."""
    p = _naparuj_stineni(monkeypatch)
    h, v = vyk()
    bez(v.stineni({"cover.o1": "zastíněno"}, 1000, 15))
    assert p == []
    assert v.stav.posledni_stineni == {"cover.o1": "zastíněno"}


def test_po_startu_reaguje_az_na_zmenu(monkeypatch):
    p = _naparuj_stineni(monkeypatch)
    h, v = vyk(po_startu=True)
    bez(v.stineni({"cover.o1": "zastíněno"}, 1000, 15))
    bez(v.stineni({"cover.o1": "zastíněno"}, 9000, 15))
    assert p == []                       # pořád stejné, nic se neděje
    bez(v.stineni({"cover.o1": "odstíněno"}, 20000, 15))
    assert p == [("cover.o1", "odstíněno")]


def test_tlacitko_srovnat_pohyb_vynuti(monkeypatch):
    """Když si člověk řekne, žaluzie se srovnají i po startu."""
    p = _naparuj_stineni(monkeypatch)
    h, v = vyk()
    bez(v.stineni({"cover.o1": "zastíněno"}, 1000, 15))
    v.zapomen()
    bez(v.stineni({"cover.o1": "zastíněno"}, 9000, 15))
    assert p == [("cover.o1", "zastíněno")]


def test_rezim_prazdna_mistnost():
    """Kuchyň se má zaclonit i doma, ale ne když v ní zrovna stojíš."""
    from vykon import REZIM_PRAZDNA
    assert st(rezim=REZIM_PRAZDNA, horko=True, v_pokoji=False) == "zastinit"
    assert st(rezim=REZIM_PRAZDNA, horko=True, v_pokoji=True) is None


def test_rezim_prazdna_odcloni_kdyz_je_zima():
    from vykon import REZIM_PRAZDNA
    assert st(rezim=REZIM_PRAZDNA, zima=True, v_pokoji=False) == "odstinit"


def test_rezim_vzdy_ignoruje_pritomnost_v_pokoji():
    assert st(rezim=REZIM_VZDY, horko=True, v_pokoji=True) == "zastinit"


# ---------------------------------------------------------------- topení

from vykon import cil_topeni


def test_mimo_sezonu_se_netopi():
    assert cil_topeni(22, False, 16, False, False, False, 28) == ("off", 16)


def test_v_sezone_se_posila_cil():
    assert cil_topeni(22.5, False, 16, True, False, False, 28) == ("heat", 22.5)


def test_otevrene_okno_srazi_na_utlum_ne_na_vypnuto():
    """Hlavice, která se úplně zavře, se pak dlouho vrací."""
    assert cil_topeni(22.5, True, 16, True, False, False, 28) == ("heat", 16)


def test_odvzdusneni_drzi_ventil_otevreny():
    assert cil_topeni(22, False, 16, True, False, True, 28) == ("heat", 28)


def test_odvzdusneni_prebiji_i_otevrene_okno():
    assert cil_topeni(22, True, 16, True, False, True, 28)[1] == 28


def test_topit_mimo_sezonu_jde_zapnout():
    assert cil_topeni(22, False, 16, False, True, False, 28) == ("heat", 22)
