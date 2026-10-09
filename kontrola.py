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
    """Jak z názvu vznikne identifikátor: bez diakritiky, bez
    interpunkce, mezery na podtržítka."""
    bez = unicodedata.normalize("NFKD", text).encode("ascii", "ignore")
    ciste = re.sub(r"[^a-z0-9]+", " ", bez.decode().lower())
    return "_".join(ciste.split())


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

# 1p) argument, který se v těle nepoužije. Vzniká, když se funkce
# přestaví a volání zůstane po starém — čte se pak něco, co nikdo
# nedodává, nebo se vleče hodnota, kterou nikdo nechce.
POVOLENE = {"self", "cls", "hass", "entry", "pridat", "user_input",
            "call", "hodnota", "sekund", "now", "event"}
for p in d.glob("*.py"):
    for f in ast.walk(ast.parse(p.read_text())):
        if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if f.name.startswith("async_step_") or f.name.startswith("__"):
            continue
        telo = ast.dump(ast.Module(body=f.body, type_ignores=[]))
        for a in f.args.args + f.args.kwonlyargs:
            if a.arg in POVOLENE or a.arg.startswith("_"):
                continue
            if f"id='{a.arg}'" not in telo:
                chyby.append(
                    f"{p.name}: {f.name}({a.arg}) se v těle nepoužívá")

# 1r) nastavení, které jde vyplnit, ale nikdo ho nečte, a naopak.
# Obojí je past: člověk něco nastaví a nic se nestane, nebo se chování
# řídí hodnotou, kterou nejde změnit.
kod_mimo_flow = "\n".join(
    x.read_text() for x in d.glob("*.py") if x.name != "config_flow.py")
# klíče, které se už nenastavují a čtou se jen kvůli převodu
PREVOD = {"CONF_NOC_UTLUM"}
UI_POLE = {"CONF_KARTA_YAML", "CONF_NAZEV_STAVU", "CONF_SEKVENCE",
           "CONF_STAVY_TEXT", "CONF_TIMEOUT", "CONF_NAZEV", "CONF_DALSI",
           "CONF_PORADI", "CONF_MISTNOSTI", "CONF_SOUSEDI",
           "CONF_ZALUZIE", "CONF_STINENI_MAPA",
           # ukládají se krokem se stavy žaluzií, ne polem ve formuláři
           "CONF_STINENI_CHOVANI"}
# Chování žaluzií se ukládá krokem, ne polem ve formuláři: klíče se
# zapisují do slovníku „chovani". Vyjmenovávat je ručně znamenalo
# doplňovat seznam při každém novém.
UI_POLE |= set(re.findall(r"chovani[^\n]*\[c\.(CONF_\w+)\]", cf_kod))
CTENO_JINAK = set(re.findall(r"(?:nej|hodnota)\(\s*(?:\w+,\s*)?(CONF_\w+)",
                             kod_mimo_flow))
ve_form = set(re.findall(r"vol\.\w+\(c\.(CONF_\w+)", cf_kod))
# Klíč se čte buď přímo přes .get(), nebo se předává jako argument
# funkci, která to udělá za nás — obojí je čtení.
cte = (set(re.findall(r"\.get\((CONF_\w+)", kod_mimo_flow))
       | set(re.findall(r"[(,]\s*(CONF_\w+),", kod_mimo_flow))
       | set(re.findall(r"[(,]\s*(CONF_\w+)\s*,\s*\"", kod_mimo_flow))
       | CTENO_JINAK)
for k in sorted(cte - ve_form):
    # „_STARE" a klíče jen pro převod ze staršího nastavení se do
    # formuláře nevracejí, čtou se kvůli zpětné slučitelnosti
    if k.endswith("_STARE") or k in UI_POLE or k in PREVOD:
        continue
    chyby.append(f"{k}: kód to čte, ale ve formuláři to nejde vyplnit")
for k in sorted(ve_form - cte - UI_POLE):
    chyby.append(f"{k}: jde to vyplnit, ale nikdo to nečte")

# 1s) tatáž hodnota nesmí mít jiné jméno v entitě a jiné ve formuláři.
# Člověk pak v dashboardu hledá něco, co v nastavení najde pod jiným
# názvem — a neví, že je to totéž.
posuvniky_klice = set(re.findall(r"Posuvnik\((CONF_\w+)",
                                 (d / "number.py").read_text()))
hodnoty_konst = dict(re.findall(r'^(CONF_\w+) = "(\w+)"',
                                (d / "const.py").read_text(), re.M))
for k in sorted(posuvniky_klice):
    klic = hodnoty_konst.get(k)
    if not klic:
        continue
    jmeno_ent = (preklady["entity"]["number"].get(klic) or {}).get("name")
    jmeno_form = preklady["config_subentries"]["mistnost"]["step"][
        "zaklad"]["data"].get(klic)
    if jmeno_ent and jmeno_form and jmeno_ent != jmeno_form:
        chyby.append(
            f"{klic}: entita se jmenuje „{jmeno_ent}“, formulář "
            f"„{jmeno_form}“ — tatáž hodnota, dvě jména")

# 1t) atribut, který senzor vystavuje nebo karta ukazuje, se musí
# někde nastavovat. Když vypadne z jádra, řádek v kartě zůstane prázdný
# a s ním tiše zmizí i to, co ten atribut hlídal.
ko_kod = (d / "coordinator.py").read_text()
nastavene_atr = set(re.findall(r'atributy\["(\w+)"\]', ko_kod))
nastavene_atr |= set(re.findall(r'"(\w+)":', ko_kod))
for soubor in ("sensor.py", "binary_sensor.py"):
    text = (d / soubor).read_text()
    for blok in re.findall(r'if k in \(([^)]*)\)', text):
        for jmeno in re.findall(r'"(\w+)"', blok):
            if jmeno not in nastavene_atr:
                chyby.append(
                    f"{soubor}: atribut {jmeno} se vystavuje, ale nikde "
                    f"se nenastavuje")

# 1u) pevná náhradní hodnota za chybějící čidlo. Po restartu čidla
# chvíli nehlásí a vymyšlené číslo se propíše do rozhodnutí — okno se
# pak zavře „kvůli chladu venku", který nikdy nebyl.
CIDLA = ("CONF_T_VENKU", "CONF_RH_VENKU", "CONF_T_VENKU_M",
         "CONF_RH_VENKU_M", "CONF_TEPLOTY", "CONF_CO2", "CONF_PM25",
         "CONF_PM10", "CONF_RH_VNITRNI")
for p in d.glob("*.py"):
    for i, radek in enumerate(p.read_text().splitlines(), 1):
        for cidlo in CIDLA:
            if re.search(rf"_cislo\(\s*\w*\.?get\({cidlo}\),\s*-?[\d.]+\)",
                         radek):
                chyby.append(
                    f"{p.name}:{i}: {cidlo} má pevnou náhradní hodnotu — "
                    f"po restartu se z ní rozhoduje")

# 1v) číslo zadrátované do rozhodování. V jádře se má rozhodovat podle
# nastavení nebo podle pojmenované konstanty — číslo uvnitř výrazu nikdo
# nenajde a nikdo neví, proč tam je.
STRUKTURA = {0, 1, 2, 24, 60, 100, 3600, 0.0, 1.0, 2.0, 100.0}
jadro = ast.parse((d / "core.py").read_text())
radky_jadra = (d / "core.py").read_text().splitlines()
videne = set()
for f in ast.walk(jadro):
    if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    for u in ast.walk(f):
        if not isinstance(u, (ast.Compare, ast.BinOp)):
            continue
        popis = ast.dump(u)
        # zajímají jen výrazy, kde vedle čísla stojí vstup, paměť
        # nebo nastavení — ostatní počty jsou vnitřní věc
        if not any(x in popis for x in ("id='v'", "id='n'", "id='p'")):
            continue
        for c in ast.walk(u):
            if (isinstance(c, ast.Constant)
                    and isinstance(c.value, (int, float))
                    and c.value not in STRUKTURA
                    and (c.lineno, c.value) not in videne):
                videne.add((c.lineno, c.value))
                chyby.append(
                    f"core.py:{c.lineno}: číslo {c.value} v rozhodování — "
                    f"patří do nastavení nebo pojmenované konstanty: "
                    f"{radky_jadra[c.lineno - 1].strip()[:50]}")

# 1w) položka paměti nebo nastavení, kterou nikdo nepoužívá. Zůstává
# po odstraněné funkci a pak se v ní nikdo nevyzná.
jadro_text = (d / "core.py").read_text()
vse_text = "\n".join(x.read_text() for x in d.glob("*.py"))
for u in ast.parse(jadro_text).body:
    if not isinstance(u, ast.ClassDef) or u.name not in ("Pamet",
                                                         "Nastaveni"):
        continue
    for pol in u.body:
        if not (isinstance(pol, ast.AnnAssign)
                and isinstance(pol.target, ast.Name)):
            continue
        jm = pol.target.id
        if len(re.findall(rf"\b{jm}\b", vse_text)) <= 1:
            chyby.append(
                f"core.py: {u.name}.{jm} nikdo nepoužívá — zbytek po "
                f"odstraněné funkci")

# 1x) konstanta, podle které se rozhoduje, musí být někde vidět.
# Nenastavitelné chování, o kterém se neví, je horší než nastavení,
# které nikdo nepoužívá.
# obě funkce s výpisem pravidel, pro byt i pro místnost
VIDITELNE = jadro_text[jadro_text.index("def pevna_pravidla_bytu"):
                       jadro_text.index("def pasmo_predpoved")]
for jm in re.findall(r"^([A-Z][A-Z_]+) = [\d.]+", jadro_text, re.M):
    if jm in ("MAGNUS_A", "MAGNUS_B"):
        continue              # vzorec, ne rozhodnutí
    if jm not in VIDITELNE:
        chyby.append(
            f"core.py: {jm} rozhoduje, ale nikde se neukazuje — "
            f"doplň ji do pevna_pravidla()")

# 1y) odkaz na nastavení nebo paměť, která v jádře neexistuje.
# Koordinátor je sestavuje za běhu, takže překladač ani testy to
# nenajdou — projeví se to až chybou při načtení integrace.
def _pole_tridy(jmeno, text=None):
    for u in ast.parse(text if text is not None else jadro_text).body:
        if isinstance(u, ast.ClassDef) and u.name == jmeno:
            return {x.target.id for x in u.body
                    if isinstance(x, ast.AnnAssign)
                    and isinstance(x.target, ast.Name)}
    return set()


# jen jednoznačná jména; „v" je běžná proměnná i jinde. Přístup přes
# třídu (Nastaveni.x) se hlídá taky — tak se do textu pravidel dostala
# zmínka o hodnotě, která už neexistovala.
TRIDY = {"nast": ("Nastaveni", _pole_tridy("Nastaveni")),
         "pamet": ("Pamet", _pole_tridy("Pamet")),
         "Nastaveni": ("Nastaveni", _pole_tridy("Nastaveni")),
         "Pamet": ("Pamet", _pole_tridy("Pamet")),
         }
# „m" je výsledek místnosti, ale jen v koordinátoru — jinde je to
# třeba výsledek regulárního výrazu.
TRIDY_KO = dict(TRIDY, m=("VysledekMistnosti",
                          _pole_tridy("VysledekMistnosti", ko_kod)))
for p in d.glob("*.py"):
    # V jádře se „nast" a „pamet" používají legitimně uvnitř funkcí,
    # ale přístup přes třídu se hlídá i tam — právě odtud se do textu
    # pravidel dostala zmínka o zrušené hodnotě.
    jen_trida = p.name == "core.py"
    text = p.read_text()
    tridy = TRIDY_KO if p.name == "coordinator.py" else TRIDY
    for u in ast.walk(ast.parse(text)):
        if not (isinstance(u, ast.Attribute)
                and isinstance(u.value, ast.Name)
                and u.value.id in tridy):
            continue
        if jen_trida and not u.value.id[:1].isupper():
            continue
        jmeno_tridy, pole = tridy[u.value.id]
        if pole and u.attr not in pole and not u.attr.startswith("_"):
            chyby.append(
                f"{p.name}:{u.lineno}: {u.value.id}.{u.attr} v {jmeno_tridy}"
                f" neexistuje — projeví se až při načtení integrace")

# 1z) překlad pole, které ve formuláři není. Zbyde po zrušeném
# nastavení a plete: člověk ho hledá na obrazovce a nenajde.
konst_hodnoty = dict(re.findall(r'^(CONF_\w+) = "(\w+)"',
                                (d / "const.py").read_text(), re.M))
ve_formulari = {konst_hodnoty[k]
                for k in re.findall(r"vol\.\w+\(c\.(CONF_\w+)", cf_kod)
                if k in konst_hodnoty}
for jazyk2 in ("cs", "en"):
    t3 = json.loads((d / "translations" / f"{jazyk2}.json").read_text())
    bloky3 = {
        "mistnost/zaklad": t3["config_subentries"]["mistnost"]["step"][
            "zaklad"]["data"],
        "mistnost/reconfigure": t3["config_subentries"]["mistnost"]["step"][
            "reconfigure"]["data"],
        "user": t3["config"]["step"]["user"]["data"],
        "nastaveni": t3["options"]["step"]["nastaveni"]["data"],
    }
    for jm3, pole3 in bloky3.items():
        for k in sorted(set(pole3) - ve_formulari):
            chyby.append(
                f"{jazyk2}/{jm3}: {k} má popisek, ale ve formuláři není")

# 1aa) hodnota, podle které se rozhoduje, musí jít nastavit, nebo být
# aspoň vidět ve výpisu pravidel. Jinak se podle ní rozhoduje a nikdo
# o ní neví — přesně to byla zadrátovaná hranice chlazení.
ve_formulari2 = {konst_hodnoty[k]
                 for k in re.findall(r"vol\.\w+\(c\.(CONF_\w+)", cf_kod)
                 if k in konst_hodnoty}
for u in ast.parse(jadro_text).body:
    if not (isinstance(u, ast.ClassDef) and u.name == "Nastaveni"):
        continue
    for pol in u.body:
        if not (isinstance(pol, ast.AnnAssign)
                and isinstance(pol.target, ast.Name)):
            continue
        jm = pol.target.id
        nastavitelne = (jm in ve_formulari2
                        or re.search(rf"\b{jm}=", ko_kod))
        if not nastavitelne and jm not in VIDITELNE:
            chyby.append(
                f"core.py: Nastaveni.{jm} rozhoduje, ale nejde nastavit "
                f"ani se neukazuje — přidej pole, nebo ho vypiš "
                f"v pevna_pravidla_bytu()")

# 1ab) přejmenovaný posuvník musí mít v kartě i své starší jméno.
# Entita si v Home Assistantu drží identifikátor, pod kterým vznikla,
# takže po přejmenování řádek z dashboardu zmizí.
import importlib.util as _iu
_spec = _iu.spec_from_file_location("_karty_k", d / "karty.py")
_k = _iu.module_from_spec(_spec)
_spec.loader.exec_module(_k)
for klic, varianty in _k.STARSI_POSUVNIKY.items():
    varianty = (varianty,) if isinstance(varianty, str) else varianty
    if klic not in {x for x, _, _ in _k.POSUVNIKY}:
        chyby.append(
            f"karty.py: starší jméno {klic} nemá protějšek mezi "
            f"posuvníky — zůstalo po smazaném nastavení")
    for v in varianty:
        if v == klic:
            chyby.append(
                f"karty.py: {klic} má jako starší jméno sám sebe")

# 1ac) čas z formuláře chodí jako „22:00:00". Kdo ho převede přímo
# na číslo, shodí načtení integrace.
CASOVE = ("CONF_NOC_OD", "CONF_NOC_DO", "CONF_PRYC_OD", "CONF_PRYC_DO")
for p in d.glob("*.py"):
    for i, radek in enumerate(p.read_text().splitlines(), 1):
        for klic in CASOVE:
            if re.search(rf"float\(\s*\w*\.?get\({klic}", radek):
                chyby.append(
                    f"{p.name}:{i}: {klic} se převádí přímo na číslo — "
                    f"použij _hodina(), formulář posílá čas jako text")

# 1ad) odkaz na konstantu cizího modulu, která tam není. Projeví se
# až při běhu, protože modul se importuje jako celek.
ALIASY = {"core": "core.py", "vy": "vykon.py", "pr": "pritomnost.py",
          "pm": "prumery.py", "sl": "slunce.py", "so": "sousedstvi.py",
          "zp": "zpravy.py"}
for p in d.glob("*.py"):
    text = p.read_text()
    for u in ast.walk(ast.parse(text)):
        if not (isinstance(u, ast.Attribute)
                and isinstance(u.value, ast.Name)
                and u.value.id in ALIASY
                and u.attr.isupper()):
            continue
        cizi = (d / ALIASY[u.value.id]).read_text()
        if not re.search(rf"^{u.attr}\s*[:=]", cizi, re.M):
            chyby.append(
                f"{p.name}:{u.lineno}: {u.value.id}.{u.attr} v "
                f"{ALIASY[u.value.id]} neexistuje")

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
    "nastaveni": pole("SCHEMA_GLOBAL", "class NaPohoduConfigFlow"),
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
        # Tatáž pole se zobrazují dvakrát: při zakládání a v Nastavit.
        # Když se doplní jen jedno, druhá obrazovka ukáže holé klíče.
        "nastaveni": t["options"]["step"]["nastaveni"],
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


# 1o) číselné pole bez jednotky dostane stupně Celsia, protože to je
# výchozí hodnota pomocníka. U počtů a časů je to nesmysl.
# celá slova, ne části: „min" v cil_min znamená minimum, ne minuty
NENI_TEPLOTA = {"poradi", "minut", "hodin", "procent", "pocet", "co2",
                "cas", "krat", "dni", "azimut", "plocha", "pm25", "pm10"}
for m in re.finditer(
        r"vol\.\w+\(c\.(CONF_\w+)[^)]*\)\s*:\s*\n?\s*_cislo\(([^)]*)\)",
        cf_kod):
    klic, argumenty = m.group(1), m.group(2)
    if '"' in argumenty or "'" in argumenty:
        continue                       # jednotka uvedená, v pořádku
    jmeno = hodnoty.get(klic, klic).lower()
    if set(jmeno.split("_")) & NENI_TEPLOTA:
        chyby.append(
            f"{klic}: číselné pole bez jednotky dostane °C, "
            f"ale podle jména to teplota není")


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
