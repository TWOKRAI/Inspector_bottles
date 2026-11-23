import importlib.util, sys, json, glob, subprocess, collections
S="/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/rev_r1/"
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); sys.modules[name]=m; spec.loader.exec_module(m); return m
v0 = load("s0", S+"score_old_r1.py")
v1 = load("s1", S+"score_r1.py")
v2 = load("s2", "/Users/twokrai/Project_code/Inspector_bottles/scripts/nav_bench/score.py")
def classify_global(question, answer, prefixes):
    expected = question.get("expected") or []
    if not expected: return "n/a"
    if answer is None: return "miss"
    cap = len(expected)+1
    claims = v2.merge_claims([c for loc in answer["locations"] for c in v2.parse_claims(loc, prefixes)])
    over = len(claims) > cap
    covered = [any(v2._claim_matches(c,e) for c in claims) for e in expected]
    need_all = question.get("require","any")=="all"
    if (all(covered) if need_all else any(covered)) and not over: return "hit"
    stray = over or any(not any(v2._claim_matches(c,e) for e in expected) for c in claims)
    return "false" if answer["confidence"]=="sure" and stray else "miss"
files = sorted(glob.glob("plans/2026-11-06_atlas-passport/reports/1.2-records/*.json")+glob.glob("plans/2026-11-06_atlas-passport/reports/pilot-2026-11-11/records/*.json"))
tot=collections.Counter(); garbage=[]; unp=[]
trees={}
for f in files:
    rec=json.load(open(f,encoding="utf-8"))
    sha=rec["repo_sha"]
    if sha not in trees:
        trees[sha]=set(subprocess.run(["git","ls-tree","-r","--name-only",sha],capture_output=True,text=True).stdout.split("\n"))
    tree=trees[sha]
    prefixes=tuple(rec.get("prefixes") or ())
    name=f.split("/")[-1]
    for ri,rep in enumerate(rec["repeats"],1):
        answers=v2.parse_answers(rep["final_text"])
        for q in rec["questions"]:
            a=answers.get(v2._key(q["id"]))
            st=next((r["verdict"] for r in rep["score"]["per_question"] if r["id"]==q["id"]),None)
            vs=[st, v0.classify(q,v0.parse_answers(rep["final_text"]).get(v0._key(q["id"])),prefixes), v1.classify(q,v1.parse_answers(rep["final_text"]).get(v1._key(q["id"])),prefixes), v2.classify(q,a,prefixes), classify_global(q,a,prefixes)]
            tot["answers"]+=1
            if vs[1]!=vs[3]: tot["v0!=cur"]+=1
            if vs[2]!=vs[3]: tot["r1!=cur"]+=1; print("R1->CUR", name, f"r{ri}", q["id"], vs[2], "->", vs[3])
            if vs[3]!=vs[4]: tot["cur!=global"]+=1; print("CUR->GLOBAL", name, f"r{ri}", q["id"], vs[3], "->", vs[4], a and a["locations"])
            if vs[0]!=vs[1]: tot["stored!=rescore_old"]+=1
            if a:
                for loc in a["locations"]:
                    cl=v2.parse_claims(loc,prefixes)
                    for c in cl:
                        p=c[0]
                        if p not in tree and (c[1] is not None or True):
                            garbage.append((name,f"r{ri}",q["id"],loc,p))
                    if v2.unparsed(loc): unp.append((name,f"r{ri}",q["id"],loc,v2.unparsed(loc)))
print(dict(tot))
print("claims with path not in tree at repo_sha:", len(garbage))
seen=set()
for g in garbage:
    if g[3] in seen: continue
    seen.add(g[3]); print("  GARBAGE", g)
print("addresses with unparsed digits tail:", len(unp))
for u in unp[:20]: print("  UNP", u)
