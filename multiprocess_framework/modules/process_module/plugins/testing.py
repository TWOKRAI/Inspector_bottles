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


class MockDocumentSink:
    """Дубль стока плоскости документов (Ф8.7), умеющий ОТКАЗЫВАТЬ.

    Дубль, который всегда успешен, глушит гейт: путь вердикта «записан» и путь
    «сток отказал» выглядели бы для теста одинаково, а различает их именно
    ``write_document`` — возвратом ``False`` и счётчиком потери. Поэтому у дубля
    есть ``refuse``, а отказы он считает так же, как настоящий стор (``dropped``).

    Args:
        refuse: отказывать в записи (``append`` вернёт ``False``).
        raises: вместо отказа поднимать исключение — третий исход настоящего
            стора (сбой хранилища), который ``write_document`` обязан пережить,
            не роняя линию.
    """

    def __init__(self, *, refuse: bool = False, raises: BaseException | None = None) -> None:
        self.refuse = refuse
        self.raises = raises
        #: Принятые документы — по ним тест судит СОДЕРЖИМОЕ конверта, а не факт вызова.
        self.documents: list[dict[str, Any]] = []
        #: Отказы. Имя как у настоящего стора: ``document_plane_report`` читает его.
        self.dropped = 0

    def append(self, document: dict[str, Any]) -> bool:
        if self.raises is not None:
            raise self.raises
        if self.refuse:
            self.dropped += 1
            return False
        self.documents.append(dict(document))
        return True


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
        document_sink: Сток плоскости документов (Ф8.7). ``None`` по умолчанию —
            «плоскость не настроена», ровно как у процесса без секции
            ``observability.documents``; ``write_document`` тогда вернёт ``False``
            и посчитает документ в ``without_sink``. Чтобы судить путь вердикта,
            передай :class:`MockDocumentSink` — он умеет и принять, и отказать.
    """

    def __init__(
        self,
        name: str = "mock",
        config: dict[str, Any] | None = None,
        router_manager: Any = None,
        memory_manager: Any = None,
        state_proxy: Any = None,
        document_sink: Any = None,
    ) -> None:
        self.name: str = name
        # Ф8.7 / задача 4.2 (Н-9): атрибут ЕСТЬ всегда, значение может быть None.
        # До 4.2 дубль стока не имел вовсе — дорога документов не судилась ни одним
        # тестом плагина: пройти её было нечем, а отказать тем более.
        self.document_sink: Any = document_sink

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

    def _record(self, level: str, msg: str, kwargs: dict[str, Any]) -> None:
        """Записать вызов ВМЕСТЕ с kwargs (A2).

        Прежде дубль молча выбрасывал ``**kwargs`` — а именно там едет
        ``module=`` со штампом имени плагина (Ф2.1). Значит свойство «запись
        приходит под именем плагина, а не процесса» не мог проверить ни один
        тест: дубль всегда «успешен», потому что не умеет потерять то, чего не
        хранит. Дубль обязан уметь отказывать.
        """
        entry: dict[str, Any] = {"level": level, "msg": msg}
        entry.update(kwargs)
        self.logs.append(entry)

    def log_debug(self, msg: str, **kwargs: Any) -> None:
        """Записать DEBUG-сообщение в self.logs."""
        self._record("DEBUG", msg, kwargs)

    def log_info(self, msg: str, **kwargs: Any) -> None:
        """Записать INFO-сообщение в self.logs."""
        self._record("INFO", msg, kwargs)

    def log_warning(self, msg: str, **kwargs: Any) -> None:
        """Записать WARNING-сообщение в self.logs."""
        self._record("WARNING", msg, kwargs)

    def log_error(self, msg: str, **kwargs: Any) -> None:
        """Записать ERROR-сообщение в self.logs."""
        self._record("ERROR", msg, kwargs)

    def log_critical(self, msg: str, **kwargs: Any) -> None:
        """Записать CRITICAL-сообщение в self.logs."""
        self._record("CRITICAL", msg, kwargs)

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
