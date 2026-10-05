# ruff: noqa: E501, E731, E741 — замерочный скрипт Task 0.6, логику не трогаем, чтобы числа baseline.md воспроизводились
import subprocess
import re
import os
import glob
import json
import collections

os.chdir("D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.claude/worktrees/atlas")
files = glob.glob("docs/claude/memory/*.md") + glob.glob("docs/claude/memory/_archive/*.md")


def cdate(f):
    o = subprocess.run(
        ["git", "log", "--follow", "--diff-filter=A", "--format=%ad", "--date=short", "--", f],
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.split()
    return o[-1] if o else None


info = {}
for f in files:
    b = os.path.basename(f)
    if b in ("MEMORY.md", "ARCHIVE.md", "INDEX.md") or b.startswith("CRAFT"):
        continue
    t = open(f, encoding="utf-8", errors="replace").read()
    if not re.search(r"^\s*type:\s*feedback", t, re.M) and not b.startswith("feedback_"):
        continue
    info[b] = {"path": f, "date": cdate(f), "text": t, "arch": "_archive" in f}
print("feedback lessons:", len(info), "archived:", sum(v["arch"] for v in info.values()))
dc = collections.Counter(v["date"] for v in info.values())
print("top creation dates:", dc.most_common(6))
new = {k: v for k, v in info.items() if v["date"] and "2026-08-05" <= v["date"] <= "2026-10-04"}
print(
    "new (2026-08-05..2026-10-04):",
    len(new),
    "dates<08-05:",
    sum(1 for v in info.values() if v["date"] and v["date"] < "2026-08-05"),
)
# merges
pairs = []
for k, v in info.items():
    if v["arch"]:
        continue
    for m in re.finditer(r"^## Слито из (\S+)", v["text"], re.M):
        a = m.group(1) + ".md"
        pairs.append((a, k))
print("merge pairs:", len(pairs))
absorbed_new = [(a, s) for a, s in pairs if a in new]
into_older = [
    (a, s, new[a]["date"], info[s]["date"])
    for a, s in absorbed_new
    if s in info and info[s]["date"] and info[s]["date"] < new[a]["date"]
]
same_or_newer = [
    (a, s, new[a]["date"], info[s]["date"])
    for a, s in absorbed_new
    if s in info and not (info[s]["date"] < new[a]["date"])
]
print(
    "new absorbed:",
    len(absorbed_new),
    "into strictly older survivor:",
    len(into_older),
    "into same-day/newer:",
    len(same_or_newer),
)
for r in into_older:
    print("OLDER", r)
for r in same_or_newer:
    print("SAMEorNEWER", r)
# survivors that are new and absorbed older ones
print("pairs where survivor new:", sum(1 for a, s in pairs if s in new))
# phrase scan
rx = re.compile(
    r"(повторил[аось]*|повторени[ея]|повторяется|снова|уже было|ещё раз|второй раз|в третий раз|та же ошибка|тот же дефект|тот же урок)",
    re.I,
)
rep = []
for k, v in new.items():
    body = v["text"].split("---", 2)[-1]
    hits = [l.strip()[:200] for l in body.splitlines() if rx.search(l) and not l.startswith("## Слито")]
    if hits:
        rep.append((k, v["date"], hits[:2]))
print("phrase-hit new lessons:", len(rep))
for r in rep:
    print(r)
json.dump({"new": sorted(new)}, open("m8_new.json", "w"))
print("-----later-created")
later = collections.OrderedDict()
for a, s in pairs:
    if a not in info or s not in info:
        continue
    da, ds = info[a]["date"], info[s]["date"]
    if da == ds:
        continue
    L, E = (a, s) if da > ds else (s, a)
    if L in new:
        later.setdefault(L, []).append(E)
print("later-created new lessons with an earlier sibling:", len(later))
for L, E in later.items():
    print("PAIR", L, "->", ", ".join(E), info[L]["date"])
same = [(a, s) for a, s in pairs if a in info and s in info and info[a]["date"] == info[s]["date"]]
print("same-day pairs (ambiguous):", len(same))
