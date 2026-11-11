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
e=[p for p,f in ctx.facts.items() if f.error is not None]; v=[p for p,f in ctx.facts.items() if f.v2_error is not None]
print("error", len(e), e[:3]); print("v2_error", len(v), v[:3])
import re
bad=0
for p in list(ctx.facts)[:]:
    b=ctx.tree.read_many([p])[p]
    if b and re.search(rb"coding[:=]\s*(?!utf-?8)", b[:200]): bad+=1; print("cookie", p)
print("non-utf8 cookie files", bad)
