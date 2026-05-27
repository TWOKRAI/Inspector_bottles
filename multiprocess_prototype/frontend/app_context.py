"""AppContext — DI-контейнер для v2 GUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from .auth_context import AuthContext  # noqa: F401 — re-export для backward-compat
from .bridge.command_sender import CommandSender
from ._deprecated_extras import _DeprecatedExtrasDict

if TYPE_CHECKING:
    from .process import GuiProcess
    from .bridge import DataReceiverBridge
    from .bridge.command_catalog import CommandCatalog
    from .bridge.topology_bridge import TopologyBridge
    from multiprocess_framework.modules.registers_module import RegistersManager
    from multiprocess_prototype.frontend.state.bindings import GuiStateBindings
    from multiprocess_prototype.frontend.state.auth_state import AuthState
    from multiprocess_prototype.frontend.topology_holder import TopologyHolder
    from multiprocess_framework.modules.actions_module.bus import ActionBus
    from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext
    from multiprocess_framework.modules.process_module.plugins.manager import PluginManager
    from multiprocess_framework.modules.service_module import ServiceRegistry
    from Services.auth.interfaces import IAuthManager
    from Services.auth.storage.audit_storage import SqliteAuditStorage
    from multiprocess_prototype.domain.app_services import AppServices


@dataclass
class AppContext:
    """DI-контейнер: единая точка доступа к зависимостям GUI.

    Передаётся виджетам и табам вместо прямых ссылок на GuiProcess.
    Нет глобальных переменных — создаётся явно через build_app_context().

    Зависимости группируются по доменам через property-аксессоры:
    - `auth` — AuthContext (manager + state + audit)
    Существующие методы (`auth_manager()`, `auth_state()`, ...) сохранены
    для обратной совместимости и будут удалены после миграции всех callers.
    """

    process: "GuiProcess"
    command_sender: CommandSender
    bridge: "DataReceiverBridge"
    config: dict[str, Any] = field(default_factory=dict)
    extras: _DeprecatedExtrasDict = field(default_factory=_DeprecatedExtrasDict)
    app_services: "AppServices | None" = field(default=None)

    # -- Domain-grouped accessors (новый API) --

    @property
    def auth(self) -> "AuthContext | None":
        """Auth-домен: manager + state + audit. None если не инициализирован.

        Пример:
            if (auth := ctx.auth) is not None:
                auth.manager.login(...)
                auth.state.access_context
        """
        mgr = self.extras.get("auth_manager")
        state = self.extras.get("auth_state")
        if mgr is None or state is None:
            return None
        return AuthContext(
            manager=mgr,
            state=state,
            audit=self.extras.get("audit_storage"),
        )

    # -- Legacy accessors (deprecated, удалить после миграции) --

    def get(self, key: str, default: Any = None) -> Any:
        """Доступ к extras по ключу."""
        return self.extras.get(key, default)

    def registers_manager(self) -> "RegistersManager | None":
        """Вернуть RegistersManager из extras, если был передан при сборке контекста."""
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

    def plugin_manager(self) -> "PluginManager | None":
        """Singleton PluginManager — автообнаружение и hot-reload плагинов.

        Инициализируется в run_gui() из путей sys_config.discovery.plugin_paths.
        None если GUI-процесс не инициализировал (например, в тестах).
        """
        return self.extras.get("plugin_manager")

    def service_registry(self) -> "ServiceRegistry | None":
        """Singleton ServiceRegistry — реестр long-running сервисов.

        Инициализируется в run_gui() после ServiceRegistry bootstrap.
        None если GUI-процесс не инициализировал (например, в тестах).
        """
        return self.extras.get("service_registry")

    @property
    def recipe_manager(self) -> Any | None:
        """RecipeManager — менеджер рецептов v2 (blueprint-based CRUD).

        Инициализируется в run_gui() через RecipeEngine + wire-up (Task 5.8).
        None если GUI-процесс не инициализировал (тесты или ошибка при старте).
        """
        return self.extras.get("recipe_manager")

    def form_context(self) -> "FormContext | None":
        """Собрать FormContext из доступных в AppContext компонентов.

        Объединяет: RegistersManager, ActionBus, V2ActionBuilder, access_level
        (из auth.state.access_context, если доступен).

        Returns:
            FormContext если RM и ActionBus доступны; None иначе
            (например, в legacy тестах без полного GUI-контекста).
        """
        from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext
        from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder

        rm = self.registers_manager()
        bus = self.action_bus()
        if rm is None or bus is None:
            return None

        # access_level из auth context (паттерн из PluginsTab._build_form_ctx)
        level = 0
        auth = self.auth
        if auth is not None and hasattr(auth.state, "access_context"):
            ctx_acc = auth.state.access_context
            if ctx_acc is not None and hasattr(ctx_acc, "level"):
                level = ctx_acc.level

        return FormContext(
            registers_manager=rm,
            action_bus=bus,
            action_builder=V2ActionBuilder,
            access_level=level,
        )

    def auth_manager(self) -> "IAuthManager | None":
        """IAuthManager из extras, если был инициализирован в run_gui()."""
        return self.extras.get("auth_manager")

    def auth_state(self) -> "AuthState | None":
        """AuthState из extras, если был инициализирован в run_gui()."""
        return self.extras.get("auth_state")

    def audit_storage(self) -> "SqliteAuditStorage | None":
        """SqliteAuditStorage из extras, если был инициализирован в run_gui().

        Используется панелями SessionsPanel и AuditLogPanel (PR4 Group C)
        для чтения сессий и аудит-лога.
        """
        return self.extras.get("audit_storage")


def build_app_context(
    process: "GuiProcess",
    config: dict | None = None,
    *,
    plugin_registry: Any | None = None,
    registers_manager: "RegistersManager | None" = None,
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
    extras: _DeprecatedExtrasDict = _DeprecatedExtrasDict()
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
