"""Testy generátoru karet."""

import yaml

from karty import dashboard


def vzdy(_):
    return True


def vsechny_karty(s):
    """Rozbalí vnořené stacky, ať testy nezávisí na dělení do sloupců."""
    import yaml

    def projdi(k):
        yield k
        for vnorena in k.get("cards", []) or []:
            yield from projdi(vnorena)

    return list(projdi(yaml.safe_load(s)))


def blok(s, nadpis):
    """Vytáhne úsek textu od nadpisu do dalšího nadpisu."""
    i = s.index(nadpis)
    zbytek = s[i:]
    dalsi = zbytek.find("heading:", 10)
    return zbytek[:dalsi if dalsi > 0 else None]


def bez_loznice(e):
    return "loznice" not in e


def test_pohled_je_platny_yaml():
    """Karty se dávají do pohledu, ne do jedné složené karty — jinak by
    na mobilu zůstaly vedle sebe a zmáčkly se."""
    s = dashboard(["kuchyne", "obyvak"], ["kuchyn_a_obyvak"], vzdy)
    d = yaml.safe_load(s)
    assert d["type"] == "masonry"
    assert d["title"] == "NaPohodu"
    assert len(d["cards"]) > 10


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
    assert d["type"] == "masonry"


def test_kazda_karta_ma_typ():
    s = dashboard(["kuchyne", "obyvak"], ["o"], vzdy)
    assert all("type" in k for k in vsechny_karty(s))


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
    assert s.count("title: Teploty") == 1
    assert "sensor.venku" in s


def test_graf_teplot_ma_jen_jeden_cil():
    """Cíle jsou skoro totožné, tři čáry navíc jen zaplevelí graf."""
    s = dashboard(["kuchyne", "obyvak", "loznice"], [], vzdy,
                  cidla={m: f"sensor.t_{m}" for m in
                         ("kuchyne", "obyvak", "loznice")})
    graf = [k for k in vsechny_karty(s)
            if k.get("title") == "Teploty"][0]
    cile = [e for e in graf["entities"]
            if "cilova_teplota" in e["entity"]]
    assert len(cile) == 1


def test_oddelovace_mezi_mistnostmi():
    """Bez čáry se řádky tří místností slijou dohromady."""
    s = dashboard(["kuchyne", "obyvak", "loznice"], [], vzdy,
                  cidla={m: f"sensor.t_{m}" for m in
                         ("kuchyne", "obyvak", "loznice")})
    # najít tu kartu, kde jsou posuvníky odchylky, a spočítat čáry v ní
    karta = [k for k in vsechny_karty(s)
             if any("odchylka_teploty" in (e.get("entity") or "")
                    for e in (k.get("entities") or []))][0]
    cary = [e for e in karta["entities"] if e.get("type") == "divider"]
    assert len(cary) == 2


def test_zaklad_vypoctu_ukazuje_zdroj_u_oboji():
    s = dashboard(["kuchyne"], [], vzdy)
    assert blok(s, "Základ výpočtu").count("attribute: zdroj") == 2


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
    assert any(k["type"] == "history-graph" for k in vsechny_karty(s))


# ---------------------------------------------------------------- sloupce

def test_karty_jsou_samostatne_ne_v_jednom_stacku():
    """Masonry si je přeskládá jen tehdy, když jsou na nejvyšší úrovni."""
    import yaml
    s = dashboard(["kuchyne", "obyvak", "loznice"], ["o"], vzdy,
                  cidla={m: f"sensor.t_{m}" for m in
                         ("kuchyne", "obyvak", "loznice")})
    d = yaml.safe_load(s)
    assert len(d["cards"]) > 20
    assert "vertical-stack" not in {k["type"] for k in d["cards"]}


def test_jedna_karta_jde_vynutit():
    import yaml
    s = dashboard(["kuchyne"], [], vzdy, jako_pohled=False)
    assert yaml.safe_load(s)["type"] == "vertical-stack"


def test_nadpis_zustane_u_svych_karet():
    """Rozseknout nadpis od karet, které k němu patří, by zamotalo."""
    s = dashboard(["kuchyne"], [], vzdy)
    radky = s.splitlines()
    for i, r in enumerate(radky):
        if "type: heading" in r:
            zbytek = radky[i + 1:i + 8]
            assert any("type: entities" in x or "type: heading" in x
                       or "type: gauge" in x for x in zbytek)
