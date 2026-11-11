"""п.7 дополнение: классификация каталогов с .py по отношению к юнитам."""
import ast, sys, json
from pathlib import Path
from collections import Counter
SRC = Path("/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/atlas-src")
sys.path.insert(0, str(SRC))
from scripts.atlas import passport as P
pilot = ast.parse((SRC / "pilot_atlas.py").read_text())
for node in pilot.body:
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        if node.targets[0].id == "SHA": SHA = ast.literal_eval(node.value)
        if node.targets[0].id == "EXCLUDE": EXCLUDE = ast.literal_eval(node.value)
ctx = P._Ctx.open(SRC, SHA, tuple(EXCLUDE), with_links=False)
units = ctx.rows()
print("units", len(units))
unit_dirs = {u["paths"][0]: u["id"] for u in units if u["paths"][0].endswith("/")}
all_paths = [(u["id"], p) for u in units for p in u["paths"] if p.endswith("/")]
files = sorted(ctx.facts)
direct = Counter(f.rsplit("/", 1)[0] + "/" if "/" in f else "./" for f in files)
rec = Counter()
for f in files:
    parts = f.split("/")
    for i in range(1, len(parts)):
        rec["/".join(parts[:i]) + "/"] += 1
print("каталогов с прямыми .py:", len(direct), "; с .py на любой глубине (без корня):", len(rec))
def longest(d):
    best = None
    for p, uid in [(p, uid) for uid, p in [(i, q) for i, q in all_paths]]:
        if d.startswith(p) and (best is None or len(p) > len(best[0])):
            best = (p, uid)
    return best
exact_p0 = {d for d in direct if d in unit_dirs}
exact_any = {d for d in direct if any(d == p for _, p in all_paths)}
inside = {d for d in direct if d not in exact_any and longest(d)}
none = {d for d in direct if not longest(d)}
print("каталоги с прямыми .py: ровно paths[0] юнита:", len(exact_p0), "; ровно любой dir-элемент paths:", len(exact_any), "; внутри юнита (глубже):", len(inside), "; вне юнитов:", len(none))
print("число .py в каталогах 'вне юнитов':", sum(direct[d] for d in none))
# сколько каталогов каждого вида «дают» юнит, если сопоставлять по самому длинному префиксу
print("none (все):")
for d in sorted(none): print("  ", d, direct[d])
# каталоги выше юнитов (содержат юниты): 
above = {d for d in rec if any(p.startswith(d) for p in unit_dirs) and d not in unit_dirs}
print("каталоги-предки юнитов (map <предок> -> несколько юнитов):", len(above), sorted(above)[:12])
# сколько юнитов под предком multiprocess_framework/
for d in ("multiprocess_framework/", "multiprocess_framework/modules/", "Services/", "Plugins/", "multiprocess_prototype/", "scripts/"):
    print(d, "юнитов внутри:", sum(1 for p in unit_dirs if p.startswith(d)))
# вложенные юниты: p0 внутри p0
nested = [(a, b) for a, pa in unit_dirs.items() for b, pb in unit_dirs.items() if a != b and pa.startswith(pb) and pa != pb]
nest_units = {a for a, _ in nested}
print("юнитов, вложенных в другой юнит:", len(nest_units), "пар:", len(nested))
print("внешние юниты, внутри которых есть другие:", len({b for _, b in nested}))
print("вложенные юниты, id:", sorted(nest_units))
print("unit passport path == paths[0]:", all(ctx.map(u["id"])["path"] == u["paths"][0] for u in units))
# прямое попадание map для директорий unit_dirs после предлагаемого правила "каталог -> юнит с paths[0]==каталог": однозначно ли?
c = Counter(p for _, p in all_paths)
print("dir-элементов paths, повторяющихся у разных юнитов:", [p for p, n in c.items() if n > 1])
# модули в modules:, у которых paths[0] — каталог, но id не совпадает с последним сегментом пути
print("пример id->p0 (15):")
for u in units[:3] + units[-12:]:
    print("  ", u["id"], "->", u["paths"][0], "| purpose:", (u.get("purpose") or "")[:50])
