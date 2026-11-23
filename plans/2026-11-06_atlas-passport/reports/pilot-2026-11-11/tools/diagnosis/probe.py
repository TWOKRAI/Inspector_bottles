import json, sys, subprocess, shlex
sys.path.insert(0, "/Users/twokrai/Project_code/Inspector_bottles")
from scripts.nav_bench import bench, score
SRC = "/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/atlas-src"
Q = json.load(open("/Users/twokrai/Project_code/Inspector_bottles/scripts/nav_bench/questions/fw2.pilot.json"))
exp = {q["id"]: q["expected"] for q in Q["questions"]}
P = json.load(open(sys.argv[1]))
for qid, tiers in P.items():
    for tier, cmds in tiers.items():
        got = set()
        for c in cmds:
            r = subprocess.run(["python", "pilot_atlas.py", *shlex.split(c)], cwd=SRC, capture_output=True, text=True)
            addrs = bench.text_addresses(r.stdout)
            d = [f"{e['symbol']}@{e['line']}" for e in exp[qid] if any(ln is not None and score.location_matches(f"{p}:{ln}", e) for p, ln in addrs)]
            got |= set(d)
            errs = r.stderr.strip().replace("\n", " | ")
            print(f"{qid} {tier} [{c}] exit={r.returncode} lines={r.stdout.count(chr(10))} err={errs[:90]!r} -> {d}")
        print(f"== {qid} {tier}: {len(got)}/{len(exp[qid])} {sorted(got)}")
