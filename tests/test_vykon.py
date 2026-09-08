"""Testy vykonávání povelů."""

import asyncio

import core
from vykon import MIN_ODSTUP_S, Vykonavac, stav_stineni


class FalesnyHass:
    def __init__(self):
        self.volani = []
        self.services = self
        self.data = {}

    async def async_call(self, domena, sluzba, data, blocking=False):
        self.volani.append((domena, sluzba, data["entity_id"]))


def vyk():
    h = FalesnyHass()
    return h, Vykonavac(h, "z1")


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
    jmena = {"zastinit": "zastíněno", "odstinit": "odstíněno", "pryc": "dolů"}
    assert stav_stineni(400, 150, True, False, True, jmena) == "zastíněno"


def test_vybere_odstineni_kdyz_je_zima():
    jmena = {"zastinit": "zastíněno", "odstinit": "odstíněno", "pryc": "dolů"}
    assert stav_stineni(400, 150, False, True, True, jmena) == "odstíněno"


def test_bez_slunce_se_nehybe():
    jmena = {"zastinit": "zastíněno"}
    assert stav_stineni(50, 150, True, False, True, jmena) is None


def test_nikdo_doma_prebiji():
    jmena = {"zastinit": "zastíněno", "pryc": "roztáhnout"}
    assert stav_stineni(400, 150, True, False, False, jmena) == "roztáhnout"


def test_nenastavene_jmeno_znamena_nedelat_nic():
    assert stav_stineni(400, 150, True, False, True, {}) is None


def test_vlazno_se_nestini():
    """Ani horko, ani zima — žaluzie se nechá být."""
    jmena = {"zastinit": "z", "odstinit": "o"}
    assert stav_stineni(400, 150, False, False, True, jmena) is None



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
    h, v = vyk()
    bez(v.stineni(["cover.o1", "cover.o2"], "zastíněno", 1000, 15))
    assert p == [("cover.o1", "zastíněno"), ("cover.o2", "zastíněno")]


def test_uz_nastavena_zaluzie_se_prekcaci(monkeypatch):
    p = _naparuj_stineni(monkeypatch)
    h, v = vyk()
    bez(v.stineni(["cover.o1", "cover.o2"], "zastíněno", 1000, 15))
    p.clear()
    bez(v.stineni(["cover.o1", "cover.o2"], "zastíněno", 9000, 15))
    assert p == []


def test_kazda_zaluzie_ma_vlastni_pamet(monkeypatch):
    """Ruční přestavení jedné nesmí rozjet ostatní."""
    p = _naparuj_stineni(monkeypatch)
    h, v = vyk()
    bez(v.stineni(["cover.o1", "cover.o2"], "zastíněno", 1000, 15))
    v.stav.posledni_stineni.pop("cover.o2")
    p.clear()
    bez(v.stineni(["cover.o1", "cover.o2"], "zastíněno", 9000, 15))
    assert p == [("cover.o2", "zastíněno")]


def test_selhani_jedne_nezastavi_ostatni(monkeypatch):
    p = _naparuj_stineni(monkeypatch, selhavajici={"cover.o1"})
    h, v = vyk()
    vysledek = bez(v.stineni(["cover.o1", "cover.o2"], "zastíněno", 1000, 15))
    assert len(p) == 2
    assert "cover.o2" in v.stav.posledni_stineni
    assert "cover.o1" not in v.stav.posledni_stineni
    assert v.stav.chyby


def test_odstup_mezi_pohyby(monkeypatch):
    p = _naparuj_stineni(monkeypatch)
    h, v = vyk()
    bez(v.stineni(["cover.o1"], "zastíněno", 1000, 15))
    p.clear()
    bez(v.stineni(["cover.o1"], "odstíněno", 1100, 15))   # za 100 s
    assert p == []
    bez(v.stineni(["cover.o1"], "odstíněno", 1000 + 16 * 60, 15))
    assert p == [("cover.o1", "odstíněno")]


def test_jedna_zaluzie_jako_retezec(monkeypatch):
    p = _naparuj_stineni(monkeypatch)
    h, v = vyk()
    bez(v.stineni("cover.o1", "dolů", 1000, 15))
    assert p == [("cover.o1", "dolů")]



# ------------------------------------------------- pravidla, kdy hýbat

from vykon import (REZIM_JEN_PRYC, REZIM_NIKDY, REZIM_VZDY, SOUKROMI_HNED,
                   SOUKROMI_NIKDY, SOUKROMI_POHYB)

JMENA = {"zastinit": "zastíněno", "odstinit": "odstíněno",
         "pryc": "nejsme doma", "soukromi": "dolů"}


def st(**kw):
    """Zkratka: výchozí je doma, den, slunce svítí."""
    a = dict(zisk=400, prah=150, horko=False, zima=False, doma=True,
             jmena=JMENA, rezim=REZIM_VZDY, po_zapadu=False, pohyb=False,
             soukromi_kdy=SOUKROMI_NIKDY)
    a.update(kw)
    return stav_stineni(**a)


def test_doma_se_nesaha_kdyz_je_rezim_jen_pryc():
    """Ložnice a obývák: co si nastavíme ručně, to zůstane."""
    assert st(rezim=REZIM_JEN_PRYC, horko=True) is None
    assert st(rezim=REZIM_JEN_PRYC, zima=True) is None


def test_ale_prazdny_byt_prebiji_i_ten_rezim():
    assert st(rezim=REZIM_JEN_PRYC, doma=False) == "nejsme doma"


def test_rezim_nikdy_nesaha_ani_kdyz_odejdeme():
    assert st(rezim=REZIM_NIKDY, doma=True, horko=True) is None


def test_kuchyne_se_stini_i_kdyz_jsme_doma():
    """Kuchyň: roztaženo pořád, kromě horka od slunce."""
    assert st(rezim=REZIM_VZDY, horko=True) == "zastíněno"
    assert st(rezim=REZIM_VZDY) is None


def test_soukromi_po_zapadu_hned():
    """Obývák: po setmění zatáhnout, ať není vidět dovnitř."""
    assert st(po_zapadu=True, soukromi_kdy=SOUKROMI_HNED,
              rezim=REZIM_JEN_PRYC) == "dolů"


def test_soukromi_az_pri_pohybu():
    """Ložnice: zatáhne se, teprve když tam někdo přijde."""
    a = dict(po_zapadu=True, soukromi_kdy=SOUKROMI_POHYB,
             rezim=REZIM_JEN_PRYC)
    assert st(**a, pohyb=False) is None
    assert st(**a, pohyb=True) == "dolů"


def test_soukromi_neplati_pres_den():
    assert st(po_zapadu=False, soukromi_kdy=SOUKROMI_HNED, pohyb=True) is None


def test_soukromi_prebiji_rezim_jen_pryc():
    """Zatáhnout po setmění chceme i tam, kde si jinak žaluzie řídíme sami."""
    assert st(po_zapadu=True, soukromi_kdy=SOUKROMI_HNED,
              rezim=REZIM_JEN_PRYC) == "dolů"


def test_bez_nastaveneho_jmena_se_nic_nedeje():
    assert st(po_zapadu=True, soukromi_kdy=SOUKROMI_HNED,
              jmena={"zastinit": "z"}) is None


def test_puvodni_volani_bez_pravidel_funguje_dal():
    assert stav_stineni(400, 150, True, False, True, JMENA) == "zastíněno"
