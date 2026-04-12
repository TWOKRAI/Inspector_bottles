# multiprocess_prototype_v3/tests/test_stage5_pipeline.py
"""Stage 5: camera_sim → SHM → processor → aggregator."""

from __future__ import annotations

import time
from pathlib import Path

from multiprocess_prototype_v3.backend.processes.aggregator.config import AggregatorConfig
from multiprocess_prototype_v3.backend.processes.camera_sim.config import CameraSimConfig
from multiprocess_prototype_v3.backend.processes.processor.config import ProcessorConfig
from multiprocess_prototype_v3.tests.support.harness import SystemTestHarness


def _any_log_contains(root: Path, needle: str) -> bool:
    if not root.exists():
        return False
    for f in root.rglob("*.log"):
        try:
            if needle in f.read_text(encoding="utf-8", errors="ignore"):
                return True
        except OSError:
            continue
    return False


def test_stage5_pipeline_shm(tmp_path, monkeypatch) -> None:
    log_root = tmp_path / "logs"
    monkeypatch.setenv("INSPECTOR_LOG_DIR", str(log_root))

    h = SystemTestHarness(stop_timeout=12.0)
    h.add_from_schema(
        CameraSimConfig(fps=8, frame_color="bright"),
        ProcessorConfig(brightness_threshold=200),
        AggregatorConfig(report_interval=0.8),
    )
    h.start_background(5.0)
    try:
        deadline = time.monotonic() + 20.0
        ok = False
        while time.monotonic() < deadline:
            if _any_log_contains(log_root, "Summary: frames="):
                ok = True
                break
            time.sleep(0.2)
        assert ok, "aggregator should log periodic summary"
    finally:
        h.stop()
