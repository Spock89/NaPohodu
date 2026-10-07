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


def test_karta_je_platny_yaml():
    """Výchozí výstup je jedna karta, která jde vložit jako Manuální."""
    s = dashboard(["kuchyne", "obyvak"], ["kuchyn_a_obyvak"], vzdy)
    d = yaml.safe_load(s)
    assert d["type"] == "vertical-stack"
    assert len(d["cards"]) > 10


def test_pohled_jde_vynutit():
    s = dashboard(["kuchyne"], [], vzdy, jako_pohled=True)
    assert yaml.safe_load(s)["type"] == "masonry"


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
    s = dashboard(["kuchyne", "obyvak"], ["o"], vzdy)
    assert all("type" in k for k in vsechny_karty(s))


def test_posuvniky_jsou_pojmenovane_cesky():
    s = dashboard(["kuchyne"], [], vzdy)
    assert "Denní hystereze" in s
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
    """Do grafu patří pojmenovaná poloha, ne entita cover — ta ukáže
    jen otevřeno, protože žaluzie jsou skoro pořád otevřené."""
    s = dashboard(["obyvak"], [], vzdy,
                  zaluzie={"obyvak": ["cover.o1", "cover.o2"]})
    assert "Okna, žaluzie a klid" in s
    assert "sensor.napohodu_obyvak_zaluzie" in s
    assert "cover.o1" not in s
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

def test_karty_jsou_na_jedne_urovni():
    import yaml
    s = dashboard(["kuchyne", "obyvak", "loznice"], ["o"], vzdy,
                  cidla={m: f"sensor.t_{m}" for m in
                         ("kuchyne", "obyvak", "loznice")})
    d = yaml.safe_load(s)
    assert len(d["cards"]) > 20
    assert "vertical-stack" not in {k["type"] for k in d["cards"]}


def test_nadpis_zustane_u_svych_karet():
    """Rozseknout nadpis od karet, které k němu patří, by zamotalo."""
    import yaml
    d = yaml.safe_load(dashboard(["kuchyne"], [], vzdy, podoba="stranka"))
    for sek in d["sections"]:
        typy = [k["type"] for k in sek["cards"]]
        if typy and typy[0] == "heading":
            assert len(typy) > 1, "nadpis zůstal sám v sekci"


def test_poradi_sekci_odpovida_nastavenemu():
    """Pořadí na stránce se ladí ručně, generátor ho musí dodržet."""
    import yaml
    from karty import PORADI_SEKCI
    d = yaml.safe_load(dashboard(
        ["kuchyne", "obyvak"], ["o"], vzdy,
        cidla={"kuchyne": "sensor.a", "obyvak": "sensor.b"},
        podoba="stranka"))
    prvni = [sek["cards"][0].get("heading") or sek["cards"][0].get("title")
             or sek["cards"][0]["type"] for sek in d["sections"]]
    assert prvni[0] == "Cílová teplota"
    assert prvni[1] == "horizontal-stack"       # místnosti hned za tím
    assert prvni[-1] == "Grafy"                 # grafy nakonec
    assert "Ladění" in prvni
    assert len(PORADI_SEKCI) >= 8


def test_grafy_maji_vlastni_sekci():
    """Ať je člověk nemusí hledat po stránce."""
    import yaml
    s = dashboard(["kuchyne", "obyvak"], [], vzdy,
                  cidla={"kuchyne": "sensor.a", "obyvak": "sensor.b"},
                  co2_cidla={"kuchyne": "sensor.c"},
                  venku="sensor.v", podoba="stranka")
    d = yaml.safe_load(s)
    grafove = [sek for sek in d["sections"]
               if any(k["type"] == "history-graph" for k in sek["cards"])]
    assert len(grafove) == 1
    # a nic jiného než nadpis a grafy v ní není
    typy = {k["type"] for k in grafove[0]["cards"]}
    assert typy <= {"heading", "history-graph"}


def test_graf_co2_a_vlhkosti():
    s = dashboard(["kuchyne"], [], vzdy,
                  co2_cidla={"kuchyne": "sensor.co2"},
                  rh_cidla={"kuchyne": "sensor.rh"})
    assert "CO2 v místnostech" in s and "sensor.co2" in s
    assert "title: Vlhkost" in s and "sensor.rh" in s


def test_graf_jedne_veliciny_staci_jedna_cara():
    """Vlhkost v jediné místnosti má taky co říct."""
    s = dashboard(["loznice"], [], vzdy, rh_cidla={"loznice": "sensor.rh"})
    assert "title: Vlhkost" in s


def test_prepinace_ovladani_hned_pod_teplotou():
    """Co smí automatika ovládat člověk hledá první, ne na konci."""
    import yaml
    d = yaml.safe_load(dashboard(
        ["kuchyne", "obyvak"], [], vzdy,
        cidla={"kuchyne": "sensor.a", "obyvak": "sensor.b"},
        podoba="stranka"))
    prvni = d["sections"][0]["cards"]
    assert prvni[0]["heading"] == "Cílová teplota"
    assert prvni[-1]["title"] == "Co smí ovládat"


def test_doma_podle_je_jen_jednou():
    """Přítomnost je společná pro celý byt, ne pro každou místnost."""
    s = dashboard(["kuchyne", "obyvak", "loznice"], [], vzdy,
                  cidla={"kuchyne": "sensor.a"}, venku="sensor.v")
    assert s.count("doma_podle") == 1
    # a patří k základu výpočtu
    zaklad = s[s.index("Základ výpočtu"):]
    assert "doma_podle" in zaklad


def test_karta_obsahuje_ovladani_zaluzii():
    """Tlačítka rolí a výběr stavu v kartě chyběly, takže je nebylo
    kde najít."""
    s = dashboard(["loznice"], [], vzdy, zaluzie={"loznice": ["cover.l"]})
    assert "Ovládání žaluzií" in s
    assert "select.napohodu_loznice_zaluzie_1_stav" in s
    assert "button.napohodu_loznice_zastinit" in s
    assert "button.napohodu_loznice_vychozi_stav_zaluzii" in s


def test_srovnani_obsahuje_i_topeni():
    s = dashboard(["loznice"], [], vzdy)
    assert "button.napohodu_loznice_srovnat_zaluzie" in s
    assert "button.napohodu_loznice_srovnat_topeni" in s


def test_popisky_maji_hacky():
    """Klíč místnosti je bez diakritiky, protože z něj vznikají
    identifikátory entit. Do popisků ale patří pravé jméno."""
    s = dashboard(["loznice"], [], vzdy, cidla={"loznice": "sensor.t"},
                  nazvy={"loznice": "Ložnice"})
    assert '"Ložnice"' in s
    assert "Loznice" not in s


def test_bez_nazvu_se_pouzije_klic():
    """Když jméno neznáme, klíč je lepší než nic."""
    s = dashboard(["loznice"], [], vzdy, cidla={"loznice": "sensor.t"})
    assert '"Loznice"' in s


def test_rozvrzeni_sekci():
    """Pořadí i seskupení podle ručně vyladěné předlohy."""
    import yaml
    d = yaml.safe_load(dashboard(
        ["obyvak", "kuchyne"], ["o"], vzdy,
        cidla={"obyvak": "sensor.a", "kuchyne": "sensor.b"},
        zaluzie={"obyvak": ["cover.o1"]}, podoba="stranka"))
    prvni = [sek["cards"][0].get("heading") or sek["cards"][0].get("title")
             or sek["cards"][0]["type"] for sek in d["sections"]]
    assert prvni[0] == "Cílová teplota"
    assert prvni[-1] == "Grafy"
    assert prvni.index("Ovládání oken") < prvni.index("Ladění")
    assert prvni.index("Zvlhčovače") < prvni.index("Obsazenost a klid")
    # obsazenost a sdílený vzduch v jedné sekci, každé s nadpisem
    sekce = d["sections"][prvni.index("Obsazenost a klid")]
    nadpisy = [k.get("heading") for k in sekce["cards"] if k.get("heading")]
    assert nadpisy == ["Obsazenost a klid", "Sdílený vzduch"]


def test_posuvniky_maji_popisky():
    """Bez nich člověk za měsíc neví, co která hodnota znamená."""
    s = dashboard(["loznice"], [], vzdy, cidla={"loznice": "sensor.t"})
    assert "V noci vychladnout nejvýš na" in s
    assert "méně cyklů za noc" in s
    # každý posuvník s položkami má svou řádku
    from karty import POSUVNIKY
    assert all(len(x) == 3 for x in POSUVNIKY)


def test_jmena_posuvniku_sedi_s_identifikatory():
    """Identifikátor entity vzniká z jejího jména, takže karta musí
    obojí držet v souladu — jinak se řádek tiše nezobrazí."""
    import json
    import pathlib
    import re
    import unicodedata
    from karty import POSUVNIKY

    def slug(t):
        bez = unicodedata.normalize("NFKD", t).encode("ascii", "ignore")
        return "_".join(re.sub(r"[^a-z0-9]+", " ", bez.decode().lower()).split())

    d = json.loads((pathlib.Path(__file__).parent.parent
                    / "custom_components/napohodu/translations/cs.json"
                    ).read_text())
    jmena = {slug(v["name"]) for v in d["entity"]["number"].values()}
    for klic, _, _ in POSUVNIKY:
        assert klic in jmena, klic


def test_starsi_instalace_ma_posuvniky_taky():
    """Home Assistant identifikátor entity při přejmenování nemění,
    takže starší instalace je má pod původními jmény."""
    import re
    from karty import POSUVNIKY, STARSI_POSUVNIKY

    # jeden posuvník může mít víc starších jmen
    stare = set()
    for v in STARSI_POSUVNIKY.values():
        stare.update((v,) if isinstance(v, str) else v)

    def existuje(e):
        if e.startswith("number.napohodu_loznice_"):
            return e.rsplit("loznice_", 1)[1] in stare
        return True

    s = dashboard(["loznice"], [], existuje, cidla={"loznice": "sensor.t"})
    najdene = set(re.findall(r"number\.napohodu_loznice_(\w+)", s))
    # u každého přejmenovaného posuvníku stačí jedno ze starších jmen —
    # entita existuje jen pod tím, pod kterým vznikla
    for klic, varianty in STARSI_POSUVNIKY.items():
        varianty = (varianty,) if isinstance(varianty, str) else varianty
        assert najdene & set(varianty) or klic in najdene, klic


def test_nova_instalace_ma_vsechny_posuvniky():
    import re
    from karty import POSUVNIKY

    nove = {k for k, _, _ in POSUVNIKY}

    def existuje(e):
        if e.startswith("number.napohodu_loznice_"):
            return e.rsplit("loznice_", 1)[1] in nove
        return True

    s = dashboard(["loznice"], [], existuje, cidla={"loznice": "sensor.t"})
    assert nove <= set(re.findall(r"number\.napohodu_loznice_(\w+)", s))


def test_konflikt_je_v_karte_celym_textem():
    """V řádku s atributem by se dlouhá věta ořízla."""
    s = dashboard(["loznice"], [], vzdy, cidla={"loznice": "sensor.t"})
    assert "konflikt_mezi" in s
    assert "Konflikt nastavení" in s
    # a jako text, ne jako atributový řádek
    assert "type: attribute\n    entity: sensor.napohodu_loznice_stav\n" \
           "    attribute: konflikt_mezi" not in s


def test_jedna_karta_na_konflikt_i_pasmo():
    """Dvě karty znamenaly, že ta s konfliktem byla většinu času
    prázdný rámeček."""
    import yaml
    d = yaml.safe_load(dashboard(
        ["loznice"], [], vzdy, cidla={"loznice": "sensor.t"},
        podoba="stranka"))
    md = [k for s in d["sections"] for k in s["cards"]
          if k["type"] == "markdown"
          and ("konflikt_mezi" in k["content"]
               or "teplotni_pasmo" in k["content"])]
    assert len(md) == 1
    assert "konflikt_mezi" in md[0]["content"]
    assert "teplotni_pasmo" in md[0]["content"]


def test_pravidla_bytu_jsou_jednou_a_v_samostatne_sekci():
    """Pravidla pro celý byt nepatří pod každou místnost."""
    import yaml
    d = yaml.safe_load(dashboard(
        ["loznice", "kuchyne"], [], vzdy,
        cidla={"loznice": "sensor.t", "kuchyne": "sensor.k"},
        podoba="stranka"))
    bytu = [k for s in d["sections"] for k in s["cards"]
            if "pevna_pravidla_bytu" in str(k.get("content", ""))]
    assert len(bytu) == 1

    # patří k základu výpočtu, ne do vlastní sekce
    sekce = [s for s in d["sections"]
             if any("pevna_pravidla_bytu" in str(k.get("content", ""))
                    for k in s["cards"])][0]
    nadpisy = [k.get("heading") for k in sekce["cards"] if k.get("heading")]
    assert nadpisy == ["Základ výpočtu", "Nastavení pro celý byt",
                       "Platí bez nastavení"]


def test_karta_zvlhcovacu():
    """Meze se dají ladit z dashboardu, ne jen přes formulář."""
    import yaml
    d = yaml.safe_load(dashboard(
        ["obyvak"], [], vzdy, cidla={"obyvak": "sensor.a"},
        podoba="stranka"))
    karty = [k for s in d["sections"] for k in s["cards"]
             if k.get("title") == "Zvlhčovače"]
    assert len(karty) == 1
    text = str(karty[0])
    assert "zvlhcovac_bezi" in text          # jestli běží
    assert "vlhkost" in text                 # kolik je v pokoji
    assert "zvlhcovac_proc" in text          # kdy zapne a vypne
    assert "zvlhcovat_pod_vlhkosti" in text  # a obě meze
    assert "vypnout_zvlhcovac_nad" in text


def test_zvlhcovace_jen_kde_jsou():
    """Bez toho karta nabízela meze vlhkosti i místnostem, které žádný
    zvlhčovač nemají."""
    import yaml
    d = yaml.safe_load(dashboard(
        ["obyvak", "kuchyne"], [], vzdy,
        cidla={"obyvak": "sensor.a", "kuchyne": "sensor.b"},
        se_zvlhcovacem={"obyvak"}, podoba="stranka"))
    karta = [k for s in d["sections"] for k in s["cards"]
             if k.get("title") == "Zvlhčovače"][0]
    text = str(karta)
    assert "obyvak" in text
    assert "kuchyne" not in text


def test_bez_zvlhcovacu_sekce_neni():
    import yaml
    d = yaml.safe_load(dashboard(
        ["obyvak"], [], vzdy, cidla={"obyvak": "sensor.a"},
        se_zvlhcovacem=set(), podoba="stranka"))
    assert not [k for s in d["sections"] for k in s["cards"]
                if k.get("title") == "Zvlhčovače"]




def test_veta_pod_stupnici_je_mimo_blok():
    """V bloku s pevnou šířkou se dlouhá věta nezalomí a odřízne se,
    takže stupnice patří do bloku a věta mimo."""
    import yaml
    d = yaml.safe_load(dashboard(
        ["loznice"], [], vzdy, cidla={"loznice": "sensor.t"},
        podoba="stranka"))
    md = [k for s in d["sections"] for k in s["cards"]
          if k["type"] == "markdown"
          and "teplotni_pasmo" in k["content"]][0]
    obsah = md["content"]
    # stupnice uvnitř bloku, předpověď za ním
    pred, _, za = obsah.partition("```")
    druhy = za.partition("```")[2]
    assert "teplotni_pasmo" in pred
    assert "teplotni_predpoved" in pred      # proměnná se nastavuje výš
    assert "{{ u }}" in druhy                # ale vypisuje se mimo blok


def test_radky_stupnice_jsou_kratke():
    """Blok nezalamuje, takže delší řádek se na mobilu odřízne."""
    from core import pasmo_jen_stupnice, pasmo_text
    r = pasmo_text(22.7, 24.4, 1.5, 18.0, 1.0, otevreno=True, t_max=24.7,
                   chladi=True, duvod="chlazení větráním")
    for radek in pasmo_jen_stupnice(r):
        assert len(radek) <= 45, radek


def test_posuvnik_najde_i_starsi_jmeno_z_vice_variant():
    """Přejmenovaná entita si drží původní identifikátor. Denní
    hystereze se za svůj život jmenovala třemi způsoby."""
    import yaml
    stare = {"number.napohodu_obyvak_ve_dne_smi_klesnout_pod_cil_o",
             "sensor.napohodu_obyvak_stav"}
    d = yaml.safe_load(dashboard(
        ["obyvak"], [], lambda e: e in stare,
        cidla={"obyvak": "sensor.t"}, podoba="stranka"))
    karta = [k for s in d["sections"] for k in s["cards"]
             if k.get("title") == "Denní hystereze"][0]
    assert karta["entities"][0]["entity"] == (
        "number.napohodu_obyvak_ve_dne_smi_klesnout_pod_cil_o")


def test_globalni_nastaveni_je_v_karte():
    """Globální hodnoty nejsou posuvníky, protože nepatří místnosti.
    Bez výpisu by na dashboardu nebyly vidět vůbec."""
    import yaml
    d = yaml.safe_load(dashboard(
        ["obyvak"], [], vzdy, cidla={"obyvak": "sensor.a"},
        podoba="stranka"))
    md = [k for s in d["sections"] for k in s["cards"]
          if "nastaveni_bytu" in str(k.get("content", ""))]
    assert len(md) == 1


def test_graf_zvlhcovacu_jen_kde_jsou():
    """Zajímá, kdy běžely — a bere se skutečná entita zařízení, ne naše
    představa o ní."""
    import yaml
    d = yaml.safe_load(dashboard(
        ["obyvak", "kuchyne"], [], vzdy,
        cidla={"obyvak": "sensor.a", "kuchyne": "sensor.b"},
        se_zvlhcovacem={"obyvak"},
        zvlhcovace={"obyvak": ["input_boolean.zvhlcovac_o"]},
        podoba="stranka"))
    grafy = [k for s in d["sections"] for k in s["cards"]
             if k["type"] == "history-graph" and k.get("title") == "Zvlhčovače"]
    assert len(grafy) == 1
    assert [e["entity"] for e in grafy[0]["entities"]] == [
        "input_boolean.zvhlcovac_o"]

    # bez zvlhčovačů graf nevznikne
    d2 = yaml.safe_load(dashboard(
        ["obyvak"], [], vzdy, cidla={"obyvak": "sensor.a"},
        podoba="stranka"))
    assert not [k for s in d2["sections"] for k in s["cards"]
                if k.get("title") == "Zvlhčovače"
                and k["type"] == "history-graph"]
