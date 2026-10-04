# ruff: noqa: E501, E731, E741 — замерочный скрипт Task 0.6, логику не трогаем, чтобы числа baseline.md воспроизводились
import subprocess
import re
import os

os.chdir("D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.claude/worktrees/atlas")


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


tests = re.compile(r"(^|/)tests?/|(^|/)test_[^/]+\.py$")


def modroot(f):
    p = f.split("/")
    if p[0] == "multiprocess_framework" and p[1] == "modules":
        return "/".join(p[:3])
    return "/".join(p[:-1])


def surf(first, sha, files):
    out = []
    for f in files:
        if f.endswith("/interfaces.py"):
            out.append(f)
        elif re.match(r"^multiprocess_framework/modules/[^/]+/__init__\.py$", f):
            d = git("diff", "-U0", first, sha, "--", f)
            if re.search(r"__all__|^[+-]\s+[\"']\w+[\"'],", d, re.M):
                out.append(f)
    return out


# B: first-parent range, same-module tests
fp = git("log", "--first-parent", "main", "--since=60.days", "--format=%H %P").splitlines()
tot = 0
bad = []
for l in fp:
    s = l.split()
    sha = s[0]
    if len(s) < 2:
        continue
    files = git("diff", "--name-only", s[1], sha).splitlines()
    sf = surf(s[1], sha, files)
    if not sf:
        continue
    tot += 1
    miss = [
        f
        for f in sf
        if not any(
            tests.search(t) and modroot(t) == modroot(f) or (tests.search(t) and t.startswith(modroot(f) + "/"))
            for t in files
        )
    ]
    if miss:
        bad.append((sha[:9], miss))
print("B same-module, first-parent: total", tot, "bad", len(bad))
for b in bad:
    print(" ", b)
# C: individual non-merge commits on main in 60 days
al = git("log", "main", "--no-merges", "--since=60.days", "--format=%H %P").splitlines()
tot = 0
bad = []
for l in al:
    s = l.split()
    sha = s[0]
    if len(s) < 2:
        continue
    files = git("diff", "--name-only", s[1], sha).splitlines()
    sf = surf(s[1], sha, files)
    if not sf:
        continue
    tot += 1
    miss = [f for f in sf if not any(tests.search(t) and t.startswith(modroot(f) + "/") for t in files)]
    if miss:
        bad.append((sha[:9], miss))
print("C same-module, non-merge commits: all", len(al), "surface", tot, "bad", len(bad))
for b in bad:
    print(" ", b)
