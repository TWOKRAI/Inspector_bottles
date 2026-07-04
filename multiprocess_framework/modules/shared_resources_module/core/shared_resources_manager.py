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
from typing import Any, Dict, List, Optional

from ...base_manager import BaseManager, ObservableMixin
from ..config_store import ConfigStore
from ..events import EventManager
from ..queues import QueueRegistry
from ..memory.core import MemoryManager
from ..state.process_data import ProcessData
from ..state.process_state_registry import ProcessStateRegistry
from ..types import ProcessStatus
from ..handles import ProcessHandle
from .interfaces import ISharedResourcesManager


def _noop(*a, **kw):
    """Pickle-safe noop stub для методов после unpickle (Windows spawn)."""
    return None


# Атрибуты ObservableMixin, которые нельзя pickle (closures)
_PICKLE_EXCLUDE = frozenset(
    (
        "log_debug",
        "log_info",
        "log_warning",
        "log_error",
        "log_critical",
        "record_metric",
        "increment",
        "record_timing",
        "gauge",
        "track_error",
        "record_error",
        "_call_manager",
        "_registry",
        "_plugin_registry",
        "_proxy_created",
    )
)


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
            logger=self,
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
        # ОБЩИЙ system_stop_event (mp.Event). Хранится здесь, а НЕ в process_data.custom:
        # custom рассылается ProcessMonitor'ом через Queue всем процессам, а сырой
        # mp.Event на Windows-spawn пиклится только через inheritance. SRM-инстанс локален
        # для процесса и никогда не сериализуется в очередь. Ставится в process_runner.
        self._system_stop_event = None

    def get_system_stop_event(self):
        """ОБЩИЙ system_stop_event (mp.Event) или None.

        Передаётся отдельным Process-аргументом (inheritance) и ставится в
        process_runner. PM/GUI читают его отсюда, чтобы взвести каскадный shutdown.
        """
        return self._system_stop_event

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
                memory_names = memory_config.get("names")
                coll = memory_config.get("coll", 2)
                if memory_names is None:
                    # Плоский формат: {"camera_frame": (h,w,c), "coll": 2}
                    memory_names = {k: v for k, v in memory_config.items() if k != "coll" and isinstance(v, tuple)}
                if memory_names:
                    names_normalized = self._normalize_memory_names(memory_names)
                    if names_normalized:
                        self._memory_manager.create_memory_dict(name, names_normalized, coll)

            self._log_info(f"Process '{name}' registered in SRM")
            return True
        except Exception as e:
            self._log_error(f"register_process('{name}') failed: {e}")
            return False

    def unregister_process(self, name: str) -> bool:
        """Единая точка СНЯТИЯ процесса — симметрия к ``register_process`` (ADR-SRM-009).

        1. Освобождает SHM процесса (``memory_manager.release_process_memory``).
        2. Удаляет запись PSR (очереди, события, метаданные — умирают вместе
           с ProcessData; иначе очереди мёртвого процесса остаются в
           routing_map новых детей и broadcast наполняет никем не читаемые Queue).
        3. Удаляет конфиг из ConfigStore.

        Идемпотентно: снятие незарегистрированного имени — no-op, True.

        Args:
            name: имя процесса.

        Returns:
            True если снятие прошло без ошибок (включая no-op).
        """
        ok = True
        try:
            self._memory_manager.release_process_memory(name)
        except Exception as e:
            self._log_error(f"unregister_process('{name}'): release SHM failed: {e}")
            ok = False

        try:
            self._process_state_registry.unregister_process(name)
        except Exception as e:
            self._log_error(f"unregister_process('{name}'): PSR unregister failed: {e}")
            ok = False

        try:
            self._config_store.remove(name)
        except Exception as e:
            self._log_error(f"unregister_process('{name}'): config remove failed: {e}")
            ok = False

        if ok:
            self._log_info(f"Process '{name}' unregistered from SRM")
        return ok

    def _normalize_memory_names(self, memory_names: Dict[str, Any]) -> Dict[str, tuple]:
        """
        Нормализовать memory names к (num_images, shape, dtype).
        Короткий формат (h, w, c) → (1, (h,w,c), "uint8").
        """
        result: Dict[str, tuple] = {}
        for name, spec in memory_names.items():
            if not isinstance(spec, tuple):
                continue
            if len(spec) == 3:
                if isinstance(spec[1], tuple):
                    result[name] = spec
                elif all(isinstance(x, (int, float)) for x in spec):
                    result[name] = (1, spec, "uint8")
            else:
                result[name] = spec
        return result

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
    # Handle API — единый паттерн доступа к ресурсам
    # =========================================================================

    def for_process(self, name: str) -> ProcessHandle:
        """
        Получить unified handle к ресурсам процесса.

        Имя `for_process`, а не `process`: у BaseManager уже есть атрибут `self.process`
        (ссылка на родительский ProcessModule), он перекрыл бы метод `process()`.

        Использование:
            handle = srm.for_process("worker")
            handle.queue("system").send(msg)
            handle.event("stop").set()
            handle.memory("frame").write(images, index=0)

        Raises:
            KeyError: если процесс не зарегистрирован.
        """
        if not self._process_state_registry.has_process(name):
            raise KeyError(
                f"Process '{name}' not registered. Available: {self._process_state_registry.get_process_names()}"
            )
        return ProcessHandle(name, self)

    def has_process(self, name: str) -> bool:
        """Проверить, зарегистрирован ли процесс."""
        return self._process_state_registry.has_process(name)

    def broadcast(
        self,
        message: Any,
        queue_type: str = "system",
        exclude: Optional[str] = None,
    ) -> int:
        """Разослать сообщение всем процессам. Возвращает количество доставок."""
        return self._queue_registry.broadcast_message(message, queue_type=queue_type, exclude_process=exclude)

    def get_all_statuses(self) -> Dict[str, ProcessStatus]:
        """Получить статусы всех процессов."""
        return {name: pd.status for name, pd in self._process_state_registry.get_all_process_data().items()}

    # =========================================================================
    # Properties — внутренние менеджеры (deprecated, используйте srm.for_process())
    # =========================================================================

    @property
    def config_store(self) -> ConfigStore:
        """Deprecated. Для конфига используйте srm.for_process(name).config."""
        return self._config_store

    @property
    def process_state_registry(self) -> ProcessStateRegistry:
        """Deprecated. Для данных используйте srm.for_process(name).data."""
        return self._process_state_registry

    @property
    def queue_registry(self) -> QueueRegistry:
        """Deprecated. Используйте srm.for_process(name).queue(type)."""
        return self._queue_registry

    @property
    def event_manager(self) -> EventManager:
        """Deprecated. Используйте srm.for_process(name).event(name)."""
        return self._event_manager

    @property
    def memory_manager(self) -> MemoryManager:
        """Deprecated. Используйте srm.for_process(name).memory(name)."""
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
            "_log_method",
            "_log_method_internal",
            "_log",
            "_record_metric_method",
            "_track_error_method",
            "_call_manager",
        )
        if name in _PICKLE_SKIP or name.startswith(("_log_", "_record_", "_track_")):
            return _noop
        if name.startswith("_") or name in (
            "_process_state_registry",
            "_event_manager",
            "_queue_registry",
            "_memory_manager",
            "_config_store",
            "get_stats",
            "__dict__",
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
