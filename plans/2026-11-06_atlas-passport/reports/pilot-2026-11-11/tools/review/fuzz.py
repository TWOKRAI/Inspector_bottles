import importlib.util, sys, random, itertools
S="/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/rev_r1/"
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); sys.modules[name]=m; spec.loader.exec_module(m); return m
old = load("score_old_r1", S+"score_old_r1.py")
new = load("score_new_r1", "/Users/twokrai/Project_code/Inspector_bottles/scripts/nav_bench/score.py")
paths = ["a.py","dir/a.py","./a.py","C:\\x\\a.py","`a.py`","my dir/a b.py","файл.py","a.py "]
specs = ["5","5-9","5–9","9-5","5:3","5-9:3","5,6","5,9-12","5, 6","5-9, 12","5,6,7,8","5-","5,","5;","5.","5)","5 (f)","5 and 9","5 6","5-9,12:3","5 - 9","5,\n6", "5:3,6","0","5,5"]
pre = ["", "see ", "(", "- ", "• ", "file: ", "`", "*"]
suf = ["", ".", ")", ",", ";", " (func)", "`", "**"]
exp = lambda line: {"path":"a.py" if "a.py" in "" else None}
reg=[]; imp=[]
import collections
cats=collections.Counter()
for p,s,a,b in itertools.product(paths, specs, pre, suf):
    t = f"{a}{p}:{s}{b}"
    path_norm = old.normalize_path(p)
    # expected entries: a.py at line 5/6/7/9/12, plus the normalized path of this p
    for line in (5,7,9,12,30):
        for ep in {"a.py", path_norm, "dir/a.py", "my dir/a b.py", "C:/x/a.py", "файл.py"}:
            e={"path":ep,"line":line}
            o=old.location_matches(t,e); n=new.location_matches(t,e)
            if o and not n: reg.append((t,ep,line))
            if n and not o: imp.append((t,ep,line))
print("old-hit-new-miss:", len(reg), " new-hit-old-miss:", len(imp))
seen=set()
for t,ep,line in reg:
    k=t
    if k in seen: continue
    seen.add(k); print("REG", repr(t), "path",ep,"line",line, "old",old.parse_location_range(t),"new",new.parse_claims(t))
    if len(seen)>25: break
