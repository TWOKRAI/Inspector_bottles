"""GenericProcess — тонкий контейнер с plugin state machine + data pipeline.

Управляет state transitions плагинов:
    _init_application_threads():  IDLE → READY → RUNNING
    shutdown():                   * → STOPPED

Data Pipeline (Phase 5):
    DataReceiver  → InspectorManager → chain_queue → PipelineExecutor → IPC
    SourceProducer → SHM write → IPC (для source-плагинов)

Registers (Phase 5.9):
    RegistersManager — per-plugin registers bootstrap + IPC register_update handler.

Загружает плагины из config["plugins"], передаёт в state machine.
Команды плагинов автоматически регистрируются в CommandManager.
"""

from __future__ import annotations

import importlib
import queue
from typing import Any

from ..core.process_module import ProcessModule
from ..io import ProcessIO
from ..plugins.base import PluginContext, PluginState, ProcessModulePlugin
from .data_receiver import DataReceiver
from .frame_shm_middleware import FrameShmMiddleware
from .inspector_manager import InspectorManager
from .pipeline_executor import PipelineExecutor
from .source_producer import SourceProducer


class GenericProcess(ProcessModule):
    """Тонкий контейнер. Только lifecycle + state transitions.

    Каждый элемент plugins — dict с ключами:
    - plugin_class: str — dotted path к классу ProcessModulePlugin
    - plugin_name: str — уникальное имя плагина в процессе
    - ... остальные поля — plugin-specific конфиг
    """

    def _init_custom_managers(self) -> None:
        """Ранняя инициализация: вызвать configure_managers() у плагинов.

        Выполняется ДО _init_application_threads() (и до configure/start).
        Позволяет плагинам создать framework-менеджеры (SQLManager и т.д.),
        которые должны существовать до основного plugin lifecycle.
        """
        super()._init_custom_managers()

        app_cfg = self.get_config("config") or {}
        plugin_defs: list[dict] = app_cfg.get("plugins", [])

        if not plugin_defs:
            return

        io = ProcessIO(self)
        base_ctx = PluginContext(
            process_name=self.name, config={}, process=self, io=io,
        )

        # StateProxy (устанавливается подклассами, например GenericProcessApp)
        state_proxy = getattr(self, '_state_proxy', None)
        if state_proxy is not None:
            base_ctx.state_proxy = state_proxy

        # Предзагрузка плагинов для early-init
        self._early_plugins: list[tuple[ProcessModulePlugin, PluginContext]] = []
        for pdef in plugin_defs:
            plugin_class_path = pdef.get("plugin_class", "")
            plugin_name = pdef.get("plugin_name", "unknown")
            if not plugin_class_path:
                continue
            try:
                plugin = self._load_plugin(plugin_class_path, plugin_name)
                plugin_config = {
                    k: v for k, v in pdef.items()
                    if k not in ("plugin_class", "plugin_name")
                }
                ctx = base_ctx.with_config(plugin_config)
                plugin.configure_managers(ctx)
                self._early_plugins.append((plugin, ctx))
            except Exception as e:
                self._log_error(
                    f"GenericProcess[{self.name}]: configure_managers '{plugin_name}': {e}"
                )

    def _init_application_threads(self) -> None:
        """Провести плагины через IDLE → READY → RUNNING.

        Плагины уже загружены в _init_custom_managers() (early-init).
        Здесь только configure → start lifecycle + registers + data pipeline.
        """
        super()._init_application_threads()

        # Плагины предзагружены в _init_custom_managers()
        early = getattr(self, "_early_plugins", [])
        if not early:
            self._log_info(f"GenericProcess[{self.name}]: нет плагинов")
            return

        self._plugins: list[ProcessModulePlugin] = []
        self._plugin_contexts: list[PluginContext] = []

        # Фаза 0: Registers bootstrap (до configure, чтобы ctx.registers был доступен)
        registers_manager = self._init_registers(early)

        # Фаза 1: IDLE → READY (configure + авторегистрация команд)
        for plugin, ctx in early:
            try:
                # Обновить ctx с registers
                if registers_manager is not None:
                    ctx.registers = registers_manager
                plugin._do_configure(ctx)
                self._plugins.append(plugin)
                self._plugin_contexts.append(ctx)
                self._log_info(
                    f"GenericProcess[{self.name}]: '{plugin.name}' "
                    f"[{plugin.category}] {plugin.state.value}"
                )
            except Exception as e:
                self._log_error(f"GenericProcess[{self.name}]: configure '{plugin.name}': {e}")

        # Фаза 2: READY → RUNNING (start)
        for plugin, ctx in zip(self._plugins, self._plugin_contexts):
            try:
                plugin._do_start(ctx)
                self._log_info(
                    f"GenericProcess[{self.name}]: '{plugin.name}' {plugin.state.value}"
                )
            except Exception as e:
                self._log_error(f"GenericProcess[{self.name}]: start '{plugin.name}': {e}")

        self._log_info(
            f"GenericProcess[{self.name}]: {len(self._plugins)} плагин(ов)"
        )

        # Фаза 3: Data Pipeline bootstrap (Phase 5)
        self._init_data_pipeline()

        # Фаза 4: Registers boot — отправить schemas в PM + handler
        if registers_manager is not None:
            self._boot_registers(registers_manager)

    # --- Registers (Phase 5.9) ---

    def _init_registers(
        self, early: list[tuple[ProcessModulePlugin, PluginContext]],
    ) -> Any | None:
        """Собрать register schemas от плагинов, создать RegistersManager.

        V3_MY_PURE: register_schema() — classmethod, возвращает list[type[SchemaBase]].
        Для обратной совместимости поддерживает и старый формат (SchemaBase instance).

        Convention mapping: plugin.name → register name в RegistersManager.
        """
        schemas: dict[str, Any] = {}

        for plugin, _ctx in early:
            try:
                result = plugin.register_schema()

                if isinstance(result, list):
                    # V3_MY_PURE: list of classes → инстанцировать каждый
                    for reg_cls in result:
                        instance = reg_cls()
                        schemas[plugin.name] = instance
                        self._log_info(
                            f"GenericProcess[{self.name}]: register '{plugin.name}' "
                            f"schema loaded ({reg_cls.__name__})"
                        )
                elif result is not None:
                    # Legacy: SchemaBase instance
                    schemas[plugin.name] = result
                    self._log_info(
                        f"GenericProcess[{self.name}]: register '{plugin.name}' "
                        f"schema loaded ({type(result).__name__})"
                    )
            except Exception as e:
                self._log_error(
                    f"GenericProcess[{self.name}]: register_schema '{plugin.name}': {e}"
                )

        if not schemas:
            return None

        try:
            from multiprocess_framework.modules.registers_module import RegistersManager
            rm = RegistersManager(registers=schemas, logger=self)
            self._registers_manager = rm
            return rm
        except Exception as e:
            self._log_error(f"GenericProcess[{self.name}]: RegistersManager init: {e}")
            return None

    def _boot_registers(self, registers_manager: Any) -> None:
        """Boot-time: handler register_update + отправка schemas в PM."""
        # Handler для runtime register_update от GUI/других процессов
        if self.router_manager:
            self.router_manager.register_message_handler(
                "register_update", self._on_register_update
            )

        # Отправить schemas в ProcessManager для broadcast
        try:
            schemas_payload = registers_manager.model_dump_all()
            io = ProcessIO(self)
            io.send_data("process_manager", "register_schemas", {
                "process_name": self.name,
                "schemas": schemas_payload,
            })
            self._log_info(
                f"GenericProcess[{self.name}]: register_schemas → PM "
                f"({len(schemas_payload)} registers)"
            )
        except Exception as e:
            self._log_error(f"GenericProcess[{self.name}]: register_schemas send: {e}")

    def _on_register_update(self, msg: dict) -> None:
        """Handler: GUI/другой процесс обновляет значение регистра."""
        rm = getattr(self, "_registers_manager", None)
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
            self._log_info(
                f"GenericProcess[{self.name}]: register_update "
                f"{register_name}.{field_name} = {value}"
            )
            # Relay register_changed → PM для broadcast
            try:
                io = ProcessIO(self)
                io.send_data("process_manager", "register_changed", {
                    "process_name": self.name,
                    "register": register_name,
                    "field": field_name,
                    "value": value,
                })
            except Exception:
                pass
        else:
            self._log_error(
                f"GenericProcess[{self.name}]: register_update failed "
                f"{register_name}.{field_name}: {error}"
            )

    # --- Data Pipeline (Phase 5) ---

    def _init_data_pipeline(self) -> None:
        """Bootstrap data pipeline компонентов (Phase 5).

        Создаёт DataReceiver, PipelineExecutor, SourceProducer (если есть source).
        Запускает каждый как LOOP worker через WorkerManager.
        """
        app_cfg = self.get_config("config") or {}

        # Pipeline config
        chain_targets = app_cfg.get("chain_targets", [])
        queue_size = app_cfg.get("queue_size", 64)
        lag_threshold = app_cfg.get("lag_alert_threshold_sec", 2.0)
        source_fps = app_cfg.get("source_target_fps", 25.0)
        max_fails = app_cfg.get("error_max_consecutive_fails", 5)
        auto_reset = app_cfg.get("error_auto_reset_sec", 60.0)
        critical = app_cfg.get("error_critical_plugins", [])

        # Разделить плагины на source и processing
        source_plugins = [p for p in self._plugins if p.is_source]
        processing_plugins = [p for p in self._plugins if not p.is_source]

        # Если нет ни source, ни processing — pipeline не нужен
        if not source_plugins and not processing_plugins:
            return

        # FrameShmMiddleware (если есть memory_manager)
        shm_middleware = None
        if self.memory_manager:
            shm_middleware = FrameShmMiddleware(
                memory_manager=self.memory_manager,
                owner=self.name,
                slot="output_frames",
                log_error=self._log_error,
            )

        # chain_queue: DataReceiver → PipelineExecutor
        self._chain_queue: queue.Queue = queue.Queue(maxsize=queue_size)

        # --- DataReceiver (если есть processing плагины) ---
        if processing_plugins:
            inspector = InspectorManager(
                timeout_sec=0.5,
                log_info=self._log_info,
                log_error=self._log_error,
            )
            self._data_receiver = DataReceiver(
                receive_fn=self.receive_message,
                shm_middleware=shm_middleware,
                inspector_manager=inspector,
                chain_queue=self._chain_queue,
                lag_alert_threshold_sec=lag_threshold,
                log_info=self._log_info,
                log_error=self._log_error,
            )
            # Подключить callback
            inspector._on_ready = self._data_receiver.on_items_ready

            # PipelineExecutor
            self._pipeline_executor = PipelineExecutor(
                plugins=processing_plugins,
                chain_targets=chain_targets,
                shm_middleware=shm_middleware,
                send_fn=self.send_message,
                max_consecutive_fails=max_fails,
                auto_reset_sec=auto_reset,
                critical_plugins=critical,
                log_info=self._log_info,
                log_error=self._log_error,
            )

            # Запуск workers через WorkerManager
            if self.worker_manager:
                self.worker_manager.create_worker(
                    worker_name="data_receiver",
                    target=self._data_receiver.run_loop,
                    config={"execution_mode": "loop", "priority": "REALTIME"},
                    auto_start=True,
                )
                self.worker_manager.create_worker(
                    worker_name="pipeline_executor",
                    target=lambda stop, pause: self._pipeline_executor.run_loop(
                        self._chain_queue, stop, pause
                    ),
                    config={"execution_mode": "loop", "priority": "REALTIME"},
                    auto_start=True,
                )
                self._log_info(
                    f"GenericProcess[{self.name}]: data pipeline started "
                    f"({len(processing_plugins)} processing plugins)"
                )

        # --- SourceProducer (для каждого source-плагина) ---
        self._source_producers: list[SourceProducer] = []
        for i, source_plugin in enumerate(source_plugins):
            producer = SourceProducer(
                plugin=source_plugin,
                shm_middleware=shm_middleware,
                send_fn=self.send_message,
                chain_targets=chain_targets,
                target_fps=source_fps,
                log_info=self._log_info,
                log_error=self._log_error,
            )
            self._source_producers.append(producer)

            if self.worker_manager:
                worker_name = f"source_producer_{source_plugin.name}"
                self.worker_manager.create_worker(
                    worker_name=worker_name,
                    target=producer.run_loop,
                    config={"execution_mode": "loop", "priority": "REALTIME"},
                    auto_start=True,
                )
                self._log_info(
                    f"GenericProcess[{self.name}]: source '{source_plugin.name}' producer started"
                )

    # --- Helpers ---

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

    def shutdown(self) -> bool:
        """* → STOPPED для всех плагинов (в обратном порядке)."""
        for plugin, ctx in reversed(list(zip(
            getattr(self, "_plugins", []),
            getattr(self, "_plugin_contexts", []),
        ))):
            try:
                plugin._do_shutdown(ctx)
                self._log_info(f"GenericProcess[{self.name}]: '{plugin.name}' {plugin.state.value}")
            except Exception as e:
                self._log_error(f"GenericProcess[{self.name}]: shutdown '{plugin.name}': {e}")

        return super().shutdown()
