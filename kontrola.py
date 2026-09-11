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

    # 4) klíče výběrů musí být bez diakritiky
    def projdi(x, cesta=""):
        if isinstance(x, dict):
            for k, v in x.items():
                if (cesta.startswith("selector.") and cesta.count(".") >= 2
                        and not re.fullmatch(r"[a-z0-9_-]+", k)):
                    chyby.append(f"{jazyk}: vadný klíč {cesta}.{k}")
                projdi(v, f"{cesta}.{k}" if cesta else k)

    projdi(t)

if chyby:
    print("NALEZENO:")
    for c in sorted(set(chyby)):
        print("  ", c)
    sys.exit(1)
print("balíček je celistvý")
