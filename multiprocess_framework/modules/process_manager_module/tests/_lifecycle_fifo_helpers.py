# -*- coding: utf-8 -*-
"""Хелперы для `test_lifecycle_fifo_acceptance.py` (Task 1.9b, слепая приёмка R1-R10).

Не production-код. Класс процесса обязан жить на верхнем уровне importable-модуля: ``run_process_function``
грузит его по dotted-пути (spawn), а не пиклит объект.

``LifecycleChild`` — настоящий дочерний процесс (spawn), которого PM создаёт из ``processes_config``:
  * ``stop_delay_s`` (конфиг процесса, дефолт 0.0) — сколько хук остановки ``stop()`` спит. Это и есть
    «медленный ребёнок»: ``run_process_function`` зовёт ``stop()`` после сигнала остановки, и только
    потом процесс выходит;
  * ``stop_exit_code`` (конфиг процесса, дефолт ``None`` — поведение 1.9b без изменений) — при значении хук
    ``stop()`` после ``stop_delay_s`` выходит ``os._exit(code)``: ребёнок, вышедший сам с кодом ≠ 0
    (Task 1.10, R13);
  * ``marker_path`` — файл, в который ребёнок дописывает по строке ``<pid>\\t<time.time()>\\t<command>``
    на каждое полученное сообщение с командой ``probe.ping``. Так тест видит, КТО и КОГДА получил
    внутреннее сообщение (relay), не зная ничего о внутренностях PM.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

LIFECYCLE_CHILD_CLASS_PATH = (
    "multiprocess_framework.modules.process_manager_module.tests._lifecycle_fifo_helpers.LifecycleChild"
)

#: Команда, которую тест кладёт во внутреннее сообщение relay; ребёнок отмечает её в marker_path.
PING_COMMAND = "probe.ping"

_READ_QUEUES = ("system", "data")


class LifecycleChild:
    """Процесс с настраиваемой задержкой хука остановки и журналом принятых ``probe.ping``."""

    def __init__(self, name: str, shared_resources: Any, config: Any) -> None:
        self.name = name
        self.shared_resources = shared_resources
        self.config = config if isinstance(config, dict) else {}
        # Потоки чтения останавливаются до выхода процесса: поток, убитый внутри ``mp.Queue.get``, оставляет
        # ``_rlock`` очереди занятым, и новое воплощение с той же очередью получает вечный ``Empty`` (R8, отчёт
        # debugger 2026-10-25_task-1.9b-R8-debugger.md).
        self._stop_readers = threading.Event()
        self._readers: list[threading.Thread] = []

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        marker = self.config.get("marker_path")
        if marker:
            for qtype in _READ_QUEUES:
                reader = threading.Thread(
                    target=self._drain, args=(qtype, str(marker)), daemon=True, name=f"drain-{qtype}"
                )
                self._readers.append(reader)
                reader.start()

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        time.sleep(float(self.config.get("stop_delay_s", 0.0)))
        exit_code = self.config.get("stop_exit_code")
        if exit_code is not None:
            os._exit(int(exit_code))

    def shutdown(self) -> None:
        self._stop_readers.set()
        for reader in self._readers:
            reader.join(1.0)

    # ------------------------------------------------------------------ #

    def _drain(self, qtype: str, marker: str) -> None:
        """Читает свою очередь до ``shutdown()``; пишет в журнал только ``probe.ping``."""
        queue = None
        registry = getattr(self.shared_resources, "process_state_registry", None)
        if registry is not None:
            queue = registry.get_queue(self.name, qtype)
        if queue is None:
            return
        while not self._stop_readers.is_set():
            try:
                message = queue.get(timeout=0.05)
            except Exception:  # noqa: BLE001 — пустая очередь / закрытие: просто следующий такт
                time.sleep(0.05)
                continue
            command = message.get("command") if isinstance(message, dict) else None
            if command == PING_COMMAND:
                with open(marker, "a", encoding="utf-8") as fh:
                    fh.write(f"{os.getpid()}\t{time.time():.6f}\t{command}\n")
