import importlib.util, sys, itertools, collections
S="/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/rev_r1/"
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); sys.modules[name]=m; spec.loader.exec_module(m); return m
r0 = load("s0", S+"score_old_r1.py"); r1 = load("s1", S+"score_r1.py")
cur = load("s2", "/Users/twokrai/Project_code/Inspector_bottles/scripts/nav_bench/score.py")
items = ["a.py:5","b.py:7","a.py","b.py","dir/c.py:9-12","a.py:5,6"]
seps = [", ", "; ", " ", "\n", " and ", ", and ", " / ", " | ", ",", ";", " + ", " & "]
exps = [("a.py",5),("a.py",6),("b.py",7),("dir/c.py",10),("a.py",None),("b.py",None)]
res=collections.defaultdict(list)
for n in (2,3):
    for combo in itertools.product(items, repeat=n):
        for sep in seps:
            t = sep.join(combo)
            for p,l in exps:
                e={"path":p,"line":l}
                h0=r0.location_matches(t,e); h1=r1.location_matches(t,e); hc=cur.location_matches(t,e)
                if h1 and not hc: res["r1hit_curmiss"].append((t,p,l))
                if hc and not h1: res["curhit_r1miss"].append((t,p,l))
                if h0 and not hc: res["r0hit_curmiss"].append((t,p,l))
for k,v in res.items():
    print(k, len(v))
    seen=set()
    for t,p,l in v:
        if t in seen: continue
        seen.add(t)
        if len(seen)<=12: print("   ", repr(t), "exp", (p,l), "r1", r1.parse_claims(t), "cur", cur.parse_claims(t))
