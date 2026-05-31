# -*- coding: utf-8 -*-
"""ProcessManagerProxy — тонкий GUI-фасад управления живым ProcessManagerProcess.

Этап 1 плана pipeline-live-control (Task 1.1). Закрывает корневой блокер:
GUI-редактор Pipeline менял топологию только in-memory, изменения не доходили
до работающего ``ProcessManagerProcess``.

Контракт (lite, см. module-contract):
    Прокси НЕ содержит бизнес-логики — только сериализация аргументов в ``dict``
    (Dict at Boundary) и отправка через уже существующий ``CommandSender``.
    Транспорт переиспользуется (RouterManager + command IPC), новый канал не создаётся.

Соответствие backend-командам (``ProcessManagerProcess._register_builtin_commands``):
    replace_blueprint(dict) → cmd="blueprint.replace", data={"blueprint": ...}
    restart_process(name)   → cmd="process.restart",   data={"process_name": ...}
    start_process(name)     → cmd="process.start",      data={"process_name": ...}
    stop_process(name)      → cmd="process.stop",       data={"process_name": ...}

Backend-приёмник: ``CommandSender.send_system_command`` шлёт сообщение
``command="process.command"`` в процесс ``ProcessManager``, где
``_handle_process_command`` распаковывает вложенный ``cmd`` и делегирует в
``CommandManager`` → готовые методы PM (``replace_blueprint`` PM:635,
``start/stop/restart_process`` PM:964-1004).

Async-семантика (важно):
    IPC fire-and-forget — реальный результат ``replace_blueprint`` (success,
    replaced, rolled_back) приходит обратно асинхронно через Router-ответ
    ``process.command.response`` и здесь НЕ дожидается. Методы возвращают
    optimistic-ack ``{"success": True, "dispatched": True}`` сразу после отправки.
    Презентер показывает «команда отправлена», не утверждая факт замены N процессов.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.bridge.command_sender import CommandSender

__all__ = ["ProcessManagerProxy"]


class ProcessManagerProxy:
    """GUI-сторона IPC-моста к ProcessManagerProcess.

    Оборачивает ``CommandSender`` (создаётся в ``app.py``). Все методы
    fire-and-forget: возвращают optimistic-ack, не дожидаясь backend-ответа.
    """

    def __init__(self, command_sender: "CommandSender") -> None:
        self._sender = command_sender

    # ------------------------------------------------------------------ #
    #  Команды управления                                                 #
    # ------------------------------------------------------------------ #

    def replace_blueprint(self, blueprint: dict[str, Any]) -> dict[str, Any]:
        """Горячая замена blueprint процессов (atomic replace + rollback на backend).

        Args:
            blueprint: blueprint-dict топологии (Dict at Boundary).

        Returns:
            optimistic-ack ``{"success": True, "dispatched": True}``.
        """
        return self._dispatch("blueprint.replace", {"blueprint": blueprint})

    def restart_process(self, process_name: str) -> dict[str, Any]:
        """Перезапустить именованный процесс."""
        return self._dispatch("process.restart", {"process_name": process_name})

    def start_process(self, process_name: str) -> dict[str, Any]:
        """Запустить именованный процесс."""
        return self._dispatch("process.start", {"process_name": process_name})

    def stop_process(self, process_name: str) -> dict[str, Any]:
        """Остановить именованный процесс."""
        return self._dispatch("process.stop", {"process_name": process_name})

    # ------------------------------------------------------------------ #
    #  Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    def _dispatch(self, cmd: str, args: dict[str, Any]) -> dict[str, Any]:
        """Собрать dict-команду и отправить через CommandSender (fire-and-forget)."""
        command: dict[str, Any] = {"cmd": cmd, **args}
        self._sender.send_system_command(command)
        return {"success": True, "dispatched": True, "cmd": cmd}
