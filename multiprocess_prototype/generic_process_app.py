"""generic_process_app.py -- GenericProcessApp для prototype_2.

Подкласс GenericProcess с интеграцией StateProxy.
Создаёт StateProxy ДО super()._init_custom_managers(), чтобы
self._state_proxy был доступен при прокидывании в PluginContext (Task 8.2).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.generic.generic_process import (
    GenericProcess,
)


class GenericProcessApp(GenericProcess):
    """GenericProcess с StateProxy для prototype_2.

    При инициализации создаёт StateProxy, который общается
    с StateStoreManager в ProcessManager через IPC.
    Плагины получают доступ к state через ctx.state_proxy.
    """

    def _init_custom_managers(self) -> None:
        """Создать StateProxy ДО super() для доступа в PluginContext."""
        from multiprocess_framework.modules.state_store_module.proxy.state_proxy import (
            StateProxy,
        )

        # logger=self.logger_manager, а НЕ logger=self (Task Т.1). StateProxy —
        # носитель ObservableMixin: он кладёт этот объект в слот 'logger' и зовёт
        # каноничный протокол warning()/error()/…, а сам процесс экспонирует
        # только log_warning()/log_error(). При logger=self КАЖДАЯ запись
        # StateProxy исчезала (измерено: 0 строк на 60 живых лог-файлах).
        # Порядок безопасен: _init_custom_managers — шаг 6 initialize(), а
        # logger_manager присваивается на шаге 3 (_init_managers) — см. тест
        # test_state_proxy_logger_wiring.py.
        self._state_proxy = StateProxy(
            process_name=self.name,
            router=self.router_manager,
            server_target="ProcessManager",
            logger=self.logger_manager,
        )
        self._state_proxy.initialize()

        # Регистрация handler для входящих state.changed от StateStoreManager
        if self.router_manager:
            self.router_manager.register_message_handler("state.changed", self._state_proxy.on_state_changed)

        # super() прокинет self._state_proxy в PluginContext (Task 8.2)
        super()._init_custom_managers()

    def shutdown(self) -> bool:
        """Shutdown: очистка StateProxy + базовый shutdown плагинов."""
        if hasattr(self, "_state_proxy") and self._state_proxy:
            self._state_proxy.shutdown()
        return super().shutdown()
