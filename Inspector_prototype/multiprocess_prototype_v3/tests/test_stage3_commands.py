# multiprocess_prototype_v3/tests/test_stage3_commands.py
"""Stage 3: команды pause/resume/status через system queue."""

from __future__ import annotations

import json
import time
from pathlib import Path

from multiprocess_prototype_v3.backend.processes.consumer.config import ConsumerConfig
from multiprocess_prototype_v3.backend.processes.producer.config import ProducerConfig
from multiprocess_prototype_v3.tests.support.harness import (
    SystemTestHarness,
    wait_for_probe_file,
)


def test_stage3_commands(tmp_path, monkeypatch) -> None:
    log_root = tmp_path / "logs"
    monkeypatch.setenv("INSPECTOR_LOG_DIR", str(log_root))
    probe = tmp_path / "consumer.probe"

    h = SystemTestHarness(stop_timeout=10.0)
    h.add_from_schema(
        ProducerConfig(interval=0.2, managers_preset="minimal"),
        ConsumerConfig(managers_preset="minimal", probe_path=str(probe)),
    )
    h.start_background(4.0)
    try:
        wait_for_probe_file(probe, min_value=2, timeout=12.0)
        h.send_system_command("producer", "pause_producing")
        time.sleep(1.2)
        c1 = int(Path(probe).read_text(encoding="utf-8").strip())
        time.sleep(1.0)
        c2 = int(Path(probe).read_text(encoding="utf-8").strip())
        assert c2 == c1, "consumer should not advance while producer paused"
        h.send_system_command("producer", "resume_producing")
        time.sleep(1.5)
        c3 = int(Path(probe).read_text(encoding="utf-8").strip())
        assert c3 > c1
        h.send_system_command("producer", "get_status")
        time.sleep(0.5)
        status_path = log_root / "producer_status.json"
        assert status_path.exists()
        data = json.loads(status_path.read_text(encoding="utf-8"))
        assert "counter" in data
    finally:
        h.stop()
