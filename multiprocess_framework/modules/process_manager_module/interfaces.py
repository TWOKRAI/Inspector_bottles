"""
Публичные контракты process_manager_module.

Правило: внешние модули импортируют только из interfaces.py, не из внутренних подпакетов.

Контракты:
    ISystemLauncher          — фасад запуска системы процессов
    IProcessManagerProcess   — оркестратор процессов
    IProcessRegistry         — реестр процессов ОС + lifecycle
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class ISystemLauncher(ABC):
    """
    Контракт фасада запуска системы процессов.

    Dict at Boundary: add_process принимает только (name, dict).
    Конвертация SchemaBase → dict выполняется в app-слое.

    Пример:
        launcher = SystemLauncher()
        launcher.add_process("Worker1", {"class": "my_module.Worker1", ...})
        launcher.run()
    """

    @abstractmethod
    def add_process(self, name: str, proc_dict: Dict[str, Any]) -> "ISystemLauncher":
        """
        Добавить процесс для запуска.

        Args:
            name: Уникальное имя процесса (ключ в processes_config).
            proc_dict: Конфиг процесса — {"class": "...", "queues": {...}, ...}.

        Returns:
            self для цепочки вызовов.
        """
        ...

    @abstractmethod
    def run(self) -> None:
        """Запустить систему и ожидать завершения (блокирующий вызов)."""
        ...

    @abstractmethod
    def start(self) -> None:
        """Запустить систему без ожидания (неблокирующий вызов)."""
        ...

    @abstractmethod
    def wait_until_ready(self, timeout: float) -> bool:
        """
        Блокирующее ожидание готовности системы.

        Возвращает True, если ProcessManagerProcess завершил инициализацию
        (все дочерние процессы spawned и запущены) в течение timeout секунд.
        False — если истёк таймаут или ProcessManager упал.

        Args:
            timeout: Максимальное время ожидания (секунды).

        Returns:
            True если система готова, False если таймаут или ошибка.
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """Остановить систему (graceful shutdown)."""
        ...

    @abstractmethod
    def shutdown(self) -> None:
        """Алиас для stop(). Для совместимости с lifecycle-интерфейсами."""
        ...

    @abstractmethod
    def wait(self) -> None:
        """Ожидать завершения ProcessManagerProcess."""
        ...

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """
        Статус системы.

        Returns:
            Dict с полями: spawner_running, process, registered_processes.
        """
        ...

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """
        Статистика системы.

        Returns:
            Dict с полями: spawner, shared_resources.
        """
        ...


class IProcessManagerProcess(ABC):
    """
    Контракт оркестратора процессов.

    ProcessManagerProcess управляет жизненным циклом всех дочерних процессов.
    Наследуется от ProcessModule, работает внутри отдельного OS-процесса.

    Порядок shutdown:
        ProcessMonitor → ProcessRegistry.stop_all → WorkerManager → ConsoleManager → super
    """

    @abstractmethod
    def create_process(
        self,
        name: str,
        class_path: str,
        config: Optional[Dict[str, Any]],
        priority: str,
    ) -> Any:
        """
        Создать и зарегистрировать дочерний процесс.

        Args:
            name: Имя процесса.
            class_path: Полный путь к классу (например, 'my_module.MyProcess').
            config: Конфиг процесса (dict).
            priority: Приоритет ('low', 'normal', 'high', 'realtime').

        Returns:
            Process ОС или None при ошибке.
        """
        ...

    @abstractmethod
    def start_process(self, process_name: str) -> bool:
        """
        Запустить именованный процесс.

        Args:
            process_name: Имя процесса.

        Returns:
            True если запущен успешно.
        """
        ...

    @abstractmethod
    def stop_process(self, process_name: Optional[str] = None) -> bool:
        """
        Остановить именованный процесс (per-process stop_event) или все.

        Args:
            process_name: Имя процесса; None — остановить все дочерние процессы.

        Returns:
            True при успехе.
        """
        ...

    @abstractmethod
    def restart_process(self, process_name: str) -> bool:
        """
        Перезапустить процесс: stop → recreate → start (нужен сохранённый конфиг).

        Args:
            process_name: Имя процесса.

        Returns:
            True если перезапуск выполнен.
        """
        ...

    @abstractmethod
    def get_process_status(self, process_name: str) -> Dict[str, Any]:
        """
        Получить статус именованного процесса.

        Args:
            process_name: Имя процесса.

        Returns:
            Dict со статусом или {} если процесс не найден.
        """
        ...

    @abstractmethod
    def get_all_processes_status(self) -> Dict[str, Dict[str, Any]]:
        """
        Получить статусы всех процессов.

        Returns:
            Dict[process_name, status_dict].
        """
        ...


class IProcessRegistry(ABC):
    """
    Контракт реестра процессов ОС.

    Хранит список OS-процессов, управляет их lifecycle (start, stop, join).
    Создаёт процессы через run_process_function (pickle-safe).
    """

    @abstractmethod
    def add_process(self, process: Any) -> None:
        """
        Добавить готовый Process ОС в реестр.

        Args:
            process: multiprocessing.Process.
        """
        ...

    @abstractmethod
    def get_process_by_name(self, name: str) -> Optional[Any]:
        """
        Получить Process ОС по имени.

        Args:
            name: Имя процесса.

        Returns:
            Process или None.
        """
        ...

    @abstractmethod
    def create_and_register(
        self,
        name: str,
        class_path: str,
        config: Optional[Dict[str, Any]],
        priority: str,
    ) -> Optional[Any]:
        """
        Создать Process ОС и добавить в реестр.

        Args:
            name: Имя процесса.
            class_path: Полный путь к классу.
            config: Конфиг процесса (dict).
            priority: Приоритет.

        Returns:
            Process ОС или None при ошибке.
        """
        ...

    @abstractmethod
    def start_all(self) -> None:
        """Запустить все зарегистрированные процессы."""
        ...

    @abstractmethod
    def stop_all(self, timeout: float) -> None:
        """
        Graceful остановка всех процессов.

        Каскад: для каждого процесса свой stop_event → join(timeout) → terminate → kill.

        Args:
            timeout: Время ожидания join для каждого процесса (секунды).
        """
        ...

    @abstractmethod
    def stop_one(self, name: str, timeout: float = 5.0) -> bool:
        """Остановить один процесс (только его stop_event)."""
        ...

    @abstractmethod
    def remove_process(self, name: str) -> None:
        """Удалить запись из реестра (после остановки), освободить stop_event."""
        ...
