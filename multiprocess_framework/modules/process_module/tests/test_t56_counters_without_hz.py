"""Task 5.6 (ревью кода, п.6): счётчики тракта в ``state.*`` публикуются и без running-воркера с hz>0.

Опасность механизма: до 5.6 секция ``state`` собиралась только вместе с агрегатом частоты
(``fps``/``latency_ms``). Если суммы счётчиков снова повесить на ту же ветку, процесс, чьи воркеры
встали (status != running или hz == 0), молча потеряет накопленные ``lag_dropped_items`` и
``not_inspected_*`` — именно тогда, когда оператору они нужнее всего.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.heartbeat.telemetry import build_worker_telemetry


def test_counters_are_published_when_no_worker_runs_with_positive_hz():
    workers = {
        "data_receiver": {"status": "stopped", "effective_hz": 0.0, "lag_dropped_items": 11, "ipc_queue_depth": 0},
        "pipeline_executor": {"status": "running", "effective_hz": 0.0, "not_inspected_handled": 5},
    }
    out = build_worker_telemetry(workers, "processor")
    assert out is not None
    path, data = out
    assert path == "processes.processor"
    state = data["state"]
    assert "fps" not in state, "агрегата частоты быть не должно: ни у кого hz>0"
    assert state["lag_dropped_items"] == 11
    assert state["not_inspected_handled"] == 5
    assert state["ipc_queue_depth"] == 0
