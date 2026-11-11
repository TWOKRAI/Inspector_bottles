import ast, sys, difflib
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
pool = sorted({d.qualname.rsplit(".",1)[-1] for f in ctx.facts.values() for d in f.defs})
print("pool", len(pool))
def top(word, pool, n=5):
    out=[]
    for x in pool:
        s=difflib.SequenceMatcher(); s.set_seq2(word); s.set_seq1(x)
        if s.real_quick_ratio()>=0.6 and s.quick_ratio()>=0.6:
            r=s.ratio()
            if r>=0.6: out.append((r,x))
    out.sort(key=lambda t:(-t[0],t[1]))
    return out[:n]
for w in ("is_valid_window","RecipeBlueprint","Backenddriver"):
    print(w, [(round(r,3),x) for r,x in top(w,pool)])
    print("  stdlib:", difflib.get_close_matches(w,pool,n=5,cutoff=0.6))
# F-file scoped
for q in ("Driver","Driver.stop","Driver.run"):
    print("Drivr vs",q, round(difflib.SequenceMatcher(None,"Drivr",q).ratio(),3), round(difflib.SequenceMatcher(None,q,"Drivr").ratio(),3))
print("Driverr vs Driver", round(difflib.SequenceMatcher(None,"Driverr","Driver").ratio(),3))
