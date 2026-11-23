import json, sys
sys.path.insert(0, "/Users/twokrai/Project_code/Inspector_bottles")
from scripts.nav_bench import score
REC = "/Users/twokrai/Project_code/Inspector_bottles/plans/2026-11-06_atlas-passport/reports/pilot-2026-11-11/records/2026-11-11_fw2-pilot_%s.json"
arms = [("A","grep-read-pilot"),("B","atlas-pilot"),("C","atlas-first-pilot"),("D","shell-pilot")]
data = {a: json.load(open(REC % n)) for a, n in arms}
q = data["A"]["questions"]
tot = {a: [0,0,0] for a,_ in arms}
for qq in q:
    qid = qq["id"]
    for e in qq["expected"]:
        cells = []
        for a, _ in arms:
            d = data[a]
            pref = tuple(d.get("prefixes") or ())
            for i, rep in enumerate(d["repeats"]):
                locs = next((r["locations"] for r in rep["score"]["per_question"] if str(r["id"]) == qid), [])
                ok = any(score.location_matches(l, e, prefixes=pref) for l in locs)
                if ok:
                    cells.append("+"); tot[a][i] += 1
                else:
                    # nearest location in same file
                    same = []
                    for l in locs:
                        p, _, ln = l.rpartition(":")
                        for pr in pref:
                            if p.startswith(pr): p = p[len(pr):].lstrip("/")
                        if p == e["path"] and ln.isdigit(): same.append(int(ln))
                    if same:
                        dl = min(same, key=lambda x: abs(x - e["line"]))
                        cells.append(f"{dl-e['line']:+d}")
                    else:
                        cells.append("-")
        print(f"{qid:3s} {e['symbol'][:38]:38s} {e['line']:4d} | " + " | ".join(" ".join(f"{c:>4s}" for c in cells[k*3:k*3+3]) for k in range(4)))
print("totals", tot)
