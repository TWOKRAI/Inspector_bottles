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
print("units", len(rows))
print("non-dir p0:", [(r["id"], r["paths"][0], len(r["paths"])) for r in rows if not r["paths"][0].endswith("/")])
for t in ("multiprocess_framework","multiprocess_framework/modules","Services","Plugins","multiprocess_prototype","scripts","tools","docs"):
    hit = [r["id"] for r in rows if r["paths"][0].startswith(t + "/")]
    exact = [r["id"] for r in rows if r["paths"][0] in (t, t + "/")]
    print(t, "prefix-count", len(hit), "exact-p0", exact, "id-is-unit", any(r["id"]==t for r in rows))
# ids that equal some other unit's directory (id-vs-dir collision)
d = {r["paths"][0].rstrip("/"): r["id"] for r in rows}
print("id==dir-of-other:", [(r["id"], d[r["id"]]) for r in rows if r["id"] in d and d[r["id"]] != r["id"]])
# map of nested ancestor: directories strictly between
import collections
print("p0 all:", collections.Counter(len(r["paths"]) for r in rows).most_common(4))
