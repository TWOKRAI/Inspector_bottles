import ast, sys, re
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
blobs = ctx.tree.read_many(sorted(ctx.facts))
for w in ("ick","Driverr","get","name","__init__","LIMIT","stat"):
    b=w.encode()
    sub=sum(1 for x in blobs.values() if x and b in x)
    wb=re.compile(rb"\b"+re.escape(b)+rb"\b")
    word=sum(1 for x in blobs.values() if x and wb.search(x))
    print(f"{w:10s} substring-files={sub:5d}  word-boundary-files={word:5d}  of {len(blobs)}")
