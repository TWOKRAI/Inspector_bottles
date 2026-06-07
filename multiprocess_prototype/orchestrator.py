"""orchestrator.py -- ProcessManagerProcessApp для prototype_2.

Подкласс ProcessManagerProcess с интеграцией StateStoreManager.
Переопределяет хук _setup_state_store() для создания реактивного
дерева состояния с initial_state из bootstrap.
"""

from __future__ import annotations


from typing import Any, Optional

from multiprocess_framework.modules.process_manager_module.process.process_manager_process import (
    ProcessManagerProcess,
)


class ProcessManagerProcessApp(ProcessManagerProcess):
    """ProcessManager с StateStoreManager для prototype_2.

    Получает initial_state и state_throttle_rules через orchestrator_config,
    который SystemLauncher мёржит в process_config оркестратора.
    Доступ внутри: self.get_config("initial_state").
    """

    _observability_watcher: Optional[Any] = None

    def initialize(self) -> bool:
        """Инициализация PM + топология engine + observability watcher.

        Порядок:
        1. ``super().initialize()`` — ProcessManagerProcess (managers, topology_manager,
           commands, процессы из config, monitor).
        2. ``_configure_topology_engine()`` — FullReplacePlanner + configure
           TopologyManager (diff_fn/commands_fn). Требует: topology_manager (шаг 1),
           logger/error/stats (шаг 1 → ProcessModule._init_managers).
        3. ``_start_observability_watcher()`` — hot-reload system.yaml.
        """
        if not super().initialize():
            return False
        self._configure_topology_engine()
        self._start_observability_watcher()
        return True

    def _configure_topology_engine(self) -> None:
        """Сконфигурировать TopologyManager: планировщик + сборка proc_dicts.

        Цепочка: unwrap_recipe → normalize_blueprint → BlueprintAssembler.assemble
        — та же сборка, что boot (Phase 1). Prototype-специфика (unwrap рецепта v3,
        SystemConfig-defaults) инъецируется через замыкание ``_build_proc_dicts``;
        framework-менеджер TopologyManager про неё не знает.

        Если ``sys_config`` отсутствует в orchestrator_config (тесты, legacy) —
        логирует и выходит без конфигурации (менеджер остаётся «спящим»:
        diff_fn/commands_fn = None → apply вернёт ``not configured``).
        """
        sys_config_dict = self.get_config("sys_config")
        if not sys_config_dict:
            self._log_info(
                "[topology-engine] sys_config отсутствует в orchestrator_config — "
                "планировщик не сконфигурирован (тесты/legacy)"
            )
            return

        # Lazy-импорты: prototype-символы, не нужные framework
        from pathlib import Path

        from multiprocess_framework.modules.process_module.configs import expand_observability
        from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

        from multiprocess_prototype.backend.assembly import BlueprintAssembler, FullReplacePlanner
        from multiprocess_prototype.backend.assembly.normalize import normalize_blueprint
        from multiprocess_prototype.backend.config.schemas import SystemConfig
        from multiprocess_prototype.backend.launch import PROJECT_ROOT, unwrap_recipe

        sys_config = SystemConfig.model_validate(sys_config_dict)

        # КРИТИЧНО: наполнить PluginRegistry в ЭТОМ процессе (PM/orchestrator).
        # BlueprintAssembler.assemble зовёт SystemBlueprint.check(), а тот резолвит
        # порты плагинов ТОЛЬКО через PluginRegistry (_find_plugin_entry). На boot
        # discover выполняется в launcher-процессе, но PM спавнится отдельно и реестр
        # НЕ наследует — без discover здесь check() считал бы ВСЕ wire невалидными
        # («источник не найден среди выходов») → BlueprintInvalid → switch рецепта
        # падал бы, не остановив старые процессы. Та же логика, что launch.py boot.
        if sys_config.discovery.auto_discover:
            plugin_paths = [
                str(PROJECT_ROOT / p) if not Path(p).is_absolute() else p for p in sys_config.discovery.plugin_paths
            ]
            discovered = PluginRegistry.discover(*plugin_paths)
            self._log_info(f"[topology-engine] PluginRegistry.discover: {discovered} плагинов в PM-процессе")

        obs_overlay = expand_observability(sys_config.observability.model_dump())
        log_dir = sys_config.system.log_dir or "logs"
        assembler = BlueprintAssembler(observability_dict=obs_overlay, log_dir=log_dir)

        def _build_proc_dicts(bp: dict) -> dict[str, dict]:
            """unwrap рецепта v3 → normalize → assemble (единая сборка boot+switch)."""
            return assembler.assemble(normalize_blueprint(unwrap_recipe(bp), sys_config))

        # Планировщик (BaseManager + ObservableMixin)
        planner = FullReplacePlanner(
            proc_dicts_fn=_build_proc_dicts,
            protected_provider=self._get_protected_names,
            current_provider=self._topology_current_names,
            logger=self.logger_manager,
            error=self.error_manager,
            stats=self.stats_manager,
        )
        planner.initialize()
        self._full_replace_planner = planner

        # Сконфигурировать менеджер: diff + commands из планировщика
        self._topology_manager.configure(
            diff_fn=planner.diff,
            commands_fn=planner.commands,
        )

        self._log_info(
            f"[topology-engine] сконфигурирован: FullReplacePlanner + BlueprintAssembler (log_dir={log_dir!r})"
        )

    def _start_observability_watcher(self) -> None:
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            start_observability_watcher,
        )

        config_path = self.get_config("observability_config_path") or ""
        if not config_path:
            return
        self._observability_watcher = start_observability_watcher(
            config_path=config_path,
            logger=self.logger_manager,
            error=self.error_manager,
            stats=self.stats_manager,
            log_info=self._log_info,
            log_error=self._log_error,
        )

    def shutdown(self) -> bool:
        """Остановить watcher (нет висящих потоков), затем штатный shutdown PM."""
        if self._observability_watcher is not None:
            try:
                self._observability_watcher.stop()
            except Exception as exc:  # noqa: BLE001 — shutdown best-effort
                self._log_error(f"[observability] watcher stop: {exc}")
            self._observability_watcher = None
        return super().shutdown()

    def _setup_state_store(self) -> None:
        """Переопределение хука: создать StateStoreManager с initial_state."""
        initial_state = self.get_config("initial_state") or {}
        throttle_rules = self.get_config("state_throttle_rules")

        from multiprocess_framework.modules.state_store_module.manager.state_store_manager import (
            StateStoreManager,
        )

        # auto_register_ipc=False: НЕ регистрировать state.* напрямую (RAW) в
        # event_dispatcher. P4.4.1 (B2): state.* — команды CommandManager
        # (register_commands ниже), kind-router в receive() диспатчит их туда по
        # type=="command", reply делает транспорт. RAW-копии в event_dispatcher
        # были бы dead-path. router всё равно нужен DeltaDispatcher'у (push дельт).
        self._state_store_manager = StateStoreManager(
            router=self.router_manager,
            initial_state=initial_state,
            logger=self,
            auto_register_ipc=False,
        )

        # Подключить ThrottleMiddleware если правила заданы
        if throttle_rules:
            from multiprocess_framework.modules.state_store_module.middleware.throttle import (
                ThrottleMiddleware,
            )

            self._state_store_manager.use(ThrottleMiddleware(throttle_rules))

        self._state_store_manager.initialize()

        # Регистрация команд state.set/get/subscribe/... в CommandManager.
        # P4.4.1 (B2): этого ДОСТАТОЧНО — kind-router в receive() диспатчит входящие
        # state.* (type=="command") напрямую в CommandManager, а reply делает транспорт
        # по request_id. Прежний wrapped-путь (register_commands_with_router +
        # _make_command_handler, копировавший state.* в event_dispatcher) удалён:
        # дупликация реестра устранена, конфликт «первая-регистрация-побеждает» (RAW vs
        # wrapped, ломавший state.get/subscribe timeout'ом) исчез структурно.
        if self.command_manager:
            self._state_store_manager.register_commands(self.command_manager)
