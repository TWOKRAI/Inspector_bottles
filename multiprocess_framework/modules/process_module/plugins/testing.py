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


class MockStatsManager:
    """Дубль ``StatsManager`` для плоскости stats (этап 6, 1.1), умеющий ОТКАЗЫВАТЬ.

    Тот же довод, что у :class:`MockDocumentSink` строкой выше: дубль,
    который всегда успешен, глушит гейт. У метрики нет возврата, поэтому
    отличить «записано» от «сбой учёта» можно только по тому, что фасад
    сказал в журнал — а сказать ему не о чем, если дубль не умеет падать.

    Записи хранятся списком в порядке вызова: тест судит СОДЕРЖИМОЕ (род,
    имя, значение, теги — в т.ч. автоштамп ``plugin``), а не факт вызова.

    Args:
        raises: поднимать это исключение на каждой записи — исход, который
            фасад обязан пережить, не роняя линию.
    """

    def __init__(self, *, raises: BaseException | None = None) -> None:
        self.raises = raises
        #: ``[(род, имя, значение, теги), …]`` — род берётся из имени метода,
        #: как и у настоящего менеджера: строкового параметра рода нет нигде.
        self.records: list[tuple[str, str, Any, dict | None]] = []

    def _put(self, kind: str, name: str, value: Any, tags: dict | None) -> None:
        if self.raises is not None:
            raise self.raises
        self.records.append((kind, name, value, dict(tags) if tags is not None else None))

    def record_metric(self, name: str, value: Any = 1, tags: dict | None = None) -> None:
        self._put("counter", name, value, tags)

    def gauge(self, name: str, value: float, tags: dict | None = None) -> None:
        self._put("gauge", name, value, tags)

    def record_timing(self, name: str, duration: float, tags: dict | None = None) -> None:
        self._put("timing", name, duration, tags)

    def histogram(self, name: str, value: float, tags: dict | None = None) -> None:
        self._put("histogram", name, value, tags)


class _MockObservationPort:
    """Тестовый двойник порта наблюдений — числа фасада форвардит в ``stats_manager``.

    Ф5, задача 5.2: ``PluginContext`` больше не пишет в
    ``services.stats_manager`` напрямую — четвёрка едет через порт
    (``_observation_port(create=False)``, резолвер
    ``observation_manager.observation_port``, ступень 1: ``services.get_manager("observation")``).
    Существующий парк тестов дороги 1 (``test_plugin_stats_road.py``,
    ``test_stats_connector_acceptance.py``) строит
    ``MockProcessServices(stats_manager=...)`` и судит СОДЕРЖИМОЕ записей у
    :class:`MockStatsManager` — их контракт про то, ЧТО дошло, а не ЧЕРЕЗ ЧТО
    именно. Этот двойник — тестовый аналог боевой проводки
    ``ProcessManagers.create_all`` (``stats.attach_observation_port(observation)``):
    прямой форвард без CRM/tap-механики, чтобы существующий парк остался
    про контракт фасада, а не про внутренний механизм доставки Ф5.

    ``collect_subtree`` — не для доставки чисел, а для того, чтобы
    РЕЗОЛВЕР (``observation_port()``) вообще принял этот объект: ступень 1
    отбирает менеджера по протоколу (``callable(getattr(manager,
    "collect_subtree", None))``), тем же доводом, что у
    ``ObservableMixin._manager_has_method`` — без метода двойник считался бы
    посторонним объектом и резолвер провалился бы на ступень 2 (уровни, не
    числа), где стенду взяться неоткуда.
    """

    __slots__ = ("_stats",)

    def __init__(self, stats_manager: Any) -> None:
        self._stats = stats_manager

    def collect_subtree(self, allowed_metrics: Any = None) -> dict:
        return {}

    def record_metric(self, name: str, value: Any = 1, tags: dict | None = None) -> None:
        self._stats.record_metric(name, value, tags)

    def increment(self, name: str, tags: dict | None = None) -> None:
        self.record_metric(name, 1, tags)

    def record_timing(self, name: str, duration: float, tags: dict | None = None) -> None:
        self._stats.record_timing(name, duration, tags)

    def gauge(self, name: str, value: float, tags: dict | None = None) -> None:
        self._stats.gauge(name, value, tags)

    def histogram(self, name: str, value: float, tags: dict | None = None) -> None:
        self._stats.histogram(name, value, tags)


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
        stats_manager: Менеджер плоскости stats (этап 6, 1.1). ``None`` по
            умолчанию — «плоскости нет», ровно как у процесса без
            ``StatsManager``: четвёрка тогда считает метрику в
            ``stats.without_plane`` и говорит один раз. Чтобы судить путь
            метрики, передай :class:`MockStatsManager`.
        event_selector: Селектор широких записей (Ф4, 4.1). ``None`` по
            умолчанию — «сшивки не было»: ``write_event`` тогда пишет фронты
            (``decisive=True``) и не пишет поток, ровно как настроенный селектор
            с дефолтом ``first_n=0, every_mth=0``. Чтобы судить лесенку отбора,
            передай настоящий ``WideEventSelector`` — фальшивка-всегда-успех
            заглушила бы ровно то свойство, которое проверяют.
        flight_recorder: Рекордер дампов кольца (Ф5, 5.1). ``None`` по умолчанию
            — «сшивки не было»: ``flight_dump`` тогда отвечает тем же названным
            отказом, что и выключённый рекордер (Р5.1-5 — у «выключено» одно
            состояние). Чтобы судить дорогу дампа, передай настоящий
            ``FlightRecorder``: он читает кольцо через ``logger_manager``, и
            фальшивка-всегда-успех заглушила бы именно ту дорогу.
        plugin_levels: Хранилище уровней дерева состояния (Task 3.5). ``None`` по
            умолчанию — и это не «плоскости нет», а нормальный старт: хранилище
            создаётся лениво на первом ``ctx.publish_metric``. Передавай готовый
            ``PluginLevels`` только чтобы заглянуть в него из теста, не поднимая
            ``ProcessHeartbeat``.
    """

    def __init__(
        self,
        name: str = "mock",
        config: dict[str, Any] | None = None,
        router_manager: Any = None,
        memory_manager: Any = None,
        state_proxy: Any = None,
        document_sink: Any = None,
        stats_manager: Any = None,
        event_selector: Any = None,
        flight_recorder: Any = None,
        plugin_levels: Any = None,
        logger_manager: Any = None,
    ) -> None:
        self.name: str = name
        # Ф8.7 / задача 4.2 (Н-9): атрибут ЕСТЬ всегда, значение может быть None.
        # До 4.2 дубль стока не имел вовсе — дорога документов не судилась ни одним
        # тестом плагина: пройти её было нечем, а отказать тем более.
        self.document_sink: Any = document_sink
        # Этап 6, 1.1: тот же довод, что у стока строкой выше — атрибут ЕСТЬ
        # всегда, значение может быть None. Без атрибута дубль перестал бы
        # удовлетворять IProcessServices, который порт объявил.
        self.stats_manager: Any = stats_manager
        # Ф4 (4.1): третий порт с тем же доводом — атрибут ЕСТЬ всегда, значение
        # может быть None. Без атрибута дубль перестал бы удовлетворять протоколу.
        self.event_selector: Any = event_selector
        # Ф5 (5.1): четвёртый порт с тем же доводом — атрибут ЕСТЬ всегда,
        # значение может быть None. Без атрибута дубль перестал бы удовлетворять
        # IProcessServices, который порт объявил.
        self.flight_recorder: Any = flight_recorder
        # Task 3.5: пятый порт с тем же доводом — атрибут ЕСТЬ всегда, значение
        # может быть None. ``None`` здесь ещё и штатный старт: хранилище уровней
        # создаётся лениво на первом ``ctx.publish_metric``, и дубль обязан этот
        # путь пройти, а не получить готовое хранилище задаром.
        self.plugin_levels: Any = plugin_levels
        # Task Т.1: шестой порт с тем же доводом — атрибут ЕСТЬ всегда, значение
        # может быть None. Без атрибута дубль перестал бы удовлетворять
        # IProcessServices, который порт объявил.
        self.logger_manager: Any = logger_manager
        # Ф5, задача 5.2: седьмой порт, тем же доводом. ``None`` при
        # ``stats_manager=None`` — «плоскости нет» ровно как раньше (см.
        # :class:`_MockObservationPort`): без него ``get_manager("observation")``
        # отдавал бы объект, форвардящий в ``None``, и падал бы там, где раньше
        # штатно срабатывал ``note_metric_without_plane``.
        self._observation_port_double: Any = _MockObservationPort(stats_manager) if stats_manager is not None else None

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

    # --- Слоты менеджеров (Ф5, задача 5.2) ---

    def get_manager(self, name: str) -> Any:
        """Слот-резолвер — сегодня отвечает ТОЛЬКО за ``"observation"``.

        Единственный вызывающий у боевого кода —
        ``PluginContext._observation_port`` (через резолвер
        ``observation_manager.observation_port``, ступень 1). Остальные
        менеджеры дубль отдаёт своими прямыми атрибутами
        (``services.worker_manager`` и т.д.) — заводить для них слот-резолвер
        значило бы вторую дорогу к тем же объектам без единого читателя.
        """
        if name == "observation":
            return self._observation_port_double
        return None

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
