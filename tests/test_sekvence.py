"""Testy posloupností pro žaluzie."""

import asyncio

import pytest
from sekvence import (ChybaSekvence, Druh, Stav, doba_s, preved, spust, zpet)


# ---------------------------------------------------------------- čtení

def test_tvoje_sekvence_z_node_red():
    """Zaclonění kuchyně: 10, počkej 5 s, 14, počkej 3 s, 10."""
    k = preved("10, 5s, 14, 3s, 10")
    assert [x.druh for x in k] == [Druh.POLOHA, Druh.CEKAT, Druh.POLOHA,
                                   Druh.CEKAT, Druh.POLOHA]
    assert [x.hodnota for x in k] == [10, 5, 14, 3, 10]


def test_desetinna_poloha():
    assert preved("12.7")[0].hodnota == 12.7


def test_carka_oddeluje_kroky_ne_desetiny():
    """Čárka nemůže být obojí. Desetinná čísla se píšou s tečkou."""
    assert [k.hodnota for k in preved("12,7")] == [12, 7]


def test_skvirka_se_stopem():
    k = preved("2.9, 1.249s, stop")
    assert k[-1].druh is Druh.STOP


def test_cekani_na_polohu():
    k = preved("0, =0, 5")
    assert k[1].druh is Druh.CEKAT_POLOHU and k[1].hodnota == 0
    assert zpet(k) == "0, =0, 5"


def test_tilt_pro_pohony_ktere_umi():
    k = preved("tilt 40")
    assert k[0].druh is Druh.TILT and k[0].hodnota == 40


def test_ruzne_oddelovace():
    assert len(preved("0 -> 5s -> 14")) == 3
    assert len(preved("0; 5s; 14")) == 3


def test_zpetny_prevod():
    for zapis in ("0, 5s, 14", "2.9, 1.25s, stop", "tilt 40", "0, =0, 5"):
        assert zpet(preved(zapis)) == zapis


# ---------------------------------------------------------------- chyby

def test_prazdna_sekvence():
    with pytest.raises(ChybaSekvence):
        preved("")


def test_nesmysl_vysvetli_co_je_spatne():
    with pytest.raises(ChybaSekvence, match="nerozumím"):
        preved("nahoru")


def test_poloha_mimo_rozsah():
    with pytest.raises(ChybaSekvence, match="rozsah"):
        preved("150")


def test_sekvence_ktera_nikam_nejede():
    with pytest.raises(ChybaSekvence, match="nikam nejede"):
        preved("5s, stop")


def test_nemuze_zacinat_stopem():
    with pytest.raises(ChybaSekvence, match="začínat"):
        preved("stop, 5")


# ---------------------------------------------------------------- pohon

class FalesnyPohon:
    """Pohon, který jede 2 % za sekundu a polohu hlásí pravdivě."""

    def __init__(self, poloha=50.0, rychlost=2.0, hlasi_polohu=True):
        self._poloha = poloha
        self._cil = poloha
        self._rychlost = rychlost
        self._cas = 0.0
        self._hlasi = hlasi_polohu
        self.povely = []

    def _posun(self, sekund):
        self._cas += sekund
        rozdil = self._cil - self._poloha
        krok = min(abs(rozdil), self._rychlost * sekund)
        self._poloha += krok if rozdil > 0 else -krok

    async def poloha(self):
        return round(self._poloha, 2) if self._hlasi else None

    async def nastav_polohu(self, hodnota):
        self.povely.append(("poloha", hodnota))
        self._cil = hodnota
        self._posun(0.1)

    async def nastav_tilt(self, hodnota):
        self.povely.append(("tilt", hodnota))

    async def stop(self):
        self.povely.append(("stop", None))
        self._cil = self._poloha

    async def cekej(self, sekund):
        self._posun(sekund)

    def cas(self):
        return self._cas


def bez(kroky, pohon, **kw):
    return asyncio.run(spust(kroky, pohon, **kw))


def test_sekvence_projede_a_dojede():
    p = FalesnyPohon(poloha=50)
    v = bez(preved("10, 5s, 14, 3s, 10"), p)
    assert v.povedlo_se
    assert v.poloha_pred == 50
    assert [x[0] for x in p.povely] == ["poloha"] * 3


def test_cekani_na_polohu_pocka_az_dojede():
    p = FalesnyPohon(poloha=50)
    v = bez(preved("0, =0, 5"), p)
    assert v.povedlo_se, v.chyba
    # čekalo se, až pohon skutečně dojel na nulu, teprve pak další povel
    assert p.povely == [("poloha", 0), ("poloha", 5)]
    assert v.provedeno == ["0", "=0", "5"]


def test_cekani_na_polohu_vyprsi_kdyz_nedojede():
    """Pohon je pomalý a do timeoutu to nestihne."""
    p = FalesnyPohon(poloha=100, rychlost=0.1)
    v = bez(preved("0, =0"), p, timeout_polohy_s=5)
    assert not v.povedlo_se
    assert "nedostavila" in v.chyba


def test_pohon_ktery_nehlasi_polohu():
    p = FalesnyPohon(hlasi_polohu=False)
    v = bez(preved("0, =0"), p, timeout_polohy_s=2)
    assert not v.povedlo_se and "nic" in v.chyba
    # bez čekání na polohu ale sekvence projde
    assert bez(preved("0, 2s, 5"), p).povedlo_se


def test_stop_zastavi_na_miste():
    p = FalesnyPohon(poloha=0, rychlost=2.0)
    v = bez(preved("100, 1.5s, stop"), p)
    assert v.povedlo_se
    assert 2 < v.poloha_po < 5               # ujelo jen kousek


def test_vysledek_popisuje_co_se_stalo():
    p = FalesnyPohon()
    v = bez(preved("10, 1s, stop"), p)
    assert v.provedeno == ["10", "1s", "stop"]
    assert v.trvani_s > 0
    assert v.jako_slovnik()["povedlo_se"] is True


# ---------------------------------------------------------------- odhad

def test_odhad_doby():
    """Odhad slouží jako pojistka proti zaseknuté sekvenci."""
    kratka = doba_s(preved("0, 5s, 14"))
    dlouha = doba_s(preved("0, 30s, 14"))
    assert dlouha > kratka
    assert doba_s(preved("0, =0")) > doba_s(preved("0"))


def test_stav_si_pamatuje_sekvenci():
    s = Stav("zastíněno", "0, 5s, 5")
    assert len(s.kroky) == 3
    assert s.jako_slovnik()["nazev"] == "zastíněno"


# ---------------------------------------------------------------- hromadně

from sekvence import do_textu, z_textu


def test_precte_stavy_po_radcich():
    text = """zastíněno = 0, 2s, 5
odstíněno = 4, 3s, 2
dolů = 0"""
    s = z_textu(text)
    assert s == {"zastíněno": "0, 2s, 5", "odstíněno": "4, 3s, 2", "dolů": "0"}


def test_prazdne_radky_a_poznamky():
    s = z_textu("# tohle je poznámka\n\nzastíněno = 0\n")
    assert list(s) == ["zastíněno"]


def test_chybejici_rovnitko_rekne_ktery_radek():
    with pytest.raises(ChybaSekvence, match="Řádek 2"):
        z_textu("a = 0\nnesmysl")


def test_chyba_v_sekvenci_rekne_ktery_stav():
    with pytest.raises(ChybaSekvence, match="odstíněno"):
        z_textu("zastíněno = 0\nodstíněno = nahoru")


def test_chybejici_nazev():
    with pytest.raises(ChybaSekvence, match="chybí název"):
        z_textu(" = 0, 5s")


def test_zpetny_prevod_do_textu():
    stavy = {"dolů": "0", "zastíněno": "0, 2s, 5"}
    assert do_textu(stavy) == "dolů = 0\nzastíněno = 0, 2s, 5"


def test_kolecko_tam_a_zpet():
    text = "dolů = 0\nškvírka = 0, 5s, 2.9, 1.25s, stop"
    assert do_textu(z_textu(text)) == text


def test_prazdny_text_da_prazdny_slovnik():
    assert z_textu("") == {}
    assert z_textu(None) == {}
