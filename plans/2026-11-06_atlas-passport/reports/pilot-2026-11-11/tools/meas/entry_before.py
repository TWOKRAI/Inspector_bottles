"""Прогон строк «до правки» из 4.7a/4.7b-cases на фикстуре F (текущий код, без правок). Запуск: python entry_before.py rows.txt"""
import shlex
import subprocess
import sys

F = "/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/meas/F"
REPO = "/Users/twokrai/Project_code/Inspector_bottles"
for r in (ln.rstrip("\n") for ln in open(sys.argv[1], encoding="utf-8") if ln.strip()):
    argv = shlex.split(r)
    cmd = [sys.executable, "-m", "scripts.atlas", *argv, "--root", F]
    if argv[0] == "ref" and "--format" not in argv:
        cmd += ["--format", "passport"]
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    out = p.stdout.splitlines()
    if argv[0] == "ref" and "json" not in r:
        keep = [x for x in out if x.startswith("== ") or x in ("not found", "ambiguous") or (x and x[0] != " " and "::" in x and "sha" not in x)]
        keep += [x for x in out if x.startswith(("ещё", "пример"))]
    else:
        keep = out[:8]
    print("###", r, "-> exit", p.returncode)
    print("  stdout:", keep[:14])
    print("  stderr:", p.stderr.strip().splitlines()[:3])
