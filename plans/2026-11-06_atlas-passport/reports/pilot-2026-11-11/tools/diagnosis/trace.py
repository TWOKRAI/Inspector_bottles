import json, sys, re
REC = "/Users/twokrai/Project_code/Inspector_bottles/plans/2026-11-06_atlas-passport/reports/pilot-2026-11-11/records/2026-11-11_fw2-pilot_%s.json"
arm = sys.argv[1]
d = json.load(open(REC % arm))
pref = d['prefixes']
SP = "/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/atlas-src/"
def short(s):
    s = str(s)
    for p in pref: s = s.replace(p + "/", "").replace(p, "<ROOT>")
    s = s.replace("python " + SP + "pilot_atlas.py", "ATLAS").replace(SP, "<SP>/")
    return s
reps = [int(x) for x in sys.argv[2:]] or range(len(d['repeats']))
for i in reps:
    r = d['repeats'][i]
    print(f"=== {arm} repeat {i+1}: calls={r['tool_calls']} turns={r['turns']} err={r['error']} subtype={r['subtype']}")
    for j, u in enumerate(r['tool_uses']):
        extra = ""
        if 'pattern' in u and u['pattern'] != u['target']: extra += f" pat={u['pattern']!r}"
        if 'glob' in u: extra += f" glob={u['glob']!r}"
        den = " DENIED/ERR" if u.get('denied') else ""
        print(f"{j:3d} {u['name']:5s} {short(u['target'])[:220]}{extra}{den}")
