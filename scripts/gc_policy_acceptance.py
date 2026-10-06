"""Приёмка T1 «политика памяти GUI-процесса» прогонами (A4 спеки task-T1.md; не pytest).

Каждый прогон — отдельный подпроцесс ``python -X faulthandler -m pytest -q -rfE -p no:cacheprovider …``
с cwd ``multiprocess_framework/modules``. Падением считается код возврата вне {0, 1} или
``Fatal Python error`` / ``Windows fatal exception`` в выводе; таймаут — тоже падение.

Из строки ``gc-policy:`` сводки сессии (печатает ``modules/conftest.py``) берутся числа политики:
``collections`` (0 — политика не работала), ``enabled_violations``, ``foreign_collections``,
``max_pause_ms``, ``total_pause_ms``; доля пауз = ``total_pause / (wall − total_pause)`` — критерий D3
арбитража CTO 2026-10-06 (``docs/reviews/2026-10-06_task-T1-review-r1-and-cto-arbitration.md``).

Использование (из корня дерева):

    python scripts/gc_policy_acceptance.py chain -n 20
    python scripts/gc_policy_acceptance.py chain -n 20 --offscreen
    python scripts/gc_policy_acceptance.py gate -n 3 --save-dir C:/tmpa4/gate   # полный вывод каждого прогона
    python scripts/gc_policy_acceptance.py process -n 3 --root C:/lcb            # контроль на базе (не-Qt набор)
    python scripts/gc_policy_acceptance.py gate -n 1 --pytest-arg=--ignore=frontend_module/tests

Печать: строка на прогон и итог
``SUMMARY <имя> crashes=X/N failed=Y gc_violations=Z pause_share_max=… max_pause_ms_max=… platform=… wall_median_s=…``.
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
    # Контроль D3: не-Qt наборы, где база 92fd0450f не аварийна — отношение HEAD / база по стенным часам.
    "process": ["process_module/tests"],
    "router": ["router_module/tests"],
    "state": ["state_store_module/tests"],
}

_CRASH_MARKERS = ("Fatal Python error", "Windows fatal exception")
_SUMMARY_RE = re.compile(r"(\d+) (failed|errors?)\b")
_POLICY_RE = re.compile(r"^gc-policy:.*$", re.M)
_FIELD_RE = re.compile(r"(\w+)=([\d.]+)")


def _policy_numbers(out: str) -> dict[str, float]:
    """Последняя строка ``gc-policy:`` сводки сессии → {поле: число}; нет строки — {}."""
    lines = _POLICY_RE.findall(out)
    return {k: float(v) for k, v in _FIELD_RE.findall(lines[-1])} if lines else {}


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
    policy = _policy_numbers(out)
    pause_ms = policy.get("total_pause_ms")
    share = (
        pause_ms / 1000.0 / (wall - pause_ms / 1000.0) if pause_ms is not None and wall > pause_ms / 1000.0 else None
    )
    tail = out.strip().splitlines()[-1] if out.strip() else "<нет вывода>"
    bad = [ln for ln in out.splitlines() if ln.startswith(("FAILED ", "ERROR ", "gc-policy:"))]
    return {
        "code": code,
        "crashed": crashed,
        "failed": failed,
        "policy": policy,
        "share": share,
        "wall": wall,
        "tail": tail,
        "bad": bad,
        "out": out,
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
    parser.add_argument("--save-dir", type=Path, default=None, help="куда класть полный вывод каждого прогона")
    args = parser.parse_args()

    root = args.root.resolve()
    timeout_s = args.timeout or (900 if args.name == "gate" else 300)
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONUTF8="1")
    if args.offscreen:
        env["QT_QPA_PLATFORM"] = "offscreen"
    else:
        env.pop("QT_QPA_PLATFORM", None)
    platform = env.get("QT_QPA_PLATFORM", "native")
    if args.save_dir:
        args.save_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for i in range(1, args.n + 1):
        r = _run_once(root, [*args.pytest_arg, *SETS[args.name]], timeout_s, env)
        results.append(r)
        if args.save_dir:
            (args.save_dir / f"{args.name}-{platform}-{i}.txt").write_text(r["out"], encoding="utf-8")
        p = r["policy"]
        share = f"{r['share']:.3f}" if r["share"] is not None else "n/a"
        print(
            f"run {i}/{args.n}: code={r['code']} crashed={r['crashed']} failed={r['failed']} "
            f"collections={p.get('collections', 'n/a')} gc_violations={p.get('enabled_violations', 'n/a')} "
            f"foreign={p.get('foreign_collections', 'n/a')} max_pause_ms={p.get('max_pause_ms', 'n/a')} "
            f"pause_share={share} wall_s={r['wall']:.1f} | {r['tail']}",
            flush=True,
        )
        for line in r["bad"]:
            print(f"    {line}", flush=True)

    crashes = sum(r["crashed"] for r in results)
    failed = sum(r["failed"] for r in results)
    known = [r["policy"]["enabled_violations"] for r in results if "enabled_violations" in r["policy"]]
    violations = int(sum(known)) if known else "n/a"
    idle = [r for r in results if r["policy"] and r["policy"].get("collections", 0) == 0]
    shares = [r["share"] for r in results if r["share"] is not None]
    pauses = [r["policy"]["max_pause_ms"] for r in results if "max_pause_ms" in r["policy"]]
    wall_median = statistics.median(r["wall"] for r in results)
    share_max = f"{max(shares):.3f}" if shares else "n/a"
    pause_max = max(pauses) if pauses else "n/a"
    print(
        f"SUMMARY {args.name} crashes={crashes}/{args.n} failed={failed} gc_violations={violations} "
        f"policy_idle_runs={len(idle)} pause_share_max={share_max} max_pause_ms_max={pause_max} "
        f"platform={platform} wall_median_s={wall_median:.1f} root={root}"
    )
    return 0 if crashes == 0 and not idle else 1


if __name__ == "__main__":
    raise SystemExit(main())
