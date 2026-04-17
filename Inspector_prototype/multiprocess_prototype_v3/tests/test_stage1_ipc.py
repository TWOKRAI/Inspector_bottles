# multiprocess_prototype_v3/tests/test_stage1_ipc.py
"""Stage 1: два процесса, IPC, чистый stop."""

from __future__ import annotations

from pathlib import Path

from multiprocess_prototype_v3.backend.processes.consumer.config import ConsumerConfig
from multiprocess_prototype_v3.backend.processes.producer.config import ProducerConfig
from multiprocess_prototype_v3.tests.support.harness import (
    SystemTestHarness,
    wait_for_probe_file,
)


def test_stage1_ipc(tmp_path, monkeypatch) -> None:
    log_root = tmp_path / "logs"
    monkeypatch.setenv("INSPECTOR_LOG_DIR", str(log_root))
    probe = tmp_path / "consumer.probe"

    h = SystemTestHarness(stop_timeout=8.0)
    h.add_from_schema(
        ProducerConfig(managers_preset="minimal", interval=0.25),
        ConsumerConfig(managers_preset="minimal", probe_path=str(probe)),
    )
    h.start_background(ready_wait_s=3.5)
    try:
        n = wait_for_probe_file(probe, min_value=4, timeout=12.0)
        assert n >= 4
    finally:
        h.stop()


def test_main_line_budget() -> None:
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    lines = [ln for ln in main_py.read_text(encoding="utf-8").splitlines() if ln.strip()]
    code_lines = [ln for ln in lines if not ln.strip().startswith("#")]
    assert len(code_lines) <= 28, f"main.py grew to {len(code_lines)} non-empty code lines"
