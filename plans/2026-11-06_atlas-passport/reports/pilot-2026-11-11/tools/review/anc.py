import ast, sys
SRC = "/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/atlas-src"
sys.path.insert(0, SRC)
from pathlib import Path
from scripts.atlas import passport as P
src = ast.parse(Path(SRC, "pilot_atlas.py").read_text())
for n in src.body:
    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
        if n.targets[0].id == "SHA": SHA = ast.literal_eval(n.value)
        if n.targets[0].id == "EXCLUDE": EXCLUDE = ast.literal_eval(n.value)
ctx = P._Ctx.open(Path(SRC), SHA, tuple(EXCLUDE), with_links=False)
rows = ctx.rows()
def step(t):
    ids = {r["id"] for r in rows}
    if t in ids: return ("unit-by-id", t)
    if t.endswith(".py") and t in ctx.facts: return ("file", t)
    m = sorted(r["id"] for r in rows if r["paths"][0] in (t, t + "/"))
    if m: return ("unit-by-p0", m[0], len(m))
    if t == ".": return ("list-all", len(rows))
    a = [r["id"] for r in rows if r["paths"][0].endswith("/") and r["paths"][0].startswith(t + "/")]
    if a: return ("list-anc", len(a))
    return ("not found",)
for t in ("multiprocess_framework","multiprocess_framework/modules","Services","Plugins","multiprocess_prototype","scripts","backend_ctl","Services/line_sim","multiprocess_framework/__init__.py","multiprocess_prototype/ARCHITECTURE.md","framework_meta","multiprocess_framework/modules/app_module","multiprocess_framework/modules/app_module/core","."):
    print(t, step(t))
# nested: dirs that are ancestor of nested units but not a unit p0 and sit INSIDE a unit
inside=[r["paths"][0] for r in rows if r["paths"][0].endswith("/")]
# Dir between: e.g. multiprocess_prototype/frontend
for t in ("multiprocess_prototype/frontend","multiprocess_prototype/frontend/widgets","multiprocess_framework/modules/frontend_module/widgets"):
    print(t, step(t))
