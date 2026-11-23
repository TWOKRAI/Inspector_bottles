import json, sys, re, subprocess, ast
sys.path.insert(0, "/Users/twokrai/Project_code/Inspector_bottles")
from scripts.nav_bench import score
REC = "/Users/twokrai/Project_code/Inspector_bottles/plans/2026-11-06_atlas-passport/reports/pilot-2026-11-11/records/2026-11-11_fw2-pilot_%s.json"
SRC = "/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/atlas-src"
arms = [("A","grep-read-pilot"),("B","atlas-pilot"),("C","atlas-first-pilot"),("D","shell-pilot")]
Q = json.load(open(REC % "grep-read-pilot"))["questions"]
# body spans of expected symbols
spans = {}
for q in Q:
    for e in q["expected"]:
        src = subprocess.run(["git","-C",SRC,"show",f"1e085652f:{e['path']}"],capture_output=True,text=True).stdout
        t = ast.parse(src); end = None
        for n in ast.walk(t):
            if hasattr(n,"lineno") and n.lineno == e["line"] and isinstance(n,(ast.FunctionDef,ast.ClassDef,ast.AsyncFunctionDef,ast.Assign,ast.AnnAssign)):
                end = n.end_lineno; break
        spans[(e["path"],e["line"])] = (e["line"], end or e["line"])
def ranges(loc, pref):
    raw = loc.strip().strip("`'\"")
    m = re.match(r"^(.+?\.py):(.*)$", raw)
    if not m: return score.normalize_path(raw, pref), []
    out = []
    for part in m.group(2).split(","):
        g = re.match(r"\s*(\d+)(?:\s*[-–]\s*(\d+))?", part)
        if g: a = int(g.group(1)); b = int(g.group(2) or a); out.append((min(a,b), max(a,b)))
    return score.normalize_path(m.group(1), pref), out
for a, n in arms:
    d = json.load(open(REC % n)); pref = tuple(d.get("prefixes") or ())
    res = []
    for rep in d["repeats"]:
        strict = lenient = body = 0
        for q in d["questions"]:
            locs = next((r["locations"] for r in rep["score"]["per_question"] if str(r["id"]) == str(q["id"])), [])
            for e in q["expected"]:
                s = any(score.location_matches(l, e, prefixes=pref) for l in locs)
                L = B = False
                for l in locs:
                    p, rs = ranges(l, pref)
                    if p != e["path"]: continue
                    for x, y in rs:
                        if x <= e["line"] + 3 and y >= e["line"] - 3: L = True
                        bs, be = spans[(e["path"], e["line"])]
                        if x <= be and y >= bs - 3: B = True
                strict += s; lenient += L; body += (L or B)
        res.append((strict, lenient, body))
    print(a, "strict/multi-range/+inside-body:", res)
print("span SystemBuilder.build:", spans[("multiprocess_prototype/backend/launch.py",623)], " system_shutdown:", spans[("backend_ctl/driver.py",680)], " TOOLS:", spans[("backend_ctl/mcp_tools.py",545)])
