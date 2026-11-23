import importlib.util, sys, time
S="/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/rev_r1/"
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); sys.modules[name]=m; spec.loader.exec_module(m); return m
old = load("score_old_r1", S+"score_old_r1.py")
new = load("score_new_r1", "/Users/twokrai/Project_code/Inspector_bottles/scripts/nav_bench/score.py")
cases = {
 "list distinct ~100KB": "a.py:" + ",".join(str(i) for i in range(18000)),
 "list distinct ranges": "a.py:" + ",".join(f"{i}-{i+1}" for i in range(9000)),
 "list same 100KB": "a.py:" + ",".join("5" for _ in range(50000)),
 "colons+digits 100KB": ":1" * 50000,
 "digits 4000": "a.py:" + "1" * 4000,
 "path-with-colons 100KB": "a:" * 50000 + "1",
 "x: lazy 100KB": "a" * 100000 + ":",
 "a.py:1- x14000": "a.py:1-" * 14000,
 "a.py:1, x12000": "a.py:1, " * 12000,
 "a.py:1,1- x11000": "a.py:1,1-" * 11000,
 ":1, x33000": ":1,"*33000,
 "a.py:1,.. then x": "a.py:" + "1,"*50000 + "x",
 "a.py:1-1-1-..": "a.py:" + ("1-"*50000),
 "newline list 12000": "\n".join("a.py:%d"%i for i in range(12000)),
}
for label, text in cases.items():
    for tag, fn in (("old", lambda t: old.parse_location_range(t)), ("new", lambda t: new.parse_claims(t))):
        t0 = time.perf_counter(); r = fn(text); dt = time.perf_counter() - t0
        n = len(r) if isinstance(r, list) else 1
        print(f"{label!r:30} len={len(text):7} {tag}: {dt*1000:9.1f} ms claims={n}", flush=True)
