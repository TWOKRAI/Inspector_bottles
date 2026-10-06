"""Приёмка T1 «политика памяти GUI-процесса» прогонами (A4 спеки task-T1.md; не pytest).

Каждый прогон — отдельный подпроцесс ``python -X faulthandler -m pytest -q -p no:cacheprovider …``
с cwd ``multiprocess_framework/modules``. Падением считается код возврата вне {0, 1} или
``Fatal Python error`` / ``Windows fatal exception`` в выводе; таймаут — тоже падение.

Использование (из корня дерева):

    python scripts/gc_policy_acceptance.py chain -n 20
    python scripts/gc_policy_acceptance.py chain -n 20 --offscreen
    python scripts/gc_policy_acceptance.py gate -n 5 --root C:/lcb   # база на другом дереве
    python scripts/gc_policy_acceptance.py gate -n 3 --pytest-arg=--ignore=frontend_module/tests

Печать: строка на прогон и итог
``SUMMARY <имя> crashes=X/N failed=Y gc_violations=Z platform=… wall_median_s=…``.
"""

from __future__ import annotations

import argparse
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

MODULES = Path("multiprocess_framework") / "modules"

_CHAIN = [
    "frontend_module/tests/test_base_tree_nav_tab.py",
    "frontend_module/tests/test_qt_event_bridge.py",
    "event_module/tests/test_subscribers.py::test_release_from_gc_finalizer_under_publisher_lock_no_deadlock",
]

SETS: dict[str, list[str]] = {
    "chain": _CHAIN,
    "reverse": ["frontend_module/tests", "event_module/tests"],
    "four": _CHAIN[:2] + ["frontend_module/tests/test_qt_lifetime.py::test_concurrent_attach_from_four_threads"],
    "gate": [],  # testpaths из modules/pytest.ini — то же, что scripts/run_framework_tests.py
}

_CRASH_MARKERS = ("Fatal Python error", "Windows fatal exception")
_SUMMARY_RE = re.compile(r"(\d+) (failed|errors?)\b")
_VIOLATIONS_RE = re.compile(r"enabled_violations=(\d+)")


def _run_once(root: Path, targets: list[str], timeout_s: int, env: dict[str, str]) -> dict:
    cmd = [sys.executable, "-X", "faulthandler", "-m", "pytest", "-q", "-rfE", "-p", "no:cacheprovider", *targets]
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=root / MODULES,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
        out = proc.stdout + proc.stderr
        code: int | None = proc.returncode
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        code = None
    wall = time.perf_counter() - started

    crashed = code is None or code not in (0, 1) or any(m in out for m in _CRASH_MARKERS)
    failed = sum(int(n) for n, _ in _SUMMARY_RE.findall(out.splitlines()[-1] if out.strip() else ""))
    violations = [int(v) for v in _VIOLATIONS_RE.findall(out)]
    tail = out.strip().splitlines()[-1] if out.strip() else "<нет вывода>"
    bad = [ln for ln in out.splitlines() if ln.startswith(("FAILED ", "ERROR ", "gc-policy:"))]
    return {
        "code": code,
        "crashed": crashed,
        "failed": failed,
        "violations": violations[-1] if violations else None,
        "wall": wall,
        "tail": tail,
        "bad": bad,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", choices=sorted(SETS))
    parser.add_argument("-n", type=int, default=1, help="число прогонов")
    parser.add_argument("--offscreen", action="store_true", help="QT_QPA_PLATFORM=offscreen")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="корень дерева (по умолчанию cwd)")
    parser.add_argument("--timeout", type=int, default=None, help="секунд на прогон (гейт 900, прочее 300)")
    parser.add_argument(
        "--pytest-arg", action="append", default=[], help="доп. аргумент pytest (повторяемый), напр. --ignore=…"
    )
    args = parser.parse_args()

    root = args.root.resolve()
    timeout_s = args.timeout or (900 if args.name == "gate" else 300)
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONUTF8="1")
    if args.offscreen:
        env["QT_QPA_PLATFORM"] = "offscreen"
    else:
        env.pop("QT_QPA_PLATFORM", None)
    platform = env.get("QT_QPA_PLATFORM", "native")

    results = []
    for i in range(1, args.n + 1):
        r = _run_once(root, [*args.pytest_arg, *SETS[args.name]], timeout_s, env)
        results.append(r)
        print(
            f"run {i}/{args.n}: code={r['code']} crashed={r['crashed']} failed={r['failed']} "
            f"gc_violations={r['violations']} wall_s={r['wall']:.1f} | {r['tail']}",
            flush=True,
        )
        for line in r["bad"]:
            print(f"    {line}", flush=True)

    crashes = sum(r["crashed"] for r in results)
    failed = sum(r["failed"] for r in results)
    known = [r["violations"] for r in results if r["violations"] is not None]
    violations = sum(known) if known else "n/a"
    wall_median = statistics.median(r["wall"] for r in results)
    print(
        f"SUMMARY {args.name} crashes={crashes}/{args.n} failed={failed} gc_violations={violations} "
        f"platform={platform} wall_median_s={wall_median:.1f} root={root}"
    )
    return 0 if crashes == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
