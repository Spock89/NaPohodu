"""Testy generátoru karet."""

import yaml

from karty import dashboard


def vzdy(_):
    return True


def bez_loznice(e):
    return "loznice" not in e


def test_karta_je_platny_yaml():
    s = dashboard(["kuchyne", "obyvak"], ["kuchyn_a_obyvak"], vzdy)
    d = yaml.safe_load(s)
    assert d["type"] == "vertical-stack"
    assert len(d["cards"]) > 5


def test_obsahuje_vsechny_mistnosti():
    s = dashboard(["kuchyne", "obyvak", "loznice"], [], vzdy)
    for m in ("kuchyne", "obyvak", "loznice"):
        assert f"sensor.napohodu_{m}_stav" in s


def test_neexistujici_entity_se_vynechaji():
    """Karta se nesmí odkazovat na to, co v Home Assistantu není."""
    s = dashboard(["kuchyne", "loznice"], [], bez_loznice)
    assert "loznice" not in s
    assert "kuchyne" in s


def test_bez_oblasti_sekce_chybi():
    s = dashboard(["kuchyne"], [], vzdy)
    assert "Sdílený vzduch" not in s


def test_s_oblasti_sekce_je():
    s = dashboard(["kuchyne"], ["oblast"], vzdy)
    assert "Sdílený vzduch" in s


def test_prazdny_seznam_nespadne():
    d = yaml.safe_load(dashboard([], [], vzdy))
    assert d["type"] == "vertical-stack"


def test_kazda_karta_ma_typ():
    d = yaml.safe_load(dashboard(["kuchyne", "obyvak"], ["o"], vzdy))
    assert all("type" in k for k in d["cards"])


def test_posuvniky_jsou_pojmenovane_cesky():
    s = dashboard(["kuchyne"], [], vzdy)
    assert "Vzduch proti teplu" in s
    assert "Nouzově otevřít nad" in s
