# multiprocess_prototype_v3/tests/test_stage4_registers.py
"""Stage 4: RegistersManager + FieldRouting + register_update."""

from __future__ import annotations

import time
from pathlib import Path

from multiprocess_prototype_v3.backend.processes.consumer.config import ConsumerConfig
from multiprocess_prototype_v3.backend.processes.producer.config import ProducerConfig
from multiprocess_prototype_v3.registers import PRODUCER_REGISTER, create_registers
from multiprocess_prototype_v3.tests.support.harness import (
    SystemTestHarness,
    wait_for_probe_file,
)


def test_stage4_register_routing_and_update(tmp_path, monkeypatch) -> None:
    log_root = tmp_path / "logs"
    monkeypatch.setenv("INSPECTOR_LOG_DIR", str(log_root))
    probe = tmp_path / "consumer.probe"

    h = SystemTestHarness(stop_timeout=10.0)
    h.add_from_schema(
        ProducerConfig(interval=0.35, managers_preset="minimal"),
        ConsumerConfig(managers_preset="minimal", probe_path=str(probe)),
    )
    h.start_background(4.0)
    try:
        sr = h.shared_resources()
        assert sr is not None

        def send_cb(
            channel: str,
            register_name: str,
            field_name: str,
            value: object,
            snapshot: dict,
        ) -> None:
            target = channel.replace("control_", "", 1) if channel.startswith("control_") else channel
            pd = sr.get_process_data(target)
            if not pd:
                return
            q = pd.get_queue("system")
            if q:
                q.put(
                    {
                        "command": "register_update",
                        "data": {
                            "field_name": field_name,
                            "value": value,
                            "register_name": register_name,
                            "snapshot": snapshot,
                        },
                    }
                )

        rm, cm = create_registers(send_callback=send_cb, load_persisted=False)
        assert PRODUCER_REGISTER in cm
        assert cm[PRODUCER_REGISTER] == "producer"

        wait_for_probe_file(probe, min_value=2, timeout=12.0)
        ok, err = rm.set_field_value(PRODUCER_REGISTER, "interval", 0.08)
        assert ok, err
        t0 = time.monotonic()
        wait_for_probe_file(probe, min_value=18, timeout=28.0)
        assert time.monotonic() - t0 < 22.0, "faster interval should fill probe quicker"
    finally:
        h.stop()
