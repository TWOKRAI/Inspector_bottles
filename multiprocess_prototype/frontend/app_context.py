"""AppContext — DI-контейнер для v2 GUI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from .bridge.command_sender import CommandSender

if TYPE_CHECKING:
    from .process import GuiProcess
    from .bridge import DataReceiverBridge
    from .bridge.command_catalog import CommandCatalog
    from .bridge.topology_bridge import TopologyBridge
    from multiprocess_prototype.registers.manager import RegistersManagerV2
    from multiprocess_prototype.frontend.state.bindings import GuiStateBindings
    from multiprocess_prototype.frontend.topology_holder import TopologyHolder
    from multiprocess_framework.modules.actions_module.bus import ActionBus


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

    def action_bus(self) -> "ActionBus | None":
        """Вернуть ActionBus из extras, если был создан в run_gui().

        Используется табами Phase 11 для undo/redo изменений параметров.
        """
        return self.extras.get("action_bus")

    def topology_holder(self) -> "TopologyHolder | None":
        """Вернуть TopologyHolder из extras, если был создан в run_gui().

        Содержит текущую topology dict с уведомлениями об изменении.
        """
        return self.extras.get("topology_holder")

    def topology_bridge(self) -> "TopologyBridge | None":
        """Вернуть TopologyBridge из extras (Phase 12).

        Единый мост GUI ↔ Runtime: field_set → IPC, state_delta → rm sync.
        """
        return self.extras.get("topology_bridge")

    def command_catalog(self) -> "CommandCatalog | None":
        """Вернуть CommandCatalog из extras (Phase 12).

        Каталог IPC-команд, собранный из PluginRegistry + ConnectionMap.
        """
        return self.extras.get("command_catalog")


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
