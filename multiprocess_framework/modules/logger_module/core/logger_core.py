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
  - self._buffer            — BatchBuffer для пакетной записи
  - self._dispatcher        — Dispatcher (базовый, для level-based routing в ErrorManager)

Публичный API не изменён (info, error, log, flush, get_stats и т.д.).
"""

import itertools
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
from contextvars import ContextVar

if TYPE_CHECKING:
    from multiprocessing import Process

from ...channel_routing_module import ChannelRoutingManager, resolve_build_result
from ...channel_routing_module.interfaces import channel_accepted
from ...channel_routing_module.buffers.batch_buffer import BatchBuffer, BatchConfig as CRMBatchConfig
from ..interfaces import ILoggerManager
from ..configs.logger_manager_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerModuleSchema,
    LoggerScopeSchema,
)
from .log_config import LogLevel, LogScope
from ...channel_routing_module.levels import is_error_level
from .error_floor import FLOOR_FILE_NAME, ErrorFloor, get_error_floor
from .log_types import LogRecord
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
      - self._buffer            — BatchBuffer для пакетной записи
      - self._dispatcher        — Dispatcher (базовый, для level-based routing в ErrorManager)

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
            dispatcher_key_field="level",
            managers=managers,
            auto_proxy=kwargs.get("auto_proxy", True),
        )

        self._config_manager = config_manager

        self.config = log_config
        self.app_name = log_config.app_name

        # R9: в базу ушло config=None (свой конфиг логгер резолвит сам), поэтому
        # слепок для отката база выставить не может — без этой строки второй
        # рубеж reconfigure у логгера и ошибок МЁРТВ: откатываться не к чему, и
        # сбой пересборки оставляет пустой реестр. Найдено слом-инъекцией B1.
        self._last_applied_config = log_config

        # Module-specific channels (separate from main registry)
        self._module_channels: Dict[str, LogChannel] = {}

        # Ф0.5: контекст в двух слоях. База — факт про процесс целиком, видна
        # всем потокам; стек push_context — факт про текущую работу текущего
        # потока/таска, соседям не виден. Один слой не покрывает оба случая:
        # чисто потоковый потерял бы proc_name у воркеров, чисто общий —
        # перемешал бы записи разных потоков (это и был дефект).
        self._ctx_key: int = next(_ctx_key_counter)
        self._base_context: Dict[str, Any] = {}
        self._base_context_lock = threading.Lock()

        # Ключ — КОРТЕЖ с Ф1.2 (см. should_log). Аннотация ``Dict[str, bool]``
        # пережила смену ключа и врала, пока её не поймало ревью.
        self._decision_cache: Dict[Tuple[LogScope, LogLevel, str], bool] = {}

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
        self._route_cache: Dict[Tuple[LogScope, LogLevel, str], Optional[Tuple[str, ...]]] = {}
        self._cache_enabled = True

        # Пол ошибок (Ф0.9) — ленивый: резолвится на первой записи, ушедшей в floor.
        self._error_floor: Optional[ErrorFloor] = None

        # Только СВОИ счётчики: четыре класса потери на стыке «менеджер → канал»
        # объявлены в базе (LOSS_COUNTER_KEYS) и общие для трёх плоскостей —
        # поэтому update(), а не присваивание: оно стёрло бы их.
        self.stats.update(
            {
                "messages_processed": 0,
                "messages_skipped": 0,
                "messages_batched": 0,
                "module_files_created": 0,
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
        self._setup_batcher()
        # Ретеншен применяется и на старте, а не только на reconfigure: процесс,
        # который подняли с настроенным ретеншеном и ни разу не переконфигурировали,
        # обязан чистить за собой — иначе чистка зависела бы от факта reload'а.
        self._enforce_retention()

    # =========================================================================
    # ЖИЗНЕННЫЙ ЦИКЛ
    # =========================================================================

    def initialize(self) -> bool:
        try:
            # _dispatcher (унаследован от ChannelRoutingManager) в LoggerManager мёртв:
            # ни одного register_handler/dispatch — логирование идёт через CRM-каналы +
            # BatchBuffer. Его no-op lifecycle не вызываем (план comm-system §11.16).
            # Инстанс остаётся в базе (его использует ErrorManager) — базу не трогаем.
            if self._buffer:
                self._buffer.start()
            self.is_initialized = True
            self.info("LoggerManager initialized", module="logger_manager")
            return True
        except Exception as e:
            self._fallback_log("ERROR", f"LoggerManager initialization failed: {e}")
            return False

    def shutdown(self) -> bool:
        try:
            self.info("LoggerManager shutting down", module="logger_manager")
            self.flush()
            if self._buffer:
                self._buffer.stop()
            # _dispatcher.shutdown() не вызываем — он мёртв в LoggerManager (§11.16, см. initialize).

            for channel in self._channel_registry.clear():
                try:
                    channel.close()
                except Exception as e:
                    self._fallback_log("ERROR", f"channel close failed: {e}")
            for channel in list(self._module_channels.values()):
                try:
                    channel.close()
                except Exception as e:
                    self._fallback_log("ERROR", f"module channel close failed: {e}")

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

    def _scope_schema(self, scope: LogScope) -> LoggerScopeSchema:
        """Скоуп из конфига или fallback (логика рядом с потребителем, не на схеме)."""
        key = scope.name
        if key in self.config.scopes:
            return self.config.scopes[key]
        ch = list(self.config.channels.keys())[:1] if self.config.channels else []
        return LoggerScopeSchema(
            enabled=True,
            min_level=self.config.default_level,
            channels=ch,
        )

    def _setup_channels(self):
        """Создать каналы из конфига и зарегистрировать в CRM registry.

        - channels: основные каналы (system_file, messages_file, console)
        - modules: отдельные файлы для модулей (database, processor, frames и т.д.)
        """
        for channel_name, channel_config in self.config.channels.items():
            if channel_config.enabled:
                self._setup_channel(str(channel_name), channel_config)

        # Автосоздание каналов для модулей из config.modules
        for module_name, module_config in self.config.modules.items():
            if getattr(module_config, "enabled", True) and getattr(module_config, "file_path", None):
                self._setup_module_channel(module_name, module_config)

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

    def _setup_module_channel(self, module_name: str, module_config: LoggerModuleSchema):
        """Создать файловый канал для module_* (из modules или enable_module_logging)."""
        path = self._resolved_file_path(
            module_config.file_path,
            f"logs/{module_name}.log",
        )
        max_size = module_config.max_size if module_config.max_size is not None else 10 * 1024 * 1024
        backup_count = module_config.backup_count if module_config.backup_count is not None else 5
        rotate = module_config.rotate
        try:
            ch_name = f"module_{module_name}"
            channel_config = LoggerChannelSchema(
                name=ch_name,
                type="file",
                enabled=True,
                file_path=path,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                max_size=max_size,
                backup_count=backup_count,
                rotate=rotate,
            )
            channel = create_channel(ch_name, channel_config)
            self._module_channels[module_name] = channel
            self._channel_registry.register(channel)
            self.stats["module_files_created"] += 1
            self.debug(
                f"Module channel created: {module_name} -> {path}",
                module="logger_manager",
            )
        except Exception as e:
            self._fallback_log("ERROR", f"Failed to setup module channel {module_name}: {e}")

    def _setup_batcher(self):
        """Настроить BatchBuffer из CRM если батчинг включён."""
        if self.config.enable_batching:
            self._buffer = BatchBuffer(
                flush_fn=self._flush_batch,
                config=CRMBatchConfig(
                    max_size=self.config.batch_size,
                    flush_interval=self.config.batch_interval,
                    # Ф0.3: потолок операбелен из конфига — иначе «ограничили»
                    # означало бы «зашили константу», и оператор не может ни
                    # поднять его под свою нагрузку, ни проверить срабатывание.
                    # Без getattr-фолбэка: поле объявлено в обеих схемах
                    # (Logger/Error), и молчаливый откат на свою копию дефолта
                    # прятал бы расхождение схем вместо того, чтобы его показать.
                    max_pending=self.config.batch_max_pending,
                    overflow_policy=self.config.batch_overflow_policy,
                ),
            )
        else:
            self._buffer = None

    # =========================================================================
    # РЕТЕНШЕН КАТАЛОГА ЛОГОВ (Ф0.7)
    # =========================================================================

    def _open_log_file_paths(self) -> List[str]:
        """Пути, в которые прямо сейчас пишут каналы этого менеджера.

        Их sweep не трогает никогда. Собираются из обоих мест: реестр CRM и
        отдельный словарь ``_module_channels`` — module-каналы лежат и там, и
        там, но полагаться на это нельзя (``disable_module_logging`` снимает
        только из реестра).
        """
        paths: List[str] = []
        for channel in list(self._channel_registry.all()) + list(self._module_channels.values()):
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

    def _enforce_retention(self) -> None:
        """Прогнать чистку каталога логов по текущему конфигу и учесть результат.

        Вызывается на старте и на каждом ``reconfigure``. Обе политики
        выключены по умолчанию — тогда это ранний выход без единого stat.
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
        (очистил реестр CRM). Но LoggerManager держит отдельный словарь
        ``_module_channels`` со ссылками на те же канал-объекты — их тоже надо
        закрыть и очистить, иначе ``_setup_channels`` создаст дубли.

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
        for channel in list(self._module_channels.values()):
            try:
                channel.close()
            except Exception as e:
                self._fallback_log("ERROR", f"module channel close failed: {e}")
        self._module_channels.clear()

        # 2. Применить новый конфиг.
        self.config = log_config
        self.app_name = self.config.app_name

        # 3. Остановить старый батчер перед пересозданием (если запущен).
        if self._buffer is not None:
            try:
                self._buffer.stop()
            except Exception as e:
                self._fallback_log("ERROR", f"buffer stop failed: {e}")
            self._buffer = None

        # 4. Воссоздать каналы и батчер из нового конфига.
        self._setup_channels()
        self._setup_batcher()
        if self.is_initialized and self._buffer is not None:
            self._buffer.start()

        # 5. Сбросить кэш решений should_log (критический баг — раньше не сбрасывался).
        self.invalidate_decision_cache()

        # 6. Применить ретеншен из нового конфига (Ф0.7). Порядок обязателен:
        # ПОСЛЕ пересоздания каналов, иначе список активных файлов был бы от
        # старого состава и sweep удалил бы файл только что открытого канала.
        self._enforce_retention()

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

        **Заодно снимается module-канал со своей карты (живая находка 2026-07-28).**
        ``disable_module_logging`` делает уборку правильно, а generic-путь
        ``set_sink_enabled(enabled=False)`` знал только реестр — запись
        оставалась в ``_module_channels``, откуда её продолжал доставать
        :meth:`_resolve_channel`. Результат воспроизведён на стенде: после
        ``logger.sink.disable module_trace`` пять записей модуля ушли в УЖЕ
        ЗАКРЫТЫЙ канал и легли в ``channel_refused_records`` (5) — то есть
        штатное «выключи мне этот лог» система показывала как потерю записей,
        а 2.V2 подняла бы по ней аномалию ``observability_loss``.
        """
        for key in _CHANNEL_BACKPRESSURE_KEYS:
            value = getattr(channel, key, 0)
            if value:
                self._absorbed_backpressure[key] = self._absorbed_backpressure.get(key, 0) + value

        name = getattr(channel, "name", None)
        if name and str(name).startswith("module_"):
            self._module_channels.pop(str(name)[len("module_") :], None)

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

    def _resolve_channel(self, name: str) -> Optional[Any]:
        """Плюс module-каналы к реестру базы.

        Они лежат отдельным словарём ``_module_channels`` и в реестре есть не
        всегда (``disable_module_logging`` снимает только из реестра). Без этого
        хука подъём писателя в базу молча потерял бы записи module-каналов —
        и потерял бы их «законно», через счётчик unresolved.
        """
        channel = self._channel_registry.get(name)
        if channel is None:
            channel = self._module_channels.get(name.replace("module_", "", 1))
        return channel

    def _flush_batch(self, channel: str, batch: List[Dict]) -> int:
        """Callback для BatchBuffer — записать пачку в канал.

        Returns:
            Число записей, которые канал ФАКТИЧЕСКИ принял.

        Возврат обязателен (Ф0.3, ревью). Раньше метод возвращал ``None`` и молча
        выходил, если канала нет, — буфер считал такую пачку доставленной, и при
        снятых приёмниках ``get_stats`` рапортовал «доставлено N, потерь 0» при
        нуле байт на диске. Разницу между отданным и принятым буфер теперь
        относит на ``flush_failed_by_channel``.
        """
        ch = self._channel_registry.get(channel)
        if ch is None:
            ch = self._module_channels.get(channel.replace("module_", "", 1))
        if ch is None:
            # Канала нет — вся пачка потеряна. Не событие «ничего не произошло».
            # Ф0.4: считаем ПОКАЗАПИСНО (не «одна пачка»), иначе размер потери
            # зависел бы от настроек батчинга, а не от числа потерянных записей.
            self._count_unresolved_channel(channel, len(batch))
            return 0

        written = 0
        for record_dict in batch:
            try:
                if _channel_accepted(ch.write(record_dict)):
                    written += 1
            except Exception:  # noqa: BLE001 — сбой одного канала не имеет права уронить эмитента; счётчик ниже делает потерю видимой
                self._count_channel_write_error(channel)
        return written

    # =========================================================================
    # ОСНОВНОЙ API ЛОГИРОВАНИЯ
    # =========================================================================

    def should_log(self, scope: LogScope, level: LogLevel, module: str) -> bool:
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
        self._decision_cache[cache_key] = result
        return result

    def _should_log_direct(self, scope: LogScope, level: LogLevel, module: str) -> bool:
        scope_config = self._scope_schema(scope)
        return scope_config.should_log(level, module)

    def _is_gate_open(self, scope: LogScope, level: LogLevel, module: str) -> bool:
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
        scope: Optional[LogScope] = None,
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

    def _route(self, scope: LogScope, level: LogLevel, module: str) -> Optional[List[str]]:
        """Куда пойдёт запись — и пойдёт ли вообще. ``None`` = отклонена гейтом.

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

        scope_config = self._scope_schema(scope)
        channels = scope_config.channels or self._channel_registry.names()

        if module in self._module_channels:
            channels = list(channels)
            module_channel = f"module_{module}"
            # Дедупликация обязательна, а не «на всякий случай»: когда у скоупа
            # НЕТ явного списка каналов, fallback берёт весь реестр — а module-канал
            # уже зарегистрирован в нём. Без проверки одна запись уходила в один и
            # тот же файл дважды, что прямо нарушает инвариант Ф0.9 «одна ошибка —
            # одна запись». В прод-дефолтах не стреляло (там скоупы со списками),
            # найдено ревью Ф0.9 с воспроизведением.
            if module_channel not in channels:
                channels.append(module_channel)

        return channels

    def _effective_route(self, scope: LogScope, level: LogLevel, module: str) -> Optional[Tuple[str, ...]]:
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
        scope: LogScope,
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
                self._route_cache[cache_key] = channels
        else:
            channels = self._effective_route(scope, level, module)

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

        # Гейт по наличию tap'ов до ``to_dict()``: сборка словаря ради пустой
        # рассылки — цена на каждой записи. У severity-пути эта проверка была,
        # у общего не было; слияние сохраняет дешёвую.
        if self._tap_sinks:
            self._emit_to_taps(record.to_dict(), level)

        if is_error_level(level):
            # Ф0.9 (floor, вариант B): error/critical НЕ буферизуются. Пачку целевых
            # каналов сбрасываем первой — иначе запись легла бы на диск раньше
            # предшествовавших ей INFO, и контекст перед падением потерял бы порядок.
            # Пустой список приёмников сюда тоже приходит — и floor его ловит.
            self._write_error_record(record, channels)
        elif not channels:
            # Ни одного приёмника: запись потеряна, но НЕ молча. Раньше этот
            # случай проваливался в ветку буфера, ничего не клал и всё равно
            # инкрементировал messages_batched — счётчик врал в сторону «ушло».
            self._count_records_without_channels(level)
        elif self._buffer:
            for ch_name in channels:
                self._buffer.enqueue(ch_name, record.to_dict())
            self.stats["messages_batched"] += 1
        else:
            self._write_record_to_channels(record, channels)

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

    def _write_error_record(self, record: LogRecord, channel_names: List[str]) -> None:
        """Синхронно записать error/critical; при нуле приёмников — в floor.

        Инвариант «одно место, без дублей»: floor пишет ТОЛЬКО когда обычный
        маршрут не записал НИ ОДНОГО канала. Пока хоть один канал жив, второй
        копии записи не появляется (это и отличает вариант B от отклонённого A).
        """
        if self._buffer is not None:
            # Порядок: сначала на диск уходит то, что накоплено ДО ошибки.
            for ch_name in channel_names:
                try:
                    self._buffer.flush(ch_name)
                except Exception:  # nosec B110 — сбой сброса не должен съесть саму ошибку
                    pass

        written = self._write_record_to_channels(record, channel_names)
        if written == 0:
            # Ни одного живого приёмника: каналы выключены конфигом, сняты
            # logger.sink.disable или все write упали. Запись обязана уцелеть.
            self._write_to_floor(record.to_dict())

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
    # УПРАВЛЕНИЕ МОДУЛЯМИ
    # =========================================================================

    def enable_module_logging(self, module_name: str, file_path: Optional[str] = None):
        self._setup_module_channel(module_name, LoggerModuleSchema(enabled=True, file_path=file_path))
        # Ф0.8: module-канал — такая же часть состава каналов, как sink.
        self._on_channels_changed()

    def disable_module_logging(self, module_name: str):
        if module_name not in self._module_channels:
            return
        channel = self._module_channels[module_name]
        try:
            channel.close()
        except Exception:  # nosec B110 — закрытие канала best-effort, ошибка не должна валить disable
            pass
        self._channel_registry.unregister(f"module_{module_name}")
        del self._module_channels[module_name]
        # F6: module-каналы — как раз тот случай, ради которого уборка и нужна:
        # их состав меняется в рантайме, и имя каждого навсегда оседало в
        # словарях буфера.
        self._forget_buffered_channel(f"module_{module_name}")
        self._on_channels_changed()

    # =========================================================================
    # SINK CONTROL PLANE — хук базы (Ф0.6)
    # =========================================================================

    def _recreate_channel(self, name: str) -> bool:
        """Пересоздать канал логгера по имени — хук ``CRM.set_sink_enabled(enabled=True)``.

        Пересоздаётся из ``self.config.channels[name]`` ДАЖЕ если там
        ``enabled=False``: включение через control-plane — явный override
        оператора над конфигом.

        **Module-каналы ищутся во ВТОРОМ месте (живая находка 2026-07-28).**
        Они описаны в ``config.modules``, а не в ``config.channels``, и прежняя
        редакция смотрела только в первый словарь — то есть ручка была
        ОДНОСТОРОННЕЙ: ``logger.sink.disable module_trace`` проходил, а обратный
        ``enable`` возвращал ``success=false``, и канал не возвращался до
        рестарта процесса. Воспроизведено вживую на camera_0. Прежний докстринг
        объяснял отказ тем, что «параметры взять негде» — для module-каналов это
        было неверно: параметры лежали рядом, и ``config.reload`` их оттуда
        доставал, восстанавливая канал. То есть отказ был не пределом, а дырой.

        Канал, поднятый ТОЛЬКО рантайм-вызовом ``enable_module_logging`` и не
        описанный в конфиге, вернуть по-прежнему неоткуда — вот там параметров
        действительно нет.

        Сам toggle (закрыть/снять/зарегистрировать) живёт в базе: он одинаков
        у всех трёх плоскостей. Здесь только «откуда взять параметры».
        """
        channel_config = self.config.channels.get(name)
        if channel_config is not None:
            self._setup_channel(str(name), channel_config)  # пересоздаёт + регистрирует
            return self._channel_registry.get(name) is not None

        text = str(name)
        if text.startswith("module_"):
            module_name = text[len("module_") :]
            module_config = self.config.modules.get(module_name)
            if module_config is not None:
                self._setup_module_channel(module_name, module_config)
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
            "module_channels_count": len(self._module_channels),
            "module_files_created": self.stats["module_files_created"],
            "batching_enabled": self.config.enable_batching,
            # Ф0.3: до этой правки счётчик жил только в self.stats и наружу не
            # выходил — «сколько ошибок не дошло ни до одного канала» нельзя было
            # спросить у живого процесса. Тот же класс, что потери буфера ниже.
            "errors_to_floor": self.stats["errors_to_floor"],
            "errors_floor_write_failures": self.stats["errors_floor_write_failures"],
            "message_build_failures": self.stats["message_build_failures"],
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

        if self._buffer:
            base_stats.update(
                {
                    "messages_batched": self.stats["messages_batched"],
                    "batch_stats": self._buffer.stats,
                }
            )

        return base_stats

    # =========================================================================
    # БУФЕР
    # =========================================================================

    def flush(self):
        if self._buffer:
            self._buffer.flush()

    # =========================================================================
    # FRAME TRACE (Option A pipeline-live-control)
    # =========================================================================

    def frame_trace(self, message: str, seq_id: Any) -> None:
        """Записать строку в per-process snapshot последнего кадра (overwrite по seq_id).

        Идёт через LoggerManager-канал ``FrameTraceChannel`` (не сырой файл): канал
        буферизует строки текущего кадра и перезаписывает ``logs/trace/<process>.log``
        одним write на кадр (batched + overwrite). No-op без ``INSPECTOR_FRAME_TRACE=1``.

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
        ch.write(
            {
                "module": "frame_trace",
                "level": "INFO",
                "message": message,
                "timestamp": time.time(),
                "extra": {"seq_id": seq_id},
            }
        )

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
