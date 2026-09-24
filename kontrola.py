"""Kontrola celistvosti balíčku. Spouští se před každým vydáním."""
import ast, json, pathlib, re, sys

d = pathlib.Path(__file__).parent / "custom_components" / "napohodu"
chyby = []

# 1) konstanty, na které se někdo odkazuje
konst = dict(re.findall(r'^(\w+) = "?([\w.]*)"?', (d / "const.py").read_text(), re.M))
for p in d.glob("*.py"):
    if p.name == "const.py":
        continue
    t = ast.parse(p.read_text())
    for u in ast.walk(t):
        if isinstance(u, ast.ImportFrom) and u.module == "const":
            for a in u.names:
                if a.name not in konst:
                    chyby.append(f"{p.name}: importuje neexistující {a.name}")
        if (isinstance(u, ast.Attribute) and isinstance(u.value, ast.Name)
                and u.value.id == "c" and u.attr.isupper()
                and u.attr not in konst):
            chyby.append(f"{p.name}: c.{u.attr} neexistuje")

# 1b) volání se špatným počtem argumentů, která projdou syntaxí
BEZNE = {"get": 2, "setdefault": 2, "pop": 2, "getattr": 3, "round": 2}
for p in d.glob("*.py"):
    for u in ast.walk(ast.parse(p.read_text())):
        if isinstance(u, ast.Call) and isinstance(u.func, ast.Attribute):
            limit = BEZNE.get(u.func.attr)
            if limit and len(u.args) > limit:
                chyby.append(
                    f"{p.name}:{u.lineno}: {u.func.attr}() má "
                    f"{len(u.args)} argumentů, nejvýš {limit}")

# 1c) zdvojená přiřazení v konstruktorech — zbytky po úpravách kódu
for p in d.glob("*.py"):
    for tr in ast.walk(ast.parse(p.read_text())):
        if not isinstance(tr, ast.ClassDef):
            continue
        for f in tr.body:
            if getattr(f, "name", "") != "__init__":
                continue
            jmena = [u.targets[0].attr for u in ast.walk(f)
                     if isinstance(u, ast.Assign)
                     and isinstance(u.targets[0], ast.Attribute)]
            for jm in set(jmena):
                if jmena.count(jm) > 1:
                    chyby.append(
                        f"{p.name}: {tr.name}.__init__ nastavuje "
                        f"self.{jm} {jmena.count(jm)}krát")

# 1d) zdvojené bloky: stejný neprázdný řádek hned dvakrát za sebou
for p in d.glob("*.py"):
    radky = p.read_text().splitlines()
    for i in range(len(radky) - 1):
        r = radky[i].strip()
        if len(r) > 20 and r == radky[i + 1].strip() and not r.startswith("#"):
            chyby.append(f"{p.name}:{i + 1}: řádek je tam dvakrát: {r[:40]}")

# 1e) moduly, které nikdo neimportuje — mrtvý kód mate a duplikuje logiku
VSTUPNI = {"__init__", "const", "config_flow", "coordinator", "entity",
           "sensor", "binary_sensor", "number", "switch", "button",
           "services", "karty", "select"}
importovane = set()
for p in d.glob("*.py"):
    for u in ast.walk(ast.parse(p.read_text())):
        if isinstance(u, ast.ImportFrom) and u.level == 1:
            if u.module:
                importovane.add(u.module.split(".")[0])
            importovane.update(a.name for a in u.names)
for p in d.glob("*.py"):
    if p.stem not in VSTUPNI and p.stem not in importovane:
        chyby.append(f"{p.name}: modul nikdo neimportuje, je to mrtvý kód")

# 1f) proměnná čtená dřív, než se přiřadí — projde syntaxí i pyflakes,
# spadne až za běhu
for p in d.glob("*.py"):
    strom = ast.parse(p.read_text())
    # funkce v modulu i metody ve třídách
    funkce = [u for u in ast.walk(strom)
              if isinstance(u, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for f in funkce:
        if True:
            # včetně parametrů vnořených funkcí — kontrola do nich
            # zabíhá a jejich jména nejsou z vnějšku vidět
            parametry = {a.arg for a in f.args.args}
            for u in ast.walk(f):
                if isinstance(u, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.Lambda)):
                    parametry.update(a.arg for a in u.args.args)
                    parametry.update(a.arg for a in u.args.kwonlyargs)
            opakovane = set()
            for u in ast.walk(f):
                cil = getattr(u, "target", None)
                if not isinstance(u, (ast.For, ast.AsyncFor,
                                      ast.comprehension)):
                    continue
                # cíl cyklu může být i rozbalení do několika jmen
                if isinstance(cil, ast.Name):
                    opakovane.add(cil.id)
                elif isinstance(cil, (ast.Tuple, ast.List)):
                    opakovane.update(x.id for x in cil.elts
                                     if isinstance(x, ast.Name))
            # Rozbalení do několika jmen naráz se taky počítá za
            # přiřazení. Musí to být vlastní smyčka: ta předchozí
            # přeskakuje vše, co není cyklus.
            for u in ast.walk(f):
                if isinstance(u, ast.Assign):
                    for t2 in u.targets:
                        if isinstance(t2, (ast.Tuple, ast.List)):
                            opakovane.update(
                                x.id for x in t2.elts
                                if isinstance(x, ast.Name))

            # nejdřívější přiřazení, ne první nalezené — průchod
            # stromem nejde po řádcích
            prvni = {}
            for u in ast.walk(f):
                # přiřazení s typovou anotací se počítá taky
                if isinstance(u, ast.AnnAssign) and isinstance(
                        u.target, ast.Name) and u.value is not None:
                    prvni[u.target.id] = min(
                        prvni.get(u.target.id, u.lineno), u.lineno)
                if isinstance(u, ast.Assign):
                    for t2 in u.targets:
                        if isinstance(t2, ast.Name):
                            prvni[t2.id] = min(prvni.get(t2.id, u.lineno),
                                               u.lineno)
            for u in ast.walk(f):
                if (isinstance(u, ast.Name) and isinstance(u.ctx, ast.Load)
                        and u.id in prvni and u.id not in parametry
                        and u.id not in opakovane
                        and u.lineno < prvni[u.id]):
                    chyby.append(
                        f"{p.name}:{u.lineno}: {f.name} čte {u.id} dřív, "
                        f"než se přiřadí (řádek {prvni[u.id]})")

# 1g) pole Vstup, která koordinátor nikdy nenastaví — funkce, kterou
# jádro umí, ale nikdo ji nespustí, je horší než chybějící
jadro = (d / "core.py").read_text()
ko_text = (d / "coordinator.py").read_text()
if "v = core.Vstup(" in ko_text:
    i = ko_text.index("v = core.Vstup(")
    hloubka, konec = 0, len(ko_text)
    for j in range(i + len("v = core.Vstup"), len(ko_text)):
        if ko_text[j] == "(":
            hloubka += 1
        elif ko_text[j] == ")":
            hloubka -= 1
            if hloubka == 0:
                konec = j
                break
    predane = set(re.findall(r"(\w+)=", ko_text[i:konec]))
    for tr in ast.walk(ast.parse(jadro)):
        if isinstance(tr, ast.ClassDef) and tr.name == "Vstup":
            for u in tr.body:
                if (isinstance(u, ast.AnnAssign)
                        and isinstance(u.target, ast.Name)
                        and u.target.id not in predane):
                    chyby.append(
                        f"coordinator.py: Vstup.{u.target.id} se nikdy "
                        f"nenastaví, zůstane na výchozí hodnotě")

# 1h) importy uvnitř funkcí. V běžícím jádře Home Assistantu je to
# blokující operace a v cyklu koordinátoru se opakuje každou minutu.
V_JADRE = {"coordinator", "sensor", "binary_sensor", "number", "switch",
           "button", "entity"}
for p in d.glob("*.py"):
    if p.stem not in V_JADRE:
        continue
    for f in ast.walk(ast.parse(p.read_text())):
        if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for u in ast.walk(f):
            if isinstance(u, (ast.Import, ast.ImportFrom)):
                jm = getattr(u, "module", None) or ",".join(
                    a.name for a in u.names)
                chyby.append(
                    f"{p.name}:{u.lineno}: {f.name} importuje {jm} "
                    f"až za běhu, patří to nahoru")

# 1i) atribut, na který se karta odkazuje, ale entita ho nevystavuje.
# Projde všemi ostatními kontrolami a v kartě zůstane prázdná pomlčka.
karty_text = (d / "karty.py").read_text()
senzor_text = (d / "sensor.py").read_text()
ko_text2 = (d / "coordinator.py").read_text()

# co která entita propouští (filtr "if k in (...)"; None = všechno)
filtry = {}
for tr in ast.walk(ast.parse(senzor_text)):
    if not isinstance(tr, ast.ClassDef):
        continue
    for f in tr.body:
        if getattr(f, "name", "") != "extra_state_attributes":
            continue
        propousti = None
        for u in ast.walk(f):
            if isinstance(u, ast.Compare) and any(
                    isinstance(o, ast.In) for o in u.ops):
                for srov in u.comparators:
                    if isinstance(srov, (ast.Tuple, ast.List, ast.Set)):
                        propousti = {x.value for x in srov.elts
                                     if isinstance(x, ast.Constant)}
        filtry[tr.name] = propousti

KONCOVKY = {"slunce_na_oknech": "SlunceMistnosti",
            "_zaluzie": "StineniMistnosti",
            "_stav": "StavMistnosti",
            "sdileny_vzduch": "StavOblasti"}

# Jméno entity se v kartě skládá do proměnné, takže se sleduje, co
# do ní naposledy přišlo. Bez toho kontrola nic nenajde.
promenne = {}
for radek in karty_text.splitlines():
    m = re.match(r'\s*(\w+) = f"sensor\.napohodu_\{[^}]+\}(\w+)"', radek)
    if m:
        promenne[m.group(1)] = m.group(2)
    m = re.search(r'_atribut\(\s*([\w"./{}]+)', radek)
    if not m:
        continue
    vyraz = m.group(1)
    koncovka = promenne.get(vyraz, vyraz)
    trida = next((jm for k, jm in KONCOVKY.items() if k in koncovka), None)
    at = re.search(r'_atribut\([^,]+,\s*"(\w+)"', radek)
    if trida is None or at is None:
        continue
    atribut = at.group(1)
    propousti = filtry.get(trida)
    if propousti is not None and atribut not in propousti:
        chyby.append(f"karty.py: {trida} nevystavuje atribut "
                     f"{atribut!r}, v kartě zůstane prázdný")
    if f'"{atribut}"' not in ko_text2 and f'"{atribut}"' not in senzor_text:
        chyby.append(f"karty.py: atribut {atribut!r} nikdo nenastavuje")

# 1k) posuvník a pole ve formuláři musí mít stejný rozsah. Jinak se
# hodnota zadaná ve formuláři do posuvníku nevejde a ty dva pak ukazují
# každý něco jiného.
n_text = (d / "number.py").read_text()
cf_text = (d / "config_flow.py").read_text()
posuvniky_rozsah = {
    m[0]: (float(m[1]), float(m[2]))
    for m in re.findall(r"Posuvnik\((CONF_\w+),\s*([\d.]+),\s*([\d.]+)",
                        n_text)}
pole_rozsah = {
    m[0]: (float(m[1]), float(m[2]))
    for m in re.findall(
        r"vol\.Optional\(c\.(CONF_\w+)[^\n]*?_cislo\(\s*(-?[\d.]+),"
        r"\s*([\d.]+)", cf_text)}
for klic, rozsah in sorted(posuvniky_rozsah.items()):
    ve_form = pole_rozsah.get(klic)
    if ve_form and ve_form != rozsah:
        chyby.append(
            f"{klic}: posuvník {rozsah[0]}–{rozsah[1]}, formulář "
            f"{ve_form[0]}–{ve_form[1]} — hodnoty se rozejdou")

# 1l) funkce, kterou nikdo mimo testy nevolá. Po odstranění nějaké
# funkce v ní zůstávají pomocníci, o kterých už nikdo neví.
HA_HOOKY = {"async_setup_entry", "async_unload_entry", "async_setup",
            "async_press", "async_turn_on", "async_turn_off",
            "async_select_option", "async_set_native_value",
            "async_added_to_hass", "is_on", "native_value",
            "extra_state_attributes", "options", "current_option",
            "available", "async_get_options_flow",
            "async_get_supported_subentry_types", "async_migrate_entry",
            "_async_update_data", "device_info", "icon", "native_unit_of_measurement"}
kod_vse = "\n".join(x.read_text() for x in d.glob("*.py"))
for p in d.glob("*.py"):
    for u in ast.walk(ast.parse(p.read_text())):
        if not isinstance(u, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        n = u.name
        if (n in HA_HOOKY or n.startswith("async_step_")
                or n.startswith("__")):
            continue
        if len(re.findall(rf"\b{n}\b", kod_vse)) <= 1:
            chyby.append(f"{p.name}: funkci {n} nikdo nevolá, je to mrtvý kód")

# 1m) entity, na které se karta odkazuje, musí opravdu vznikat.
# Identifikátor se skládá z PŘELOŽENÉHO jména, ne z klíče v kódu —
# „srovnat_stineni" se jmenuje Srovnat žaluzie a entita končí na
# srovnat_zaluzie. Karta si jména skládá za běhu, takže se musí
# vygenerovat a posbírat, na co se ptá.
import unicodedata


def _slug(text):
    bez = unicodedata.normalize("NFKD", text).encode("ascii", "ignore")
    return "_".join(bez.decode().lower().split())


try:
    sys.path.insert(0, str(d))
    import karty as _karty

    preklady = json.loads((d / "translations" / "cs.json").read_text())
    znama = {druh: {_slug(v.get("name", ""))
                    for v in (preklady["entity"].get(druh) or {}).values()}
             for druh in preklady["entity"]}

    # Napodobíme čistou instalaci: existují jen entity, které se
    # opravdu založí. Karta si pak sama vybere platné varianty a ve
    # výsledku nesmí zůstat nic, co nevznikne.
    def existuje(eid):
        druh, _, zbytek = eid.partition(".")
        if not zbytek.startswith("napohodu_") or druh not in znama:
            return True               # cizí entita, do toho nemluvíme
        zbytek = zbytek[len("napohodu_"):]
        for predpona in ("pokoj_", "oblast_", ""):
            if zbytek.startswith(predpona):
                return zbytek[len(predpona):] in znama[druh]
        return False

    text = _karty.dashboard(
        ["pokoj"], ["oblast"], existuje,
        cidla={"pokoj": "sensor.cizi"}, zaluzie={"pokoj": ["cover.cizi"]})

    for eid in set(re.findall(r"\b(\w+\.napohodu_[\w]+)", text)):
        druh, _, zbytek = eid.partition(".")
        if druh not in znama:
            continue
        zbytek = zbytek[len("napohodu_"):]
        for predpona in ("pokoj_", "oblast_", ""):
            if zbytek.startswith(predpona):
                konec = zbytek[len(predpona):]
                break
        if konec and konec not in znama[druh]:
            chyby.append(
                f"karty.py: {eid} nikde nevzniká — "
                f"{druh} umí {sorted(znama[druh])}")
    # A opačně: entita, která vzniká, ale v kartě není, se prostě
    # nikdy neukáže. Přesně tak zmizela tlačítka stínění.
    PATRI_JINAM = {"venku_za_tyden", "venku_za_tri_dny",
                   "okno_pro_topeni",          # mají starší variantu
                   "ovladat_klimatizaci"}      # klima má vlastní kartu
    vse = _karty.dashboard(
        ["pokoj"], ["oblast"], lambda e: True,
        cidla={"pokoj": "sensor.cizi"}, zaluzie={"pokoj": ["cover.cizi"]})
    for druh, polozky in preklady["entity"].items():
        for v in polozky.values():
            jm = _slug(v.get("name", ""))
            if not jm or jm in PATRI_JINAM or "{" in v.get("name", ""):
                continue
            if all(f"{druh}.napohodu_{x}{jm}" not in vse
                   for x in ("", "pokoj_", "oblast_")):
                chyby.append(
                    f"karty.py: {druh} {jm} vzniká, ale v kartě není")
except Exception as e:      # pragma: no cover
    chyby.append(f"kontrola karty selhala: {e}")

# 1n) výchozí hodnota ve formuláři proti té v kódu. Když se rozejdou,
# platí pro každého něco jiného podle toho, jestli si pole někdy uložil.
vse_kod = "\n".join(x.read_text() for x in d.glob("*.py"))
cf_kod = (d / "config_flow.py").read_text()
for m in re.finditer(r"vol\.Optional\(c\.(CONF_\w+),\s*default=([^)]+?)\)",
                     cf_kod):
    klic, ve_form = m.group(1), m.group(2).strip()
    v_kodu = {x.strip() for x in re.findall(
        rf"(?:d|g|data)\.get\({klic},\s*([^),]+?)\)", vse_kod)}
    cisla = {x for x in v_kodu if re.fullmatch(r"-?[\d.]+", x)}
    if not re.fullmatch(r"-?[\d.]+", ve_form) or not cisla:
        continue
    if all(abs(float(ve_form) - float(x)) > 1e-9 for x in cisla):
        chyby.append(
            f"{klic}: formulář má výchozí {ve_form}, kód bere "
            f"{sorted(cisla)} — komu se pole neuložilo, platí jiná hodnota")

# 2) místní moduly
soubory = {p.stem for p in d.glob("*.py")}
for p in d.glob("*.py"):
    for u in ast.walk(ast.parse(p.read_text())):
        if (isinstance(u, ast.ImportFrom) and u.level == 1 and u.module
                and u.module not in soubory):
            chyby.append(f"{p.name}: chybí modul .{u.module}")

# 3) každé pole formuláře má název i popisek, v přidání i v úpravě
s = (d / "config_flow.py").read_text()
hodnoty = {k: v for k, v in konst.items() if k.startswith("CONF_")}


def pole(od, do):
    blok = s[s.index(od):s.index(do)]
    return {hodnoty[m] for m in re.findall(r"vol\.\w+\(c\.(CONF_\w+)", blok)
            if m in hodnoty}


bloky = {
    "user": pole("SCHEMA_GLOBAL", "class NaPohoduConfigFlow"),
    "zaklad": pole("def _schema_mistnost", "SCHEMA_PRITOMNOST"),
    "pritomnost": pole("SCHEMA_PRITOMNOST", "SCHEMA_INDICIE"),
    "indicie": pole("SCHEMA_INDICIE", "class MistnostSubentryFlow"),
    "zona": pole("def _schema_zona", "class ZonaSubentryFlow"),
    "klima": pole("def _schema_klima", "class KlimaSubentryFlow"),
}
for jazyk in ("cs", "en"):
    t = json.loads((d / "translations" / f"{jazyk}.json").read_text())
    mapa = {
        "user": t["config"]["step"]["user"],
        "zaklad": t["config_subentries"]["mistnost"]["step"]["zaklad"],
        "pritomnost": t["config_subentries"]["mistnost"]["step"]["pritomnost"],
        "indicie": t["config_subentries"]["mistnost"]["step"]["indicie"],
        "zona": t["config_subentries"]["zona"]["step"]["user"],
        "klima": t["config_subentries"]["klima"]["step"]["user"],
    }
    for jm, polia in bloky.items():
        for k in sorted(polia):
            if k not in mapa[jm].get("data", {}):
                chyby.append(f"{jazyk}/{jm}: chybí název {k}")
            if k not in mapa[jm].get("data_description", {}):
                chyby.append(f"{jazyk}/{jm}: chybí popisek {k}")
    rec = t["config_subentries"]["mistnost"]["step"]["reconfigure"]
    vse = bloky["zaklad"] | bloky["pritomnost"] | bloky["indicie"]
    for k in sorted(vse - set(rec.get("data", {}))):
        chyby.append(f"{jazyk}/reconfigure: chybí {k}")

# 1j) pole, které v překladu je, ale ve formuláři chybí. Celý blok
# polí se dá omylem smazat a nikde to nezaskřípe — v překladu zůstane.
for jazyk in ("cs", "en"):
    t2 = json.loads((d / "translations" / f"{jazyk}.json").read_text())
    kroky = {
        "zaklad": t2["config_subentries"]["mistnost"]["step"]["zaklad"],
        "zona": t2["config_subentries"]["zona"]["step"]["user"],
        "klima": t2["config_subentries"]["klima"]["step"]["user"],
        "user": t2["config"]["step"]["user"],
    }
    schemata = {
        "zaklad": ("def _schema_mistnost", "SCHEMA_PRITOMNOST"),
        "zona": ("def _schema_zona", "class ZonaSubentryFlow"),
        "klima": ("def _schema_klima", "class KlimaSubentryFlow"),
        "user": ("SCHEMA_GLOBAL", "class NaPohoduConfigFlow"),
    }
    cf2 = (d / "config_flow.py").read_text()
    for jm, (od, do) in schemata.items():
        blok = cf2[cf2.index(od):cf2.index(do)]
        ve_schematu = {hodnoty[m] for m in
                       re.findall(r"vol\.\w+\(c\.(CONF_\w+)", blok)
                       if m in hodnoty}
        for klic in sorted(set(kroky[jm].get("data", {})) - ve_schematu):
            chyby.append(
                f"{jazyk}/{jm}: {klic!r} je v překladu, ale ve formuláři "
                f"chybí — nesmazal se omylem?")


    # 4) klíče výběrů musí být bez diakritiky
    def projdi(x, cesta=""):
        if isinstance(x, dict):
            for k, v in x.items():
                if (cesta.startswith("selector.") and cesta.count(".") >= 2
                        and not re.fullmatch(r"[a-z0-9_-]+", k)):
                    chyby.append(f"{jazyk}: vadný klíč {cesta}.{k}")
                projdi(v, f"{cesta}.{k}" if cesta else k)

    projdi(t)

# 5) verze v manifestu — ať se nestane, že vydám balíček se starým číslem
manifest = json.loads((d / "manifest.json").read_text())
ocekavana = (pathlib.Path(__file__).parent / "VERZE").read_text().strip() \
    if (pathlib.Path(__file__).parent / "VERZE").exists() else None
if ocekavana and manifest.get("version") != ocekavana:
    chyby.append(
        f"manifest má verzi {manifest.get('version')}, ale VERZE říká "
        f"{ocekavana}")
print("verze v manifestu:", manifest.get("version"))

if chyby:
    print("NALEZENO:")
    for c in sorted(set(chyby)):
        print("  ", c)
    sys.exit(1)
print("balíček je celistvý")
