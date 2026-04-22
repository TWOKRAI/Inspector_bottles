"""
QueueRegistry — создание и доступ к очередям процессов.

PSR (ProcessStateRegistry) — единственный source of truth для Queue ссылок.
QueueRegistry делегирует хранение в PSR.

Pickle-safe: Queue ссылки живут в ProcessData (pickle-safe).
"""

import time
from multiprocessing import Queue
from typing import Any, Dict, List, Optional

from ....base_manager import BaseManager, ObservableMixin
from ..interfaces import IQueueRegistry
from ...mixins import ManagerStatsMixin

try:
    from multiprocessing.queues import Empty
except ImportError:
    from queue import Empty


class QueueRegistry(BaseManager, ObservableMixin, IQueueRegistry, ManagerStatsMixin):
    """
    Реестр очередей для межпроцессного взаимодействия.

    Создаёт Queue объекты и регистрирует их в PSR.
    PSR — единственный source of truth (ADR-018).
    """

    def __init__(
        self,
        manager_name: str = "QueueRegistry",
        process: Optional[Any] = None,
        process_state_registry: Optional[Any] = None,
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

        self._process_state_registry = process_state_registry
        # Queue refs хранятся в PSR (ProcessData._queues_dict) — единственный source of truth

        self._stats = {"created": 0, "registered": 0, "removed": 0, "errors": 0}

    # =========================================================================
    # Жизненный цикл
    # =========================================================================

    def initialize(self) -> bool:
        try:
            self.is_initialized = True
            self._log_info(f"QueueRegistry '{self.manager_name}' initialized")
            return True
        except Exception as e:
            self._log_error(f"QueueRegistry.initialize() failed: {e}")
            return False

    def shutdown(self) -> bool:
        try:
            self.is_initialized = False
            self._log_info("QueueRegistry shutdown completed")
            return True
        except Exception as e:
            self._log_error(f"QueueRegistry.shutdown() failed: {e}")
            return False

    # =========================================================================
    # IQueueRegistry
    # =========================================================================

    def create_queues(
        self,
        queue_config: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Queue]:
        """Создать Queue объекты по конфигурации."""
        if not queue_config:
            return {}
        queues: Dict[str, Queue] = {}
        try:
            for queue_type, cfg in queue_config.items():
                maxsize = cfg.get("maxsize", 0) if isinstance(cfg, dict) else 0
                queues[queue_type] = Queue(maxsize=maxsize)
                self._stats["created"] += 1
        except Exception as e:
            self._log_error(f"create_queues() failed: {e}")
            self._stats["errors"] += 1
        return queues

    def register_process_queues(
        self,
        process_name: str,
        queues: Dict[str, Queue],
    ) -> bool:
        """Зарегистрировать очереди в PSR (единственный source of truth)."""
        try:
            self._stats["registered"] += len(queues)
            if self._process_state_registry:
                for queue_type, queue in queues.items():
                    self._process_state_registry.add_queue(process_name, queue_type, queue)
            self._log_debug(f"Registered {len(queues)} queues for '{process_name}'")
            return True
        except Exception as e:
            self._log_error(f"register_process_queues('{process_name}') failed: {e}")
            self._stats["errors"] += 1
            return False

    def create_and_register_queues(
        self,
        process_name: str,
        queue_config: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Queue]:
        """Создать и зарегистрировать очереди для процесса."""
        queues = self.create_queues(queue_config)
        if queues:
            self.register_process_queues(process_name, queues)
        return queues

    def get_queue(self, process_name: str, queue_type: str) -> Optional[Queue]:
        """Получить очередь из PSR."""
        if self._process_state_registry:
            return self._process_state_registry.get_queue(process_name, queue_type)
        return None

    def get_process_queues(self, process_name: str) -> Dict[str, Queue]:
        """Получить все очереди процесса из PSR."""
        if self._process_state_registry:
            pd = self._process_state_registry.get_process_data(process_name)
            if pd:
                return dict(pd.queues.items())
        return {}

    def send_to_queue(
        self,
        process_name: str,
        queue_type: str,
        message: Any,
        timeout: float = 0.0,
    ) -> bool:
        queue = self.get_queue(process_name, queue_type)
        if queue is None:
            self._log_warning(f"Queue '{queue_type}' not found for '{process_name}'")
            return False
        try:
            self.remove_old_if_full(queue)
            if timeout > 0:
                queue.put(message, timeout=timeout)
            else:
                queue.put_nowait(message)
            return True
        except Exception as e:
            self._log_error(f"send_to_queue('{process_name}', '{queue_type}') failed: {e}")
            self._stats["errors"] += 1
            return False

    def receive_from_queue(
        self,
        process_name: str,
        queue_type: str,
        timeout: float = 0.0,
    ) -> Optional[Any]:
        queue = self.get_queue(process_name, queue_type)
        if queue is None:
            return None
        try:
            return queue.get(timeout=timeout) if timeout > 0 else queue.get_nowait()
        except Empty:
            return None
        except Exception as e:
            self._log_error(f"receive_from_queue('{process_name}', '{queue_type}') failed: {e}")
            self._stats["errors"] += 1
            return None

    def broadcast_message(
        self,
        message: Any,
        queue_type: str = "system",
        exclude_process: Optional[str] = None,
    ) -> int:
        """Разослать сообщение всем процессам через PSR."""
        if not self._process_state_registry:
            return 0
        sent = 0
        for process_name in list(self._process_state_registry.get_process_names()):
            if exclude_process and process_name == exclude_process:
                continue
            if self.send_to_queue(process_name, queue_type, message):
                sent += 1
        return sent

    def get_queue_sizes(self) -> Dict[str, Dict[str, int]]:
        sizes: Dict[str, Dict[str, int]] = {}
        if not self._process_state_registry:
            return sizes
        for process_name in self._process_state_registry.get_process_names():
            pd = self._process_state_registry.get_process_data(process_name)
            if not pd:
                continue
            sizes[process_name] = {}
            for queue_type in pd.queues:
                queue = pd.get_queue(queue_type)
                if queue is None:
                    continue
                try:
                    sizes[process_name][queue_type] = queue.qsize()
                except (NotImplementedError, OSError, AttributeError):
                    sizes[process_name][queue_type] = 0
        return sizes

    def remove_process_queues(self, process_name: str) -> bool:
        """Удалить процесс из PSR (unregister) — только статистика; PSR чистит SRM/PSR."""
        if self._process_state_registry and self._process_state_registry.has_process(process_name):
            self._stats["removed"] += 1
            return True
        return False

    def get_registered_processes(self) -> List[str]:
        if self._process_state_registry:
            return self._process_state_registry.get_process_names()
        return []

    # =========================================================================
    # Утилиты
    # =========================================================================

    def clear_queue(self, queue: Queue, keep_elements: int = 0) -> None:
        """Надёжная очистка очереди (Windows-safe: не использует queue.empty()).
        Учитывает асинхронность multiprocessing.Queue на macOS/spawn — повторный
        проход после короткой паузы для «задержанных» элементов."""
        saved = []
        try:
            for _ in range(10_000):
                try:
                    saved.append(queue.get_nowait())
                except Empty:
                    break
            # Повторный проход для macOS: put() может быть асинхронным
            for _ in range(3):
                time.sleep(0.05)
                for _ in range(1_000):
                    try:
                        saved.append(queue.get_nowait())
                    except Empty:
                        break
            if keep_elements > 0 and len(saved) > keep_elements:
                saved = saved[-keep_elements:]
            elif keep_elements == 0:
                saved = []
            for item in saved:
                queue.put(item)
        except Exception as e:
            self._log_error(f"clear_queue() failed: {e}")
            self._stats["errors"] += 1

    def remove_old_if_full(self, queue: Queue) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except Empty:
                pass

    # =========================================================================
    # Статистика
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        process_names = self.get_registered_processes()
        total = 0
        if self._process_state_registry:
            for p in process_names:
                pd = self._process_state_registry.get_process_data(p)
                if pd:
                    total += len(pd.queues)
        queue_stats = {
            **self._stats,
            "total_queues": total,
            "processes_count": len(process_names),
            "processes": process_names,
        }
        return self._merge_stats("queues", queue_stats)
