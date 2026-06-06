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
    shutdown_system()       → cmd="system.shutdown",    data={}

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

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.bridge.command_sender import CommandSender
    from multiprocess_prototype.frontend.bridge.request_runner import RequestRunner

__all__ = ["ProcessManagerProxy"]

ResultCallback = Callable[[dict[str, Any]], None]


class ProcessManagerProxy:
    """GUI-сторона IPC-моста к ProcessManagerProcess.

    Оборачивает ``CommandSender`` (создаётся в ``app.py``).

    Два режима (command-result-bridge):
      - **fire-and-forget** (``replace_blueprint`` и пр.): optimistic-ack, не ждёт
        backend-ответа. Для путей, где результат не нужен.
      - **request/response** (``*_async``): реальный результат PM приходит в
        ``on_result`` в Qt main-thread; request исполняется на worker-потоке
        (``RequestRunner``), UI не фризится.
    """

    def __init__(
        self,
        command_sender: "CommandSender",
        runner: "RequestRunner | None" = None,
    ) -> None:
        self._sender = command_sender
        self._runner = runner  # создаётся лениво при первом *_async-вызове

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

    def shutdown_system(self) -> dict[str, Any]:
        """Завершить ВСЮ систему (PM ставит stop_event → каскадный teardown дерева).

        Для явного «Выход» из GUI. Закрытие окна само по себе шлёт этот сигнал из
        ``GuiProcess.run()`` — здесь дублирующий публичный API для меню/действий.
        """
        return self._dispatch("system.shutdown", {})

    # ------------------------------------------------------------------ #
    #  Команды с результатом (request/response, command-result-bridge)    #
    # ------------------------------------------------------------------ #

    def replace_blueprint_async(self, blueprint: dict[str, Any], on_result: ResultCallback) -> None:
        """Горячая замена blueprint с РЕАЛЬНЫМ результатом в ``on_result``.

        В отличие от :meth:`replace_blueprint` (fire-and-forget) — backend-ответ
        (``success``/``replaced``/``rolled_back``) приходит в ``on_result`` в Qt
        main-thread. request исполняется на worker-потоке (UI не фризится).
        """
        self._dispatch_async("blueprint.replace", {"blueprint": blueprint}, on_result)

    def restart_process_async(self, process_name: str, on_result: ResultCallback) -> None:
        """Перезапустить процесс с результатом в ``on_result``."""
        self._dispatch_async("process.restart", {"process_name": process_name}, on_result)

    def start_process_async(self, process_name: str, on_result: ResultCallback) -> None:
        """Запустить процесс с результатом в ``on_result``."""
        self._dispatch_async("process.start", {"process_name": process_name}, on_result)

    def stop_process_async(self, process_name: str, on_result: ResultCallback) -> None:
        """Остановить процесс с результатом в ``on_result``."""
        self._dispatch_async("process.stop", {"process_name": process_name}, on_result)

    # ------------------------------------------------------------------ #
    #  Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    def _dispatch(self, cmd: str, args: dict[str, Any]) -> dict[str, Any]:
        """Собрать dict-команду и отправить через CommandSender (fire-and-forget)."""
        command: dict[str, Any] = {"cmd": cmd, **args}
        self._sender.send_system_command(command)
        return {"success": True, "dispatched": True, "cmd": cmd}

    def _ensure_runner(self) -> "RequestRunner":
        """Лениво создать RequestRunner (только при первом *_async-вызове)."""
        if self._runner is None:
            from multiprocess_prototype.frontend.bridge.request_runner import RequestRunner

            self._runner = RequestRunner()
        return self._runner

    def _dispatch_async(self, cmd: str, args: dict[str, Any], on_result: ResultCallback) -> None:
        """Собрать команду и отправить через request/response на worker-потоке."""
        command: dict[str, Any] = {"cmd": cmd, **args}
        runner = self._ensure_runner()
        runner.submit(lambda: self._sender.request_system_command(command), on_result)
