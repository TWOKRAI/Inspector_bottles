"""Замер скорости `card`/`ref` для приёмки Task 1.6g: один протокол для базы и для ветки.

Запуск из корня репозитория: `python plans/2026-10-04_atlas/reports/1.6g.bench.py card|ref [--runs N] [--max-first S]`.
Прогон протокола: `build` (реестр в кэше) -> кэш видов `view_cache` очищен, каталог `data/atlas/checkout` удалён ->
первый вызов (FIRST) -> три следующих модуля той же ревизии (SECOND), каждый в новом процессе. По N прогонам
печатаются медиана FIRST и медиана медиан SECOND; медиана FIRST больше `--max-first` -> exit 1.
На базе без выгрузки на диске удалять нечего — протокол тот же.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import statistics
import subprocess  # nosec B404 — замер запускает только CLI Атласа этого репозитория
import sys
import time
from pathlib import Path

FIRST = "config_module"
SECOND = ("logger_module", "worker_module", "command_module")


def _run(root: Path, *argv: str) -> float:
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONUTF8="1")
    start = time.perf_counter()
    cmd = [sys.executable, "-m", "scripts.atlas", *argv]
    proc = subprocess.run(cmd, cwd=root, env=env, capture_output=True)  # nosec B603
    took = time.perf_counter() - start
    if proc.returncode != 0 or proc.stderr:
        sys.exit(f"{' '.join(argv)}: rc={proc.returncode} stderr={proc.stderr.decode('utf-8', 'replace')[-300:]}")
    return took


def _protocol(root: Path, view: str) -> tuple[float, float]:
    """Один прогон протокола: (FIRST, медиана SECOND)."""
    _run(root, "build")
    con = sqlite3.connect(root / "data" / "atlas.sqlite")
    con.execute("DELETE FROM view_cache")
    con.commit()
    con.close()
    shutil.rmtree(root / "data" / "atlas" / "checkout", ignore_errors=True)
    first = _run(root, view, FIRST)
    seconds = [_run(root, view, module) for module in SECOND]
    print(f"{view} run: first {first:.2f} s; second {', '.join(f'{s:.2f}' for s in seconds)} s", flush=True)
    return first, statistics.median(seconds)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("view", choices=["card", "ref"])
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--max-first", type=float, default=None)
    args = parser.parse_args()
    root = Path.cwd()
    runs = [_protocol(root, args.view) for _ in range(args.runs)]
    first = statistics.median(r[0] for r in runs)
    second = statistics.median(r[1] for r in runs)
    print(f"{args.view} first median: {first:.2f} s (runs={args.runs})")
    print(f"{args.view} second-module median: {second:.2f} s (runs={args.runs})")
    if args.max_first is not None and first > args.max_first:
        print(f"{args.view} first median {first:.2f} s > {args.max_first:.2f} s")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
