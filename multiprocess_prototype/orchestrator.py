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
        """Инициализация PM + запуск observability hot-reload watcher (P3.3).

        Watcher следит за system.yaml: правка секции observability на лету
        перестраивает Logger/Error/Stats этого процесса без рестарта.
        Cross-process распространение — Phase 4 (IPC config.reload).
        """
        if not super().initialize():
            return False
        self._start_observability_watcher()
        return True

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
        # message_dispatcher. P4.4.1 (B2): state.* — команды CommandManager
        # (register_commands ниже), kind-router в receive() диспатчит их туда по
        # type=="command", reply делает транспорт. RAW-копии в message_dispatcher
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
        # _make_command_handler, копировавший state.* в message_dispatcher) удалён:
        # дупликация реестра устранена, конфликт «первая-регистрация-побеждает» (RAW vs
        # wrapped, ломавший state.get/subscribe timeout'ом) исчез структурно.
        if self.command_manager:
            self._state_store_manager.register_commands(self.command_manager)
