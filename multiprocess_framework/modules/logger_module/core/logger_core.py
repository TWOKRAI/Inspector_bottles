# -*- coding: utf-8 -*-
"""
LoggerCore — общий лог-слой (общий предок LoggerManager и ErrorManager).

Task 5.14 (CRM-развязка):
  - LoggerCore несёт ВСЁ тело логирования (каналы, батчинг, scope-routing,
    tap-sink'и, sink-control, frame-trace, контекст, статистику).
  - LoggerManager и ErrorManager — БРАТЬЯ через LoggerCore (композиция общего
    слоя), а НЕ Logger←Error (IS-A). Оба — потомки ChannelRoutingManager.
  - Process-wide singleton (``_instance``) живёт ТОЛЬКО на LoggerManager —
    здесь его НЕТ, чтобы создание ErrorManager не перетирало get_logger().

Наследование от ChannelRoutingManager:
  - self._channel_registry  — thread-safe хранилище каналов (IChannel)

Публичный API не изменён (info, error, log, flush, get_stats и т.д.).
"""

import itertools
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple, TYPE_CHECKING
from contextvars import ContextVar

if TYPE_CHECKING:
    from multiprocessing import Process

from ...channel_routing_module import ChannelRoutingManager, resolve_build_result
from ...channel_routing_module.interfaces import channel_accepted
from ..interfaces import ILoggerManager
from ..configs.logger_manager_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from .log_config import LogLevel, LogScope, ScopeName
from .name_hierarchy import NameHierarchy
from ...channel_routing_module.levels import UNKNOWN_SEVERITY, is_error_level, severity_of
from .error_floor import FLOOR_FILE_NAME, ErrorFloor, get_error_floor
from .log_types import LogRecord, Processor
from .redaction import SecretRedactor
from .sampling import RateSampler
from ..channels.log_channel import (
    create_channel,
    drop_memory_rings,
    enforce_log_retention,
    LogChannel,
)
from .log_paths import resolve_log_file_path
from ..utils import LogMessage, apply_format

#: Пломба (2.V1): сквозной номер записи В ПРЕДЕЛАХ ПРОЦЕССА.
#:
#: Модульный, а не по экземпляру, намеренно: у процесса ДВЕ плоскости
#: (``LoggerManager`` и ``ErrorManager`` — братья через этот же класс), и
#: сквозной номер на обе даёт проверяющему одно свойство вместо двух —
#: «объединение номеров по всем файлам процесса непрерывно». Номер по
#: экземпляру дал бы две независимые последовательности, а потеря на стыке
#: плоскостей (запись ушла в error-плоскость и пропала) не была бы видна ни в
#: одной из них.
#:
#: Счётчик процессный «даром»: старт всегда spawn
#: (``process_manager_module/platforms/base.py``), поэтому модуль в дочернем
#: процессе импортируется заново и счёт идёт с единицы. При fork ребёнок
#: унаследовал бы значение родителя — проверяющий поэтому смотрит на
#: непрерывность от min до max, а не «начинается ли с 1».
#:
#: ``next()`` на ``itertools.count`` — один вызов C-уровня, атомарный под GIL:
#: двум потокам один номер не достанется. Отдельный лок здесь был бы дороже
#: самой записи.
#: Часовой промаха кэша маршрута. Отдельный объект нужен потому, что `None` —
#: ЗАКОННОЕ закэшированное значение («запись отклонена гейтом»), и обычный
#: `dict.get(key)` не отличил бы «отклонена» от «ещё не считали».
_ROUTE_MISS = object()

#: Ф2.х (Н5): потолок карт решений/маршрута. После 2.4 ось `scope` — произвольная
#: строка с call-site, то есть ключ ``(scope, level, module)`` растёт без предела
#: на динамических именах (проба ревью: 3000 имён → 3000 записей в каждой карте;
#: класс Ф0.3/F6 — «безлимитный рост по оси имён»). На переполнении карта
#: ЧИСТИТСЯ целиком: кэш — мемо, а не состояние, корректность от сброса не
#: страдает, а честный LRU стоил бы порядка на горячем пути. Запас кратный:
#: боевой прогон webcam_sketch держит десятки имён источников и четыре скоупа.
_DECISION_CACHE_CEILING = 4096

#: Ф2.х (Н5): потолок ПОИМЁННОГО учёта незнакомых скоупов. Выше — насыщение с
#: одной финальной жалобой (см. ``_check_scope_declared``): больше разных имён —
#: это уже динамическая строка в ``scope``, и перечислять её значения поимённо
#: значило бы расти без предела там, где детектор жалуется на чужой рост.
_UNKNOWN_SCOPES_CEILING = 64

#: Метки экземпляров менеджеров — ключ процессного реестра колец `memory`.
#: Счётчик, а не ``id()``: адрес переиспользуется после сборки мусора, и новый
#: менеджер унаследовал бы кольцо покойного.
_owner_seq = itertools.count(1)

_seq_counter = itertools.count(1)


def _next_seq() -> int:
    """Следующий номер пломбы. Вынесено в функцию ради слом-инъекции в тестах."""
    return next(_seq_counter)


#: Публичная «форточка» контекста: любой код может положить сюда поля, и они
#: попадут в extra записи. Самый низкий приоритет — её перекрывают и база
#: процесса, и потоковый контекст, и явный ``extra`` вызова.
log_context: ContextVar[Dict[str, Any]] = ContextVar("log_context", default={})


@contextmanager
def contextualize(**fields: Any) -> Iterator[None]:
    """Положить поля в форточку :data:`log_context` на время блока (Ф4.3).

    Единственный правильный способ пользоваться форточкой: два правила её
    безопасного применения — «пересоздавать значение целиком» и «возвращать
    по токену в ``finally``» — заведомо нарушаются при переписывании руками, а
    цена нарушения тихая: чужой ``trace_id`` в записях следующего кадра.

    ::

        with contextualize(trace_id=tid):
            ...           # каждая запись отсюда несёт trace_id

    **Функция модуля, а не метод менеджера, и это не экономия.** Форточка одна
    на модуль: поля увидят ВСЕ менеджеры процесса (и ``LoggerManager``, и
    брат-``ErrorManager``), поэтому метод создавал бы ложное впечатление
    привязки к тому менеджеру, у которого его позвали. Вдобавок единственный
    сегодняшний потребитель — ``frame_trace.log_correlation`` — менеджера не
    держит вовсе.

    **Видимость модульная, а семантика — потоковая.** ``ContextVar`` не
    пересекает границу потока: соседний поток полей не увидит, и ставить надо
    в каждом потоке, который пишет свои записи (asyncio-таск наследует
    контекст при создании — там достаточно одной постановки). Кадр, идущий
    через два-три потока, требует двух-трёх блоков; одна постановка накрыла бы
    записи только своего потока, а выглядела бы как сквозная корреляция.

    **Приоритет слоя — самый низкий.** Поле форточки перекрывает и база
    процесса (:meth:`LoggerCore.set_base_context`), и потоковый контекст
    (:meth:`LoggerCore.push_context`), и явный ``extra`` вызова. Имя, уже
    занятое базой процесса (``proc_name``), отсюда до записи не доедет —
    молча, поэтому имена лучше не пересекать.

    Вложенность работает: внутренний блок видит поля внешнего и перекрывает их
    по совпадающим ключам, а на выходе возвращается ровно прежнее значение —
    в том числе если тело блока бросило.
    """
    token = log_context.set({**log_context.get(), **fields})
    try:
        yield
    finally:
        log_context.reset(token)


#: Стеки контекста ``push_context`` — ОДИН ContextVar на модуль, внутри
#: словарь «ключ менеджера → стек уровней».
#:
#: Почему ContextVar, а не ``threading.local``: изоляция нужна и между
#: потоками, и между asyncio-тасками одного потока (тестировщик подтвердил
#: утечку между тасками на старой реализации). Почему один общий, а не по
#: ContextVar на инстанс: ContextVar'ы не рассчитаны на создание в рантайме —
#: каждый тест, создающий менеджер, оставлял бы новый.
#:
#: Значение ОБЯЗАНО пересоздаваться целиком (`{**stacks, key: ...}`), а не
#: мутироваться на месте: мутация общего словаря видна всем потокам сразу и
#: вернула бы ровно ту утечку, ради которой всё это.
_context_stacks: ContextVar[Dict[int, tuple]] = ContextVar("logger_context_stacks", default={})

#: Счётчики ретеншена (Ф0.7). Один список на объявление в ``self.stats``, на
#: выдачу в ``get_stats`` и на реестр ``PLANE_COUNTER_KEYS``: разъехавшийся
#: перечень уже стоил одной невидимой наружу метрики (урок Ф0.4).
_RETENTION_STAT_KEYS = (
    "retention_files_deleted",
    "retention_files_compressed",
    "retention_delete_failures",
    "retention_compress_failures",
    "retention_bytes_freed",
)

#: Обратное давление приёмников (R2). Считает КАНАЛ, спрашивают у менеджера —
#: суммируется по реестру. Канал, не умеющий этих полей, даёт 0.
_CHANNEL_BACKPRESSURE_KEYS = (
    "console_writes_dropped",
    "console_slow_writes",
)

#: Раздатчик ключей инстансов. Не ``id(self)``: id переиспользуется после сборки
#: мусора, и новый менеджер унаследовал бы контекст покойного в том потоке,
#: который не сделал pop.
_ctx_key_counter = itertools.count()

#: Эпоха наблюдаемости процесса (2.2). Растёт, когда связанному виду
#: (:class:`StdLoggerFacade`) больше нельзя верить своей связке:
#:
#:   * появился/сменился процессный ``LoggerManager`` (``__init__``);
#:   * инвалидирован кэш решений — сменился конфиг, состав каналов, пороги.
#:
#: **Список из одного числа, а не модульная переменная**: вид сравнивает эпохи
#: на КАЖДОЙ записи, и `_EPOCH[0]` — индексация (быстро), тогда как чтение
#: переменной чужого модуля стоило бы поиска в его словаре. Именно ради этой
#: цены вид и существует.
#:
#: Одна эпоха на оба события намеренно: виду безразлично, ПОЧЕМУ его связка
#: устарела — он в любом случае пересвязывается целиком. Два счётчика означали
#: бы два сравнения на горячем пути и две точки, которые могут разъехаться.
OBSERVABILITY_EPOCH = [0]


def bump_observability_epoch() -> None:
    """Объявить связанные виды устаревшими. Зовётся из двух мест — см. эпоху."""
    OBSERVABILITY_EPOCH[0] += 1


#: Какой скоуп подразумевает удобный метод уровня (``info`` → BUSINESS и т.д.).
#: Нужен :meth:`LoggerCore.is_enabled_for`: предикат обязан отвечать про тот же
#: маршрут, по которому пойдёт ``logger.info(...)``, иначе он «дешёвый», но про
#: другую запись. Соответствие таблицы фактическому поведению удобных методов
#: закреплено тестом ``test_gate_predicate.py`` — сама таблица его доказать не
#: может, она лишь объявляет намерение.
_LEVEL_DEFAULT_SCOPE = {
    LogLevel.DEBUG: LogScope.DEBUG,
    LogLevel.INFO: LogScope.BUSINESS,
    LogLevel.WARNING: LogScope.SYSTEM,
    LogLevel.ERROR: LogScope.SYSTEM,
    LogLevel.CRITICAL: LogScope.SYSTEM,
}


#: Разбор ответа канала поднят в общую базу (``channel_routing_module.interfaces``):
#: пока предикат был приватным здесь, severity-путь ErrorManager его не звал —
#: и закрытый приёмник считался записавшим. Псевдоним оставлен, чтобы не менять
#: вызовы внутри модуля.
_channel_accepted = channel_accepted


class LoggerCore(ChannelRoutingManager, ILoggerManager):
    """
    Общий лог-слой (наследует ChannelRoutingManager).

    Использует от ChannelRoutingManager:
      - self._channel_registry  — thread-safe хранилище каналов (IChannel)

    Специфика:
      - LoggerManagerConfig    — конфигурация областей/уровней/каналов (SchemaBase)
      - Scope-based routing    — log() определяет каналы по LoggerScopeSchema
      - Module channels        — отдельный файл для каждого модуля
      - Context stack          — push_context / pop_context
    """

    def __init__(
        self,
        manager_name: str = "LoggerManager",
        process: Optional["Process"] = None,
        config: Optional[Any] = None,
        config_manager: Optional[Any] = None,
        managers: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        if managers is None:
            managers = {}

        # --- Normalize config ---
        log_config = self._resolve_log_config(config)

        # --- Init ChannelRoutingManager (without buffer — set up later) ---
        ChannelRoutingManager.__init__(
            self,
            manager_name=manager_name,
            process=process,
            config=None,
            buffer_strategy=None,
            managers=managers,
            auto_proxy=kwargs.get("auto_proxy", True),
        )

        self._config_manager = config_manager

        self.config = log_config
        self.app_name = log_config.app_name

        # Ф6.9: поля подметальщика заводятся ДО каналов и первого свипа.
        # ``_apply_log_config_rebuild`` (наследник зовёт его из своего
        # ``_rebuild_from_config``) трогает их первым делом, и порядок
        # инициализации не должен зависеть от того, кто наследник.
        self._retention_stop = threading.Event()
        self._retention_thread: Optional[threading.Thread] = None

        # R9: в базу ушло config=None (свой конфиг логгер резолвит сам), поэтому
        # слепок для отката база выставить не может — без этой строки второй
        # рубеж reconfigure у логгера и ошибок МЁРТВ: откатываться не к чему, и
        # сбой пересборки оставляет пустой реестр. Найдено слом-инъекцией B1.
        self._last_applied_config = log_config

        # Module-specific channels (separate from main registry)

        # Ф2.2: дерево правил по имени источника. Заводится ДО первой записи и
        # пересобирается там же, где каналы (``_apply_log_config_rebuild``), —
        # своей точки пересборки у него нет намеренно: правила приезжают тем же
        # конфигом, что каналы, и разъехаться они не имеют права.
        self._name_hierarchy = NameHierarchy(
            log_config.loggers,
            getattr(log_config, "logger_groups", None),
            complain=self._complain_about_groups,
        )

        # Ф0.5: контекст в двух слоях. База — факт про процесс целиком, видна
        # всем потокам; стек push_context — факт про текущую работу текущего
        # потока/таска, соседям не виден. Один слой не покрывает оба случая:
        # чисто потоковый потерял бы proc_name у воркеров, чисто общий —
        # перемешал бы записи разных потоков (это и был дефект).
        self._ctx_key: int = next(_ctx_key_counter)
        self._base_context: Dict[str, Any] = {}
        self._base_context_lock = threading.Lock()

        # Ф2.4: имена скоупов, которых в конфиге нет, а записи в них были.
        # Словарь-как-упорядоченное-множество: порядок появления — часть ответа
        # («что случилось раньше»), членство — O(1). Прежняя редакция держала
        # список и объясняла его «размер ограничен опечатками» — опровергнуто
        # пробой ревю Ф2: после 2.4 скоуп — произвольная строка с call-site, и
        # динамическое имя (f-string с id) растило список без предела при O(n)
        # скане под локом (класс Ф0.3/F6). Теперь есть потолок и насыщение —
        # Ф2.х (Н5). Свой lock, а не общий с контекстом: он берётся один раз на
        # новое имя и не имеет права встретиться на пути записи с чужим локом
        # (правило Ф0.5).
        self._unknown_scopes: Dict[str, None] = {}
        self._unknown_scopes_saturated = False
        self._unknown_scopes_lock = threading.Lock()

        # Ключ — КОРТЕЖ с Ф1.2 (см. should_log). Аннотация ``Dict[str, bool]``
        # пережила смену ключа и врала, пока её не поймало ревью.
        self._decision_cache: Dict[Tuple[ScopeName, LogLevel, str], bool] = {}

        # 2.2-перф: кэш РЕЗУЛЬТАТА маршрута, а не решения гейта. Тот же ключ, но
        # значение — кортеж имён приёмников либо None («отклонена»). Схлопывает
        # три кадра (_route → _is_gate_open → should_log = 183 нс замером) в один
        # поиск по словарю (54 нс). Кортеж, а не список: закэшированное значение
        # отдаётся наружу, и изменяемый список позволил бы вызывающему испортить
        # кэш всем последующим записям.
        #
        # Ключ тот же, что у `_decision_cache`, — две карты по одному ключу
        # держатся сознательно: `should_log`/`is_enabled_for` спрашивают гейт
        # ОТДЕЛЬНО от эмиссии (у ErrorManager severity-путь гейт не спрашивает
        # вовсе), и вывести один ответ из другого нельзя.
        self._route_cache: Dict[Tuple[ScopeName, LogLevel, str], Optional[Tuple[str, ...]]] = {}
        self._cache_enabled = True

        # Пол ошибок (Ф0.9) — ленивый: резолвится на первой записи, ушедшей в floor.
        self._error_floor: Optional[ErrorFloor] = None

        # Ф4.1: цепочка процессоров. Кортеж, а не список — см. add_processor.
        self._processors: Tuple[Processor, ...] = ()

        # Ф4.5: редакция секретов включена ПО ПОСТРОЕНИЮ, и именно здесь.
        #
        # Три причины, и ни одна не про удобство. (1) Цепочка живёт на
        # ЭКЗЕМПЛЯРЕ, а менеджеров в процессе минимум два — регистрация в общем
        # предке достаётся обоим, включая severity-путь, по которому и едут
        # трейсбеки. (2) Конструктор, а не проводка после boot: запись,
        # эмитированная в окне загрузки, — обычная запись, и «редакция ещё не
        # встала» означало бы секрет в файле. (3) Первым в цепочке: всё, что
        # добавят позже (сэмплинг Ф7.1), обязано видеть уже замаскированное.
        self._redactor = SecretRedactor()

        # Ф7.1: сэмплинг — ВТОРЫМ, после редактора, ровно как обещал его
        # докстринг. Порядок несущий: дроссель решает по тексту сообщения, и
        # текст обязан быть уже замаскированным — иначе два вызова с разными
        # паролями в одной строке считались бы разными событиями и дроссель
        # молча не сработал бы там, где секреты как раз и текут.
        #
        # Как и редактор — в КОНСТРУКТОРЕ, а не проводкой после boot. Но
        # причина другая: у сэмплинга есть состояние (окна ключей), и
        # пересоздание на каждом ``reload`` означало бы «дёрнул конфиг под
        # штормом — получил шторм заново». Параметры меняются в
        # ``_apply_sampling_config``, состояние продолжается.
        self._sampler = RateSampler()
        self._processors = (self._redactor, self._sampler)
        self._apply_sampling_config(log_config)

        # Только СВОИ счётчики: четыре класса потери на стыке «менеджер → канал»
        # объявлены в базе (LOSS_COUNTER_KEYS) и общие для трёх плоскостей —
        # поэтому update(), а не присваивание: оно стёрло бы их.
        self.stats.update(
            {
                "messages_processed": 0,
                "messages_skipped": 0,
                # Сколько раз штатный маршрут ошибок не принял запись и сработал
                # floor. Ненулевое значение — сигнал «маршрут ошибок сломан», а
                # не норма. У статистики аналога нет: там нет записи, которую
                # нельзя потерять, — метрики агрегаты (см. ADR-CRM-011).
                "errors_to_floor": 0,
                # Пол не смог записать — запись потеряна ПОЛНОСТЬЮ. Отдельно от
                # errors_to_floor: «спасено» и «не спасено» нельзя складывать.
                "errors_floor_write_failures": 0,
                # Ф1.4: отложенное сообщение не собралось (callable бросил,
                # __str__ упал). Запись при этом СОХРАНЕНА — с текстом об
                # ошибке вместо содержимого, — но факт обязан быть виден:
                # молчаливая подмена текста хуже, чем видимая.
                "message_build_failures": 0,
                # Ф4.1: запись НАМЕРЕННО поглощена процессором (вернул None).
                # Это законная потеря — сэмплинг Ф7.1 ради неё и заводится, —
                # но «терять можно, молчать нельзя»: без счётчика «уровень
                # включён, а записей нет» неотличимо от сломанного маршрута.
                "records_dropped_by_processor": 0,
                # Ф4.1: процессор БРОСИЛ. Запись при этом продолжает путь —
                # перехватчик не имеет права её потерять, — но отказ обязан
                # быть слышен: молчащий процессор выглядит как работающий.
                "processor_failures": 0,
                # Ф0.7: результат чистки каталога логов (ключи — _RETENTION_STAT_KEYS).
                # Отдельно «удалили» и «не смогли удалить»: на Windows занятый файл
                # не удаляется, и молчащий ретеншен неотличим от работающего, если
                # считать только успехи.
                **{key: 0 for key in _RETENTION_STAT_KEYS},
            }
        )

        # R2: счётчики потерь ушедших каналов. Живут на менеджере, потому что
        # канал уносит свои с собой (см. _on_channel_removed).
        self._absorbed_backpressure: Dict[str, int] = {}

        self._setup_channels()
        # Ретеншен применяется и на старте, а не только на reconfigure: процесс,
        # который подняли с настроенным ретеншеном и ни разу не переконфигурировали,
        # обязан чистить за собой — иначе чистка зависела бы от факта reload'а.
        self._enforce_retention()
        self._start_retention_sweeper()

    # =========================================================================
    # ЖИЗНЕННЫЙ ЦИКЛ
    # =========================================================================

    def initialize(self) -> bool:
        try:
            # Ф4.6: _dispatcher больше нет и в самой базе. Он был мёртв не только
            # здесь — у всех четырёх наследников; комментарий «его использует
            # ErrorManager» был ложным и держал слот живым на бумаге.
            self.is_initialized = True
            self.info("LoggerManager initialized", module="logger_manager")
            return True
        except Exception as e:
            self._fallback_log("ERROR", f"LoggerManager initialization failed: {e}")
            return False

    def shutdown(self) -> bool:
        try:
            # Свип останавливается ПЕРВЫМ: он ходит по тому же каталогу, куда
            # сейчас будут дописывать и который потом закроют. Обход, начатый
            # после закрытия каналов, увидел бы уже неактивные файлы активными
            # (список берётся из живых реестров) — и наоборот.
            self._stop_retention_sweeper()
            self.info("LoggerManager shutting down", module="logger_manager")
            self.flush()
            # Ф2.6: жалоба на молчавшие приёмники. Здесь, а не только в базе:
            # этот shutdown — полный override, базовый не вызывается вовсе
            # (Ф4.6: диспетчера в базе больше нет вовсе). Хук только в базе не сработал бы
            # на ГЛАВНОЙ плоскости — поймано тестом. Повтор защищён флагом.
            self._warn_about_idle_sinks()

            for channel in self._channel_registry.clear():
                try:
                    channel.close()
                except Exception as e:
                    self._fallback_log("ERROR", f"channel close failed: {e}")

            # Кольца `memory` переживают КАНАЛ намеренно, но не менеджера: реестр
            # процессный, и без этой уборки они жили бы до конца процесса.
            drop_memory_rings(getattr(self, "_channel_owner_token", None))

            self.is_initialized = False
            return True
        except Exception as e:
            self._fallback_log("ERROR", f"LoggerManager shutdown failed: {e}")
            return False

    # =========================================================================
    # SETUP
    # =========================================================================

    @staticmethod
    def _resolve_log_config(config: Any) -> LoggerManagerConfig:
        """Convert config (None | dict | LoggerManagerConfig | build()) to LoggerManagerConfig.

        D1 (constructor-master Ф5-добор, ADR-CRM-008): разбор build()-объекта
        (tuple/dict payload) делегирован общему примитиву CRM
        ``resolve_build_result`` — не переопределяем эту логику здесь.
        Исключения из ``config.build()`` НЕ перехватываются (как и раньше).
        """
        if config is None:
            return LoggerManagerConfig()
        if isinstance(config, LoggerManagerConfig):
            return config
        if isinstance(config, dict):
            return LoggerManagerConfig.model_validate(config) if config else LoggerManagerConfig()
        resolved = resolve_build_result(config)
        if resolved is not None:
            _, cfg_dict = resolved
            return LoggerManagerConfig.model_validate(cfg_dict) if cfg_dict else LoggerManagerConfig()
        return LoggerManagerConfig()

    def _scope_schema(self, scope: ScopeName) -> LoggerScopeSchema:
        """Скоуп из конфига или запасная ветка (логика рядом с потребителем, не на схеме).

        Ф2.4: ключ — сама строка скоупа, без ``.name``. Одно написание на всё
        (Р-2.4-А), поэтому промежуточного превращения больше нет; регистр
        приводится валидатором на границе конфига, а не здесь — ``.upper()`` на
        этом пути стоил бы аллокации на каждом промахе кэша.

        **Запасная ветка молчит здесь намеренно** — говорит о ней
        :meth:`_check_scope_declared` с пути записи. Разница не косметическая:
        сюда доходит не всякая запись в незаявленную группу. Когда обе оси
        решения забирает правило имени (Ф2.2), этот метод не зовётся вовсе — а
        группы в конфиге всё равно нет. Поймано тестом readback'а, а не
        рассуждением: первая редакция 2.4 ставила сигнал именно здесь и молчала
        на конфиге прототипа, где правила задают приёмники двум источникам.
        После 2.3b (корневое правило) сигнал замолчал бы вообще везде.
        """
        schema = self.config.scopes.get(scope)
        if schema is not None:
            return schema
        ch = list(self.config.channels.keys())[:1] if self.config.channels else []
        return LoggerScopeSchema(
            enabled=True,
            min_level=self.config.default_level,
            channels=ch,
        )

    def _complain_about_groups(self, message: str) -> None:
        """Жалоба раскрытия ярлыков — аварийным выходом (Ф2.5, Р-2.5-В).

        Зовётся ТОЛЬКО при сборке дерева, то есть на старте и на пересборке, а не
        на записи. Аварийный выход, а не свои каналы, по той же причине, что у
        соседей: раскрытие правил решает в том числе, какие каналы у записи
        будут, и жаловаться на это тем же маршрутом значило бы доверять предмету
        спора. К тому же на старте дерево собирается ДО каналов.
        """
        self._fallback_log("WARNING", f"[группы] {message}")

    def logger_groups(self) -> Dict[str, List[str]]:
        """Ярлыки как их объявили — для readback пульта (Ф2.5).

        Отдаёт ОБЪЯВЛЕННОЕ, а рядом ``rules_table()`` показывает раскрытое.
        Расхождение между ними и есть «ярлык написан, а не действует»: член,
        у которого нашлось собственное правило, в раскрытии не появится.
        """
        return {label: list(members) for label, members in self._name_hierarchy.groups.items()}

    def _check_scope_declared(self, scope: ScopeName, channels: Optional[Tuple[str, ...]]) -> None:
        """Сказать вслух про группу без объявления — ОДИН раз на имя (Р-2.4-Б).

        Зовётся с ПРОМАХА кэша маршрута, то есть один раз на новую тройку
        «скоуп-уровень-источник», а не на запись: на попадании в кэш цена ноль.

        Форма — детектор Р-2.6-Е: якорь событийный (первая запись под этим
        именем), сигнал самоочищается (второй раз не повторяется) и называет не
        только проблему, но и **куда запись при этом ушла** — иначе
        предупреждение заставляет искать записи там, где их нет. Маршрут берётся
        фактический, уже посчитанный: он честен независимо от того, кто его
        решил — запасная ветка скоупа или правило имени.

        Идёт аварийным выходом, а не своими каналами: претензия ровно к тому,
        какие каналы запись получила, и писать её тем же маршрутом значило бы
        доверять предмету спора.

        Не потеря и потому не счётчик потерь: запись доставлена, просто не туда,
        куда думал автор. Четыре класса ``LOSS_COUNTER_KEYS`` лечатся разным, и
        пятый, означающий «всё дошло», размыл бы их (правило заведено в Ф0.4).
        Наружу имена уходят списком в :meth:`unknown_scopes`.

        **Детектор насыщаем** (Ф2.х, Н5): после ``_UNKNOWN_SCOPES_CEILING``
        разных имён новые не записываются, и об этом сказано ОДИН раз. Больше
        потолка разных незнакомых имён — это уже не опечатки, а динамические
        имена в ``scope``; перечислять их поимённо значило бы расти без предела
        ровно там, где детектор жалуется на чужой рост.
        """
        if scope in self.config.scopes:
            return
        with self._unknown_scopes_lock:
            if scope in self._unknown_scopes:
                return
            if len(self._unknown_scopes) >= _UNKNOWN_SCOPES_CEILING:
                if self._unknown_scopes_saturated:
                    return
                self._unknown_scopes_saturated = True
                saturated = True
            else:
                self._unknown_scopes[scope] = None
                saturated = False
        if saturated:
            self._fallback_log(
                "WARNING",
                f"незнакомых групп логов больше {_UNKNOWN_SCOPES_CEILING} — детектор насыщен, "
                f"дальнейшие имена не записываются. Столько разных имён — почти наверняка "
                f"динамическая строка в scope; scope — это ГРУППА, переменное кладут в module/extra",
            )
            return
        where = "отклонена гейтом" if channels is None else f"идут в {list(channels)}"
        self._fallback_log(
            "WARNING",
            f"группа логов '{scope}' в конфиге не объявлена: записи {where}. Это опечатка "
            f"в имени либо ещё не заведённая группа — объяви её в observability.scopes",
        )

    def unknown_scopes(self) -> List[str]:
        """Имена скоупов, которых в конфиге нет, а записи в них были (Ф2.4).

        Ответ на вопрос, который до Ф2.4 задать было нечем: readback
        ``introspect.observability.logger.scopes`` показывает ОБЪЯВЛЕННЫЕ группы,
        то есть ровно то множество, в котором незаведённой группы по определению
        нет. Соседний ``sources`` (2.6) устроен так же и по той же причине.

        Порядок — появления, не сортированный: он говорит, что случилось раньше.
        """
        with self._unknown_scopes_lock:
            return list(self._unknown_scopes)

    def _setup_channels(self):
        """Создать каналы из конфига и зарегистрировать в CRM registry.

        - channels: основные каналы (system_file, messages_file, console)
        - modules: отдельные файлы для модулей (database, processor, frames и т.д.)
        """
        for channel_name, channel_config in self.config.channels.items():
            if channel_config.enabled:
                self._setup_channel(str(channel_name), channel_config)

        self._warn_on_silenced_error_scopes()

    def _warn_on_silenced_error_scopes(self) -> None:
        """Сказать вслух про скоуп ошибок, ведущий ТОЛЬКО в «никуда» (2.9).

        ``NullChannel`` рапортует успех, поэтому запись, ушедшая только туда,
        для системы **доставлена**: пол ошибок её не подхватит (он ловит записи
        БЕЗ каналов), ни один класс потерь не вырастет, счётчики будут чисты —
        и ошибки исчезнут бесследно при полностью здоровой картине наблюдаемости.

        Это законная конфигурация: бывает, что шум конкретного скоупа не нужен.
        Запрещать нечего, но и молчать нельзя — молчание здесь неотличимо от
        «всё в порядке». Предупреждение идёт **аварийной функцией**, а не через
        собственные каналы: их состав ровно и есть предмет претензии.

        Зовётся на поднятии каналов И на каждом изменении их состава
        (``_on_channels_changed``). Второе — не «заодно»: ровно там оператор
        снимает файловый приёмник, оставляя скоуп с одним ``null``, и счётчики
        этого не видят по построению (см. докстринг хука).

        Порога по ``min_level`` здесь НЕТ, и это не упущение: потолка у скоупа
        не бывает, поэтому ERROR доходит до любого — даже до того, чей
        ``min_level`` стоит на ``CRITICAL``. Отсеять по порогу было бы нельзя
        ни один.

        Каждый наследник проверяет СВОЙ резолв: у скоупов плоскости ошибок
        приёмников нет по определению, её severity-карту досматривает
        ``ErrorManager``, расширяя этот метод.
        """
        for scope_name, scope in self.config.scopes.items():
            if not getattr(scope, "enabled", True):
                continue
            names = list(getattr(scope, "channels", None) or ())
            if not names or not self._all_null_sinks(names):
                continue
            self._warn_silenced_route(f"scope '{scope_name}' (min_level={scope.min_level})", names)

    def routes_using_sink(self, name: str) -> List[str]:
        """Скоупы, чей список каналов содержит это имя (плюс module-канал, если это он).

        Скоуп без явного списка каналов адресует ВЕСЬ реестр — такой попадает в
        ответ тоже, иначе «затронутых нет» читалось бы как «снятие безопасно».
        """
        target = str(name)
        affected = []
        for scope_name, scope in self.config.scopes.items():
            if not getattr(scope, "enabled", True):
                continue
            names = list(getattr(scope, "channels", None) or ())
            if not names or target in names:
                affected.append(str(scope_name))
        return sorted(affected)

    def _all_null_sinks(self, names: List[str]) -> bool:
        """Все ЖИВЫЕ каналы из списка — типа ``null``? Пустой живой набор → False.

        Пустой набор отдаётся как False намеренно: «приёмников нет» — это случай
        пола ошибок и счётчиков потерь, он и так видим. Здесь речь только про
        приёмник, который есть и рапортует успех.
        """
        live = [ch for ch in (self._resolve_channel(str(name)) for name in names) if ch is not None]
        return bool(live) and all(getattr(ch, "channel_type", "") == "null" for ch in live)

    def _warn_silenced_route(self, what: str, names: List[str]) -> None:
        """Одно предупреждение о маршруте, ведущем только в «никуда»."""
        self._fallback_log(
            "WARNING",
            f"{what} ведёт ТОЛЬКО в null-приёмники {names}: записи уровня ERROR будут "
            f"отброшены молча — пол ошибок их не увидит, счётчики потерь останутся нулевыми",
        )

    def _resolved_file_path(self, file_path: Optional[str], fallback: str) -> str:
        # Каждый процесс пишет в свою подпапку: logs/{process_name}/
        log_dir = self.config.log_directory
        if self.process is not None and hasattr(self.process, "name"):
            from pathlib import Path as _Path

            base = _Path(log_dir) if log_dir else _Path("logs")
            log_dir = str(base / self.process.name)
        return resolve_log_file_path(
            file_path,
            fallback=fallback,
            log_directory=log_dir,
        )

    @property
    def _channel_owner(self) -> str:
        """Метка ЭТОГО экземпляра менеджера — ключ к ресурсам, переживающим канал.

        Имени менеджера мало: два менеджера с одним именем в одном процессе
        (тесты, а в проде — край) разделили бы одно кольцо ``memory``. Ленивая:
        нужна только тому, у кого есть такой канал, а конструктор общий на всех.
        """
        token = getattr(self, "_channel_owner_token", None)
        if token is None:
            token = self._channel_owner_token = f"{self.manager_name}#{next(_owner_seq)}"
        return token

    def _setup_channel(self, channel_name: str, channel_config: LoggerChannelSchema):
        try:
            # Владелец проставляется ВСЕГДА и здесь: канал, чей ресурс переживает
            # его самого (кольцо `memory` в процессном реестре), обязан знать, чей
            # он — иначе одноимённые каналы логгера и ошибок делили бы одно кольцо.
            cfg = channel_config.model_copy(update={"owner": self._channel_owner})
            if channel_config.type == "file":
                fb = f"logs/{channel_name}.log"
                cfg = cfg.model_copy(
                    update={
                        "file_path": self._resolved_file_path(
                            channel_config.file_path,
                            fb,
                        ),
                    }
                )
            channel = create_channel(channel_name, cfg)
            self._channel_registry.register(channel)
        except Exception as e:
            self._fallback_log("ERROR", f"Failed to setup channel {channel_name}: {e}")

    # =========================================================================
    # РЕТЕНШЕН КАТАЛОГА ЛОГОВ (Ф0.7)
    # =========================================================================

    def _open_log_file_paths(self) -> List[str]:
        """Пути, в которые прямо сейчас пишут каналы этого менеджера.

        Их sweep не трогает никогда. Источник ровно один — реестр CRM.
        До Ф2.6 их было два: per-module каналы жили ещё и в отдельном словаре,
        и полагаться на их присутствие в реестре было нельзя.
        """
        paths: List[str] = []
        for channel in list(self._channel_registry.all()):
            file_path = getattr(channel, "file_path", None)
            if file_path:
                paths.append(str(file_path))
        return paths

    def _retention_root(self) -> str:
        """Каталог, который метёт ЭТОТ менеджер — тот же, куда он пишет свои файлы.

        Не корень ``logs/``: у процесса это ``logs/<имя процесса>/``. Так
        удалить активный файл соседнего процесса структурно невозможно — знать
        чужие открытые хэндлы менеджер не может, а значит и претендовать на
        чужой каталог не должен.
        """
        # Fallback без префикса ``logs/`` — иначе резолвер вложил бы ещё один
        # уровень (``<корень>/logs/…``) и мели бы мы не тот каталог.
        return str(Path(self._resolved_file_path(None, "retention.probe")).parent)

    def _retention_is_on(self) -> bool:
        """Включён ли ретеншен хоть одной политикой.

        Тот же предикат, что и ранний выход ``_enforce_retention`` — но
        нужен отдельно: по нему решается, поднимать ли фоновый поток. Держать
        поток, который просыпается раз в час только чтобы выйти по первому
        ``if``, — ровно тот «механизм, живущий сам для себя», который эта
        задача и убирает.
        """
        cfg = self.config
        return cfg.retention_days > 0 or cfg.retention_total_mb > 0 or bool(cfg.compress_rotated)

    def _start_retention_sweeper(self) -> None:
        """Поднять фоновый свип, если он вообще имеет смысл.

        Ф6.9. До этой правки свип звался только на старте и на
        ``reconfigure``: на стенде, работающем сутками без единого reload'а,
        настроенный ретеншен не подметал НИ РАЗУ — а именно там он и нужен.
        Живая находка Н-3 (2026-08-03): 471 МБ в ``logs/`` и ноль удалений.

        Поток не поднимается, если ретеншен выключен или интервал нулевой:
        в дефолтной конфигурации фреймворка (обе политики = 0) поведение
        остаётся бит-в-бит прежним, без единого лишнего потока на процесс.
        """
        interval = float(getattr(self.config, "retention_sweep_interval_sec", 0.0) or 0.0)
        if interval <= 0 or not self._retention_is_on():
            return
        self._retention_stop.clear()
        thread = threading.Thread(
            target=self._retention_loop,
            args=(interval,),
            name=f"{self.manager_name}-retention",
            daemon=True,
        )
        self._retention_thread = thread
        thread.start()

    def _retention_loop(self, interval: float) -> None:
        """Просыпаться по таймеру и мести, пока не попросят остановиться.

        Ожидание — на ``Event``, а не ``sleep``: остановка обязана быть
        немедленной, иначе ``shutdown`` ждал бы до конца интервала (час).

        Исключение здесь ловится, хотя ``_enforce_retention`` ловит своё:
        снаружи остаётся учёт статистики под локом. Поток, умерший молча, —
        это «выключено по построению» во второй раз, только теперь ещё и
        незаметно.
        """
        while not self._retention_stop.wait(interval):
            try:
                self._enforce_retention()
            except Exception as e:  # noqa: BLE001 — фоновый поток не имеет права умереть молча
                self._fallback_log("ERROR", f"periodic retention sweep failed: {e}")

    def _stop_retention_sweeper(self) -> None:
        """Остановить свип и дождаться его — с крайним сроком.

        ``join`` с дедлайном, а не бессрочный: поток может стоять в середине
        обхода каталога, и вечное ожидание превратило бы остановку процесса в
        зависание (у проекта это уже было — 5-секундный ханг graceful-stop).
        Поток демонский, поэтому истёкший дедлайн не держит интерпретатор; но
        факт называется вслух, а не проглатывается.
        """
        self._retention_stop.set()
        thread = self._retention_thread
        self._retention_thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
            if thread.is_alive():
                self._fallback_log("ERROR", "retention sweeper did not stop within 5s")

    def _enforce_retention(self) -> None:
        """Прогнать чистку каталога логов по текущему конфигу и учесть результат.

        Вызывается на старте, на каждом ``reconfigure`` и — с Ф6.9 — фоновым
        подметальщиком по таймеру. Обе политики выключены по умолчанию — тогда
        это ранний выход без единого stat.
        """
        cfg = self.config
        if cfg.retention_days <= 0 and cfg.retention_total_mb <= 0 and not cfg.compress_rotated:
            return
        try:
            result = enforce_log_retention(
                self._retention_root(),
                retention_days=cfg.retention_days,
                retention_total_mb=cfg.retention_total_mb,
                compress_rotated=cfg.compress_rotated,
                active_files=self._open_log_file_paths(),
            )
        except Exception as e:
            # Чистка диска не имеет права уронить поднятие логгера: без логгера
            # не будет видно и самой причины падения.
            self._fallback_log("ERROR", f"retention sweep failed: {e}")
            return

        with self._miss_lock:
            self.stats["retention_files_deleted"] += result["deleted"]
            self.stats["retention_files_compressed"] += result["compressed"]
            self.stats["retention_delete_failures"] += result["delete_failures"]
            self.stats["retention_compress_failures"] += result["compress_failures"]
            self.stats["retention_bytes_freed"] += result["bytes_freed"]

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """R9: разобрать конфиг ДО того, как ``reconfigure`` закроет каналы.

        Тот же разбор, что и в ``_rebuild_from_config``, но раньше — и только
        ради исключения. Раньше единственной проверкой был этот же
        ``model_validate`` ВНУТРИ пересборки, то есть уже после
        ``_close_all_channels()``: опечатка в значении поля стоила всего реестра.
        """
        self._resolve_log_config(config)

    def _rebuild_from_config(self, config: Dict[str, Any]) -> None:
        """Хук CRM.reconfigure: пересобрать каналы из нового конфига + сбросить кэш.

        Базовый ``reconfigure`` уже сделал flush() и ``_close_all_channels()``
        (очистил реестр CRM). До Ф2.6 здесь требовалась вторая уборка: логгер
        держал per-module каналы отдельным словарём, и без неё ``_setup_channels``
        создавал дубли. Второго места больше нет.

        Повторяем именно логику ``_setup_channels`` (каналы регистрируются прямо
        в ``_channel_registry.register``, без route в Dispatcher — в отличие от
        CRM.register_channel), затем пересоздаём батчер и инвалидируем
        ``_decision_cache`` (иначе старые решения should_log залипают — критический
        баг: кэш никогда не сбрасывался).
        """
        self._apply_log_config_rebuild(self._resolve_log_config(config))

    def _apply_log_config_rebuild(self, log_config: "LoggerManagerConfig") -> None:
        """Воссоздать каналы/батчер из готового LoggerManagerConfig + сбросить кэш.

        Выделено отдельным шагом, чтобы наследник (ErrorManager) переиспользовал
        пересборку каналов после своей нормализации (expand_error_manager_config),
        не дублируя логику. Предполагается, что ``reconfigure`` уже закрыл реестр
        CRM через ``_close_all_channels()``.
        """
        # 1. Закрыть и очистить module-каналы (их ещё нет в очищенном реестре).
        # 2. Применить новый конфиг.
        self.config = log_config
        self.app_name = self.config.app_name
        # Ф2.2: дерево правил ПЕРЕСОБИРАЕТСЯ, а не правится на месте. Мутация
        # живой таблицы оставила бы правила, которых в новом конфиге больше нет
        # (тот же класс, что воскресающий после reload канал из 5.12), —
        # и «снял правило конфигом, а оно действует» искалось бы днями.
        self._name_hierarchy = NameHierarchy(
            self.config.loggers,
            getattr(self.config, "logger_groups", None),
            complain=self._complain_about_groups,
        )

        # Ф7.1: сэмплеру отдаются ПАРАМЕТРЫ, а сам он не пересоздаётся — в
        # отличие от дерева правил строкой выше. Разница не в аккуратности, а в
        # природе состояния: правило — целиком описание из конфига, и снятое
        # правило обязано исчезнуть; окно сэмплинга — факт о том, что уже
        # произошло, и стирать его сменой конфига значит терять дроссель ровно
        # в момент, когда оператор правит конфиг из-за шторма.
        self._apply_sampling_config(self.config)

        # 3. Воссоздать каналы из нового конфига (Ф7.4: батчера больше нет —
        # запись синхронна, поэтому останавливать и пересоздавать нечего).
        self._setup_channels()

        # 5. Сбросить кэш решений should_log (критический баг — раньше не сбрасывался).
        self.invalidate_decision_cache()

        # 6. Применить ретеншен из нового конфига (Ф0.7). Порядок обязателен:
        # ПОСЛЕ пересоздания каналов, иначе список активных файлов был бы от
        # старого состава и sweep удалил бы файл только что открытого канала.
        #
        # Ф6.9: подметальщик перезапускается по НОВОМУ конфигу — старый поток
        # держал бы прежний интервал и продолжал бы мести после того, как
        # ретеншен выключили. Остановка идёт до свипа, чтобы фоновый обход не
        # шёл одновременно с этим, синхронным.
        self._stop_retention_sweeper()
        self._enforce_retention()
        self._start_retention_sweeper()

    def invalidate_decision_cache(self) -> None:
        """Очистить кэш решений should_log.

        После смены default_level / scope-конфигурации старые закэшированные
        решения становятся неверными. Вызывается из ``_rebuild_from_config``
        и из ``_on_channels_changed``; также доступен публично.

        2.2: заодно поднимается эпоха наблюдаемости — связанные виды держат
        СВОЮ связку с менеджером, и без этого они пережили бы reconfigure с
        устаревшим указателем. Бамп здесь, а не у каждого вызывающего: точка
        инвалидации одна, и вторую заводить нельзя — разъедутся.
        """
        self._decision_cache.clear()
        # 2.2-перф: обе карты живут по одному ключу и обязаны стареть ВМЕСТЕ.
        # Оставленный кэш маршрута хуже оставленного кэша гейта: симптом не
        # «лог не пишется», а «лог пишется в снятый канал» — ищется днями.
        self._route_cache.clear()
        # Ф2.2: третья карта того же возраста. **Сегодня этот вызов избыточен, и
        # это сказано прямо, а не выдано за защиту**: резолв имени — чистая
        # функция от таблицы правил, таблица меняется только с конфигом, а на
        # пересборке объект дерева заменяется целиком (кэш и так пуст).
        # Избыточным он перестанет быть ровно тогда, когда правило начнёт
        # зависеть от живого состояния приёмников; ставится здесь, потому что
        # точка старения всех карт обязана остаться ОДНА (урок 0.8: вторая
        # точка инвалидации разъезжается с первой).
        self._name_hierarchy.clear_cache()
        bump_observability_epoch()

    def _on_channel_removed(self, channel: Any) -> None:
        """Забрать у уходящего канала его счётчики потерь (R2).

        Иначе история теряется ровно в тот момент, когда её читают: разбирая
        инцидент с консолью, оператор жмёт ``logger.sink.disable console`` — и
        число отброшенных записей обнуляется вместе с каналом. Воспроизведено
        ревью фазы: 7 → disable → 0.

        Накопитель на менеджере складывается с живыми каналами в
        :meth:`get_stats`, поэтому сумма монотонна и переживает и снятие
        приёмника, и полный ``reconfigure``.

        **Ф2.6: вторая карта каналов убрана вместе с механизмом per-module
        файлов.** Здесь же снималась запись из неё — живая находка 2026-07-28:
        ``set_sink_enabled(enabled=False)`` знал только реестр, запись оставалась
        во втором словаре, и после ``logger.sink.disable module_trace`` пять
        записей ушли в УЖЕ ЗАКРЫТЫЙ канал (``channel_refused_records`` = 5).
        Штатное «выключи мне этот лог» выглядело потерей записей. Теперь карта
        одна, и этот класс дефекта невозможен: снимать нечего.
        """
        for key in _CHANNEL_BACKPRESSURE_KEYS:
            value = getattr(channel, key, 0)
            if value:
                self._absorbed_backpressure[key] = self._absorbed_backpressure.get(key, 0) + value

    def _on_channels_changed(self) -> None:
        """Состав каналов изменился в рантайме → решение should_log больше не доверенное.

        Ф0.8. **Хук стал НЕСУЩИМ (2.2-перф + 2.8) — прежняя редакция этого
        докстринга больше не верна и оставлять её нельзя.** Она гласила:
        «сегодня это профилактика, а не починка симптома… стейла физически не
        бывает», потому что ``_should_log_direct`` смотрел только на
        scope/level/module. С тех пор произошло два события:

        * 2.2-перф завёл ``_route_cache`` — кэш РЕЗУЛЬТАТА маршрута, куда состав
          приёмников входит напрямую;
        * 2.8 добавил в резолв множество «снято оператором».

        Теперь без этой инвалидации стейл наступает немедленно и симптом у него
        ровно тот, который прежний текст называл гипотетическим: не «лог не
        пишется», а «лог пишется в снятый канал» либо «перестал писаться в
        живой» — неверный ОТВЕТ вместо отсутствия ответа, и ищется он днями.

        Проверяемость — слом-инъекция H1 (снять ``_route_cache.clear()``) и пары
        в ``test_route_cache.py``.

        **Плюс пересмотр «а не остался ли маршрут только в никуда» (находка
        ревью 2.9, воспроизведена).** Проверка стояла ТОЛЬКО на поднятии каналов,
        а 2.8 сама завела второй путь к вырожденному состоянию: оператор снимает
        файловый приёмник, и в скоупе остаётся один ``null``. Наблюдалось так —
        предупреждений 0, ``errors_to_floor`` 0, все четыре класса потерь 0,
        floor-файлов нет, а запись уровня ERROR исчезла бесследно. Докстринг
        проверки при этом утверждал, что рантайм-случай «виден счётчиками 2.8» —
        видеть его там нечем по построению: ``null`` рапортует успех.
        У плоскости ошибок этот путь был закрыт с самого начала
        (``_setup_level_routes`` зовётся отсюда же), у логгера — нет.
        """
        self.invalidate_decision_cache()
        self._warn_on_silenced_error_scopes()

    # =========================================================================
    # УЧЁТ ПОТЕРЬ НА СТЫКЕ «ИМЯ → КАНАЛ» (Ф0.4)
    # =========================================================================

    # =========================================================================
    # ОСНОВНОЙ API ЛОГИРОВАНИЯ
    # =========================================================================

    def should_log(self, scope: ScopeName, level: LogLevel, module: str) -> bool:
        """Решение гейта с кэшем. Ф1.2: ключ — КОРТЕЖ, а не f-string.

        Прежний ключ ``f"{scope.value}:{level.value}:{module}"`` аллоцировал
        новую строку на КАЖДОЙ записи, включая отклонённую, — то есть самый
        дешёвый исход стоил дороже всего остального в нём. Кортеж из уже
        существующих объектов (два члена enum и имя модуля) не аллоцирует ничего
        сверх самого кортежа.

        **Правка 2.2: прежняя редакция утверждала, что «enum'ы хэшируются по
        identity». Это было неверно, и цена ошибки измерена.** ``Enum.__hash__``
        — Python-функция, делающая ``hash(self._name_)``: два enum'а в ключе
        стоили **165 нс** на одном только хэшировании, при 23 нс у ключа с
        быстрым хэшем. Настоящий выигрыш лежал рядом и не был взят именно
        потому, что докстринг объяснял ситуацию уверенно и неправильно —
        класс «уверенное неверное объяснение переживает баг». Хэш по identity
        теперь действительно стоит на месте: см. ``log_enums._IDENTITY_HASH``.

        Заодно снят и вопрос про Ф1.2: f-string (сборка ~180 нс + поиск 16) и
        кортеж-из-enum'ов (165) стоили примерно ОДИНАКОВО — вот почему
        слом-инъекция Ф1.2 оставалась зелёной с f-string-ключом. Прежняя
        редакция списала это на невозможность коллизии; настоящая причина в
        том, что обе версии были одинаково дорогими.
        """
        if not self._cache_enabled:
            return self._should_log_direct(scope, level, module)
        cache_key = (scope, level, module)
        cached = self._decision_cache.get(cache_key)
        if cached is not None:
            return cached
        result = self._should_log_direct(scope, level, module)
        # Ф2.х (Н5): потолок. Сброс, а не отказ от записи: пришедший ключ —
        # самый горячий из известных прямо сейчас, терять его глупее всего.
        if len(self._decision_cache) >= _DECISION_CACHE_CEILING:
            self._decision_cache.clear()
        self._decision_cache[cache_key] = result
        return result

    def effective_level(self, name: str) -> Optional[str]:
        """Порог, который правило иерархии назначило источнику ``name`` (Ф2.2).

        Резолв идёт вверх по точкам до первого правила, задавшего уровень:
        ``vision.capture.hikvision`` → ``vision.capture`` → ``vision`` → корень
        (пустая строка).

        Returns:
            Имя уровня либо ``None`` — «ни одно правило про этот источник
            уровня не задаёт».

        **Что метод НЕ обещает: что запись такого уровня будет записана.** Он
        отвечает про одну ось решения, а не про судьбу записи: приёмник может
        быть снят оператором, а плоскость ошибок ходит своим severity-путём.
        Оговорка стоит здесь потому, что соседний предикат ``is_enabled_for``
        уже один раз обещал больше, чем делал, и ревью Ф1 сняло это запуском.
        """
        return self._name_hierarchy.level(name)

    def effective_channels(self, name: str) -> Optional[Tuple[str, ...]]:
        """Приёмники, назначенные источнику ``name`` правилом иерархии (Ф2.2).

        Returns:
            Кортеж имён — возможно **пустой** («приёмников нет, и это
            объявлено») — либо ``None``: правил про приёмники этого источника
            нет, набор берёт скоуп.

        Ось резолвится независимо от уровня: правило может задать порог и
        промолчать про приёмники — тогда приёмники придут с более короткого
        префикса. Список снятых оператором приёмников здесь НЕ применяется: он
        живёт в ``_effective_route``, общем для обеих плоскостей.
        """
        return self._name_hierarchy.channels(name)

    def resolve_rule(self, name: str) -> Dict[str, Any]:
        """Полный разбор имени для пульта: что действует и **какое правило победило**.

        Ф2.6, шаг 6. Соседи выше отвечают ЗНАЧЕНИЕМ, но молчат про происхождение —
        а на живом стенде вопрос звучит иначе: «почему у этого источника такой
        порог и кто его задал». Без ответа четыре слоя настройки и дерево правил
        превращают разбор в чтение конфигов глазами.

        Отвечает на ЛЮБОЕ имя, включая то, под которым ещё никто не писал: это
        вопрос-гипотеза («если напишу правило вот так — что получится»), а не
        разбор случившегося. Образец — ``GET /actuator/loggers/{name}``.

        Возвращает плоский ``dict``: ответ уходит на пульт через IPC.

        **Что метод не обещает — того же, чего не обещает** :meth:`effective_level`:
        это разбор ОДНОЙ оси решения, а не судьба записи. Приёмник может быть снят
        оператором (``_effective_route``), а плоскость ошибок ходит своим
        severity-путём и иерархию не спрашивает вовсе.
        """
        return self._name_hierarchy.resolve(name)

    def seen_sources(self) -> List[str]:
        """Имена источников, реально писавших в этом процессе (Ф2.6, шаг 4).

        :meth:`resolve_rule` отвечает про имя, которое спрашивающий уже знает. Но
        на живом стенде вопрос обычно обратный — **какие имена вообще бывают**, и
        до сих пор узнать это можно было только грепом по файлу лога, то есть
        только про те источники, чьи записи куда-то доехали.

        **Новое состояние не заводится.** Обе карты решений ключуются
        ``(скоуп, уровень, имя)`` и заполняются на каждой записи независимо от
        того, есть ли правила, — множество имён в них уже лежит. Отдельный
        ``set`` на горячем пути стоил бы вставки за запись ради того, что и так
        известно.

        Берутся ОБЕ карты, и причина установлена ЗАМЕРОМ, а не рассуждением —
        первая редакция этого докстринга объясняла союз неверно, а слом-инъекция
        показала, что объяснение ничем не подтверждено:

        * на плоскости ЛОГОВ обе карты держат одно и то же. Отклонённая запись
          тоже попадает в карту маршрута — там кэшируется сам факт отказа
          (``None``), поэтому источник, у которого всё гасится порогом, виден в
          любой из двух. Замер: ``route == {'молчун': None, 'говорун': ('f',)}``;
        * на плоскости ОШИБОК карта решений остаётся **пустой**:
          ``ErrorManager._route`` идёт severity-путём и гейт не спрашивает вовсе.
          Замер: ``decision == []``, ``route == ['источник']``.

        То есть союз нужен ради наследника, а не ради отклонённых записей.

        **Ограничение названо вслух:** список живёт от последней пересборки
        конфигурации, а не от старта процесса — карты стареют вместе с решениями
        (единая точка инвалидации). Сразу после ``config.reload`` он пуст, и это
        не поломка, а «с тех пор ещё никто не писал». Отдельное вечное множество
        завели бы, если бы понадобилось помнить дольше; сегодня повода нет.
        """
        names = {key[2] for key in self._decision_cache}
        names.update(key[2] for key in self._route_cache)
        return sorted(names)

    def rules_table(self) -> Dict[str, Dict[str, Any]]:
        """Таблица правил как она задана — readback для пульта (Ф2.6, шаг 6).

        Отличается от :meth:`resolve_rule` тем же, чем ``configuredLevel`` от
        ``effectiveLevel`` в Spring: здесь — что написано, там — что из этого
        вышло для конкретного имени. Оба нужны: расхождение между ними и есть
        «правило написано, но не действует».

        Пустая таблица отдаётся пустым словарём, а не опускается: «правил нет» —
        это ответ, и молчание вместо него отправило бы оператора искать поломку
        доставки там, где просто ничего не настроено.
        """
        table: Dict[str, Dict[str, Any]] = {}
        for key, rule in self._name_hierarchy.rules.items():
            table[str(key)] = {
                "level": getattr(rule, "level", None),
                "channels": list(getattr(rule, "channels", None) or [])
                if getattr(rule, "channels", None) is not None
                else None,
                "channels_extra": list(getattr(rule, "channels_extra", None) or [])
                if getattr(rule, "channels_extra", None) is not None
                else None,
            }
        return table

    def _should_log_direct(self, scope: ScopeName, level: LogLevel, module: str) -> bool:
        """Решение гейта без кэша. **Правило имени сильнее скоупа** (Ф2.2).

        Решение владельца 2026-08-03: когда про запись говорят обе оси, порог
        задаёт самое длинное совпавшее правило имени, а скоуп остаётся
        поставщиком набора приёмников по умолчанию. Это единственный расклад,
        при котором «включить DEBUG одному файлу» не требует открыть шлюз всему
        скоупу — то есть ровно то, ради чего фаза делается.

        **Правило имени перекрывает и ``enabled``, и whitelist ``modules``
        скоупа — намеренно, и вот почему это названо вслух.** Скоуп ``DEBUG`` в
        дефолтах выключен (``enabled=False``, иначе пер-кадровый firehose), и
        трактовка «выключенный скоуп сильнее» сделала бы главную ручку фазы
        мёртвой в дефолтной поставке — то есть работающей на тестах и
        бесполезной live. Цена решения: опечатка в префиксе правила способна
        разбудить выключенный скоуп для поддерева. Осознанно принято; страж —
        пара тестов «правило будит выключенный скоуп» / «без правила выключенный
        скоуп молчит».

        Когда правило молчит (``None``), решение принимает скоуп — байт-в-байт
        как до Ф2.2. Пустая таблица правил (дефолт) в эту ветку не заходит
        вовсе.
        """
        if self._name_hierarchy:
            rule_level = self._name_hierarchy.level(module)
            if rule_level is not None:
                min_severity = severity_of(rule_level)
                severity = severity_of(level)
                # Незнакомый уровень ПРОПУСКАЕТ запись — та же политика, что у
                # ``LoggerScopeSchema.should_log``. Две соседние ветки одного
                # решения с противоположной политикой были бы худшим вариантом:
                # опечатка в имени уровня означала бы тишину в одном месте и
                # firehose в другом.
                if min_severity == UNKNOWN_SEVERITY or severity == UNKNOWN_SEVERITY:
                    return True
                return severity >= min_severity
        scope_config = self._scope_schema(scope)
        return scope_config.should_log(level, module)

    def _is_gate_open(self, scope: ScopeName, level: LogLevel, module: str) -> bool:
        """Пройдёт ли запись гейт — ЕДИНСТВЕННОЕ место, где это решается.

        Хук, а не прямой вызов ``should_log`` из двух мест: у наследника решение
        может приниматься иначе (severity-маршрут ``ErrorManager`` не спрашивает
        скоуп вовсе), и тогда публичный предикат :meth:`is_enabled_for` обязан
        отвечать ровно то же, что сделает :meth:`_route`. Иначе появляется
        второй, чуть-чуть другой гейт — ровно та развилка, которую убирала Ф4.2.

        Согласие двух путей закреплено тестом-сеткой ``test_gate_predicate.py``
        (для КАЖДОЙ пары scope×level×module: ``is_enabled_for`` ⇔ ``_route is not None``),
        параметризованным по обоим менеджерам.

        **Честная оговорка про сегодняшнее состояние (ревью Ф1).** На двух
        существующих наследниках подмена этого вызова обратно на
        ``self.should_log`` НЕНАБЛЮДАЕМА: у ``ErrorManager`` severity-ветка до
        ``super()._route`` не доходит, а для DEBUG/INFO хук тождественен
        ``should_log``. То есть сетка доказывает согласие самого хука с
        ``_route``, но не то, что ``_route`` спрашивает именно хук — на текущих
        наследниках такого теста построить нельзя. Хук здесь ради третьего
        наследника, чей гейт будет строже скоупа; называть его работающей
        развилкой сегодня — аванс.
        """
        return self.should_log(scope, level, module)

    def is_enabled_for(
        self,
        name: str,
        level: LogLevel,
        scope: Optional[ScopeName] = None,
    ) -> bool:
        """Дешёвый публичный предикат «эта запись ПРОЙДЁТ ГЕЙТ?» (Ф1.3).

        **Что он НЕ обещает: что у записи есть живой приёмник.** Первая
        редакция называла его «пойдёт ли запись хоть куда-нибудь», и ревью Ф1
        это опровергло запуском: у логгера со снятым командой каналом
        ``is_enabled_for(INFO)`` возвращает ``True``, запись уходит в
        ``unresolved_channel_records``; у плоскости ошибок без единого
        severity-канала ``True`` для WARNING оборачивается
        ``records_without_channels``. Для ERROR/CRITICAL ``True`` защищён полом,
        для остальных — нет.

        Сетка ``test_gate_predicate.py`` этого поймать и не могла: она сверяет
        ``is_enabled_for ⇔ _route is not None``, а «пустой список» и «список
        мёртвых имён» одинаково не ``None``. Так что предикат отвечает ровно
        про решение гейта — этого достаточно для его назначения (не платить за
        сборку сообщения), но выдавать его за гарантию доставки нельзя.

        Нужен и stdlib-совместимому коду (``logger.isEnabledFor``), и OTel Logs
        Bridge API (``Logger.enabled``): вызывающий хочет узнать про гейт ДО
        того, как заплатит за сборку сообщения. Ленивое сообщение (Ф1.4)
        закрывает тот же случай изнутри, но не всякий вызов можно свести к
        одному callable — иногда дорога вся ветка кода вокруг записи.

        Args:
            name: имя модуля-источника (то же, что ``module`` в :meth:`log`).
            level: уровень записи.
            scope: скоуп; ``None`` — тот, который для этого уровня возьмёт
                удобный метод (:data:`_LEVEL_DEFAULT_SCOPE`), чтобы предикат
                отвечал про ``logger.info(...)``, а не про абстрактную запись.

        Стоимость — кэшированный гейт: тот же путь, что у :meth:`log`, без
        сборки записи.
        """
        if scope is None:
            scope = _LEVEL_DEFAULT_SCOPE.get(level, LogScope.SYSTEM)
        return self._is_gate_open(scope, level, name)

    def _route(self, scope: ScopeName, level: LogLevel, module: str) -> Optional[Sequence[str]]:
        """Куда пойдёт запись — и пойдёт ли вообще. ``None`` = отклонена гейтом.

        Возврат — ``Sequence``, а не ``List``: правило иерархии (Ф2.2) отдаёт
        уже готовый кортеж из своего кэша, и материализация его в список стоила
        бы аллокации на каждом промахе кэша маршрута ради одной лишь буквы в
        аннотации. Единственный потребитель — ``_effective_route`` — приводит
        результат к кортежу сам.

        **Единственная точка расширения эмиссии (Ф4.2).** Наследник, у которого
        другой резолв приёмников, переопределяет ЭТОТ метод, а не ``log()``:
        всё остальное — контекст, сборка записи, tap'ы, floor, три класса учёта
        потерь — общее и обязано лежать в одном месте.

        Так закрыта развилка, стоившая фазе четырёх ручных зеркалирований:
        ``ErrorManager.log`` был полным override'ом, и каждое улучшение
        ``LoggerCore.log`` приходилось повторять руками — 0.4 в двух местах,
        0.9 в двух, tap'ы в двух, а 0.5 забыли, из-за чего на ГЛАВНОМ пути
        ошибок терялся ``proc_name``.

        Гейт стоит здесь, а не в ``log()``, намеренно: наследник, которому
        решение принимает не скоуп (severity-маршрут ошибок), должен уметь
        вернуть приёмники, не спрашивая ``should_log`` вовсе.
        """
        if not self._is_gate_open(scope, level, module):
            return None

        # Ф2.2: приёмники сперва спрашиваются у иерархии имён. Пустой кортеж от
        # правила — законный ответ («приёмников нет, объявлено»), и подменять
        # его набором скоупа нельзя: ``or`` здесь съел бы объявленную пустоту,
        # то есть правило «этому поддереву — никуда» молча не работало бы.
        # Поэтому сравнение именно с ``None``.
        named = self._name_hierarchy.channels(module) if self._name_hierarchy else None
        if named is not None:
            channels: Any = named
        else:
            scope_config = self._scope_schema(scope)
            channels = scope_config.channels or self._channel_registry.names()

        # Ф2.6 (Р-2.6-Ж): добавки поверх унаследованного набора. Стоит ПОСЛЕ выбора
        # базы намеренно — добавка складывается и с набором правила, и с набором
        # скоупа, иначе «свой файл И общий» выражалось бы только там, где правило
        # приёмники уже задало, то есть ровно не в том случае, ради которого
        # операция заведена.
        #
        # Дедупликация обязательна по той же причине, что ниже у module-канала:
        # приёмник, названный и базой, и добавкой, принял бы ОДНУ запись ДВАЖДЫ —
        # прямое нарушение инварианта Ф0.9 «одна ошибка — одна запись».
        if self._name_hierarchy:
            extra = self._name_hierarchy.channels_extra(module)
            if extra:
                merged = list(channels)
                for channel_name in extra:
                    if channel_name not in merged:
                        merged.append(channel_name)
                channels = merged

        return channels

    def _effective_route(self, scope: ScopeName, level: LogLevel, module: str) -> Optional[Tuple[str, ...]]:
        """Маршрут БЕЗ приёмников, снятых оператором (2.8).

        **Стоит здесь, а не внутри `_route`, намеренно.** `ErrorManager`
        переопределяет `_route` целиком (severity-путь не спрашивает скоуп), и
        фильтр внутри родителя оставил бы дефект жить на плоскости ошибок —
        это было бы четвёртое ручное зеркалирование того же класса, что уже
        стоило фазе четырёх правок (см. докстринг `_route`). Здесь точка одна
        и общая: `log()` наследуют оба менеджера.

        Пустой кортеж — законный результат и НЕ то же самое, что `None`:
        `None` значит «отклонена гейтом» (не потеря), а пустой кортеж —
        «приёмников не осталось», и `log()` учтёт запись как
        `records_without_channels`. Именно так снятие ЕДИНСТВЕННОГО приёмника
        скоупа остаётся потерей: оператор неявно замолчал целый вид логов.

        Возвращает кортеж, а не список: значение уходит в кэш и наружу, и
        изменяемый список позволил бы одному вызывающему испортить маршрут
        всем последующим записям.
        """
        resolved = self._route(scope, level, module)
        if resolved is None:
            return None
        disabled = self._sinks_disabled_by_operator
        if disabled:
            return tuple(name for name in resolved if name not in disabled)
        return tuple(resolved)

    def log(
        self,
        scope: ScopeName,
        level: LogLevel,
        message: "LogMessage",
        module: str = "main",
        *args: Any,
        **extra,
    ):
        """Записать. Сообщение может быть отложенным (Ф1.4).

        Args:
            message: строка, ``%``-шаблон или ``Callable[[], str]``. Callable
                вызывается ТОЛЬКО после гейта и ровно один раз.
            module: имя модуля-источника.
            *args: аргументы ``%``-формата (как в stdlib). Применяются один раз
                — до сборки записи, а не по разу на канал.

        Почему ``*args`` стоит ПОСЛЕ ``module``, а не сразу за сообщением, как в
        stdlib: ``module`` во фреймворке повсеместно передают четвёртым
        позиционным аргументом, и перестановка молча съела бы его в ``args``.
        Совместимость важнее сходства с чужой сигнатурой.

        Отложенность нужна ровно там, где гейт закрыт: цена f-string на
        call-site платится ДО входа сюда и никаким гейтом внутри не снимается
        (об этом же — шапка Ф1 в плане). ``log(..., lambda: f"...")`` и
        ``log(..., "%s", "main", value)`` — два способа эту цену не платить.
        """
        self.stats["messages_processed"] += 1

        # 2.2-перф: один поиск вместо трёх кадров. `_route` остаётся
        # ЕДИНСТВЕННЫМ местом, где ответ ВЫЧИСЛЯЕТСЯ (инвариант Ф4.2 цел) —
        # кэш лишь помнит уже вычисленный. Часовой `_ROUTE_MISS` обязателен:
        # `None` здесь законное значение («отклонена гейтом»), и `.get(key)`
        # не отличил бы его от промаха, пересчитывая отклонённые каждый раз —
        # то есть ровно тот случай, ради которого кэш и заводится.
        if self._cache_enabled:
            cache_key = (scope, level, module)
            channels = self._route_cache.get(cache_key, _ROUTE_MISS)
            if channels is _ROUTE_MISS:
                channels = self._effective_route(scope, level, module)
                # Ф2.х (Н5): потолок — тот же, что у карты решений (ключ общий).
                if len(self._route_cache) >= _DECISION_CACHE_CEILING:
                    self._route_cache.clear()
                self._route_cache[cache_key] = channels
                self._check_scope_declared(scope, channels)
        else:
            channels = self._effective_route(scope, level, module)
            self._check_scope_declared(scope, channels)

        if channels is None:
            self.stats["messages_skipped"] += 1
            return

        # Строго ПОСЛЕ гейта: в этом весь смысл. И ровно один раз — запись
        # общая для всех каналов, поэтому число приёмников на цену не влияет.
        if not isinstance(message, str):
            try:
                message = message() if callable(message) else str(message)
            except Exception as exc:  # noqa: BLE001 — сборка сообщения не имеет права уронить эмитента
                # Ф1.4 переносит ДОРОГУЮ сборку внутрь логгера, а дорогая сборка
                # — ровно то, что умеет падать. Без этой ветки исключение
                # пробивалось в вызывающий код, и приложение падало на строчке
                # логирования (воспроизведено ревью Ф1, итерация 2). Политика
                # взята у соседнего пути: ``apply_format`` на кривом шаблоне
                # тоже сохраняет запись, а не теряет её. Два соседних пути с
                # противоположной политикой были бы худшим из вариантов.
                message = f"<сборка сообщения упала: {exc!r}>"
                self.stats["message_build_failures"] += 1
        if args:
            message = apply_format(message, args)

        record = LogRecord(
            timestamp=time.time(),
            level=level,
            scope=scope,
            message=message,
            module=module,
            extra=self._build_context(extra),
            # Пломба (2.V1) ставится ПОСЛЕ гейта и ДО любого приёмника — то
            # есть ровно на тех записях, которые обязаны оказаться на диске.
            # Отклонённая гейтом номера не получает намеренно: иначе дырка
            # означала бы «или потеря, или штатный отказ», и проверяющему
            # пришлось бы спрашивать счётчики — ровно то, чего 2.V1 избегает.
            seq=_next_seq(),
        )

        # Ф4.1: словарь собирается ОДИН раз на запись и дальше едет им.
        #
        # До цепочки ``to_dict()`` звался по разу на tap И по разу на КАЖДЫЙ
        # канал в батч-цикле: на трёх каналах с одним tap'ом — четыре сборки
        # одного и того же содержимого (числа сняты характеризацией до правки).
        # Запись общая для всех приёмников по построению, поэтому число
        # приёмников на цену сборки влиять не вправе.
        record_dict = record.to_dict()

        processed = self._run_processors(scope, level, record_dict)
        if processed is None:
            self.stats["records_dropped_by_processor"] += 1
            return
        record_dict = processed

        # Гейт по наличию tap'ов сохранён, хотя словарь уже собран: сам обход
        # tap'ов и вычисление severity — тоже цена на каждой записи.
        #
        # Порядок «процессоры → tap'ы» не косметика: tap уходит оператору и в
        # backend_ctl, и редакция секретов (4.5) обязана застать запись ДО него.
        # Иначе замаскированным оказался бы только файл.
        if self._tap_sinks:
            self._emit_to_taps(record_dict, level)

        if is_error_level(level):
            # Ф0.9 (floor, вариант B): error/critical НЕ буферизуются. Пачку целевых
            # каналов сбрасываем первой — иначе запись легла бы на диск раньше
            # предшествовавших ей INFO, и контекст перед падением потерял бы порядок.
            # Пустой список приёмников сюда тоже приходит — и floor его ловит.
            self._write_error_record(record_dict, channels)
        elif not channels:
            # Ни одного приёмника: запись потеряна, но НЕ молча. Раньше этот
            # случай проваливался в ветку буфера, ничего не клал и всё равно
            # инкрементировал ``messages_batched`` — счётчик врал в сторону
            # «ушло». Сам буфер снят в Ф7.4; ветка учёта осталась честной.
            self._count_records_without_channels(level)
        else:
            # Ф4.1: словарь ОДИН на все каналы. Прежний ``record.to_dict()``
            # внутри цикла давал каждому каналу свою копию — и это была не
            # изоляция, а побочный эффект сборки: копию никто не запрашивал.
            # Общий словарь безопасен, потому что запись после процессоров
            # **только читают**: каналы форматируют и пишут, а изменение
            # display-вида (``stamp_observed``) происходит уже на приёмной
            # стороне, за IPC, на своей копии. Разделяемая мутация здесь была бы
            # дефектом канала, и стережёт её отдельный тест.
            self._write_record_to_channels(record_dict, channels)

    # =========================================================================
    # FLOOR ОШИБОК (Ф0.9, вариант B — инвариант 1 плана observability-unified-routing)
    # =========================================================================

    @property
    def error_floor(self) -> ErrorFloor:
        """Пол ошибок. Ленивый: файл создаётся на первой реальной ошибке."""
        if self._error_floor is None:
            self._error_floor = get_error_floor(self._resolve_floor_path())
        return self._error_floor

    def _resolve_floor_path(self) -> str:
        """Куда класть floor: рядом с теми логами, которые он подстраховывает.

        ``log_directory`` есть не у всех менеджеров: прод собирает ErrorManager из
        ``ErrorManagerConfig`` с АБСОЛЮТНЫМИ путями каналов и без ``log_directory``
        (`managers_config.managers_from_log_dir`). Наивный резолв отправил бы его
        floor в системный temp, тогда как сам ``errors.log`` лежит в каталоге логов —
        пол оказался бы не там, где его станут искать.

        Поэтому: ``log_directory``, если задан; иначе каталог первого
        ВКЛЮЧЁННОГО файлового канала; иначе общий дефолт.

        Путь обязан быть ПРОЦЕССНЫМ, и это не косметика (блокер ревью Ф0.9,
        воспроизведён). Прод отдаёт всем процессам один и тот же абсолютный
        каталог логов, поэтому ветка «каталог файлового канала» сводила floor'ы
        ВСЕХ процессов в один файл. ``open(path, "a")`` на Windows атомарной
        дозаписи не даёт: 4 процесса × 300 записей давали ~9-11 % потерь и
        битые строки JSONL — в приёмнике последней инстанции, ровно во время
        системного шторма ошибок. Вторая половина того же дефекта: у ОДНОГО
        процесса floor'ов получалось два в разных каталогах (логгерный — в
        подпапке процесса, ошибочный — в корне), и в какой ляжет запись,
        зависело от того, какой менеджер её потерял. Отсюда ``_floor_scope()``:
        оба менеджера одного процесса дают один файл, разные процессы — разные.

        Фильтр по ``enabled`` — из той же находки: выключенный канал это ровно
        тот случай, ради которого floor существует, и он не должен ещё и
        решать, куда floor ляжет.
        """
        if self.config.log_directory:
            return self._resolved_file_path(None, FLOOR_FILE_NAME)

        for channel_config in self.config.channels.values():
            raw = getattr(channel_config, "file_path", None)
            if not raw or getattr(channel_config, "type", None) != "file":
                continue
            if not getattr(channel_config, "enabled", True):
                continue
            parent = Path(raw).expanduser().parent
            if parent.is_absolute():
                return str(parent / self._floor_scope() / FLOOR_FILE_NAME)

        return self._resolved_file_path(None, FLOOR_FILE_NAME)

    def _floor_scope(self) -> str:
        """Подкаталог, разводящий floor'ы разных процессов.

        Имя процесса, если оно известно; иначе PID — он различает процессы
        всегда, пусть и менее читаемо. Имя предпочтительнее: ``logs/camera/``
        ищется глазами, ``logs/17324/`` — нет.
        """
        name = getattr(self.process, "name", None) if self.process is not None else None
        return str(name) if name else f"pid_{os.getpid()}"

    # =========================================================================
    # ЦЕПОЧКА ПРОЦЕССОРОВ (Ф4.1)
    # =========================================================================

    def add_processor(self, processor: Processor) -> None:
        """Добавить процессор в конец цепочки.

        Порядок значим: процессоры видят запись в том порядке, в каком добавлены,
        и каждый следующий получает результат предыдущего.

        Список хранится **кортежем и заменяется целиком**, а не мутируется:
        ``log()`` зовут из многих потоков, и читатель обязан получить либо
        прежнюю цепочку, либо новую, но никогда — половину. Это тот же приём,
        что у tap'ов (снимок вместо блокировки): запись не должна ждать лока
        ради операции, которая случается раз в жизни процесса.
        """
        self._processors = (*self._processors, processor)

    def remove_processor(self, processor: Processor) -> bool:
        """Убрать процессор. ``False`` — если его в цепочке не было."""
        remaining = tuple(p for p in self._processors if p is not processor)
        if len(remaining) == len(self._processors):
            return False
        self._processors = remaining
        return True

    def _apply_sampling_config(self, log_config: "LoggerManagerConfig") -> None:
        """Ф7.1: параметры дросселя из конфига — БЕЗ сброса окон.

        ``getattr`` с дефолтом, потому что ``ErrorManager`` собирается из своей
        схемы (``ErrorManagerConfig``), у которой этих полей нет вовсе: у
        плоскости ошибок дроссель отключён по построению, и отсутствие полей —
        это ответ, а не пробел.
        """
        self._sampler.configure(
            first_n=getattr(log_config, "sampling_first_n", 0),
            every_mth=getattr(log_config, "sampling_every_mth", 100),
            burst_reset_sec=getattr(log_config, "sampling_burst_reset_sec", 5.0),
            max_level=getattr(log_config, "sampling_max_level", "DEBUG"),
        )

    def _run_processors(
        self,
        scope: ScopeName,
        level: LogLevel,
        record_dict: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Провести запись через цепочку. ``None`` = поглощена процессором.

        Две политики, и обе выбраны сознательно:

        * **процессор вернул ``None``** — запись поглощена НАМЕРЕННО (ради этого
          заводится сэмплинг Ф7.1). Законная потеря, но считаемая:
          ``records_dropped_by_processor``;
        * **процессор БРОСИЛ** — запись продолжает путь, отказ считается и
          слышен. Перехватчик не вправе терять то, что ему дали посмотреть:
          дефект в редакции секретов не должен превращаться в исчезновение
          логов. Та же политика, что у упавшей сборки сообщения выше.

        Цена на пустой цепочке — один проход по пустому кортежу; отдельного
        гейта ``if self._processors`` нет намеренно: он стоил бы столько же.
        """
        for processor in self._processors:
            try:
                result = processor(scope, level, record_dict)
            except Exception as exc:  # noqa: BLE001 — перехватчик не роняет эмитента
                self.stats["processor_failures"] += 1
                self._fallback_log(
                    "ERROR",
                    f"процессор {getattr(processor, '__name__', processor)!r} бросил "
                    f"{exc!r} — запись доставлена без его правки "
                    f"(см. processor_failures)",
                )
                continue
            if result is None:
                return None
            record_dict = result
        return record_dict

    def _write_error_record(self, record_dict: Dict[str, Any], channel_names: List[str]) -> None:
        """Синхронно записать error/critical; при нуле приёмников — в floor.

        Инвариант «одно место, без дублей»: floor пишет ТОЛЬКО когда обычный
        маршрут не записал НИ ОДНОГО канала. Пока хоть один канал жив, второй
        копии записи не появляется (это и отличает вариант B от отклонённого A).
        """
        written = self._write_record_to_channels(record_dict, channel_names)
        if written == 0:
            # Ни одного живого приёмника: каналы выключены конфигом, сняты
            # logger.sink.disable или все write упали. Запись обязана уцелеть.
            self._write_to_floor(record_dict)

    def _write_to_floor(self, record_dict: Dict[str, Any]) -> None:
        """Последняя попытка сохранить запись + ЧЕСТНЫЙ учёт её исхода.

        ``errors_to_floor`` считает записи, реально легшие в пол, а не
        переданные ему. Раньше счётчик инкрементировался ДО записи, а результат
        ``ErrorFloor.write`` отбрасывался — и при отказе самого пола (нет прав,
        каталог удалён, диск полон) запись исчезала полностью, а счётчик
        уверял, что она спасена. Это класс «следствие без причины»: счётчик,
        означающий «передано», хуже отсутствующего, потому что ему верят.
        Найдено ревью Ф0.9.

        Отказ пола уходит в stdlib-fallback уровнем CRITICAL: пол — последняя
        инстанция, и его отказ уже нельзя рассказать через собственные каналы.
        """
        if self.error_floor.write(record_dict):
            self.stats["errors_to_floor"] += 1
            return
        self.stats["errors_floor_write_failures"] += 1
        self._fallback_log(
            "CRITICAL",
            "запись об ошибке потеряна полностью: ни один приёмник не принял её, "
            "и пол ошибок тоже не смог записать (см. errors_floor_write_failures)",
        )

    def _build_context(self, extra: Dict[str, Any]) -> Dict[str, Any]:
        """Собрать ``extra`` записи из всех слоёв контекста — ЕДИНОЕ место сборки.

        Приоритет снизу вверх: форточка ``log_context`` → база процесса
        (:meth:`set_base_context`) → контекст потока (:meth:`push_context`) →
        явный ``extra`` вызова. Каждый следующий слой знает больше про
        конкретную запись, поэтому и перекрывает предыдущий.

        Выделено в метод по находке ревью фазы (2026-07-27, воспроизведено
        дважды двумя независимыми ревьюерами). Сборка была заинлайнена в
        ``LoggerCore.log``, а severity-путь ``ErrorManager.log`` — полный
        override — собирал свой ``extra`` руками и брал только потоковый слой.
        Итог: на ГЛАВНОМ производственном пути ошибок терялись ``proc_name``
        (ради которого Ф0.5 и вводила базу процесса) и вся форточка
        ``log_context``. Класс дефекта — не разовый промах, а свойство
        развилки: 0.4 зеркалили в двух местах, 0.9 в двух, tap'ы в двух, а
        0.5 забыли. Пока развилка жива (её убирает Ф4.2), общее обязано
        лежать в общем методе, а не копироваться.
        """
        return {
            **log_context.get(),
            **self._get_base_context(),
            **self._get_thread_context(),
            **extra,
        }

    # =========================================================================
    # КОНТЕКСТ
    # =========================================================================

    def push_context(self, **context_vars):
        """Добавить поля контекста ТЕКУЩЕМУ потоку (и текущему asyncio-таску).

        Вложенность работает: внутренний уровень перекрывает внешний по
        совпадающим ключам. Соседний поток этого не видит и не теряет своего.
        """
        stacks = _context_stacks.get()
        stack = stacks.get(self._ctx_key, ())
        merged = {**(stack[-1] if stack else {}), **context_vars}
        _context_stacks.set({**stacks, self._ctx_key: stack + (merged,)})

    def pop_context(self):
        """Снять верхний уровень контекста ТЕКУЩЕГО потока.

        В потоке, который ничего не клал, — тихий no-op. Раньше такой вызов
        снимал уровень, положенный ЧУЖИМ потоком: стек был один на инстанс.
        """
        stacks = _context_stacks.get()
        stack = stacks.get(self._ctx_key, ())
        if not stack:
            return
        _context_stacks.set({**stacks, self._ctx_key: stack[:-1]})

    def _get_thread_context(self) -> Dict[str, Any]:
        """Верхний уровень контекста текущего потока/таска (без базы процесса)."""
        stack = _context_stacks.get().get(self._ctx_key, ())
        return stack[-1] if stack else {}

    def set_base_context(self, **context_vars):
        """Задать поля контекста, видимые из ВСЕХ потоков процесса.

        Ф0.5, и это не украшение API, а необходимость. Единственный
        производственный потребитель контекста — процесс, который на старте
        кладёт ``proc_name`` из своего главного потока
        (``process_module.py``), а пишут логи потоки-воркеры. Сделай контекст
        просто thread-local — и ``proc_name`` молча исчезнет из всех записей
        воркеров, потому что новый поток стартует с чистым контекстом (это
        верно и для ``ContextVar``, не только для ``threading.local``).

        Фактов действительно два, и слоёв поэтому тоже два: база — про процесс
        целиком, стек ``push_context`` — про текущую работу текущего потока.
        Ключи базы перекрываются потоковым контекстом, а тот — явным ``extra``.

        Вызовы накапливаются (merge), не затирают друг друга.
        """
        with self._base_context_lock:
            self._base_context = {**self._base_context, **context_vars}

    def clear_base_context(self):
        """Очистить базу процесса — парная операция к :meth:`set_base_context`."""
        with self._base_context_lock:
            self._base_context = {}

    def _get_base_context(self) -> Dict[str, Any]:
        with self._base_context_lock:
            return self._base_context

    # =========================================================================
    # УДОБНЫЕ МЕТОДЫ ПО ОБЛАСТИ
    # =========================================================================

    def system(self, level: LogLevel, message: LogMessage, module: str = "main", *args: Any, **extra):
        self.log(LogScope.SYSTEM, level, message, module, *args, **extra)

    def business(self, level: LogLevel, message: LogMessage, module: str = "main", *args: Any, **extra):
        self.log(LogScope.BUSINESS, level, message, module, *args, **extra)

    def performance(self, level: LogLevel, message: LogMessage, module: str = "main", *args: Any, **extra):
        self.log(LogScope.PERFORMANCE, level, message, module, *args, **extra)

    def audit(self, level: LogLevel, message: LogMessage, module: str = "main", *args: Any, **extra):
        self.log(LogScope.AUDIT, level, message, module, *args, **extra)

    def security(self, level: LogLevel, message: LogMessage, module: str = "main", *args: Any, **extra):
        self.log(LogScope.SECURITY, level, message, module, *args, **extra)

    # =========================================================================
    # УДОБНЫЕ МЕТОДЫ ПО УРОВНЮ
    # =========================================================================
    #
    # Скоуп каждого из них обязан совпадать с таблицей _LEVEL_DEFAULT_SCOPE —
    # иначе is_enabled_for отвечает про другой маршрут. Сверяет тест-сетка
    # test_gate_predicate.py, а не глаз.

    def debug(self, message: LogMessage, module: str = "main", *args: Any, **extra):
        self.log(LogScope.DEBUG, LogLevel.DEBUG, message, module, *args, **extra)

    def info(self, message: LogMessage, module: str = "main", *args: Any, **extra):
        self.log(LogScope.BUSINESS, LogLevel.INFO, message, module, *args, **extra)

    def warning(self, message: LogMessage, module: str = "main", *args: Any, **extra):
        self.log(LogScope.SYSTEM, LogLevel.WARNING, message, module, *args, **extra)

    def error(self, message: LogMessage, module: str = "main", *args: Any, **extra):
        self.log(LogScope.SYSTEM, LogLevel.ERROR, message, module, *args, **extra)

    def critical(self, message: LogMessage, module: str = "main", *args: Any, **extra):
        self.log(LogScope.SYSTEM, LogLevel.CRITICAL, message, module, *args, **extra)

    # =========================================================================
    # SINK CONTROL PLANE — хук базы (Ф0.6)
    # =========================================================================

    def _recreate_channel(self, name: str) -> bool:
        """Пересоздать канал логгера по имени — хук ``CRM.set_sink_enabled(enabled=True)``.

        Пересоздаётся из ``self.config.channels[name]`` ДАЖЕ если там
        ``enabled=False``: включение через control-plane — явный override
        оператора над конфигом.

        **Ф2.6: второе место, где искались параметры, убрано.** До неё
        per-module каналы описывались секцией ``modules``, а не ``channels``, и
        ручка была ОДНОСТОРОННЕЙ: ``sink.disable`` проходил, а обратный
        ``enable`` возвращал ``success=false`` до перезапуска процесса
        (воспроизведено вживую на camera_0). Вместе с механизмом ушёл и порядок
        ветвления, который приходилось держать обратным, чтобы запись об отмене
        не была прочитана как описание канала и не породила фантомный файл.

        Сам toggle (закрыть/снять/зарегистрировать) живёт в базе: он одинаков
        у всех трёх плоскостей. Здесь только «откуда взять параметры».
        """
        channel_config = self.config.channels.get(name)
        if channel_config is not None:
            self._setup_channel(str(name), channel_config)  # пересоздаёт + регистрирует
            return self._channel_registry.get(name) is not None

        return False

    # =========================================================================
    # СТАТИСТИКА
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        base_stats = {
            "app_name": self.app_name,
            "messages_processed": self.stats["messages_processed"],
            "messages_skipped": self.stats["messages_skipped"],
            "channels_count": len(self._channel_registry),
            # Ф0.3: до этой правки счётчик жил только в self.stats и наружу не
            # выходил — «сколько ошибок не дошло ни до одного канала» нельзя было
            # спросить у живого процесса. Тот же класс, что потери буфера ниже.
            "errors_to_floor": self.stats["errors_to_floor"],
            "errors_floor_write_failures": self.stats["errors_floor_write_failures"],
            "message_build_failures": self.stats["message_build_failures"],
            "records_dropped_by_processor": self.stats["records_dropped_by_processor"],
            "processor_failures": self.stats["processor_failures"],
            # Ф4.5: без этих двух редакция ненаблюдаема — «ни одного секрета не
            # было» и «редактор не звался вовсе» дают одинаковые логи. Второй
            # ключ отдельно: сбой редакции означает запись с маркером вместо
            # содержимого (fail-closed), и молча так терять текст нельзя.
            "records_redacted": self._redactor.records_redacted,
            "redaction_failures": self._redactor.redaction_failures,
            # Ф7.1: дроссель. Три ключа, потому что три разных вопроса, и ни
            # один не выводится из соседей: сколько подавлено (потеря законная,
            # но обязана быть видна), сколько ключей под учётом (близость к
            # потолку видна ЗАРАНЕЕ, а не по факту насыщения) и сколько записей
            # прошло мимо дросселя из-за переполнения карты — то есть «дроссель
            # включён, а не работает».
            "records_sampled_out": self._sampler.records_sampled_out,
            "sampler_keys_tracked": self._sampler.keys_tracked,
            "sampler_keys_saturated": self._sampler.keys_saturated,
            "error_floor": (self._error_floor.stats if self._error_floor is not None else None),
        }

        # Ф0.4: потери на стыке «имя канала → объект канала». Ключи присутствуют
        # ВСЕГДА (нулями), а не появляются по факту потери: «ключа нет» и
        # «потерь нет» — разные факты, и потребитель не должен их путать.
        # Четыре класса потери + разбивка по каналам — из базы одним снимком.
        # Своя копия перечня здесь уже была источником расхождения (Ф0.4).
        base_stats.update(self._loss_counters_snapshot())
        with self._miss_lock:
            # Ф0.7: та же логика присутствия — ключи есть всегда, даже когда
            # ретеншен выключен. Нулевой ``retention_delete_failures`` при
            # ненулевом ``retention_files_deleted`` — «чистка работает»;
            # обратное сочетание — «настроена, но не может удалить».
            for key in _RETENTION_STAT_KEYS:
                base_stats[key] = self.stats[key]

        # R2: обратное давление консоли измеряет КАНАЛ (только он видит свою
        # запись), но спрашивают у менеджера — поэтому «живое с каналов» плюс
        # «унесённое ушедшими каналами».
        #
        # Прежний комментарий здесь утверждал, что сумма по каналам, в отличие
        # от копии счётчика, переживает пересоздание канала. Это НЕПРАВДА, и
        # ревью фазы это воспроизвело: `console_writes_dropped=7` →
        # `logger.sink.disable console` → readback 0. Канал уходит из реестра и
        # уносит историю с собой — а `sink.disable`/`reconfigure` это ровно то,
        # что делают ВО ВРЕМЯ инцидента, разбирая который эти числа и смотрят.
        # Поэтому при снятии канала его счётчики переезжают в накопитель
        # менеджера (см. `_absorb_channel_backpressure`), и наружу едет сумма
        # «накоплено + живое». Ключи присутствуют всегда, нулями.
        for key in _CHANNEL_BACKPRESSURE_KEYS:
            live = sum(getattr(ch, key, 0) for ch in self._channel_registry.all())
            base_stats[key] = self._absorbed_backpressure.get(key, 0) + live

        return base_stats

    # =========================================================================
    # СБРОС
    # =========================================================================

    def flush(self):
        """No-op: с Ф7.4 запись синхронна, накопленного между вызовами нет.

        Метод оставлен намеренно: его зовут ``shutdown``, команды наблюдаемости и
        прикладной код. Обещание «после flush запись на диске» он выполняет
        по-прежнему — только выполняет его сама запись, а не сброс пачки.
        """

    # =========================================================================
    # FRAME TRACE (Option A pipeline-live-control)
    # =========================================================================

    def frame_trace(self, message: str, seq_id: Any) -> None:
        """Записать строку в per-process snapshot последнего кадра (overwrite по seq_id).

        Идёт через LoggerManager-канал ``FrameTraceChannel`` (не сырой файл): канал
        буферизует строки текущего кадра и перезаписывает ``logs/trace/<process>.log``
        одним write на кадр (batched + overwrite). No-op без ``INSPECTOR_FRAME_TRACE=1``.

        **Граница с цепочкой процессоров — решение Ф7.5, названо здесь целиком.**
        Этот путь идёт МИМО :meth:`log`, то есть мимо ``_run_processors``. Из двух
        процессоров цепочки один зовётся явно, второй — сознательно нет:

        * **редакция (``SecretRedactor``) — зовётся.** ADR-LOG-006 сделал маскировку
          безусловной, а этот метод пишет на диск в обход неё. Сегодня единственный
          вызывающий (``process_managers._log_message_middleware``) передаёт только
          метаданные конверта (``type``/``sender``/``targets``/``data_type``/
          ``command``/``event_type``) — проверено по коду, пользовательских строк там
          нет. Но метод ПУБЛИЧНЫЙ и ничего такого не обещает: гарантия, которая держится
          на привычках единственного вызывающего, — не гарантия;
        * **сэмплинг (``RateSampler``) — НЕ зовётся, и это не забывчивость.** Дроссель
          душит повторы по ключу ``level+message``, а здесь повтор одинаковой строки на
          соседних кадрах — норма жанра. Задросселировать его значило бы выбросить
          именно те кадры, ради сравнения которых трассу и включают. Канал и так
          «батчит + перезаписывает», то есть объём ограничен кадром, а не темпом.

        Всю цепочку целиком не зовём по этой же причине: она приходит комплектом,
        а нужна её половина. Пара тестов (``test_frame_trace_boundary.py``) сторожит
        обе стороны решения — маскировку и невлияние сэмплинга.

        Args:
            message: строка цепочки (например, router-сообщение).
            seq_id: идентификатор кадра — граница перезаписи.
        """
        enabled = getattr(self, "_frame_trace_enabled", None)
        if enabled is None:
            import os

            enabled = os.environ.get("INSPECTOR_FRAME_TRACE", "").strip().lower() in ("1", "true", "yes")
            self._frame_trace_enabled = enabled
        if not enabled:
            return

        ch = getattr(self, "_frame_trace_channel", "unset")
        if ch == "unset":
            ch = self._ensure_frame_trace_channel()
        if ch is None:
            return
        record = {
            "module": "frame_trace",
            "level": "INFO",
            "message": message,
            "timestamp": time.time(),
            "extra": {"seq_id": seq_id},
        }
        # Ф7.5: половина цепочки, названная в докстринге. Редактор fail-closed сам
        # (при сбое отдаёт запись с маркером вместо содержимого), поэтому запись
        # не теряется, а её содержимое не утекает. ``or record`` — на случай, если
        # процессор когда-нибудь научится поглощать: трасса кадра поглощению не
        # подлежит, у неё своя граница объёма (перезапись по seq_id).
        record = self._redactor(LogScope.SYSTEM, "INFO", record) or record
        ch.write(record)

    def _ensure_frame_trace_channel(self) -> Optional[LogChannel]:
        """Лениво создать+зарегистрировать FrameTraceChannel (per-process trace-файл)."""
        proc = self.process.name if self.process else (self.config.app_name or "proc")
        path = self._resolved_file_path(None, f"trace/{proc}.log")
        try:
            cfg = LoggerChannelSchema(
                name=f"frame_trace_{proc}",
                type="frame_trace",
                enabled=True,
                file_path=path,
                format="%(message)s",
            )
            ch = create_channel(f"frame_trace_{proc}", cfg)
            self._channel_registry.register(ch)
            self._frame_trace_channel = ch
            return ch
        except Exception as e:
            self._fallback_log("ERROR", f"frame_trace channel failed: {e}")
            self._frame_trace_channel = None
            return None
