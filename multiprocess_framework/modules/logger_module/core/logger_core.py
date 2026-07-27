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
from typing import Any, Dict, List, Optional, TYPE_CHECKING
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
from ..channels.log_channel import create_channel, enforce_log_retention, LogChannel
from .log_paths import resolve_log_file_path

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

        self._decision_cache: Dict[str, bool] = {}
        self._cache_enabled = True

        # Пол ошибок (Ф0.9) — ленивый: резолвится на первой записи, ушедшей в floor.
        self._error_floor: Optional[ErrorFloor] = None

        self.stats = {
            "messages_processed": 0,
            "messages_skipped": 0,
            "messages_batched": 0,
            "module_files_created": 0,
            # Сколько раз штатный маршрут ошибок не принял запись и сработал floor.
            # Ненулевое значение — сигнал «маршрут ошибок сломан», а не норма.
            "errors_to_floor": 0,
            # Пол не смог записать — запись потеряна ПОЛНОСТЬЮ. Отдельно от
            # errors_to_floor: «спасено» и «не спасено» нельзя складывать.
            "errors_floor_write_failures": 0,
            # Ф0.4: запись адресована каналу, которого нет (опечатка в scopes,
            # канал снят logger.sink.disable, module-канал удалён). До этой правки
            # такая запись исчезала молча — ни счётчика, ни следа.
            "unresolved_channel_records": 0,
            # Ф0.4: канал есть, но его write() бросил исключение. Отличается от
            # отказа статусом {"status": "error"} — тот учтён как flush_failed
            # буфера; здесь именно проглоченное исключение.
            "channel_write_errors": 0,
            # Канал жив, но записи не принял (ответил status=error). Третий
            # класс потери — отдельно от «канала нет» и «канал бросил»: они
            # лечатся разным. Найдено ревью фазы: на прямом (небатченом) пути
            # такой отказ не считал НИКТО.
            "channel_refused_records": 0,
            # Ф0.7: результат чистки каталога логов (ключи — _RETENTION_STAT_KEYS).
            # Отдельно «удалили» и «не смогли удалить»: на Windows занятый файл
            # не удаляется, и молчащий ретеншен неотличим от работающего, если
            # считать только успехи.
            **{key: 0 for key in _RETENTION_STAT_KEYS},
        }

        # Разбивка потерь по именам каналов + «кому уже сказали». Живут отдельно
        # от self.stats: там только числа, здесь словари/множество.
        self._unresolved_channels: Dict[str, int] = {}
        self._channel_write_errors: Dict[str, int] = {}
        self._channel_refused: Dict[str, int] = {}
        self._warned_unknown_channels: set = set()
        self._warned_write_error_channels: set = set()
        self._warned_refused_channels: set = set()
        # R2: счётчики потерь ушедших каналов. Живут на менеджере, потому что
        # канал уносит свои с собой (см. _on_channel_removed).
        self._absorbed_backpressure: Dict[str, int] = {}
        # Берётся ТОЛЬКО на пути потери (канала нет / write бросил), поэтому на
        # здоровом пути не стоит ничего. Без него два потока-эмитента и поток
        # таймера буфера теряют инкременты — счётчик потерь врал бы в меньшую
        # сторону, то есть ровно в опасную.
        self._miss_lock = threading.Lock()

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

    def _setup_channel(self, channel_name: str, channel_config: LoggerChannelSchema):
        try:
            cfg = channel_config
            if channel_config.type == "file":
                fb = f"logs/{channel_name}.log"
                cfg = channel_config.model_copy(
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
        """
        self._decision_cache.clear()

    def _on_channel_removed(self, channel: Any) -> None:
        """Забрать у уходящего канала его счётчики потерь (R2).

        Иначе история теряется ровно в тот момент, когда её читают: разбирая
        инцидент с консолью, оператор жмёт ``logger.sink.disable console`` — и
        число отброшенных записей обнуляется вместе с каналом. Воспроизведено
        ревью фазы: 7 → disable → 0.

        Накопитель на менеджере складывается с живыми каналами в
        :meth:`get_stats`, поэтому сумма монотонна и переживает и снятие
        приёмника, и полный ``reconfigure``.
        """
        for key in _CHANNEL_BACKPRESSURE_KEYS:
            value = getattr(channel, key, 0)
            if value:
                self._absorbed_backpressure[key] = self._absorbed_backpressure.get(key, 0) + value

    def _on_channels_changed(self) -> None:
        """Состав каналов изменился в рантайме → решение should_log больше не доверенное.

        Ф0.8. **Сегодня это профилактика, а не починка симптома**, и врать об
        этом нельзя: ``_should_log_direct`` считает решение только по
        scope/level/module, состав каналов в него не входит — значит стейла
        сейчас физически не бывает.

        Правка сделана до появления симптома потому, что Ф2.2 кладёт в то же
        решение резолв ``effective_channels``. С этого момента ``logger.sink.disable``
        начал бы оставлять кэш с ответом про уже снятый канал — и симптом был
        бы не «лог не пишется», а «лог пишется в никуда», что ищется днями.
        Дешевле поставить инвалидацию сейчас, чем вспоминать про неё потом.

        Проверяемость обеспечена тестом-симуляцией Ф2.2: наследник, чьё
        ``_should_log_direct`` зависит от реестра каналов, без этого хука
        отвечает старой правдой.
        """
        self.invalidate_decision_cache()

    # =========================================================================
    # УЧЁТ ПОТЕРЬ НА СТЫКЕ «ИМЯ → КАНАЛ» (Ф0.4)
    # =========================================================================

    def _count_unresolved_channel(self, channel_name: str, count: int = 1) -> None:
        """Учесть ``count`` записей, ушедших в несуществующий канал, и один раз сказать об этом.

        Предупреждение — РОВНО ОДНО на имя за жизнь процесса: имя канала не
        меняется от записи к записи, а лог-шторм внутри логгера — та самая
        болезнь, ради которой соседние ``except`` стоят молча. Учёт при этом
        не глушится никогда: заглушённое предупреждение не должно означать
        «потерь нет».

        Предупреждение уходит через fallback-логгер (stdlib), а НЕ через
        собственную маршрутизацию: сообщение о том, что канал не резолвится,
        не имеет права зависеть от резолва каналов.
        """
        with self._miss_lock:
            self.stats["unresolved_channel_records"] += 1 * count
            self._unresolved_channels[channel_name] = self._unresolved_channels.get(channel_name, 0) + count
            total = self._unresolved_channels[channel_name]
            first_time = channel_name not in self._warned_unknown_channels
            if first_time:
                self._warned_unknown_channels.add(channel_name)

        if first_time:
            # Вне lock-а: fallback-логгер пишет в stderr/handlers, его цена
            # не должна удерживать счётчик потерь.
            self._fallback_log(
                "WARNING",
                f"канал {channel_name!r} не резолвится — записи до него не доходят "
                f"(учтено {total}; error/critical подстрахованы floor'ом, остальные "
                f"уровни потеряны; дальше считаем молча, счётчик в "
                f"get_stats['unresolved_channels'])",
            )

    def _count_channel_write_error(self, channel_name: str) -> None:
        """Учесть запись, потерянную из-за ИСКЛЮЧЕНИЯ в ``write()`` канала.

        Отказ статусом (``{"status": "error"}``) сюда НЕ попадает — у него свой
        счётчик :meth:`_count_channel_refused`. Прежняя формулировка этого
        docstring («отказ честно виден как разница отдано-минус-принято через
        flush_failed буфера») была ВЕРНА ТОЛЬКО ДЛЯ БАТЧЕНОГО ПУТИ и оказалась
        ровно тем неверным объяснением, из-за которого дыру на прямом пути
        никто не искал: буфера там нет, а значит нет и разницы, которую можно
        было бы увидеть.
        """
        with self._miss_lock:
            self.stats["channel_write_errors"] += 1
            self._channel_write_errors[channel_name] = self._channel_write_errors.get(channel_name, 0) + 1
            first_time = channel_name not in self._warned_write_error_channels
            if first_time:
                self._warned_write_error_channels.add(channel_name)

        if first_time:
            self._fallback_log(
                "WARNING",
                f"канал {channel_name!r} бросил исключение при записи — запись потеряна "
                f"(дальше считаем молча, счётчик в get_stats['channel_write_errors_by_channel'])",
            )

    def _count_channel_refused(self, channel_name: str) -> None:
        """Учесть запись, которую живой канал НЕ принял (ответил ``status=error``).

        Третий, отдельный класс потери — рядом с «канала нет»
        (``unresolved_channel_records``) и «канал бросил»
        (``channel_write_errors``). Смешивать их нельзя: они лечатся разным.
        «Канала нет» — опечатка в scopes или снятый sink; «бросил» — дефект
        канала; «не принял» — сток жив, но отказывает (закрыт, переполнен,
        консоль отброшена по пределу ожидания).
        """
        with self._miss_lock:
            self.stats["channel_refused_records"] += 1
            self._channel_refused[channel_name] = self._channel_refused.get(channel_name, 0) + 1
            first_time = channel_name not in self._warned_refused_channels
            if first_time:
                self._warned_refused_channels.add(channel_name)

        if first_time:
            self._fallback_log(
                "WARNING",
                f"канал {channel_name!r} не принял запись (ответил отказом) — запись потеряна "
                f"(дальше считаем молча, счётчик в get_stats['channel_refused_by_channel'])",
            )

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
        if not self._cache_enabled:
            return self._should_log_direct(scope, level, module)
        cache_key = f"{scope.value}:{level.value}:{module}"
        if cache_key in self._decision_cache:
            return self._decision_cache[cache_key]
        result = self._should_log_direct(scope, level, module)
        self._decision_cache[cache_key] = result
        return result

    def _should_log_direct(self, scope: LogScope, level: LogLevel, module: str) -> bool:
        scope_config = self._scope_schema(scope)
        return scope_config.should_log(level, module)

    def log(
        self,
        scope: LogScope,
        level: LogLevel,
        message: str,
        module: str = "main",
        **extra,
    ):
        self.stats["messages_processed"] += 1

        if not self.should_log(scope, level, module):
            self.stats["messages_skipped"] += 1
            return

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

        context = self._build_context(extra)

        record = LogRecord(
            timestamp=time.time(),
            level=level,
            scope=scope,
            message=message,
            module=module,
            extra=context,
        )

        self._emit_to_taps(record.to_dict(), level)

        if is_error_level(level):
            # Ф0.9 (floor, вариант B): error/critical НЕ буферизуются. Пачку целевых
            # каналов сбрасываем первой — иначе запись легла бы на диск раньше
            # предшествовавших ей INFO, и контекст перед падением потерял бы порядок.
            self._write_error_record(record, channels)
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

    def _write_record_to_channels(self, record: LogRecord, channel_names: List[str]) -> int:
        """Записать запись напрямую в названные каналы (мимо буфера).

        Принимает и ``LogRecord``, и уже готовый dict: severity-путь
        ``ErrorManager`` строит запись сам и обязан идти сюда же, а не иметь
        свою копию цикла (в его копии не считались ни отказ, ни отсутствие
        канала — см. ``channel_refused_records``).

        Returns:
            Число каналов, принявших запись. Ноль означает «запись никуда не легла» —
            по этому признаку ``_write_error_record`` включает floor.
        """
        record_dict = record.to_dict() if isinstance(record, LogRecord) else record
        written = 0
        for ch_name in channel_names:
            ch = self._channel_registry.get(ch_name)
            if ch is None:
                ch = self._module_channels.get(ch_name.replace("module_", "", 1))
            if ch is None:
                # Ф0.4: прямой путь теряет запись так же молча, как батчевый.
                self._count_unresolved_channel(ch_name)
                continue
            try:
                if _channel_accepted(ch.write(record_dict)):
                    written += 1
                else:
                    # Канал ЖИВ, но записи не принял (закрыт, консоль отброшена
                    # по пределу ожидания R2, HTTP-сток ответил ошибкой). На
                    # батченом пути такой отказ ловит flush_failed буфера, а на
                    # прямом — не ловил НИКТО: для error/critical запись спасал
                    # floor, а WARNING/INFO/DEBUG исчезали без единого следа.
                    # Путь достижим из прод-конфига: enable_batching операбелен
                    # из секции observability, то есть оператор мог выключить
                    # батчинг и молча включить потери. Находка ревью фазы.
                    self._count_channel_refused(ch_name)
            except Exception:  # noqa: BLE001 — сбой одного канала не должен съесть запись целиком; потеря учтена счётчиком
                self._count_channel_write_error(ch_name)
        return written

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

    def system(self, level: LogLevel, message: str, module: str = "main", **extra):
        self.log(LogScope.SYSTEM, level, message, module, **extra)

    def business(self, level: LogLevel, message: str, module: str = "main", **extra):
        self.log(LogScope.BUSINESS, level, message, module, **extra)

    def performance(self, level: LogLevel, message: str, module: str = "main", **extra):
        self.log(LogScope.PERFORMANCE, level, message, module, **extra)

    def audit(self, level: LogLevel, message: str, module: str = "main", **extra):
        self.log(LogScope.AUDIT, level, message, module, **extra)

    def security(self, level: LogLevel, message: str, module: str = "main", **extra):
        self.log(LogScope.SECURITY, level, message, module, **extra)

    # =========================================================================
    # УДОБНЫЕ МЕТОДЫ ПО УРОВНЮ
    # =========================================================================

    def debug(self, message: str, module: str = "main", **extra):
        self.log(LogScope.DEBUG, LogLevel.DEBUG, message, module, **extra)

    def info(self, message: str, module: str = "main", **extra):
        self.log(LogScope.BUSINESS, LogLevel.INFO, message, module, **extra)

    def warning(self, message: str, module: str = "main", **extra):
        self.log(LogScope.SYSTEM, LogLevel.WARNING, message, module, **extra)

    def error(self, message: str, module: str = "main", **extra):
        self.log(LogScope.SYSTEM, LogLevel.ERROR, message, module, **extra)

    def critical(self, message: str, module: str = "main", **extra):
        self.log(LogScope.SYSTEM, LogLevel.CRITICAL, message, module, **extra)

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
        self._on_channels_changed()

    # =========================================================================
    # SINK CONTROL PLANE — хук базы (Ф0.6)
    # =========================================================================

    def _recreate_channel(self, name: str) -> bool:
        """Пересоздать канал логгера по имени — хук ``CRM.set_sink_enabled(enabled=True)``.

        Пересоздаётся из ``self.config.channels[name]`` ДАЖЕ если там
        ``enabled=False``: включение через control-plane — явный override
        оператора над конфигом. Канал, не описанный в конфиге, включить
        неоткуда — параметры взять негде.

        Сам toggle (закрыть/снять/зарегистрировать) живёт в базе: он одинаков
        у всех трёх плоскостей. Здесь только «откуда взять параметры».
        """
        channel_config = self.config.channels.get(name)
        if channel_config is None:
            return False
        self._setup_channel(str(name), channel_config)  # пересоздаёт + регистрирует
        return self._channel_registry.get(name) is not None

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
            "error_floor": (self._error_floor.stats if self._error_floor is not None else None),
        }

        # Ф0.4: потери на стыке «имя канала → объект канала». Ключи присутствуют
        # ВСЕГДА (нулями), а не появляются по факту потери: «ключа нет» и
        # «потерь нет» — разные факты, и потребитель не должен их путать.
        with self._miss_lock:
            base_stats["unresolved_channel_records"] = self.stats["unresolved_channel_records"]
            base_stats["unresolved_channels"] = dict(self._unresolved_channels)
            base_stats["channel_write_errors"] = self.stats["channel_write_errors"]
            base_stats["channel_write_errors_by_channel"] = dict(self._channel_write_errors)
            base_stats["channel_refused_records"] = self.stats["channel_refused_records"]
            base_stats["channel_refused_by_channel"] = dict(self._channel_refused)
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
