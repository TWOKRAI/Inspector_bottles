# multiprocess_prototype_v3/backend/processes/producer/process.py
"""ProducerProcess — счётчик и отправка DATA-сообщений consumer."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from multiprocess_framework.modules.message_module import MessageAdapter
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig


class ProducerProcess(ProcessModule):
    """Генерирует counter-сообщения с заданным интервалом."""

    def _init_application_threads(self) -> None:
        self.msg = MessageAdapter(sender=self.name)
        self._counter = 0
        self._interval = float(self.get_config("interval", 0.5))
        self._prefix = str(self.get_config("message_prefix", "msg"))
        self._producing_enabled = bool(self.get_config("enabled", True))

        self._paused_explicit = False
        self.command_manager.register_command("pause_producing", self._cmd_pause)
        self.command_manager.register_command("resume_producing", self._cmd_resume)
        self.command_manager.register_command("get_status", self._cmd_status)
        self.command_manager.register_command("register_update", self._apply_register_update)

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker("produce", self._produce_worker, cfg, auto_start=True)

    def _cmd_pause(self, _data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._paused_explicit = True
        self.worker_manager.pause_worker("produce")
        return {"status": "ok", "paused": True}

    def _cmd_resume(self, _data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._paused_explicit = False
        self.worker_manager.resume_worker("produce")
        return {"status": "ok", "paused": False}

    def _cmd_status(self, _data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        paused = self._paused_explicit
        status = {
            "counter": self._counter,
            "interval": self._interval,
            "is_paused": paused or not self._producing_enabled,
            "prefix": self._prefix,
            "enabled": self._producing_enabled,
        }
        self._write_status_probe(status)
        return {"status": "ok", **status}

    def _write_status_probe(self, status: Dict[str, Any]) -> None:
        env_ld = os.environ.get("INSPECTOR_LOG_DIR")
        log_dir = Path(env_ld) if env_ld else Path(__file__).resolve().parent.parent.parent.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        probe = log_dir / "producer_status.json"
        try:
            probe.write_text(json.dumps(status), encoding="utf-8")
        except OSError:
            pass

    def _apply_register_update(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return {"status": "error", "reason": "invalid payload"}
        field = data.get("field_name") or data.get("field")
        value = data.get("value")
        if field == "interval":
            self._interval = float(value)
            self.update_config("interval", self._interval)
        elif field == "enabled":
            self._producing_enabled = bool(value)
            self.update_config("enabled", self._producing_enabled)
            if self._producing_enabled:
                self.worker_manager.resume_worker("produce")
            else:
                self.worker_manager.pause_worker("produce")
        elif field == "message_prefix":
            self._prefix = str(value)
            self.update_config("message_prefix", self._prefix)
        return {"status": "ok", "field": field}

    def _produce_worker(self, stop_event, pause_event) -> None:
        while not stop_event.is_set():
            if pause_event.is_set() or not self._producing_enabled:
                time.sleep(0.05)
                continue
            self._counter += 1
            payload = {"value": self._counter, "prefix": self._prefix}
            msg = self.msg.data(
                targets=["consumer"],
                data_type="counter",
                data=payload,
            )
            self.send_message("consumer", msg.to_dict())
            self._log_info(f"Sent #{self._counter}")
            if self._counter % 10 == 0:
                self._log_info(f"Produced {self._counter} messages (batch log)")
            self._record_metric("messages_produced", self._counter, {"process": self.name})
            stop_event.wait(self._interval)
