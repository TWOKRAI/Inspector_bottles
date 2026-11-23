import ast, re, sys, time
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
t = time.perf_counter(); blobs = ctx.tree.read_many(sorted(ctx.facts)); print("read_many", round(time.perf_counter() - t, 2), "s", len(blobs), "files")
for name in ("ick", "stat", "get", "name", "__init__", "is_valid_window"):
    leaf = name.encode()
    t = time.perf_counter(); sub = [p for p, b in blobs.items() if b and leaf in b]; t_sub = time.perf_counter() - t
    rx = re.compile(rb"\b" + re.escape(leaf) + rb"\b")
    t = time.perf_counter(); wb = [p for p, b in blobs.items() if b and rx.search(b)]; t_rx = time.perf_counter() - t
    t = time.perf_counter()
    for p in wb:
        try: P._body_bindings(ast.parse(blobs[p].decode("utf-8").removeprefix("﻿")).body)
        except Exception: pass
    t_parse = time.perf_counter() - t
    print(f"{name:16s} подстрока {len(sub):5d} ({t_sub:.2f} с) | граница слова {len(wb):5d} ({t_rx:.2f} с) | parse+bindings по ним {t_parse:.2f} с")
