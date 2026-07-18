# -*- coding: utf-8 -*-
"""Live headless-приёмка TelemetrySinkPlugin (Task 3.2 плана telemetry-db-sink).

Поднимает топологию `telemetry_sink.yaml` БЕЗ GUI (camera_0 + telemetry_sink),
даёт стоку отработать несколько окон семпла и проверяет, что в реальной БД
`data/telemetry.db` появились строки `telemetry_snapshots` через настоящий
процесс telemetry_sink + SQLManager (а не in-memory unit-стаб).

Это аналог database live-proof (318/258 строк в `detections`): доказывает, что
вертикальный срез subscribe→sample-worker→SQLite собирается и пишет в проде.

Запуск:
    python -m backend_ctl.probes.telemetry_sink_proof
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

# Топология и БД (пути относительно корня проекта = cwd запуска).
_TOPOLOGY = "multiprocess_prototype/backend/topology/telemetry_sink.yaml"
_DB_PATH = Path("data/telemetry.db")
# sample_interval_sec в топологии = 5.0 → ждём ~3 окна, чтобы строки точно записались.
_SETTLE_SEC = 17.0


def _count_rows(db: Path) -> tuple[int, dict[str, int]]:
    """Вернуть (всего строк, {process_name: число строк}) из telemetry_snapshots."""
    con = sqlite3.connect(str(db))
    try:
        total = con.execute("SELECT COUNT(*) FROM telemetry_snapshots").fetchone()[0]
        by_proc = dict(
            con.execute("SELECT process_name, COUNT(*) FROM telemetry_snapshots GROUP BY process_name").fetchall()
        )
    finally:
        con.close()
    return total, by_proc


def main() -> int:
    from multiprocess_prototype.main import bootstrap

    # Свежий старт: удаляем прошлую БД, чтобы считать ровно строки этого прогона.
    if _DB_PATH.exists():
        _DB_PATH.unlink()
        print(f"[proof] удалил прошлую БД {_DB_PATH}")

    print(f"[proof] поднимаю топологию headless: {_TOPOLOGY}")
    launcher = bootstrap(_TOPOLOGY)
    launcher.start()
    if not launcher.wait_until_ready(timeout=30.0):
        print("[proof] FAIL: система не готова за 30с")
        launcher.shutdown()
        return 1
    print(f"[proof] система готова, даю стоку отработать {_SETTLE_SEC}с (semпл 5с)...")

    try:
        time.sleep(_SETTLE_SEC)
    finally:
        print("[proof] гашу систему (PID-specific)...")
        launcher.shutdown()

    # Финальный семпл в shutdown тоже пишет — даём файлу закрыться.
    time.sleep(1.0)

    if not _DB_PATH.exists():
        print(f"[proof] FAIL: БД {_DB_PATH} не создана — сток не запустился")
        return 1

    total, by_proc = _count_rows(_DB_PATH)
    print(f"[proof] строк в telemetry_snapshots: {total}")
    for proc, n in sorted(by_proc.items()):
        print(f"[proof]   {proc:18} {n}")

    rc = 0 if total > 0 else 1
    print(f"[proof] {'PASS' if rc == 0 else 'FAIL — 0 строк, сток ничего не записал'}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
