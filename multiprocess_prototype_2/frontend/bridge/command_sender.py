"""CommandSender — обёртка для отправки команд из GUI в процессы через IPC."""
from __future__ import annotations
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..process import GuiProcess


class CommandSender:
    """Формирует и отправляет IPC-команды из GUI в целевые процессы.

    Использует router_manager процесса для отправки dict-сообщений.
    Dict at Boundary: всё передаётся как dict.
    """

    def __init__(self, process: "GuiProcess"):
        self._process = process

    def send_command(self, target_process: str, command: str, args: dict[str, Any] | None = None) -> None:
        """Отправить команду в целевой процесс.

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
