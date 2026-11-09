# -*- coding: utf-8 -*-
"""Хелпер Task 1.4 (gui-graceful-close): настоящий spawn-ребёнок для слепой приёмки ``pre_stop``.

Не production-код. Класс живёт на верхнем уровне importable-модуля (``run_process_function`` грузит его по
dotted-пути при spawn). Образец — ``_lifecycle_fifo_helpers.LifecycleChild`` (не ``IProcessModule``: ``ready_event``
взводит раннер сразу после ``initialize()``).

``AckChild`` читает свои очереди ``system`` и ``data`` и на каждую команду с префиксом ``t14.`` и ``request_id``:
  * пишет в файл-метку ``marker_path`` строку ``recv<TAB>время<TAB>команда``;
  * спит ``ack_delay_s`` (дефолт 0.0), отвечает в системную очередь отправителя конвертом, как
    ``RouterManager.reply_to_request`` (``type: response``, ``request_id``, ``success``, ``result``),
    режим ``ack_mode``: ``ack`` (``success: True``, дефолт) | ``nack`` (``success: False``) | ``silent`` (молчит);
  * пишет ``reply_sent<TAB>время<TAB>команда`` — время ДО постановки ответа в очередь.
Отдельный поток ждёт общий ``system_stop_event`` (атрибут ``shared_resources._system_stop_event`` — его ставит
``run_process_function``) и пишет ``event_seen<TAB>время`` — момент, когда ребёнок увидел событие.
Время — ``time.time()`` (один хост, сравнимо между процессами).
"""

from __future__ import annotations

import threading
import time
from typing import Any

ACK_CHILD_CLASS_PATH = "multiprocess_framework.modules.process_manager_module.tests._pre_stop_ack_plugin.AckChild"
STEP_PREFIX = "t14."
_READ_QUEUES = ("system", "data")


class AckChild:
    """Ребёнок, отвечающий на команды шагов ``pre_stop`` и фиксирующий в файле, когда увидел системный стоп."""

    def __init__(self, name: str, shared_resources: Any, config: Any) -> None:
        self.name = name
        self.shared_resources = shared_resources
        self.config = config if isinstance(config, dict) else {}
        self._quit = threading.Event()
        self._threads: list[threading.Thread] = []
        self._file_lock = threading.Lock()

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        for qtype in _READ_QUEUES:
            thread = threading.Thread(target=self._drain, args=(qtype,), daemon=True, name=f"ack-drain-{qtype}")
            self._threads.append(thread)
            thread.start()
        watcher = threading.Thread(target=self._watch_event, daemon=True, name="ack-event-watch")
        self._threads.append(watcher)
        watcher.start()

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        time.sleep(float(self.config.get("stop_delay_s", 0.0)))

    def shutdown(self) -> None:
        self._quit.set()
        for thread in self._threads:
            thread.join(1.0)

    # ------------------------------------------------------------------ #

    def _mark(self, kind: str, stamp: float, extra: str = "") -> None:
        path = self.config.get("marker_path")
        if not path:
            return
        with self._file_lock, open(str(path), "a", encoding="utf-8") as fh:
            fh.write(f"{kind}\t{stamp:.6f}\t{extra}\n")

    def _watch_event(self) -> None:
        event = getattr(self.shared_resources, "_system_stop_event", None)
        if event is None:
            return
        while not self._quit.is_set():
            if event.wait(0.005):
                self._mark("event_seen", time.time())
                return

    def _drain(self, qtype: str) -> None:
        registry = getattr(self.shared_resources, "process_state_registry", None)
        queue = registry.get_queue(self.name, qtype) if registry is not None else None
        if queue is None:
            return
        while not self._quit.is_set():
            try:
                message = queue.get(timeout=0.02)
            except Exception:  # noqa: BLE001 — пусто / закрытие очереди: следующий такт
                time.sleep(0.02)
                continue
            if isinstance(message, dict):
                self._handle(message)

    def _handle(self, message: dict) -> None:
        command = message.get("command")
        if not isinstance(command, str) or not command.startswith(STEP_PREFIX):
            return
        self._mark("recv", time.time(), command)
        data = message.get("data")
        request_id = message.get("request_id") or (data.get("correlation_id") if isinstance(data, dict) else None)
        mode = str(self.config.get("ack_mode", "ack"))
        if not request_id or mode == "silent":
            return
        time.sleep(float(self.config.get("ack_delay_s", 0.0)))
        sender = message.get("sender") or "ProcessManager"
        success = mode != "nack"
        reply = {
            "type": "response",
            "command": "command.response",
            "sender": self.name,
            "targets": [sender],
            "queue_type": "system",
            "request_id": request_id,
            "success": success,
            "result": {"success": success},
        }
        queue = self.shared_resources.process_state_registry.get_queue(sender, "system")
        self._mark("reply_sent", time.time(), command)
        queue.put(reply)
