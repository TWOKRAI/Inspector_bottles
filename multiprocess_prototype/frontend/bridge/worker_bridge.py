# -*- coding: utf-8 -*-
"""WorkerBridge — отправка IPC-команд управления воркерами в процесс-владелец.

Тонкая обёртка над CommandSender: формирует data-payload для worker.create /
remove / update / restart / stop и шлёт ПРЯМО в процесс-владелец (target=process_name),
а не через ProcessManager wrapper. Команда доходит до message_processor процесса →
CommandManager → BuiltinCommands worker.* хендлер → WorkerManager.

Pure Python (без Qt). command_sender может быть None (degraded mode без runtime IPC) —
тогда методы возвращают False, не падая (config-персист в presenter всё равно проходит).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.bridge.command_sender import CommandSender


class WorkerBridge:
    """Мост GUI → runtime для CRUD воркеров в конкретном процессе."""

    def __init__(self, command_sender: "CommandSender | None" = None) -> None:
        self._sender = command_sender

    # ------------------------------------------------------------------ #
    #  CRUD                                                                #
    # ------------------------------------------------------------------ #

    def worker_create(
        self,
        process_name: str,
        *,
        worker_name: str,
        priority: str = "NORMAL",
        execution_mode: str = "loop",
        target_interval_ms: int | None = None,
        worker_class: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> bool:
        """Создать и запустить воркер в живом процессе."""
        data: dict[str, Any] = {
            "worker_name": worker_name,
            "priority": priority,
            "execution_mode": execution_mode,
        }
        if target_interval_ms is not None:
            data["target_interval_ms"] = target_interval_ms
        if worker_class:
            data["worker_class"] = worker_class
        if config:
            data["config"] = config
        return self._send(process_name, "worker.create", data)

    def worker_remove(self, process_name: str, worker_name: str) -> bool:
        """Удалить воркер из живого процесса."""
        return self._send(process_name, "worker.remove", {"worker_name": worker_name})

    def worker_update(
        self,
        process_name: str,
        worker_name: str,
        *,
        priority: str | None = None,
        execution_mode: str | None = None,
        target_interval_ms: int | None = None,
    ) -> bool:
        """Перенастроить воркер (приоритет/режим/интервал) в живом процессе."""
        data: dict[str, Any] = {"worker_name": worker_name}
        if priority is not None:
            data["priority"] = priority
        if execution_mode is not None:
            data["execution_mode"] = execution_mode
        if target_interval_ms is not None:
            data["target_interval_ms"] = target_interval_ms
        return self._send(process_name, "worker.update", data)

    def worker_restart(self, process_name: str, worker_name: str) -> bool:
        """Перезапустить воркер в живом процессе."""
        return self._send(process_name, "worker.restart", {"worker_name": worker_name})

    def worker_start(self, process_name: str, worker_name: str) -> bool:
        """Запустить остановленный воркер (без пересоздания) в живом процессе."""
        return self._send(process_name, "worker.start", {"worker_name": worker_name})

    def worker_stop(self, process_name: str, worker_name: str) -> bool:
        """Остановить воркер (без удаления) в живом процессе."""
        return self._send(process_name, "worker.stop", {"worker_name": worker_name})

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _send(self, process_name: str, command: str, data: dict[str, Any]) -> bool:
        """Отправить команду в процесс-владелец. False если sender недоступен."""
        if self._sender is None:
            return False
        self._sender.send_command(process_name, command, data)
        return True
