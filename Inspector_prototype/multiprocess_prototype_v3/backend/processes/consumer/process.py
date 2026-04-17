# multiprocess_prototype_v3/backend/processes/consumer/process.py
"""ConsumerProcess — приём DATA с канала data."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig


class ConsumerProcess(ProcessModule):
    """Считает входящие counter-сообщения."""

    def _init_application_threads(self) -> None:
        self._received = 0
        self._last_log_received = 0

        self.command_manager.register_command("get_count", self._cmd_get_count)

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker("consume", self._consume_worker, cfg, auto_start=True)

    def _cmd_get_count(self, _data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"status": "ok", "received": self._received}

    def _consume_worker(self, stop_event, pause_event) -> None:
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue
            msgs = self.receive(timeout=0.1, channel_types=["data"])
            for msg_dict in msgs:
                self._received += 1
                raw = msg_dict.get("data") if isinstance(msg_dict, dict) else {}
                if not isinstance(raw, dict):
                    raw = {}
                value = raw.get("value", "?")
                self._log_info(f"Received #{self._received}: value={value}")
                if self._received % 25 == 0:
                    self._log_error(f"Simulated error at message {self._received}")
                if self._received - self._last_log_received >= 20:
                    self._last_log_received = self._received
                    self._log_info(f"Total received: {self._received}")
                self._write_probe()
            time.sleep(0.02)

    def _write_probe(self) -> None:
        raw = self.get_config("probe_path")
        if not raw:
            return
        try:
            Path(raw).write_text(str(self._received), encoding="utf-8")
        except OSError:
            pass
