"""
ConsoleLogChannel — канал логирования, пишущий в ConsoleManager.

Мост: LoggerManager → ConsoleManager.write().

Добавляется в LoggerManager как дополнительный канал когда ConsoleManager
активен. Существующий ConsoleChannel (stdout через StreamHandler) в
logger_module остаётся; этот канал — для управляемого вывода.
"""
from typing import Any, Dict

from ...logger_module.interfaces import ILogChannel
from ..interfaces import IConsoleManager


class ConsoleLogChannel(ILogChannel):
    """ILogChannel, который пишет в ConsoleManager."""

    def __init__(
        self,
        console_manager: IConsoleManager,
        name: str = "console_managed",
    ) -> None:
        self._console = console_manager
        self._name = name
        self._active = True

    # -------------------------------------------------------------------------
    # IChannel / ILogChannel
    # -------------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "console_managed"

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        if not self._active:
            return {"status": "skipped", "channel": self.name}
        level = record.get("level", "INFO")
        message = record.get("message", "")
        module = record.get("module", "")
        text = f"[{level}] {module}: {message}\n" if module else f"[{level}] {message}\n"
        self._console.write(text, level=level)
        return {"status": "success", "channel": self.name}

    def close(self) -> None:
        self._active = False

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "active": self._active,
            "type": self.channel_type,
        }
