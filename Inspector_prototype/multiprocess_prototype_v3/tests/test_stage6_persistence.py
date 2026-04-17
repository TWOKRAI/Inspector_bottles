# multiprocess_prototype_v3/tests/test_stage6_persistence.py
"""Stage 6: SQLite детекций + сохранение регистров в JSON."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from multiprocess_prototype_v3.backend.processes.aggregator.config import AggregatorConfig
from multiprocess_prototype_v3.backend.processes.camera_sim.config import CameraSimConfig
from multiprocess_prototype_v3.backend.processes.processor.config import ProcessorConfig
from multiprocess_prototype_v3.persistence import paths as persistence_paths
from multiprocess_prototype_v3.registers import PRODUCER_REGISTER, create_registers, save_register_snapshot
from multiprocess_prototype_v3.tests.support.harness import SystemTestHarness


def test_stage6_sqlite_and_register_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_root = tmp_path / "logs"
    data_dir = tmp_path / "data"
    cfg_path = data_dir / "config.json"
    db_path = data_dir / "detections.db"
    data_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("INSPECTOR_LOG_DIR", str(log_root))

    def _cfg_path() -> Path:
        return cfg_path

    def _db_url() -> str:
        return f"sqlite:///{db_path}"

    monkeypatch.setattr(persistence_paths, "config_json_path", _cfg_path)
    monkeypatch.setattr(persistence_paths, "detections_db_url", _db_url)

    rm, _ = create_registers(load_persisted=False)
    ok, _ = rm.set_field_value(PRODUCER_REGISTER, "interval", 0.35)
    assert ok
    save_register_snapshot(rm)

    h = SystemTestHarness(stop_timeout=12.0)
    h.add_from_schema(
        CameraSimConfig(fps=6, frame_color="dark"),
        ProcessorConfig(brightness_threshold=128),
        AggregatorConfig(report_interval=0.7, persist_detections=True),
    )
    h.start_background(5.0)
    try:
        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline:
            if db_path.exists() and db_path.stat().st_size > 100:
                break
            time.sleep(0.25)
        assert db_path.exists()
        assert db_path.stat().st_size > 0
    finally:
        h.stop()

    rm2, _ = create_registers(load_persisted=True)
    snap = rm2.get_register(PRODUCER_REGISTER)
    assert snap is not None
    assert abs(float(snap.interval) - 0.35) < 1e-6
