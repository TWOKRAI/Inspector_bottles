"""пп. 6 (детерминизм резолва), 7 (map/юниты), 8 (12 вызовов пилота) + кросс-проверка эмуляции R0 против ctx.resolve."""

import ast
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

SRC = Path("/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/atlas-src")
H = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
from scripts.atlas import passport as P  # noqa: E402
from scripts.atlas.tree import AtlasError  # noqa: E402

pilot = ast.parse((SRC / "pilot_atlas.py").read_text())
for node in pilot.body:
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        if node.targets[0].id == "SHA":
            SHA = ast.literal_eval(node.value)
        if node.targets[0].id == "EXCLUDE":
            EXCLUDE = ast.literal_eval(node.value)

ctx = P._Ctx.open(SRC, SHA, tuple(EXCLUDE), with_links=False)
rows = json.loads((H / "defs.json").read_text())["rows"]
by_last = defaultdict(list)
for r in rows:
    by_last[r["qualname"].rsplit(".", 1)[-1]].append(r)


def isdef(r):
    return r["kind"] in ("function", "nested_function", "class", "method")


def exact_defs(name):
    return sorted({r["path"] for r in by_last.get(name, []) if isdef(r) and r["qualname"] == name})


# ---------- кросс-проверка эмуляции R0 против живого resolve
random.seed(1)
sample = random.sample(sorted(by_last), 400) + ["run", "main", "build", "__init__", "ProcessConfig", "park", "name", "get"]
bad = 0
for n in sample:
    live = sorted(x.split("::")[0] for x in ctx.resolve(n))
    if live != exact_defs(n):
        bad += 1
        print("MISMATCH", n, live[:3], exact_defs(n)[:3])
print("кросс-проверка R0: выборка", len(sample), "расхождений", bad)

# ---------- п.8: цели вызовов пилота
calls = [
    ("C3", "map", ["multiprocess_framework"]),
    ("D1.1", "ref", ["ProcessConfig", "TopologySession", "LayoutController", "RecipesPresenter", "BackendDriver"]),
    ("D1.2", "ref", ["as_generic_config", "system_shutdown"]),
    ("D1.3", "map", ["multiprocess_framework/modules/process_manager_module/topology/blueprint.py"]),
    ("D1.4", "map", ["multiprocess_framework/modules/app_module"]),
    ("D1.5", "ref", ["SystemBlueprint"]),
    ("D2.1", "map", ["."]),
    ("D2.2", "ref", ["BackendDriver", "ProcessConfig", "TopologySession", "LayoutController"]),
    ("D2.3", "ref", ["is_valid_window", "ProcessConfig", "RecipeBlueprint"]),
    ("D2.4", "ref", ["_same_config_value"]),
    ("D2.5", "ref", ["BackendDriver", "system_shutdown", "park"]),
    ("D3.1", "map", ["."]),
]
# приоритет: R1 тиры + прод-правило
def cls(r):
    d = "." in r["qualname"]
    return ("def_tail" if d else "def_exact") if isdef(r) else ("bind_tail" if d else "bind_exact")


def r1(name):
    rs = by_last.get(name, [])
    g = defaultdict(list)
    for r in rs:
        g[cls(r)].append(r)
    for tier in (g["def_exact"], g["bind_exact"], g["def_tail"] + g["bind_tail"]):
        if tier:
            tier_name = "exact-def" if tier is g["def_exact"] else "exact-binding" if tier is g["bind_exact"] else "tail"
            prod = [r for r in tier if r["scope"] == "prod"]
            cand = tier
            via = ""
            if prod and len(prod) < len(tier) and len({(r["path"], r["qualname"]) for r in prod}) == 1:
                cand, via = prod, "+prod-rule"
            ids = sorted({(r["path"], r["qualname"]) for r in cand})
            return tier_name + via, ids
    return "none", []


print("\n== п.8 цели 12 вызовов ==")
fail_today = 0
n_targets = 0
for cid, kind, targets in calls:
    for t in targets:
        n_targets += 1
        if kind == "ref":
            live = ctx.resolve(t)
            today = "ok" if len(live) == 1 else ("not found" if not live else f"ambiguous({len(live)})")
            tier, ids = r1(t)
            new = "not found" if not ids else ("ok" if len(ids) == 1 else f"ambiguous({len(ids)})")
            # все кандидаты плоско (R3) для справки
            flat = len({(r["path"], r["qualname"]) for r in by_last.get(t, [])})
            print(f"{cid} ref {t}: сегодня {today}; R1+prod [{tier}] -> {new}; плоско {flat}; "
                  + (ids[0][0] + "::" + ids[0][1] if len(ids) == 1 else ""))
        else:
            try:
                rec = ctx.map(t)
                today = f"ok kind={rec['kind']}"
            except AtlasError as e:
                today = f"{e}"
            print(f"{cid} map {t}: сегодня {today}")
        if today.startswith("not") or today.startswith("amb"):
            fail_today += 1
print("целей", n_targets, "ошибочных сегодня", fail_today)

# ---------- п.6: детерминизм порядка
# порядок, как сегодня печатает resolve: sorted(facts) по пути; в пределах файла одно совпадение
import hashlib
names = ["run", "main", "close", "start", "write", "process", "_run", "configure", "logger", "ProcessConfig", "build", "get", "name", "__init__"]
sig = {}
for n in names:
    sig[n] = ctx.resolve(n)
(H / f"resolve_order_{sys.argv[1] if len(sys.argv) > 1 else 'x'}.json").write_text(json.dumps(sig, ensure_ascii=False))
print("order sig", hashlib.sha1(json.dumps(sig).encode()).hexdigest())

# ---------- п.7: юниты
units = ctx.rows()
print("\n== п.7 строки реестра ==")
print("всего строк:", len(units), "юнитов(roots):", sum(1 for u in units if u.get("purpose") is not None or u["parent"] is None))
print("ключи строки:", sorted(units[0].keys()))
kindc = Counter()
tab = []
for u in units:
    p0 = u["paths"][0]
    tab.append((u["id"], p0, u["paths"], u.get("layer")))
print(Counter("dir" if u["paths"][0].endswith("/") else "file" for u in units))
res = []
for u in units:
    p0 = u["paths"][0]
    variants = {"p0": p0, "p0_no_slash": p0.rstrip("/"), "p0_backslash": p0.replace("/", "\\"), "p0_slash_end": p0 if p0.endswith("/") else p0 + "/",
                "id": u["id"]}
    r = {"uid": u["id"], "p0": p0}
    for k, v in variants.items():
        try:
            rec = ctx.map(v)
            r[k] = f"ok:{rec['kind']}" + (f":{rec['id']}" if k != "id" and rec["kind"] == "unit" else "")
        except AtlasError as e:
            r[k] = str(e)
    res.append(r)
for k in ("p0", "p0_no_slash", "p0_backslash", "p0_slash_end", "id"):
    print(k, dict(Counter(r[k].split(":")[0] + ":" + r[k].split(":")[1] if r[k].startswith("ok") else r[k] for r in res)))
(H / "units_map_probe.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
print("примеры:", res[:3])
print("юниты, чей paths[0] — файл:", [(u["id"], u["paths"]) for u in units if not u["paths"][0].endswith("/")][:5])

# вложенность: p0 одного юнита внутри p0 другого
dirs = [(u["id"], u["paths"][0]) for u in units if u["paths"][0].endswith("/")]
nested = []
for a, pa in dirs:
    for b, pb in dirs:
        if a != b and pa.startswith(pb):
            nested.append((a, pa, b, pb))
print("вложенных юнитов (paths[0] внутри paths[0] другого):", len(nested))
for x in nested[:10]:
    print("  ", x)
# все paths (не только [0]) для «каталог -> юнит»
allp = [(u["id"], p) for u in units for p in u["paths"]]
dup = Counter(p for _, p in allp)
print("paths у нескольких юнитов:", [(p, c) for p, c in dup.items() if c > 1][:5])
print("разные layer у юнитов:", Counter(u.get("layer") for u in units))

# каталоги без юнита с .py
unit_dirs = {pb for _, pb in dirs}
pydirs = Counter()
for path in ctx.facts:
    parts = path.split("/")
    for i in range(1, len(parts)):
        pydirs["/".join(parts[:i]) + "/"] += 1  # каталог содержит .py (рекурсивно)
direct = Counter(path.rsplit("/", 1)[0] + "/" if "/" in path else "./" for path in ctx.facts)  # прямые .py
def covered(d):
    return any(d.startswith(ud) for ud in unit_dirs)
nu_rec = sorted(d for d in pydirs if not covered(d))
nu_dir = sorted(d for d in direct if not covered(d))
print("каталогов (любой глубины) с .py внутри, не покрытых ни одним юнитом:", len(nu_rec))
print("из них с .py НЕПОСРЕДСТВЕННО:", len(nu_dir))
top_nu = sorted({d.split("/")[0] + "/" for d in nu_rec})
print("верхнеуровневые каталоги без юнита:", top_nu)
print("10 примеров (непосредственные, по убыванию числа .py):")
for d in sorted(nu_dir, key=lambda d: -direct[d])[:10]:
    print("  ", d, direct[d])
print("пример: корневые .py файлы не в каталоге:", [p for p in ctx.facts if "/" not in p][:5])
print("кол-во .py вне юнитов всего:", sum(1 for p in ctx.facts if not covered(p)), "из", len(ctx.facts))
(H / "units.json").write_text(json.dumps(dict(dirs=dirs, nu_rec=nu_rec, nu_dir=nu_dir), ensure_ascii=False))
