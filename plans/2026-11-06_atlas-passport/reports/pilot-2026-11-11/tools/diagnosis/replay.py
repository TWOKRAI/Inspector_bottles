import json, sys, subprocess, re
sys.path.insert(0, "/Users/twokrai/Project_code/Inspector_bottles")
from scripts.nav_bench import bench, score
REC = "/Users/twokrai/Project_code/Inspector_bottles/plans/2026-11-06_atlas-passport/reports/pilot-2026-11-11/records/2026-11-11_fw2-pilot_%s.json"
SRC = "/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/atlas-src"
for arm in sys.argv[1:]:
    d = json.load(open(REC % arm))
    exp = [(q["id"], e) for q in d["questions"] for e in q["expected"]]
    for i, r in enumerate(d["repeats"]):
        for j, u in enumerate(r["tool_uses"]):
            t = str(u.get("target"))
            if u["name"] != "Bash" or "pilot_atlas" not in t: continue
            seen = subprocess.run(["bash", "-c", t], cwd=SRC, capture_output=True, text=True)
            seen_txt = seen.stdout + seen.stderr
            # full (strip pipes and redirections)
            base = re.split(r"\s*(\|| 2>)", t)[0]
            full = subprocess.run(["bash", "-c", base], cwd=SRC, capture_output=True, text=True)
            full_txt = full.stdout
            def deliv(txt):
                out = []
                for qid, e in exp:
                    for p, ln in bench.text_addresses(txt):
                        if ln is not None and score.location_matches(f"{p}:{ln}", e):
                            out.append(f"{qid}:{e['symbol']}"); break
                return out
            short = t.replace("python " + SRC + "/pilot_atlas.py", "ATLAS")
            print(f"[{arm[:11]} r{i+1} #{j}] {short}")
            print(f"   exit(full)={full.returncode} full_lines={full_txt.count(chr(10))} seen_lines={seen_txt.count(chr(10))} stderr={full.stderr.strip()[:120]!r}")
            print(f"   delivered(seen)={deliv(seen_txt)}")
            print(f"   delivered(full)={deliv(full_txt)}")
