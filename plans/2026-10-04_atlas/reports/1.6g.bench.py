"""Замер скорости `card`/`ref` для приёмки Task 1.6g: один протокол для базы и для ветки.

Запуск из корня репозитория: `python plans/2026-10-04_atlas/reports/1.6g.bench.py card|ref`.
Протокол: `build` (реестр в кэше) -> кэш видов `view_cache` очищен, каталог `data/atlas/checkout` удалён ->
первый вызов (FIRST) -> три следующих модуля той же ревизии (SECOND), каждый в новом процессе; медиана SECOND.
На базе без выгрузки на диске удалять нечего — протокол тот же.
"""

from __future__ import annotations

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
    proc = subprocess.run([sys.executable, "-m", "scripts.atlas", *argv], cwd=root, env=env, capture_output=True)  # nosec B603
    took = time.perf_counter() - start
    if proc.returncode != 0 or proc.stderr:
        sys.exit(f"{' '.join(argv)}: rc={proc.returncode} stderr={proc.stderr.decode('utf-8', 'replace')[-300:]}")
    return took


def main() -> None:
    view = sys.argv[1]
    root = Path.cwd()
    _run(root, "build")
    con = sqlite3.connect(root / "data" / "atlas.sqlite")
    con.execute("DELETE FROM view_cache")
    con.commit()
    con.close()
    shutil.rmtree(root / "data" / "atlas" / "checkout", ignore_errors=True)
    first = _run(root, view, FIRST)
    seconds = [_run(root, view, module) for module in SECOND]
    print(f"{view} first {FIRST}: {first:.2f} s")
    print(f"{view} second-module runs: {', '.join(f'{s:.2f}' for s in seconds)} s")
    print(f"{view} second-module median: {statistics.median(seconds):.2f} s (n={len(seconds)})")


if __name__ == "__main__":
    main()
