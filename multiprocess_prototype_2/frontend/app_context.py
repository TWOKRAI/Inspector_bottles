"""AppContext — DI-контейнер для v2 GUI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from .bridge.command_sender import CommandSender

if TYPE_CHECKING:
    from .process import GuiProcess
    from .bridge import DataReceiverBridge


@dataclass
class AppContext:
    """DI-контейнер: единая точка доступа к зависимостям GUI.

    Передаётся виджетам и табам вместо прямых ссылок на GuiProcess.
    Нет глобальных переменных — создаётся явно через build_app_context().
    """

    process: "GuiProcess"
    command_sender: CommandSender
    bridge: "DataReceiverBridge"
    config: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Доступ к extras по ключу."""
        return self.extras.get(key, default)


def build_app_context(process: "GuiProcess", config: dict | None = None) -> AppContext:
    """Собрать AppContext из GuiProcess.

    Args:
        process: инициализированный GuiProcess (с _bridge)
        config: дополнительная конфигурация приложения

    Returns:
        Готовый AppContext для передачи в GUI-компоненты

    Raises:
        AttributeError: если process._bridge не инициализирован
            (build_app_context должен вызываться после _init_application_threads)
    """
    bridge = getattr(process, "_bridge", None)
    if bridge is None:
        raise AttributeError(
            "GuiProcess._bridge не инициализирован. "
            "build_app_context должен вызываться после _init_application_threads."
        )

    command_sender = CommandSender(process)

    return AppContext(
        process=process,
        command_sender=command_sender,
        bridge=bridge,
        config=config or {},
        extras={},
    )
