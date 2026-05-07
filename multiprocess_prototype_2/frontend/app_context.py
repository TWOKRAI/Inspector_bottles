"""AppContext — DI-контейнер для v2 GUI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from .bridge.command_sender import CommandSender

if TYPE_CHECKING:
    from .process import GuiProcess
    from .bridge import DataReceiverBridge
    from multiprocess_prototype_2.registers.manager import RegistersManagerV2
    from multiprocess_prototype_2.frontend.state.bindings import GuiStateBindings


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

    def registers_manager(self) -> "RegistersManagerV2 | None":
        """Вернуть RegistersManagerV2 из extras, если был передан при сборке контекста."""
        return self.extras.get("registers_manager")

    def plugin_registry(self) -> Any | None:
        """Вернуть PluginRegistry из extras, если был передан при сборке контекста."""
        return self.extras.get("plugin_registry")

    def bindings(self) -> "GuiStateBindings | None":
        """Вернуть GuiStateBindings из extras, если был создан в run_gui().

        Используется табами Phase 10B для реактивного обновления виджетов
        по путям StateStore (FPS, status, latency и т.п.).
        """
        return self.extras.get("bindings")


def build_app_context(
    process: "GuiProcess",
    config: dict | None = None,
    *,
    plugin_registry: Any | None = None,
    registers_manager: "RegistersManagerV2 | None" = None,
) -> AppContext:
    """Собрать AppContext из GuiProcess.

    Args:
        process: инициализированный GuiProcess (с _bridge)
        config: дополнительная конфигурация приложения
        plugin_registry: глобальный каталог плагинов (опционально)
        registers_manager: менеджер регистров v2 (опционально)

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

    # Собираем extras с опциональными зависимостями
    extras: dict[str, Any] = {}
    if plugin_registry is not None:
        extras["plugin_registry"] = plugin_registry
    if registers_manager is not None:
        extras["registers_manager"] = registers_manager

    return AppContext(
        process=process,
        command_sender=command_sender,
        bridge=bridge,
        config=config or {},
        extras=extras,
    )
