"""
SharedResourcesManager — фасад-делегатор для всех общих ресурсов системы.

Pickle-safe «записная книжка»: создаётся в ProcessManager, заполняется через
register_process(), передаётся напрямую в дочерние процессы через pickle.

После unpickle дочерний процесс вызывает reinitialize_in_child() для
восстановления non-pickle ресурсов (EventManager internal Queue, SharedMemory handles).

ADR-018: register_process() — единая точка регистрации.
ADR-021: прямой pickle SRM вместо ad-hoc bundle dict.
"""
from __future__ import annotations

from multiprocessing import Event, Queue
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ...base_manager import BaseManager, ObservableMixin
from ...base_manager.core.base_manager import _noop

from ..config.config_store import ConfigStore
from ..events.event_manager import EventManager
from ..queues.queue_registry import QueueRegistry
from ..memory.memory_manager import MemoryManager
from ..state.process_data import ProcessData
from ..state.process_state_registry import ProcessStateRegistry
from ..types import ProcessStatus
from .interfaces import ISharedResourcesManager


# Атрибуты ObservableMixin, которые нельзя pickle (closures)
_PICKLE_EXCLUDE = frozenset((
    "log_debug", "log_info", "log_warning", "log_error", "log_critical",
    "record_metric", "increment", "record_timing", "gauge",
    "track_error", "record_error",
    "_call_manager", "_registry", "_plugin_registry", "_proxy_created",
))


class SharedResourcesManager(BaseManager, ObservableMixin, ISharedResourcesManager):
    """
    Фасад-делегатор для всех общих ресурсов системы.

    Содержит пять внутренних компонентов:
      - ConfigStore         — конфиги всех процессов (статика)
      - ProcessStateRegistry — runtime-состояния (Queue/Event ссылки)
      - QueueRegistry       — создание и доступ к очередям
      - EventManager        — системные события
      - MemoryManager       — SharedMemory по именам

    Pickle-safe: Queue/Event нативно pickle-able; EventManager._event_queue
    и SharedMemory handles пересоздаются через reinitialize_in_child().
    """

    def __init__(
        self,
        manager_name: str = "SharedResourcesManager",
        process: Optional[Any] = None,
        router_manager: Optional[Any] = None,
        logger: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        BaseManager.__init__(self, manager_name=manager_name, process=process)

        managers = kwargs.get("managers", {})
        if logger and "logger" not in managers:
            managers["logger"] = logger
        ObservableMixin.__init__(
            self,
            managers=managers,
            config=kwargs.get("config", {}),
            auto_proxy=kwargs.get("auto_proxy", True),
        )

        # Внутренние компоненты (порядок важен: PSR нужен раньше QR/MM)
        self._config_store = ConfigStore()
        self._event_manager = EventManager(
            manager_name=f"{manager_name}_EventManager",
            process=process,
            router_manager=router_manager,
            logger=logger,
        )
        self._process_state_registry = ProcessStateRegistry(
            event_manager=self._event_manager,
        )
        self._queue_registry = QueueRegistry(
            manager_name=f"{manager_name}_QueueRegistry",
            process_state_registry=self._process_state_registry,
            logger=logger,
        )
        self._memory_manager = MemoryManager(
            manager_name=f"{manager_name}_MemoryManager",
            process_state_registry=self._process_state_registry,
            logger=logger,
        )

        # Обратная совместимость: старый код мог использовать shared_resources dict
        self.shared_resources: Dict[str, Any] = {}

    # =========================================================================
    # ISharedResourcesManager — жизненный цикл
    # =========================================================================

    def initialize(self) -> bool:
        try:
            if not self._event_manager.initialize():
                return False
            self._queue_registry.initialize()
            self._memory_manager.initialize()
            self.is_initialized = True
            self._log_info(f"SharedResourcesManager '{self.manager_name}' initialized")
            return True
        except Exception as e:
            self._log_error(f"SharedResourcesManager.initialize() failed: {e}")
            return False

    def shutdown(self) -> bool:
        try:
            self._event_manager.shutdown()
            self._queue_registry.shutdown()
            self._memory_manager.shutdown()
            self.shared_resources.clear()
            self.is_initialized = False
            self._log_info("SharedResourcesManager shutdown completed")
            return True
        except Exception as e:
            self._log_error(f"SharedResourcesManager.shutdown() failed: {e}")
            return False

    # =========================================================================
    # ISharedResourcesManager — register_process (ADR-018)
    # =========================================================================

    def register_process(self, name: str, config: dict) -> bool:
        """
        Единая точка регистрации процесса.

        1. Сохраняет конфиг в ConfigStore.
        2. Создаёт ProcessData в PSR.
        3. Создаёт очереди из config["queues"].
        4. Создаёт стандартные события stop/pause.
        5. Создаёт SharedMemory если config["memory"] задан.
        """
        try:
            # 1. Конфиг
            self._config_store.store(name, config)

            # 2. ProcessData
            self._process_state_registry.register_process(name)

            # 3. Очереди
            queues_config = config.get("queues", {})
            if queues_config:
                self._queue_registry.create_and_register_queues(name, queues_config)

            # 4. Стандартные события
            self._create_standard_events(name, config)

            # 5. SharedMemory
            memory_config = config.get("memory")
            if memory_config and isinstance(memory_config, dict):
                memory_names = memory_config.get("names", {})
                coll = memory_config.get("coll", 1)
                if memory_names:
                    self._memory_manager.create_memory_dict(name, memory_names, coll)

            self._log_info(f"Process '{name}' registered in SRM")
            return True
        except Exception as e:
            self._log_error(f"register_process('{name}') failed: {e}")
            return False

    def _create_standard_events(self, name: str, config: dict) -> None:
        """Создать стандартные события stop/pause для процесса."""
        stop_event = Event()
        pause_event = Event()
        self._process_state_registry.add_event(name, "stop", stop_event)
        self._process_state_registry.add_event(name, "pause", pause_event)

        # Дополнительные события из конфига
        for event_name in config.get("events", []):
            self._process_state_registry.add_event(name, event_name, Event())

    # =========================================================================
    # ISharedResourcesManager — reinitialize_in_child (ADR-020)
    # =========================================================================

    def reinitialize_in_child(self) -> bool:
        """
        Восстановить non-pickle ресурсы после unpickle в дочернем процессе.

        Вызывается явно в ProcessModule.initialize() — не автоматически.
        """
        try:
            # EventManager: пересоздать internal Queue/Event для локальных подписок
            self._event_manager.reinitialize()

            # MemoryManager: открыть SharedMemory по именам (create=False)
            self._memory_manager.reinitialize_handles()

            # QueueRegistry: убедиться что ссылка на PSR актуальна
            self._queue_registry._process_state_registry = self._process_state_registry

            self._log_info("SRM reinitialized in child process")
            return True
        except Exception as e:
            self._log_error(f"reinitialize_in_child() failed: {e}")
            return False

    # =========================================================================
    # Properties (ISharedResourcesManager)
    # =========================================================================

    @property
    def config_store(self) -> ConfigStore:
        return self._config_store

    @property
    def process_state_registry(self) -> ProcessStateRegistry:
        return self._process_state_registry

    @property
    def queue_registry(self) -> QueueRegistry:
        return self._queue_registry

    @property
    def event_manager(self) -> EventManager:
        return self._event_manager

    @property
    def memory_manager(self) -> MemoryManager:
        return self._memory_manager

    # =========================================================================
    # Доступ к данным процессов
    # =========================================================================

    def get_process_data(self, process_name: str) -> Optional[ProcessData]:
        return self._process_state_registry.get_process_data(process_name)

    def get_all_process_data(self) -> Dict[str, ProcessData]:
        return self._process_state_registry.get_all_process_data()

    def get_process_config(self, name: str) -> Optional[dict]:
        return self._config_store.get(name)

    def get_process_names(self) -> List[str]:
        return self._process_state_registry.get_process_names()

    def get_process_queue(self, process_name: str, queue_type: str) -> Optional[Queue]:
        pd = self.get_process_data(process_name)
        return pd.get_queue(queue_type) if pd else None

    def get_process_event(self, process_name: str, event_name: str) -> Optional[Event]:
        pd = self.get_process_data(process_name)
        return pd.get_event(event_name) if pd else None

    # =========================================================================
    # Обратная совместимость (старый API)
    # =========================================================================

    def register_process_state(
        self,
        process_name: str,
        initial_state: Optional[Dict[str, Any]] = None,
        queue_names: Optional[Dict[str, str]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Устаревший метод. Используйте register_process()."""
        return self._process_state_registry.register_process(
            process_name, initial_state, config=config
        )

    def register_process_with_config(
        self,
        process_name: str,
        config: Any,
        initial_state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Устаревший метод. Используйте register_process()."""
        return self._process_state_registry.register_process_with_config(
            process_name, config, initial_state
        )

    def update_process_state(
        self,
        process_name: str,
        status: Optional[Any] = None,
        events: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        queues: Optional[Dict[str, str]] = None,
        custom: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return self._process_state_registry.update_state(
            process_name, status, events, metadata, queues, custom
        )

    def get_process_state(self, process_name: str) -> Optional[Dict[str, Any]]:
        return self._process_state_registry.get_state(process_name)

    def get_all_process_states(self) -> Dict[str, Dict[str, Any]]:
        return self._process_state_registry.get_all_states()

    def add_shared_resource(self, name: str, resource: Any) -> None:
        self.shared_resources[name] = resource

    def get_shared_resource(self, name: str) -> Optional[Any]:
        return self.shared_resources.get(name)

    def get_data_manager(self) -> Optional[Any]:
        from ..adapters.data_schema_adapter import DataSchemaAdapter
        if not hasattr(self, "_data_schema_adapter"):
            self._data_schema_adapter = DataSchemaAdapter(self)
        return self._data_schema_adapter.get_data_manager()

    @property
    def data_manager(self) -> Optional[Any]:
        return self.get_data_manager()

    # =========================================================================
    # Статистика
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        base = super().get_stats() if hasattr(super(), "get_stats") else {}
        srm_stats = {
            "process_state_registry": self._process_state_registry.get_stats(),
            "queue_registry": self._queue_registry.get_stats(),
            "memory_manager": self._memory_manager.get_stats(),
            "event_manager": self._event_manager.get_stats(),
            "config_store": {"processes": list(self._config_store._configs.keys())},
        }
        if isinstance(base, dict):
            base["shared_resources"] = srm_stats
        else:
            base = {"shared_resources": srm_stats}
        return base

    # =========================================================================
    # Динамический доступ к процессам (shared_resources.process_name)
    # =========================================================================

    def __getattr__(self, name: str) -> Any:
        _PICKLE_SKIP = (
            "_log_method", "_log_method_internal", "_log",
            "_record_metric_method", "_track_error_method", "_call_manager",
        )
        if name in _PICKLE_SKIP or name.startswith(("_log_", "_record_", "_track_")):
            return _noop
        if name.startswith("_") or name in (
            "_process_state_registry", "shared_resources", "_event_manager",
            "_queue_registry", "_memory_manager", "_config_store",
            "get_stats", "__dict__",
        ):
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

        pd = self._process_state_registry.get_process_data(name)
        if pd is not None:
            return pd
        raise AttributeError(
            f"'{type(self).__name__}' has no attribute '{name}'. "
            f"Available processes: {self._process_state_registry.get_process_names()}"
        )

    # =========================================================================
    # Pickle (ADR-021)
    # =========================================================================

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        for key in _PICKLE_EXCLUDE:
            state.pop(key, None)
        state.setdefault("_adapters", {})
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)

    def __str__(self) -> str:
        psr_stats = self._process_state_registry.get_stats()
        return (
            f"SharedResourcesManager("
            f"processes={psr_stats.get('total_processes', 0)}, "
            f"configs={len(self._config_store)})"
        )
