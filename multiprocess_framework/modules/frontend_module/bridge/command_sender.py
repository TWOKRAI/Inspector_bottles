"""CommandSender — отправка IPC-команд из GUI в процессы.

v2 (Phase 12): debounce для slider dragging, send_field_command, send_action_command.
Обратная совместимость: send_command() работает как прежде.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from multiprocess_framework.modules.message_module import (
    build_command_message,
    build_system_command_message,
)

logger = logging.getLogger(__name__)

__all__ = [
    "IProcess",
    "IRequestingProcess",
    "CommandSender",
    "DEFAULT_REQUEST_TIMEOUT",
]

# Дефолтный таймаут request-команд. Щедрый, т.к. дискретные операции (blueprint.replace
# = спавн N процессов) идут секунды. Прогресс-индикация (lifecycle, follow-up) уберёт
# слепое ожидание; пока — индикатор «выполняется…» на стороне presenter.
DEFAULT_REQUEST_TIMEOUT = 30.0


@runtime_checkable
class IProcess(Protocol):
    """Минимальный интерфейс процесса для CommandSender (fire-and-forget)."""

    name: str

    def send_message(self, target: str, msg: dict[str, Any]) -> None: ...


@runtime_checkable
class IRequestingProcess(IProcess, Protocol):
    """Процесс, поддерживающий request/response (для command-result-bridge).

    Расширяет :class:`IProcess` доступом к ``router_manager`` с методом
    ``request(msg, timeout) -> dict`` (P0.5). GuiProcess(ProcessModule) ему
    удовлетворяет: ``self.router_manager`` — рабочий RouterManager.

    Контракт потока: ``request()`` БЛОКИРУЕТ вызывающий поток до ответа/таймаута
    и НЕ должен вызываться из приёмного потока процесса (дедлок). В GUI request-
    методы исполняются на worker-потоке (RequestRunner), не в Qt main-thread.
    """

    router_manager: Any


class CommandSender:
    """Формирует и отправляет IPC-команды из GUI в целевые процессы.

    Dict at Boundary: всё передаётся как dict.

    v2 добавляет:
    - send_field_command() — с debounce (coalescing через QTimer)
    - send_action_command() — для явных команд (start/stop)
    - _pending dict для coalescing быстрых изменений одного поля
    """

    def __init__(self, process: IProcess) -> None:
        self._process = process
        # Pending dict для debounce: (target, command, field) → value
        self._pending: dict[tuple[str, str, str], Any] = {}
        # QTimer создаётся лениво (только при первом debounce)
        self._timer: Any | None = None
        self._debounce_ms: int = 0

    # --- Базовый метод (v1, обратная совместимость) ---

    def send_command(
        self,
        target_process: str,
        command: str,
        args: dict[str, Any] | None = None,
    ) -> None:
        """Отправить команду в целевой процесс (v1 API, без изменений).

        Args:
            target_process: имя процесса-получателя
            command: имя команды (data_type в сообщении)
            args: аргументы команды
        """
        # Форма сообщения — общий билдер протокола (один источник правды с driver'ом).
        msg = build_command_message(target_process, command, args, sender=self._process.name)
        self._route_command(target_process, msg)

    def _route_command(self, target_process: str, msg: dict[str, Any]) -> None:
        """Доставить команду: свой процесс/PM — напрямую, остальные — через PM-relay.

        PM-relay (см. process.relay в ProcessManager): команды НЕ-своему процессу
        маршрутизируем через ProcessManager, у которого ВСЕГДА свежие очереди.
        Прямой send_message из GUI после hot-swap рецепта кладёт билет в мёртвую
        очередь (стейл pickle-копия PSR GUI — GUI protected, не пересоздаётся) →
        тихая потеря. Свой процесс (GUI→GUI) и сам PM — напрямую (их очереди
        стабильны: GUI не пересоздаётся, PM провижинит сам себя).
        """
        if target_process == self._process.name or target_process == "ProcessManager":
            self._process.send_message(target_process, msg)
            return
        self.send_system_command({"cmd": "process.relay", "target_process": target_process, "inner_message": msg})

    # --- v2: field command с debounce ---

    def send_field_command(
        self,
        target_process: str,
        command: str,
        args: dict[str, Any],
        *,
        debounce_ms: int = 0,
    ) -> None:
        """Отправить команду изменения поля с опциональным debounce.

        При debounce_ms > 0: сохраняет в pending dict, отправляет
        по таймеру. Повторные вызовы для того же (target, command, field)
        перезаписывают значение (coalescing).

        Args:
            target_process: имя процесса-получателя
            command: имя команды
            args: {field_name: value}
            debounce_ms: задержка перед отправкой (0 = немедленно)
        """
        if debounce_ms <= 0:
            self.send_command(target_process, command, args)
            return

        # Coalescing: сохраняем в pending, перезаписывая предыдущее
        for field_name, value in args.items():
            key = (target_process, command, field_name)
            self._pending[key] = value

        self._ensure_timer(debounce_ms)

    def send_action_command(
        self,
        target_process: str,
        command: str,
        args: dict[str, Any] | None = None,
    ) -> None:
        """Отправить action-команду (start/stop и т.п.) — всегда немедленно."""
        self.send_command(target_process, command, args)

    # --- Debounce internals ---

    def _ensure_timer(self, debounce_ms: int) -> None:
        """Создать/перезапустить QTimer для debounce."""
        try:
            from multiprocess_framework.modules.frontend_module.core.qt_imports import QTimer
        except ImportError:
            # Без Qt — отправляем немедленно (тесты без GUI)
            self._flush_pending()
            return

        if self._timer is None:
            self._timer = QTimer()
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self._flush_pending)

        self._debounce_ms = debounce_ms
        # Перезапуск таймера (coalescing)
        self._timer.start(debounce_ms)

    def _flush_pending(self) -> None:
        """Отправить все накопленные pending-команды."""
        if not self._pending:
            return

        # Группируем по (target, command)
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for (target, command, field_name), value in self._pending.items():
            key = (target, command)
            grouped.setdefault(key, {})[field_name] = value

        self._pending.clear()

        for (target, command), args in grouped.items():
            self.send_command(target, command, args)

    @property
    def pending_count(self) -> int:
        """Количество pending-записей (для тестов)."""
        return len(self._pending)

    def flush(self) -> None:
        """Принудительный flush pending (для тестов и shutdown)."""
        if self._timer is not None:
            self._timer.stop()
        self._flush_pending()

    # --- v2: system command ---

    def send_system_command(self, command: dict[str, Any]) -> None:
        """Отправить system-level команду в ProcessManager.

        Используется для горячего добавления/удаления процессов,
        управления wire'ами и прочих системных операций.
        """
        target = "ProcessManager"
        # Форма сообщения — общий билдер протокола (один источник правды с driver'ом).
        msg = build_system_command_message(command, sender=self._process.name)
        self._process.send_message(target, msg)

    # --- request/response (command-result-bridge): GUI узнаёт результат ---

    def request_command(
        self,
        target_process: str,
        command: str,
        args: dict[str, Any] | None = None,
        *,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> dict[str, Any]:
        """Отправить команду и ДОЖДАТЬСЯ реального ответа процесса (round-trip).

        В отличие от :meth:`send_command` (fire-and-forget) — блокирует поток до
        ``response`` или таймаута. correlation_id проставляет ``router.request()``.

        Контракт потока: вызывать с worker-потока (НЕ Qt main, НЕ приёмный поток).

        Args:
            target_process: имя процесса-получателя.
            command: имя команды.
            args: аргументы команды.
            timeout: ожидание ответа, сек.

        Returns:
            dict ответа (``success``/``result``; при таймауте — ``{"success":
            False, "error": "timeout", ...}``).
        """
        msg = build_command_message(target_process, command, args, sender=self._process.name)
        return self._request(msg, timeout)

    def request_system_command(
        self,
        command: dict[str, Any],
        *,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> dict[str, Any]:
        """System-команда в ProcessManager с ожиданием реального результата.

        Round-trip-вариант :meth:`send_system_command`. Backend (``_handle_process_command``)
        отвечает ``process.command.response`` с результатом вложенной команды
        (например ``replace_blueprint`` → ``{success, replaced, rolled_back, ...}``).

        Контракт потока: вызывать с worker-потока (см. :meth:`request_command`).
        """
        msg = build_system_command_message(command, sender=self._process.name)
        return self._request(msg, timeout)

    def _request(self, msg: dict[str, Any], timeout: float) -> dict[str, Any]:
        """Отправить билет через ``router.request`` и вернуть ответ.

        Требует, чтобы процесс предоставлял ``router_manager`` (см.
        :class:`IRequestingProcess`). Иначе — ошибка конфигурации.
        """
        router = getattr(self._process, "router_manager", None)
        if router is None or not hasattr(router, "request"):
            raise RuntimeError(
                "request_command/request_system_command требуют process.router_manager "
                "с методом request() (см. IRequestingProcess)"
            )
        return router.request(msg, timeout=timeout)
