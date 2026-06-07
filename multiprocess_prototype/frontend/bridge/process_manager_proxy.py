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
    apply_topology(dict)    → cmd="topology.apply", data={"topology_dict": ...}
    restart_process(name)   → cmd="process.restart", data={"process_name": ...}
    start_process(name)     → cmd="process.start",   data={"process_name": ...}
    stop_process(name)      → cmd="process.stop",    data={"process_name": ...}
    shutdown_system()       → cmd="system.shutdown",  data={}

Backend-приёмник: ``CommandSender.send_system_command`` шлёт сообщение
``command="process.command"`` в процесс ``ProcessManager``, где
``_handle_process_command`` распаковывает вложенный ``cmd`` и делегирует в
``CommandManager`` → ``PM.apply_topology`` (транзакция + rollback + debounce).

Async-семантика (важно):
    Sync-путь (``on_result=None``) — fire-and-forget: возвращает optimistic-ack
    ``{"success": True, "dispatched": True}`` сразу после отправки.
    Async-путь (``on_result`` задан) — request/response на worker-потоке: реальный
    ответ PM (``success``/``replaced``/``rolled_back``) приходит в ``on_result``
    в Qt main-thread (command-result-bridge). UI не фризится.
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

    Два режима apply_topology (command-result-bridge):
      - **fire-and-forget** (``on_result=None``): optimistic-ack, не ждёт
        backend-ответа. Для путей, где результат не нужен.
      - **request/response** (``on_result`` задан): реальный результат PM приходит в
        ``on_result`` в Qt main-thread; request исполняется на worker-потоке
        (``RequestRunner``), UI не фризится.

    Proxy НЕ содержит debounce-логики — он живёт на backend (``PM.apply_topology``).
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

    def apply_topology(
        self,
        source: dict[str, Any],
        on_result: ResultCallback | None = None,
    ) -> dict[str, Any] | None:
        """Применить топологию blueprint к живому backend через ``topology.apply``.

        Единственная точка входа для замены топологии. Debounce живёт на backend
        (``PM.apply_topology``), прокси никакой коалесинг не делает.

        Args:
            source: blueprint-dict топологии (Dict at Boundary).
            on_result: если задан — async request/response (command-result-bridge):
                реальный ответ PM (``success``/``replaced``/``rolled_back``) придёт
                в ``on_result`` в Qt main-thread; UI не фризится.
                Если ``None`` — fire-and-forget: возвращает optimistic-ack.

        Returns:
            При ``on_result=None``: optimistic-ack ``{"success": True, "dispatched": True}``.
            При ``on_result`` задан: ``None`` (результат придёт асинхронно).
        """
        payload = {"topology_dict": source}
        if on_result is None:
            return self._dispatch("topology.apply", payload)
        self._dispatch_async("topology.apply", payload, on_result)
        return None

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
