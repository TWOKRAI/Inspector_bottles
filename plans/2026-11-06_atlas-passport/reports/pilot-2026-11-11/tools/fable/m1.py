import sys, json
sys.path.insert(0, "scripts/nav_bench")
import score
E3 = [{"path": "a.py", "line": n} for n in (100, 300, 500)]
Q3 = {"id": "Q", "expected": E3, "require": "all"}
Q1 = {"id": "Q", "expected": [{"path": "a.py", "line": 100}], "require": "all"}
def run(q, locs, conf="sure"):
    return score.classify(q, {"id": "Q", "answer": "", "locations": locs, "confidence": conf})
cases = [
 ("1 wide range, 3 expected", Q3, ["a.py:1-100000"]),
 ("2 precise list of 5 lines, 3 right", Q3, ["a.py:100", "a.py:300", "a.py:500", "a.py:700", "a.py:900"]),
 ("2b same content as one range", Q3, ["a.py:100-900"]),
 ("3 chain of adjacent ranges in 3 strings", Q3, ["a.py:98-102", "a.py:103-299", "a.py:300-503"]),
 ("4 right def + 2 call sites, 1 expected", Q1, ["a.py:100", "b.py:7", "c.py:9"]),
 ("4b right def only", Q1, ["a.py:100"]),
 ("5 'and' between claims", Q3, ["a.py:98-102 and a.py:300-301 and a.py:500"]),
 ("6 bare comma between paths", {"id":"Q","expected":[{"path":"a.py","line":5},{"path":"b.py","line":7}],"require":"all"}, ["a.py:5,b.py:7"]),
 ("7a #L form", Q1, ["a.py#L100"]),
 ("7b :L form", Q1, ["a.py:L100"]),
 ("7c (line N)", Q1, ["a.py (line 100)"]),
 ("7d em dash range", Q1, ["a.py:90—110"]),
 ("7e 'lines 98-102'", Q1, ["a.py lines 98-102"]),
 ("8 abs path no prefix", Q1, ["/tmp/copy/a.py:100"]),
]
for name, q, locs in cases:
    claims = score.merge_claims([c for l in locs for c in score.parse_claims(l)])
    print(f"{name:42} -> {run(q, locs):5} | claims={claims} | unparsed={[score.unparsed(l) for l in locs]}")
