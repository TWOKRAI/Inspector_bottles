"""Mock-реализация IProcessServices для тестирования плагинов.

Позволяет тестировать плагины изолированно, без поднятия ProcessModule.

Использование::

    from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
    from multiprocess_framework.modules.process_module.plugins.base import PluginContext

    services = MockProcessServices(name="test")
    ctx = PluginContext(services=services, config={"key": "val"})
    plugin = MyPlugin()
    plugin.configure(ctx)
    assert plugin.state == PluginState.READY

    # Проверка вызовов
    assert services.worker_manager.calls["create_worker"][0] == ("my_worker",)
    assert any("started" in msg for msg in services.logs)
"""

from __future__ import annotations

from typing import Any, Callable


# ---------------------------------------------------------------------------
# Mock-менеджеры
# ---------------------------------------------------------------------------


class MockWorkerManager:
    """No-op менеджер воркеров с записью всех вызовов для assert-проверок."""

    def __init__(self) -> None:
        # Словарь вызовов: имя_метода → list[tuple[args...]]
        self.calls: dict[str, list[tuple[Any, ...]]] = {
            "create_worker": [],
            "pause_worker": [],
            "resume_worker": [],
            "start_worker": [],
            "is_worker_running": [],
        }

    def create_worker(
        self,
        worker_name: str,
        target: Callable,
        config: Any = None,
        auto_start: bool = True,
    ) -> None:
        """Записать вызов create_worker."""
        self.calls["create_worker"].append((worker_name, target, config, auto_start))

    def pause_worker(self, worker_name: str) -> None:
        """Записать вызов pause_worker."""
        self.calls["pause_worker"].append((worker_name,))

    def resume_worker(self, worker_name: str) -> None:
        """Записать вызов resume_worker."""
        self.calls["resume_worker"].append((worker_name,))

    def start_worker(self, worker_name: str) -> None:
        """Записать вызов start_worker."""
        self.calls["start_worker"].append((worker_name,))

    def is_worker_running(self, worker_name: str) -> bool:
        """Записать вызов is_worker_running, вернуть False."""
        self.calls["is_worker_running"].append((worker_name,))
        return False


class MockCommandManager:
    """No-op менеджер команд — записывает зарегистрированные команды."""

    def __init__(self) -> None:
        # Словарь зарегистрированных команд: имя → handler
        self.commands: dict[str, Callable] = {}

    def register_command(self, name: str, handler: Callable, **kwargs: Any) -> None:
        """Зарегистрировать команду (сохраняет для последующей проверки)."""
        self.commands[name] = handler


# ---------------------------------------------------------------------------
# MockProcessServices
# ---------------------------------------------------------------------------


class MockProcessServices:
    """Лёгкий mock IProcessServices для изолированного тестирования плагинов.

    Не требует поднятия ProcessModule, multiprocessing, очередей и т.д.
    Все менеджеры — mock-объекты, записывающие вызовы.

    Args:
        name: Имя процесса (по умолчанию «mock»).
        config: Словарь конфигурации, доступный через get_config().
        router_manager: Можно передать кастомный mock RouterManager.
        memory_manager: Можно передать кастомный mock MemoryManager.
        state_proxy: Можно передать кастомный StateProxy.
    """

    def __init__(
        self,
        name: str = "mock",
        config: dict[str, Any] | None = None,
        router_manager: Any = None,
        memory_manager: Any = None,
        state_proxy: Any = None,
    ) -> None:
        self.name: str = name

        # Менеджеры (создаются автоматически)
        self.worker_manager: MockWorkerManager = MockWorkerManager()
        self.command_manager: MockCommandManager = MockCommandManager()
        self.router_manager: Any = router_manager
        self.memory_manager: Any = memory_manager
        self.state_proxy: Any = state_proxy

        # Внутренний конфиг для get_config()
        self._config: dict[str, Any] = config or {}

        # Журнал лог-сообщений: каждая запись — dict с level и msg
        self.logs: list[dict[str, str]] = []

        # Очередь исходящих сообщений (для проверки в тестах)
        self.sent_messages: list[dict[str, Any]] = []

    # --- Логирование ---

    def log_info(self, msg: str, **kwargs: Any) -> None:
        """Записать INFO-сообщение в self.logs."""
        self.logs.append({"level": "INFO", "msg": msg})

    def log_warning(self, msg: str, **kwargs: Any) -> None:
        """Записать WARNING-сообщение в self.logs."""
        self.logs.append({"level": "WARNING", "msg": msg})

    def log_error(self, msg: str, **kwargs: Any) -> None:
        """Записать ERROR-сообщение в self.logs."""
        self.logs.append({"level": "ERROR", "msg": msg})

    # --- IPC ---

    def send_message(self, target: str, message: dict) -> bool:
        """Записать исходящее сообщение в self.sent_messages, вернуть True."""
        self.sent_messages.append({"target": target, "message": message})
        return True

    def receive_message(self, timeout: float | None = None) -> dict | None:
        """Нет входящих сообщений — всегда возвращает None."""
        return None

    # --- Конфигурация ---

    def get_config(self, key: str, default: Any = None) -> Any:
        """Вернуть значение из внутреннего конфига по ключу."""
        return self._config.get(key, default)
