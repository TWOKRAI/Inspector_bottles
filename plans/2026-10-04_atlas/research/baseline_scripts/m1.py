# ruff: noqa: E501, E731, E741 — замерочный скрипт Task 0.6, логику не трогаем, чтобы числа baseline.md воспроизводились
import ast
import subprocess
import re
import os

R = "D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.claude/worktrees/atlas"
os.chdir(R)


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


mods = sorted(
    set(
        l.split("/")[2]
        for l in git("ls-files", "multiprocess_framework/modules").splitlines()
        if l.count("/") >= 3 and l.split("/")[2] != "tests" and not l.split("/")[2].endswith(".py")
    )
)
rows = []
ta = tc = 0
for m in mods:
    p = f"multiprocess_framework/modules/{m}/interfaces.py"
    src = git("show", f"HEAD:{p}")
    if not src:
        rows.append((m, None, None, []))
        continue
    try:
        tree = ast.parse(src)
    except Exception:
        rows.append((m, "ERR", 0, []))
        continue
    names = None
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "__all__" for t in n.targets):
            try:
                names = list(ast.literal_eval(n.value))
            except Exception:
                names = None
        if isinstance(n, ast.AugAssign) and getattr(n.target, "id", None) == "__all__":
            try:
                names = (names or []) + list(ast.literal_eval(n.value))
            except Exception:
                pass
    if names is None:
        rows.append((m, "no __all__", 0, []))
        continue
    td = f"multiprocess_framework/modules/{m}/tests"
    files = [f for f in git("ls-files", td).splitlines() if f.endswith(".py")]
    blob = "\n".join(git("show", f"HEAD:{f}") for f in files)
    cov = [n for n in names if re.search(r"(?<![A-Za-z0-9_])" + re.escape(n) + r"(?![A-Za-z0-9_])", blob)]
    rows.append((m, len(names), len(cov), [n for n in names if n not in cov]))
    ta += len(names)
    tc += len(cov)
print("| модуль | имён в __all__ | упомянуто в tests/ | доля |")
for m, a, c, miss in rows:
    if isinstance(a, int):
        print(f"| {m} | {a} | {c} | {100 * c // a if a else 0}% |")
    else:
        print(f"| {m} | {a} | - | - |")
print("TOTAL", ta, tc, round(100 * tc / ta, 1) if ta else 0)
