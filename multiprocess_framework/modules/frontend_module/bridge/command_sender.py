"""CommandSender — отправка IPC-команд из GUI в процессы.

v2 (Phase 12): debounce для slider dragging, send_field_command, send_action_command.
Обратная совместимость: send_command() работает как прежде.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

__all__ = [
    "IProcess",
    "CommandSender",
]


@runtime_checkable
class IProcess(Protocol):
    """Минимальный интерфейс процесса для CommandSender."""

    name: str

    def send_message(self, target: str, msg: dict[str, Any]) -> None: ...


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
        msg = {
            "type": "command",
            "command": command,
            "data_type": command,
            "sender": self._process.name,
            "targets": [target_process],
            "data": args or {},
        }
        self._process.send_message(target_process, msg)

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
        msg = {
            "type": "command",
            "command": "process.command",
            "data_type": "process.command",
            "sender": self._process.name,
            "targets": [target],
            "data": command,
        }
        self._process.send_message(target, msg)
