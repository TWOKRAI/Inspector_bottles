import json, difflib
from collections import defaultdict
rows = json.load(open("defs.json"))["rows"]
by = defaultdict(list)
for r in rows: by[r["qualname"].rsplit(".", 1)[-1]].append(r)
def isdef(r): return r["kind"] in ("function","nested_function","class","method")
for n in ("ProcessConfig","system_shutdown","as_generic_config","park","is_valid_window","RecipeBlueprint"):
    print(n, [(r["scope"], r["path"].split("/")[-1], r["qualname"], r["kind"]) for r in by.get(n, [])][:8])
names = sorted(by)
for n in ("is_valid_window","RecipeBlueprint"):
    print(n, "difflib:", difflib.get_close_matches(n, names, n=5, cutoff=0.6))
    print("  подстрока:", [x for x in names if n.lower().replace("is_","") in x.lower()][:8])
# R4 breakdown
def ids(rs): return {(r["path"], r["qualname"]) for r in rs}
