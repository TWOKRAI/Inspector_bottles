"""orchestrator.py -- ProcessManagerProcessApp для prototype_2.

Подкласс ProcessManagerProcess с интеграцией StateStoreManager.
Переопределяет хук _setup_state_store() для создания реактивного
дерева состояния с initial_state из bootstrap.
"""

from __future__ import annotations


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

        # auto_register_ipc=False: НЕ регистрировать state.* напрямую (RAW) в
        # message_dispatcher из initialize(). RAW-хендлеры не зовут
        # reply_to_request и, побеждая по «первая регистрация» в dispatcher,
        # ломают request/reply (state.get/subscribe → timeout). Вместо этого —
        # wrapped-путь ниже. router всё равно нужен DeltaDispatcher'у (push дельт).
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

        # Регистрация команд state.set/get/subscribe/... в CommandManager
        if self.command_manager:
            self._state_store_manager.register_commands(self.command_manager)

        # Синхронизировать state.* в router.message_dispatcher ЧЕРЕЗ wrapped-путь
        # (register_commands_with_router → _make_command_handler с reply_to_request).
        # Поскольку выше auto_register_ipc=False, RAW-регистрации из initialize()
        # НЕТ → wrapped-путь занимает ключи state.* ПЕРВЫМ и побеждает в dispatcher
        # («первая регистрация» в base_dispatcher.register_handler). Почему важно:
        #   • входящие IPC state.* диспатчатся ТОЛЬКО через message_dispatcher
        #     (system_threads.py) — register_commands выше кладёт их лишь в CommandManager;
        #   • RAW-хендлер handle_state_subscribe НЕ зовёт reply_to_request → ломал бы
        #     request/reply (driver/любой request-инициатор получал timeout);
        #   • wrapped-путь даёт И доставку (gui fire-and-forget), И reply. Здесь — в
        #     initialize, ДО спавна детей → закрывает стартовый race с ранней подпиской GUI.
        if self.command_manager and self.router_manager:
            self._lifecycle.register_commands_with_router()
