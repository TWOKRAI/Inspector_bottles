# multiprocess_prototype_v3/tests/test_stage2_observability.py
"""Stage 2: файлы логов и errors.log."""

from __future__ import annotations

from pathlib import Path

from multiprocess_prototype_v3.backend.processes.consumer.config import ConsumerConfig
from multiprocess_prototype_v3.backend.processes.producer.config import ProducerConfig
from multiprocess_prototype_v3.tests.support.harness import (
    SystemTestHarness,
    wait_for_log_substring,
    wait_for_probe_file,
)


def test_stage2_logs_and_errors(tmp_path, monkeypatch) -> None:
    log_root = tmp_path / "logs"
    monkeypatch.setenv("INSPECTOR_LOG_DIR", str(log_root))
    probe = tmp_path / "consumer.probe"

    h = SystemTestHarness(stop_timeout=10.0)
    h.add_from_schema(
        ProducerConfig(interval=0.15, managers_preset="standard"),
        ConsumerConfig(managers_preset="standard", probe_path=str(probe)),
    )
    h.start_background(4.0)
    try:
        wait_for_probe_file(probe, min_value=26, timeout=20.0)
        errors = log_root / "errors.log"
        wait_for_log_substring(errors, "Simulated error", timeout=15.0)
        assert any(log_root.glob("*.log"))
    finally:
        h.stop()
