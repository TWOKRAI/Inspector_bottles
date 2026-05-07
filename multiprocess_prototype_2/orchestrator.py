"""orchestrator.py -- ProcessManagerProcessApp для prototype_2.

Подкласс ProcessManagerProcess с интеграцией StateStoreManager.
Переопределяет хук _setup_state_store() для создания реактивного
дерева состояния с initial_state из bootstrap.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.process_manager_module.process.process_manager_process import (
    ProcessManagerProcess,
)


class ProcessManagerProcessApp(ProcessManagerProcess):
    """ProcessManager с StateStoreManager для prototype_2.

    Получает initial_state и state_throttle_rules через orchestrator_config,
    который SystemLauncher мёржит в process_config оркестратора.
    Доступ внутри: self.get_config("initial_state").
    """

    def _setup_state_store(self) -> None:
        """Переопределение хука: создать StateStoreManager с initial_state."""
        initial_state = self.get_config("initial_state") or {}
        throttle_rules = self.get_config("state_throttle_rules")

        from multiprocess_framework.modules.state_store_module.manager.state_store_manager import (
            StateStoreManager,
        )

        self._state_store_manager = StateStoreManager(
            router=self.router_manager,
            initial_state=initial_state,
            logger=self,
        )

        # Подключить ThrottleMiddleware если правила заданы
        if throttle_rules:
            from multiprocess_framework.modules.state_store_module.middleware.throttle import (
                ThrottleMiddleware,
            )

            self._state_store_manager.use(ThrottleMiddleware(throttle_rules))

        self._state_store_manager.initialize()

        # Регистрация команд state.set/get/subscribe/... в CommandManager
        if self.command_manager:
            self._state_store_manager.register_commands(self.command_manager)
