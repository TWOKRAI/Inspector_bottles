"""
ProcessManagerProcessApp — подкласс ProcessManagerProcess для прототипа.

Подключает topology_adapter к TopologyManager и StateStoreManager после базовой
инициализации. StateStoreManager создаётся через хук _setup_state_store(),
добавленный в базовый класс в Фазе 1.

Порядок вызовов в initialize() (наследуется от ProcessManagerProcess):
    super().initialize()
        → _setup_topology_manager()  (хук, переопределён здесь)
        → _setup_state_store()       (хук, переопределён здесь)
        → _register_builtin_commands()
        → _create_processes_from_config()  ← дочерние процессы стартуют
"""

from multiprocess_framework.modules.process_manager_module.process.process_manager_process import (
    ProcessManagerProcess,
)

# Путь для передачи в SystemLauncher(orchestrator_class_path=...)
PROCESS_MANAGER_APP_CLASS_PATH = (
    "multiprocess_prototype.backend.processes.process_manager.process"
    ".ProcessManagerProcessApp"
)


class ProcessManagerProcessApp(ProcessManagerProcess):
    """ProcessManagerProcess с подключённым topology_adapter и StateStoreManager."""

    # Аннотация типа для статических анализаторов; реальный тип StateStoreManager
    # импортируется лениво в _setup_state_store() во избежание циклических зависимостей.
    _state_store_manager = None

    def _setup_topology_manager(self) -> None:
        """Создать TopologyManager (базовый) + подключить diff/commands из прототипа."""
        super()._setup_topology_manager()
        if self._topology_manager is None:
            return
        from multiprocess_prototype.registers.system_topology.topology_adapter import (
            configure_topology_manager,
        )
        configure_topology_manager(self._topology_manager)

    def _setup_state_store(self) -> None:
        """Создать StateStoreManager с bootstrap и middleware.

        Вызывается хуком из ProcessManagerProcess.initialize(), строго ДО
        _create_processes_from_config(), — чтобы StateStoreManager был готов
        принимать state.* команды от дочерних процессов при их старте.

        Ленивые импорты: избегаем циклических зависимостей при загрузке модуля.
        Guard: если _state_store_manager уже создан — пропускаем (идемпотентность).
        """
        # Идемпотентный guard — _setup_state_store() вызывается один раз
        if self._state_store_manager is not None:
            return

        # Ленивые импорты для изоляции от циклических зависимостей
        from multiprocess_prototype.state_store.manager.state_store_manager import (
            StateStoreManager,
        )
        from multiprocess_prototype.state_store.bootstrap import build_initial_state
        from multiprocess_prototype.state_store.middleware.validation import ValidationMiddleware
        from multiprocess_prototype.state_store.middleware.throttle import ThrottleMiddleware
        from multiprocess_prototype.backend.processes.process_manager.state_store_config import (
            build_validation_rules,
            build_throttle_rules,
        )

        # Dict at Boundary: app_config передан через orchestrator_config в SystemLauncher
        app_config = self.get_config("app_config") or {}

        # Построить начальное дерево состояния из AppConfig (Dict at Boundary)
        initial_state = build_initial_state(app_config)

        # Создать StateStoreManager; router_manager доступен после super().initialize()
        self._state_store_manager = StateStoreManager(
            router=self.router_manager,
            initial_state=initial_state,
        )

        # Подключить middleware: сначала validation (отклоняет невалидные значения),
        # затем throttle (ограничивает частоту высокочастотных метрик)
        self._state_store_manager.use(ValidationMiddleware(build_validation_rules()))
        self._state_store_manager.use(ThrottleMiddleware(build_throttle_rules()))

        # Регистрирует обработчики state.* в RouterManager (если router задан)
        self._state_store_manager.initialize()

        n_keys = len(initial_state)
        self._log_info(
            f"StateStoreManager подключён, initial_state с {n_keys} ключами верхнего уровня"
        )

    def shutdown(self) -> bool:
        """Завершение с корректной остановкой StateStoreManager перед super()."""
        if self._state_store_manager is not None:
            self._state_store_manager.shutdown()
        return super().shutdown()
