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


# ---------------------------------------------------------------- grafy

def test_budiky_u_kazde_mistnosti():
    """Cíl vedle skutečnosti, ať je rozdíl vidět hned."""
    s = dashboard(["kuchyne", "obyvak"], [], vzdy,
                  cidla={"kuchyne": "sensor.t_kuchyne",
                         "obyvak": "sensor.t_obyvak"})
    assert s.count("type: gauge") == 4          # dvě místnosti po dvou
    assert "sensor.t_kuchyne" in s


def test_graf_teplot_je_jeden_pro_vsechny():
    s = dashboard(["kuchyne", "obyvak"], [], vzdy,
                  cidla={"kuchyne": "sensor.t_kuchyne",
                         "obyvak": "sensor.t_obyvak"},
                  venku="sensor.venku")
    assert s.count("Cíl proti skutečnosti") == 1
    assert "sensor.venku" in s


def _graf_pohybu(s):
    """Vytáhne z karty jen graf oken a žaluzií."""
    i = s.index("Okna, žaluzie a klid")
    zbytek = s[i:]
    konec = zbytek.find("  - type:", 10)
    return zbytek[:konec if konec > 0 else None]


def test_do_grafu_pohybu_jen_mistnosti_s_okny():
    """Obývák bez ovládaného okna do grafu nepatří."""
    s = dashboard(["kuchyne", "obyvak"], [], vzdy,
                  s_okny={"kuchyne"}, s_klidem={"kuchyne", "obyvak"})
    g = _graf_pohybu(s)
    assert "napohodu_kuchyne_okno" in g
    assert "napohodu_obyvak_okno" not in g


def test_mistnost_bez_okna_nema_radek_okno():
    import re
    s = dashboard(["obyvak"], [], vzdy, s_okny=set())
    entity = set(re.findall(r"entity: ([a-z_]+\.[a-z0-9_]+)", s))
    assert "binary_sensor.napohodu_obyvak_okno" not in entity
    # okenní senzor pro topení tam zůstává, ten s ovládáním nesouvisí
    assert "binary_sensor.napohodu_obyvak_okno_otevreno" in entity
    assert "sensor.napohodu_obyvak_stav" in entity


def test_klid_se_neukazuje_kde_se_neresi():
    s = dashboard(["kuchyne", "loznice"], [], vzdy,
                  s_klidem={"loznice"})
    assert "napohodu_loznice_klid" in s
    assert "napohodu_kuchyne_klid" not in s


def test_graf_pohybu_obsahuje_okna_zaluzie_i_klid():
    s = dashboard(["obyvak"], [], vzdy,
                  zaluzie={"obyvak": ["cover.o1", "cover.o2"]})
    assert "Okna, žaluzie a klid" in s
    assert "cover.o1" in s and "cover.o2" in s
    assert "binary_sensor.napohodu_obyvak_klid" in s


def test_graf_bez_cidla_se_vynecha():
    """Graf s jedinou čarou nemá co ukázat."""
    s = dashboard(["kuchyne"], [], lambda e: "napohodu" in e)
    assert "cíl proti skutečnosti" not in s


def test_karta_s_grafy_je_platny_yaml():
    import yaml
    s = dashboard(["kuchyne", "loznice"], ["o"], vzdy,
                  cidla={"kuchyne": "sensor.a", "loznice": "sensor.b"},
                  zaluzie={"loznice": ["cover.z"]}, venku="sensor.v")
    d = yaml.safe_load(s)
    assert any(k["type"] == "history-graph" for k in d["cards"])
