import ast, sys, time
SRC = "/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/atlas-src"
sys.path.insert(0, SRC)
from pathlib import Path
from scripts.atlas import passport as P
src = ast.parse(Path(SRC, "pilot_atlas.py").read_text())
for n in src.body:
    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
        if n.targets[0].id == "SHA": SHA = ast.literal_eval(n.value)
        if n.targets[0].id == "EXCLUDE": EXCLUDE = ast.literal_eval(n.value)
t=time.perf_counter(); ctx = P._Ctx.open(Path(SRC), SHA, tuple(EXCLUDE), with_links=True); print("open(with_links)", round(time.perf_counter()-t,2))
t=time.perf_counter(); ctx2 = P._Ctx.open(Path(SRC), SHA, tuple(EXCLUDE), with_links=False); print("open(no links)", round(time.perf_counter()-t,2))
t=time.perf_counter(); names=set()
paths = sorted(ctx2.facts)
blobs = ctx2.tree.read_many(paths)
print("read_many", round(time.perf_counter()-t,2), len(blobs))
t=time.perf_counter(); ok=0
for p,b in blobs.items():
    try:
        m = ast.parse(b.decode("utf-8").removeprefix("﻿")); ok+=1
        P._body_bindings(m.body)
    except Exception: pass
print("pure ast.parse of blobs (no per-file git) + module bindings", round(time.perf_counter()-t,2), ok)
