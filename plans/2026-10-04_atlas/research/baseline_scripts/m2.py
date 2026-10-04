# ruff: noqa: E501, E731, E741 — замерочный скрипт Task 0.6, логику не трогаем, чтобы числа baseline.md воспроизводились
import subprocess
import re
import os

R = "D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.claude/worktrees/atlas"
os.chdir(R)


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


base = "main"
log = git("log", "--first-parent", base, "--since=60.days", "--format=%H %ad %P|%s", "--date=short").splitlines()
print("first-parent commits:", len(log), "newest", log[0][:60], "oldest", log[-1][:60])
iface = re.compile(r"^multiprocess_framework/modules/[^/]+/(interfaces\.py|__init__\.py)$")
tests = re.compile(r"(^|/)tests?/|(^|/)test_[^/]+\.py$")
hits = []
for l in log:
    head, subj = l.split("|", 1)
    sha, date, *par = head.split()
    first = par[0] if par else None
    if not first:
        continue
    files = git("diff", "--name-only", f"{first}", sha).splitlines()
    # all-surface files: interfaces.py any module (incl. Services/Plugins?) restrict to framework modules + also any interfaces.py
    sf = [f for f in files if iface.match(f) or f.endswith("/interfaces.py") or f == "interfaces.py"]
    # __init__ counts only if __all__ line changed
    real = []
    for f in sf:
        if f.endswith("__init__.py"):
            d = git("diff", "-U0", first, sha, "--", f)
            if not re.search(r"^[+-].*(__all__|^\+\s+\"|^-\s+\")", d, re.M):
                continue
            if not re.search(r"__all__|^[+-]\s+[\"']\w+[\"'],", d, re.M):
                continue
        real.append(f)
    if not real:
        continue
    t = [f for f in files if tests.search(f)]
    hits.append((sha[:9], date, subj[:70], len(real), len(t)))
n = len(hits)
bad = [h for h in hits if h[4] == 0]
print("touching surface:", n, "without tests:", len(bad))
for h in hits:
    print(("NOTEST " if h[4] == 0 else "ok     "), *h)
