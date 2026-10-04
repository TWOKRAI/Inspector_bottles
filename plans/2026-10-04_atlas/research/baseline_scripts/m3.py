import subprocess
import re
import os

os.chdir("D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.claude/worktrees/atlas")
out = subprocess.run(
    ["git", "log", "main", "--no-merges", "--since=2026-08-05", "--format=%x01%h|%ad|%s%x02%b", "--date=short"],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
).stdout
a = re.compile(r"находк|дефект|сломал|врал[а-я]*\b|вскры|выявил|не предсказ|нашёл|нашел", re.I)
b = re.compile(r"стенд|живь|живой|живого|живом", re.I)
rows = []
for ch in out.split("\x01")[1:]:
    head, _, body = ch.partition("\x02")
    h, d, s = head.split("|", 2)
    if a.search(s) and b.search(s):
        rows.append((d, h, s[:150]))
print(len(rows))
for r in sorted(rows):
    print(*r, sep=" | ")
