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
}
for jazyk in ("cs", "en"):
    t = json.loads((d / "translations" / f"{jazyk}.json").read_text())
    mapa = {
        "user": t["config"]["step"]["user"],
        "zaklad": t["config_subentries"]["mistnost"]["step"]["zaklad"],
        "pritomnost": t["config_subentries"]["mistnost"]["step"]["pritomnost"],
        "indicie": t["config_subentries"]["mistnost"]["step"]["indicie"],
        "zona": t["config_subentries"]["zona"]["step"]["user"],
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
