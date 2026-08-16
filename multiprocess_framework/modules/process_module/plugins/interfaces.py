"""Контракты (Protocol) между plugin-системой и ProcessModule.

Назначение:
- IProcessServices — главный контракт, которому удовлетворяет ProcessModule
  через structural subtyping (без изменения его кода).
- IPluginWorkerManager, IPluginCommandManager, IPluginRouter, IPluginMemoryManager,
  IPluginStatsManager — узкие контракты отдельных менеджеров, используемых плагинами.

Все Protocol-ы @runtime_checkable — можно использовать в assert-проверках dev-режима::

    assert isinstance(process, IProcessServices), "ожидается IProcessServices"

Для тестов используйте MockProcessServices вместо реального ProcessModule.
"""

from __future__ import annotations

from typing import Any, Callable, runtime_checkable
from typing import Protocol


# ---------------------------------------------------------------------------
# Менеджеры
# ---------------------------------------------------------------------------


@runtime_checkable
class IPluginWorkerManager(Protocol):
    """Контракт WorkerManager для плагинов.

    Плагины создают/управляют воркерами только через этот интерфейс.
    WorkerManager в ProcessModule удовлетворяет Protocol structural subtyping.
    """

    def create_worker(
        self,
        worker_name: str,
        target: Callable,
        config: Any = None,
        auto_start: bool = True,
    ) -> None:
        """Создать воркер с заданным target-callable."""
        ...

    def pause_worker(self, worker_name: str) -> None:
        """Приостановить воркер по имени."""
        ...

    def resume_worker(self, worker_name: str) -> None:
        """Возобновить воркер по имени."""
        ...

    def start_worker(self, worker_name: str) -> None:
        """Запустить воркер по имени."""
        ...

    def is_worker_running(self, worker_name: str) -> bool:
        """Проверить, запущен ли воркер."""
        ...


@runtime_checkable
class IPluginCommandManager(Protocol):
    """Контракт CommandManager для плагинов.

    Плагины регистрируют команды через этот интерфейс.
    CommandManager в ProcessModule удовлетворяет Protocol structural subtyping.
    """

    def register_command(self, name: str, handler: Callable, **kwargs: Any) -> None:
        """Зарегистрировать обработчик команды по имени."""
        ...


@runtime_checkable
class IPluginRouter(Protocol):
    """Контракт RouterManager для плагинов.

    Плагины добавляют/удаляют middleware и обработчики сообщений
    только через этот интерфейс.
    RouterManager в ProcessModule удовлетворяет Protocol structural subtyping.
    """

    def add_send_middleware(self, middleware: Callable) -> None:
        """Добавить middleware для исходящих сообщений."""
        ...

    def remove_send_middleware(self, middleware: Callable) -> None:
        """Удалить middleware для исходящих сообщений."""
        ...

    def add_receive_middleware(self, middleware: Callable) -> None:
        """Добавить middleware для входящих сообщений."""
        ...

    def remove_receive_middleware(self, middleware: Callable) -> None:
        """Удалить middleware для входящих сообщений."""
        ...

    def register_message_handler(self, msg_type: str, handler: Callable) -> None:
        """Зарегистрировать обработчик для типа сообщения."""
        ...


@runtime_checkable
class IPluginStatsManager(Protocol):
    """Контракт StatsManager для плагинов — плоскость stats (этап 6, задача 1.1).

    Ровно та четвёрка, что есть у ``MetricType``: counter / gauge / timing /
    histogram. Параметра ``metric_type`` здесь нет намеренно — род метрики
    выбирается ИМЕНЕМ метода, как у ``StatsManager``; строковый род пятым
    аргументом завёл бы второе написание того же выбора.

    **Сигнатуры дословно совпадают со ``StatsManager``, включая единицы.** Это
    не стиль, а защита от уже случившегося: имя ``record_metric`` живёт в
    проекте с ДВУМЯ противоположными смыслами — у ``StatsManager`` и
    ``ObservableMixin`` это counter, у ``ObservabilityHub._emit_stat`` — gauge.
    Совпадение проверяется контракт-тестом, который сверяет
    ``inspect.signature`` этого протокола с настоящим менеджером: ``isinstance``
    у ``runtime_checkable``-протокола проверяет ТОЛЬКО имена, и расхождение
    порядка или единицы он пропустил бы молча.

    Не путать с ``plugins.metrics.PluginMetrics``: та считает время lifecycle'а
    плагина для UI и в плоскость stats не едет. Разные механизмы с похожими
    именами — поэтому названы друг через друга здесь.
    """

    def record_metric(self, name: str, value: Any = 1, tags: dict | None = None) -> None:
        """Записать счётчик (counter): прибавить ``value`` к серии ``name``."""
        ...

    def gauge(self, name: str, value: float, tags: dict | None = None) -> None:
        """Записать текущее значение (перезаписывает предыдущее в окне)."""
        ...

    def record_timing(self, name: str, duration: float, tags: dict | None = None) -> None:
        """Записать длительность. **Единица — СЕКУНДЫ**, как у ``StatsManager``.

        Миллисекунды поверх секундной модели не упали бы тестом: агрегат
        собрался бы, а границы бакетов (задача 2.2) сложили бы все кадровые
        тайминги в первый — и p95 стал бы константой при зелёном прогоне.
        """
        ...

    def histogram(self, name: str, value: float, tags: dict | None = None) -> None:
        """Записать наблюдение в распределение."""
        ...


@runtime_checkable
class IPluginMemoryManager(Protocol):
    """Контракт MemoryManager для плагинов.

    Плагины освобождают разделяемую память через этот интерфейс.
    MemoryManager в ProcessModule удовлетворяет Protocol structural subtyping.
    """

    def close_all(self, owner: str) -> None:
        """Закрыть все SHM-блоки, принадлежащие owner."""
        ...


# ---------------------------------------------------------------------------
# Главный контракт
# ---------------------------------------------------------------------------


@runtime_checkable
class IProcessServices(Protocol):
    """Контракт сервисов процесса, доступных plugin-системе.

    ProcessModule удовлетворяет этот Protocol через structural subtyping —
    менять код ProcessModule не нужно.

    Примечание о property vs атрибут:
        ProcessModule хранит менеджеры как обычные атрибуты (не property).
        Python разрешает это — structural subtyping проверяет наличие имени,
        не способ доступа к нему.

    Для тестов используйте MockProcessServices:
        class MockProcessServices:
            name = "mock"
            worker_manager = None
            ...
    """

    @property
    def name(self) -> str:
        """Имя процесса. В ProcessModule это self.name (не process_name)."""
        ...

    # --- Менеджеры (None до вызова initialize()) ---

    @property
    def worker_manager(self) -> IPluginWorkerManager | None:
        """WorkerManager или None до initialize()."""
        ...

    @property
    def command_manager(self) -> IPluginCommandManager | None:
        """CommandManager или None до initialize()."""
        ...

    @property
    def router_manager(self) -> IPluginRouter | None:
        """RouterManager или None до initialize()."""
        ...

    @property
    def memory_manager(self) -> IPluginMemoryManager | None:
        """MemoryManager или None до initialize()."""
        ...

    @property
    def stats_manager(self) -> IPluginStatsManager | None:
        """StatsManager процесса или ``None``, если плоскость stats не поднята.

        Объявлено по образцу ``document_sink`` ниже и по тому же доводу: фасад
        ``PluginContext.record_metric`` читает менеджер ИМЕННО с сервисов, и
        пока протокол о нём не знал, дорога метрик существовала бы в коде и
        отсутствовала в контракте — дубль, собранный по протоколу, менеджера
        не имел бы, и путь метрики нельзя было бы ни пройти, ни отказать.

        Своего имени этот порт не заводит: атрибут — существующий
        ``stats_manager`` процесса (``ProcessModule.__init__`` ставит его
        всегда, ``bundle.stats`` — при initialize). Второй алиас на тот же
        объект означал бы два имени одной дороги.

        ``None`` — законное состояние (процесс без плоскости), а не ошибка:
        фасад тогда считает метрику в ``stats.without_plane`` и говорит об этом
        ОДИН раз. Исключения на этом пути нет ни при какой конфигурации —
        метрика не имеет права ронять линию.
        """
        ...

    # --- Состояние (опциональное) ---

    @property
    def state_proxy(self) -> Any | None:
        """StateProxy для реактивного дерева состояния, или None."""
        ...

    # --- Логирование (публичные методы ObservableMixin) ---
    #
    # A2 (Б-2): пятёрка, а не тройка. Прежде здесь было объявлено три метода,
    # ``ObservableMixin`` имел пять, а ``PluginContext`` штамповал два — три
    # разных списка в трёх местах. Плагин, звавший ``ctx.log_warning`` в ветке
    # штатной деградации, получал ``AttributeError`` вместо предупреждения.
    # Список судится тестом, который читает его ОТСЮДА: добавление метода
    # обязано ломать проверку фасада, а не оставлять дыру.

    def log_debug(self, msg: str, **kwargs: Any) -> None:
        """Записать DEBUG-сообщение через LoggerManager процесса."""
        ...

    def log_info(self, msg: str, **kwargs: Any) -> None:
        """Записать INFO-сообщение через LoggerManager процесса."""
        ...

    def log_warning(self, msg: str, **kwargs: Any) -> None:
        """Записать WARNING-сообщение через LoggerManager процесса."""
        ...

    def log_error(self, msg: str, **kwargs: Any) -> None:
        """Записать ERROR-сообщение через LoggerManager процесса."""
        ...

    def log_critical(self, msg: str, **kwargs: Any) -> None:
        """Записать CRITICAL-сообщение через LoggerManager процесса."""
        ...

    # --- IPC ---

    def send_message(self, target: str, message: dict) -> bool:
        """Отправить dict-сообщение целевому процессу по имени."""
        ...

    def receive_message(self, timeout: float | None = None) -> dict | None:
        """Получить одно входящее сообщение (блокирующий вызов с таймаутом)."""
        ...

    # --- Конфигурация ---

    def get_config(self, key: str, default: Any = None) -> Any:
        """Получить значение конфигурации по ключу."""
        ...

    # --- Отбор широких записей (Ф4, задача 4.1) ---

    @property
    def event_selector(self) -> Any | None:
        """Живой :class:`WideEventSelector` процесса или ``None``.

        Объявлено по тому же доводу, что ``document_sink`` ниже: фасад
        ``PluginContext.write_event`` читает селектор ИМЕННО с сервисов
        (``getattr(services, EVENT_SELECTOR_ATTR)``), и пока протокол о нём не
        знает, дорога широкой записи существует в коде и отсутствует в контракте
        — дубль, собранный по протоколу, селектора не имел бы, и путь нельзя было
        бы ни пройти, ни прорядить в тесте плагина.

        ``None`` — законное состояние (сшивка не проходила: одиночный запуск,
        тест, объект без сеттеров). Поведение при нём НАЗВАНО и совпадает с
        дефолтом настроенного селектора: фронты (``decisive=True``) пишутся,
        поток — нет. Двух разных исполнений у «выключено» быть не должно.
        Атрибут обязан СУЩЕСТВОВАТЬ всегда — иначе процесс без сшивки перестал бы
        удовлетворять этому протоколу, и dev-проверка
        ``isinstance(process, IProcessServices)`` падала бы на штатной
        конфигурации (урок 4.2, дословно).
        """
        ...

    # --- Дамп кольца записей (Ф5, задача 5.1) ---

    @property
    def flight_recorder(self) -> Any | None:
        """Живой ``FlightRecorder`` процесса или ``None``.

        Объявлено ОДНОЙ правкой вместе с атрибутом класса у ``ProcessModule`` —
        урок 4.2 дословно: объявление в протоколе без атрибута ломает
        ``isinstance(process, IProcessServices)`` на штатной конфигурации, где
        сшивки не было (одиночный запуск, тестовый стенд).

        Довод тот же, что у ``event_selector`` выше: фасад
        ``PluginContext.flight_dump`` читает рекордер ИМЕННО с сервисов
        (``getattr(services, FLIGHT_RECORDER_ATTR)``), и пока протокол о нём не
        знает, дорога дампа существует в коде и отсутствует в контракте — дубль,
        собранный по протоколу, рекордера не имел бы, и путь нельзя было бы ни
        пройти, ни отказать в тесте плагина.

        ``None`` — законное состояние, и поведение при нём НАЗВАНО: то же, что у
        настроенного рекордера с ``enabled=False`` — отказ с адресом ручки
        ``observability.flight.enabled``. Двух разных исполнений у «выключено»
        быть не должно (Р5.1-5).
        """
        ...

    # --- Плоскость документов (Ф8.7, объявлена задачей 4.2 / Н-9) ---

    @property
    def document_sink(self) -> Any | None:
        """Сток плоскости документов или ``None``, если плоскость не поднята.

        Объявлено здесь, потому что ``PluginContext.write_document`` читает это
        ИМЕННО с сервисов (``getattr(services, DOCUMENT_SINK_ATTR)``). Пока
        объявления не было, дорога документов существовала в коде и отсутствовала
        в контракте: дубль, собранный по протоколу, стока не имел, значит путь
        вердикта нельзя было ни пройти, ни отказать в тесте плагина — он просто
        не судился.

        Имя атрибута — ``DOCUMENT_SINK_ATTR`` из ``managers.observability_wiring``;
        совпадение имени с этим объявлением судит контракт-тест, а не глаз: две
        рукописные копии имени разъезжаются молча.

        ``None`` — законное состояние (плоскость не настроена), а не ошибка:
        ``write_document`` в этом случае вернёт ``False`` и посчитает документ
        в ``without_sink``. Атрибут обязан СУЩЕСТВОВАТЬ всегда — иначе процесс
        без плоскости перестал бы удовлетворять этому протоколу, и dev-проверка
        ``isinstance(process, IProcessServices)`` падала бы на штатной конфигурации.
        """
        ...
