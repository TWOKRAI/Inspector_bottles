import json, glob, re, sys, statistics
sys.path.insert(0, "scripts/nav_bench")
import score
ARM = {"grep-read-pilot": "A", "atlas-pilot": "B", "atlas-first-pilot": "C", "shell-pilot": "D"}
SEARCH = re.compile(r"\b(grep|rg|find|ls|tree|wc)\b")
def rel(t, prefixes):
    for p in prefixes:
        p = p.rstrip("/") + "/"
        i = t.find(p)
        if i >= 0:
            return t[i + len(p):]
    m = re.search(r"/nav_bench/[0-9a-f]{40}-[0-9a-f]+/(.*)", t)
    return m.group(1) if m else t
def match1(claims, exps):
    owner = {}
    def tryc(e, seen):
        for ci, c in enumerate(claims):
            if ci in seen or not score._claim_matches(c, exps[e]): continue
            seen.add(ci)
            if ci not in owner or tryc(owner[ci], seen):
                owner[ci] = e; return True
        return False
    return sum(tryc(e, set()) for e in range(len(exps)))
rows = []
for p in sorted(glob.glob("plans/2026-11-06_atlas-passport/reports/pilot-2026-11-11/records/*.json")):
    d = json.load(open(p)); arm = ARM[d["condition"]]; pref = tuple(d["prefixes"])
    exp_files = {score.normalize_path(e["path"]) for q in d["questions"] for e in q["expected"]}
    for r in d["repeats"]:
        ans = score.parse_answers(r["final_text"])
        any_n = one_n = wide = 0
        for q in d["questions"]:
            a = ans.get(score._key(q["id"])); locs = a["locations"] if a else []
            raw = [c for l in locs for c in score.parse_claims(l, pref)]
            for e in q["expected"]:
                ms = [c for c in raw if score._claim_matches(c, e)]
                if ms:
                    any_n += 1
                    if min(c[2] - c[1] + 1 for c in ms) > 10: wide += 1
            one_n += match1(raw, q["expected"])
        cat = {"read_exp": 0, "read_other": 0, "search": 0, "atlas": 0, "other": 0}
        first = {}
        for i, u in enumerate(r["tool_uses"], 1):
            t = u.get("target") or ""; n = u["name"]
            if n == "Read":
                f = rel(t, pref)
                if f in exp_files: cat["read_exp"] += 1; first.setdefault(f, i)
                else: cat["read_other"] += 1
            elif n in ("Grep", "Glob"): cat["search"] += 1
            elif n == "Bash":
                if "pilot_atlas.py" in t: cat["atlas"] += 1
                elif SEARCH.search(t):
                    cat["search"] += 1
                else:
                    hit = [f for f in exp_files if f in t]
                    if hit:
                        cat["read_exp"] += 1
                        for f in hit: first.setdefault(f, i)
                    else: cat["other"] += 1
            else: cat["other"] += 1
        n = len(r["tool_uses"]); fi = sorted(first.values())
        rows.append((arm, r["index"], any_n, one_n, wide, n, cat, len(first), len(exp_files), fi[0] if fi else None, statistics.median(fi) if fi else None, fi[-1] if fi else None, r["cache_read_tokens"], r["final_context_tokens"]))
print("arm r | any one2one wide>10 | calls | read_exp read_other search atlas other | exp_files_read/of | first/median/last first-read idx | cache_read ctx")
for x in sorted(rows):
    c = x[6]
    print(f"{x[0]} {x[1]} | {x[2]:3} {x[3]:3} {x[4]:3} | {x[5]:3} | {c['read_exp']:3} {c['read_other']:3} {c['search']:3} {c['atlas']:3} {c['other']:3} | {x[7]}/{x[8]} | {x[9]}/{x[10]}/{x[11]} | {x[12]/1e6:.1f}M {x[13]//1000}k")
tot = {k: sum(x[6][k] for x in rows) for k in rows[0][6]}; N = sum(x[5] for x in rows)
print("TOTAL", N, {k: f"{v} ({100*v/N:.0f}%)" for k, v in tot.items()})
