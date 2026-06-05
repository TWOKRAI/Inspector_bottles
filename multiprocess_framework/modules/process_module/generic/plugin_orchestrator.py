"""PluginOrchestrator — управление lifecycle плагинов через IProcessServices.

Извлечён из GenericProcess (Task 3, refactor/t1.1-plugin-composition).
Не зависит от ProcessModule напрямую — работает через Protocol.
Тестируется с MockProcessServices.

Lifecycle:
    load_and_configure_managers(plugin_defs) — загрузка + early init
    boot() — IDLE -> READY -> RUNNING + registers
    shutdown() — * -> STOPPED (обратный порядок)
"""

from __future__ import annotations

import importlib
from typing import Any

from ..plugins.base import PluginContext, ProcessModulePlugin
from ..plugins.interfaces import IProcessServices


class PluginOrchestrator:
    """Управляет lifecycle плагинов через IProcessServices.

    Не зависит от ProcessModule — работает через Protocol.
    Тестируется с MockProcessServices.

    Lifecycle:
        load_and_configure_managers(plugin_defs) — загрузка + early init
        boot() — IDLE -> READY -> RUNNING + registers
        shutdown() — * -> STOPPED (обратный порядок)
    """

    def __init__(self, services: IProcessServices, io: Any | None = None) -> None:
        self._services = services
        self._io = io
        self._plugins: list[ProcessModulePlugin] = []
        self._contexts: list[PluginContext] = []
        self._early_plugins: list[tuple[ProcessModulePlugin, PluginContext]] = []
        self._registers_manager: Any | None = None

    # --- Публичный API ---

    def load_and_configure_managers(self, plugin_defs: list[dict]) -> None:
        """Загрузить плагины, вызвать configure_managers().

        Выполняется ДО boot() (и до configure/start).
        Позволяет плагинам создать framework-менеджеры (SQLManager и т.д.),
        которые должны существовать до основного plugin lifecycle.
        """
        base_ctx = PluginContext(
            services=self._services,
            config={},
            io=self._io,
        )

        # StateProxy (устанавливается подклассами, например GenericProcessApp)
        state_proxy = getattr(self._services, "_state_proxy", None)
        if state_proxy is not None:
            base_ctx.state_proxy = state_proxy

        self._early_plugins = []
        for pdef in plugin_defs:
            plugin_class_path = pdef.get("plugin_class", "")
            plugin_name = pdef.get("plugin_name", "unknown")
            # Short-name resolution: если plugin_class пуст или это короткое имя
            # (без точки) — резолвим через PluginRegistry по plugin_name.
            resolved_class_path = self._resolve_plugin_class(
                plugin_class_path,
                plugin_name,
            )
            if not resolved_class_path:
                continue
            try:
                plugin = self._load_plugin(resolved_class_path, plugin_name)
                plugin_config = {k: v for k, v in pdef.items() if k not in ("plugin_class", "plugin_name")}
                ctx = base_ctx.with_config(plugin_config)
                plugin.configure_managers(ctx)
                self._early_plugins.append((plugin, ctx))
            except Exception as e:
                self._services.log_error(
                    f"PluginOrchestrator[{self._services.name}]: configure_managers '{plugin_name}': {e}"
                )

    def boot(self) -> None:
        """IDLE -> READY -> RUNNING + registers bootstrap.

        Плагины уже загружены в load_and_configure_managers().
        Здесь только configure -> start lifecycle + registers.
        """
        if not self._early_plugins:
            self._services.log_info(f"PluginOrchestrator[{self._services.name}]: нет плагинов")
            return

        self._plugins = []
        self._contexts = []

        # Фаза 0: Registers bootstrap (до configure, чтобы ctx.registers был доступен)
        registers_manager = self._init_registers(self._early_plugins)

        # Фаза 1: IDLE -> READY (configure + авторегистрация команд)
        for plugin, ctx in self._early_plugins:
            try:
                # Обновить ctx с registers
                if registers_manager is not None:
                    ctx.registers = registers_manager
                # frame-trace: имя процесса-узла для process-спанов плагина.
                plugin._trace_node = self._services.name
                plugin._do_configure(ctx)
                self._plugins.append(plugin)
                self._contexts.append(ctx)
                self._services.log_info(
                    f"PluginOrchestrator[{self._services.name}]: '{plugin.name}' "
                    f"[{plugin.category}] {plugin.state.value}"
                )
            except Exception as e:
                self._services.log_error(f"PluginOrchestrator[{self._services.name}]: configure '{plugin.name}': {e}")

        # Фаза 2: READY -> RUNNING (start)
        for plugin, ctx in zip(self._plugins, self._contexts):
            try:
                plugin._do_start(ctx)
                self._services.log_info(
                    f"PluginOrchestrator[{self._services.name}]: '{plugin.name}' {plugin.state.value}"
                )
            except Exception as e:
                self._services.log_error(f"PluginOrchestrator[{self._services.name}]: start '{plugin.name}': {e}")

        self._services.log_info(f"PluginOrchestrator[{self._services.name}]: {len(self._plugins)} плагин(ов)")

        # Фаза 4: Registers boot — отправить schemas в PM + handler
        if registers_manager is not None:
            self._boot_registers(registers_manager)

    def shutdown(self) -> None:
        """* -> STOPPED для всех плагинов (в обратном порядке)."""
        for plugin, ctx in reversed(list(zip(self._plugins, self._contexts))):
            try:
                plugin._do_shutdown(ctx)
                self._services.log_info(
                    f"PluginOrchestrator[{self._services.name}]: '{plugin.name}' {plugin.state.value}"
                )
            except Exception as e:
                self._services.log_error(f"PluginOrchestrator[{self._services.name}]: shutdown '{plugin.name}': {e}")

    # --- Properties ---

    @property
    def plugins(self) -> list[ProcessModulePlugin]:
        """Список загруженных плагинов."""
        return self._plugins

    @property
    def registers_manager(self) -> Any | None:
        """RegistersManager или None."""
        return self._registers_manager

    # --- Приватные методы ---

    def _load_plugin(self, class_path: str, plugin_name: str) -> ProcessModulePlugin:
        """Загрузить класс плагина по dotted path."""
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)

        if not (isinstance(cls, type) and issubclass(cls, ProcessModulePlugin)):
            raise TypeError(f"'{class_path}' не является ProcessModulePlugin")

        instance = cls()
        if not instance.name:
            instance.name = plugin_name
        return instance

    @staticmethod
    def _resolve_plugin_class(class_path: str, plugin_name: str) -> str:
        """Резолв коротких имён плагинов через PluginRegistry.

        YAML может содержать либо полный dotted path
        (``Plugins.sources.camera_service.plugin.CameraServicePlugin``),
        либо короткое имя (``camera_service``) — тогда категория и путь
        вычисляются через PluginRegistry (discover был выполнен на старте).

        Если class_path пуст — резолвим по plugin_name.
        """
        from ..plugins.registry import PluginRegistry

        candidate = class_path or plugin_name
        if not candidate:
            return ""
        if "." in candidate:
            return candidate  # full dotted path
        entry = PluginRegistry.get(candidate)
        if entry is None:
            return ""
        return entry.class_path

    def _init_registers(
        self,
        early: list[tuple[ProcessModulePlugin, PluginContext]],
    ) -> Any | None:
        """Собрать register schemas от плагинов, создать RegistersManager.

        V3_MY_PURE: register_schema() — classmethod, возвращает list[type[SchemaBase]].
        Для обратной совместимости поддерживает и старый формат (SchemaBase instance).

        Convention mapping: plugin.name -> register name в RegistersManager.
        """
        schemas: dict[str, Any] = {}

        for plugin, _ctx in early:
            try:
                result = plugin.register_schema()

                if isinstance(result, list):
                    # V3_MY_PURE: list of classes -> инстанцировать каждый
                    for reg_cls in result:
                        instance = reg_cls()
                        schemas[plugin.name] = instance
                        self._services.log_info(
                            f"PluginOrchestrator[{self._services.name}]: "
                            f"register '{plugin.name}' schema loaded "
                            f"({reg_cls.__name__})"
                        )
                elif result is not None:
                    # Legacy: SchemaBase instance
                    schemas[plugin.name] = result
                    self._services.log_info(
                        f"PluginOrchestrator[{self._services.name}]: "
                        f"register '{plugin.name}' schema loaded "
                        f"({type(result).__name__})"
                    )
            except Exception as e:
                self._services.log_error(
                    f"PluginOrchestrator[{self._services.name}]: register_schema '{plugin.name}': {e}"
                )

        if not schemas:
            return None

        try:
            from multiprocess_framework.modules.registers_module import RegistersManager

            rm = RegistersManager(registers=schemas, logger=self._services)
            self._registers_manager = rm
            return rm
        except Exception as e:
            self._services.log_error(f"PluginOrchestrator[{self._services.name}]: RegistersManager init: {e}")
            return None

    def _boot_registers(self, registers_manager: Any) -> None:
        """Boot-time: регистрация handler'а register_update от GUI/других процессов.

        (Раньше здесь же слались register_schemas в PM «для broadcast» — мёртвый
        relay: приёмника msg_type register_schemas нет нигде, dead letter. Удалён
        по плану comm-system §11.7.)
        """
        # P4.4.1 (B2): register_update — обычная команда CommandManager (kind-router
        # по type=command зовёт CM). manages_own_reply=True: fire-and-forget (handler
        # ничего не возвращает инициатору), авто-reply пропускается для паритета.
        cm = getattr(self._services, "command_manager", None)
        if cm is not None:
            cm.register_command(
                "register_update",
                self._on_register_update,
                expects_full_message=True,
                metadata={"description": "GUI/процесс обновляет значение регистра", "manages_own_reply": True},
                tags=["registers"],
            )
        else:  # fallback (нет CommandManager) — прежний прямой путь
            router = getattr(self._services, "router_manager", None)
            if router:
                router.register_message_handler("register_update", self._on_register_update)

    def _on_register_update(self, msg: dict) -> None:
        """Handler: GUI/другой процесс обновляет значение регистра."""
        rm = self._registers_manager
        if rm is None:
            return

        data = msg.get("data", {})
        register_name = data.get("register")
        field_name = data.get("field")
        value = data.get("value")

        if not register_name or not field_name:
            return

        success, error = rm.set_field_value(register_name, field_name, value)
        if success:
            self._services.log_info(
                f"PluginOrchestrator[{self._services.name}]: register_update {register_name}.{field_name} = {value}"
            )
            # (Раньше тут был relay register_changed -> PM «для broadcast» — мёртвое
            # письмо: приёмника msg_type register_changed нет. Удалён по плану §11.7/8.)
        else:
            self._services.log_error(
                f"PluginOrchestrator[{self._services.name}]: register_update failed "
                f"{register_name}.{field_name}: {error}"
            )
