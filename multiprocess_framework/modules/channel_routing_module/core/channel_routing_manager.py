# -*- coding: utf-8 -*-
"""
ChannelRoutingManager — базовый менеджер маршрутизации по каналам.

Устраняет дублирование между RouterManager, LoggerManager и ErrorManager:
  - ChannelRegistry          (thread-safe хранилище каналов)
  - Dispatcher               (маршрутизация ключ → обработчик)
  - IBufferStrategy          (опциональная буферизация)
  - normalize_config()       (Dict at Boundary)

Наследники настраивают, но не переписывают:
  - RouterManager  — key=command/type, buffer=AsyncSenderBuffer, channels=IMessageChannel
  - LoggerCore     — key=level/scope,  buffer=BatchBuffer,       channels=ILogChannel
                     (LoggerManager = LoggerCore + process-singleton)
  - ErrorManager   — брат LoggerManager (общий предок LoggerCore), + severity routing
  - StatsManager   — key=metric_name,  buffer=AggregationWindow, channels=IMetricChannel
"""

import logging as _stdlib_logging
import threading
from typing import Any, Callable, Dict, List, Optional, Union

from ...base_manager import BaseManager, ObservableMixin
from ...dispatch_module import Dispatcher, DispatchStrategy
from ..interfaces import IChannel, IBufferStrategy, IChannelRoutingManager, channel_accepted
from ..levels import level_rank
from .channel_registry import ChannelRegistry
from .config_normalizer import normalize_config

#: Приёмник последней надежды. Именно stdlib, а не собственные каналы: сообщение
#: о поломке маршрута наблюдаемости не имеет права идти по этому же маршруту.
_fallback_logger = _stdlib_logging.getLogger(__name__)

#: Четыре класса потери записи на стыке «менеджер → канал». Один список на
#: объявление в ``self.stats``, на выдачу в ``get_stats`` и на реестр публикации
#: ``PLANE_COUNTER_KEYS``: разъехавшийся перечень уже стоил одной невидимой
#: наружу метрики (урок Ф0.4). Классы не сливаются, потому что лечатся разным:
#: «канала нет» — опечатка в конфиге или снятый sink; «бросил» — дефект канала;
#: «не принял» — сток жив, но отказывает; «приёмников нет вовсе» — пустой реестр.
LOSS_COUNTER_KEYS = (
    "unresolved_channel_records",
    "channel_write_errors",
    "channel_refused_records",
    "records_without_channels",
)

#: Маркер «config не удалось нормализовать». normalize_config на любом отказе
#: возвращает копию default, поэтому отличить отказ от пустого dict можно только
#: по содержимому. Ключ намеренно уродливый — он не должен встретиться в конфиге.
_UNNORMALIZABLE = "__crm_unnormalizable__"


class ChannelRoutingManager(BaseManager, ObservableMixin, IChannelRoutingManager):
    """Базовый менеджер маршрутизации: канальный реестр + диспетчер + буфер.

    Общие методы (пишутся один раз, используются всеми наследниками):
        register_channel()      — thread-safe регистрация канала
        unregister_channel()    — thread-safe удаление канала
        get_channel()           — получить канал по имени
        get_all_channels()      — список всех каналов
        register_route()        — зарегистрировать правило маршрутизации
        register_broadcast()    — отправить в несколько каналов
        route()                 — маршрутизировать данные к каналу
        flush()                 — принудительный сброс буфера
        get_stats()             — статистика (каналы, буфер, роутинг)

    Типичное использование (наследование):
        class LoggerManager(ChannelRoutingManager):
            def __init__(self, config=None):
                super().__init__(
                    "LoggerManager",
                    config=config,
                    buffer_strategy=BatchBuffer(flush_fn=self._do_batch_flush),
                    dispatcher_key_field="level",
                )
            def initialize(self) -> bool:
                result = super().initialize()
                self._setup_channels_from_config()
                return result
    """

    def __init__(
        self,
        manager_name: str,
        config: Optional[Union[Dict[str, Any], Any]] = None,
        buffer_strategy: Optional[IBufferStrategy] = None,
        dispatcher_key_field: str = "type",
        dispatcher_strategy: Optional[DispatchStrategy] = None,
        managers: Optional[Dict[str, Any]] = None,
        process: Optional[Any] = None,
        observable_config: Optional[Dict[str, Any]] = None,
        auto_proxy: bool = False,
        **kwargs,
    ) -> None:
        """
        Args:
            manager_name:         Уникальное имя менеджера
            config:               None | dict | RegisterBase (normalize_config обработает)
            buffer_strategy:      Стратегия буферизации. None = прямой write()
            dispatcher_key_field: Поле в data для ключа маршрутизации (по умолчанию "type")
            dispatcher_strategy:  Стратегия Dispatcher по умолчанию (EXACT_MATCH, PATTERN и т.д.)
            managers:             Словарь менеджеров для ObservableMixin
            process:              Ссылка на родительский процесс
            observable_config:    Конфиг для ObservableMixin (enable/disable managers)
            auto_proxy:           Создать публичные прокси-методы (ObservableMixin)
            **kwargs:             Дополнительные параметры ObservableMixin
        """
        BaseManager.__init__(self, manager_name, process=process)
        ObservableMixin.__init__(
            self,
            managers=managers or {},
            config=observable_config,
            auto_proxy=auto_proxy,
            **kwargs,
        )

        self._config = normalize_config(config)
        # R9: последний ПРИНЯТЫЙ ввод конфига в исходной форме (dict / pydantic /
        # build()-объект). Нужен для отката, когда пересборка развалилась уже
        # после закрытия старых каналов. Храним сырой ввод, а не нормализованный
        # dict: наследники строятся именно из него (ErrorManager теряет
        # include_stacktrace на dict-форме LoggerManagerConfig).
        self._last_applied_config: Optional[Union[Dict[str, Any], Any]] = config
        self._key_field = dispatcher_key_field
        self._buffer = buffer_strategy

        self._channel_registry = ChannelRegistry(
            log_warning=self._log_warning,
            log_error=self._log_error,
            log_debug=self._log_debug,
        )

        self._dispatcher = Dispatcher(
            f"{manager_name}_dispatcher",
            process=process,
            default_strategy=dispatcher_strategy or DispatchStrategy.EXACT_MATCH,
        )

        # Tap-приёмники (Ф0.6 — подъём из LoggerCore). Живут ОТДЕЛЬНО от
        # _channel_registry: reconfigure() их не сбрасывает, подписка на tail
        # переживает hot-reload. {имя: (IChannel, min_rank)}.
        self._tap_sinks: Dict[str, tuple] = {}

        self._routed: int = 0
        self._errors: int = 0

        # P5: учёт потерь — общее хозяйство ТРЁХ плоскостей, а не логгера.
        # До подъёма он жил в LoggerCore: у логов и ошибок потеря была названа и
        # видна наружу, а у статистики ``_do_flush`` ловил только исключение и
        # увеличивал безымянный ``_errors``. Инвариант «дроп допустим, невидимый
        # дроп — нет» работал для двух плоскостей из трёх.
        self.stats: Dict[str, Any] = {key: 0 for key in LOSS_COUNTER_KEYS}
        # Разбивка по именам каналов + «кому уже сказали». Отдельно от stats:
        # там только числа, здесь словари и множества.
        self._unresolved_channels: Dict[str, int] = {}
        self._channel_write_errors: Dict[str, int] = {}
        self._channel_refused: Dict[str, int] = {}
        self._warned_unknown_channels: set = set()
        self._warned_write_error_channels: set = set()
        self._warned_refused_channels: set = set()
        # «Приёмников нет вовсе» — привязать предупреждение не к чему, поэтому
        # один флаг, а не множество имён.
        self._warned_without_channels: bool = False
        # Берётся ТОЛЬКО на пути потери, поэтому на здоровом пути не стоит
        # ничего. Без него два потока-эмитента и поток таймера буфера теряют
        # инкременты — счётчик потерь врал бы в меньшую сторону, то есть ровно
        # в опасную.
        self._miss_lock = threading.Lock()

    # =========================================================================
    # ЖИЗНЕННЫЙ ЦИКЛ
    # =========================================================================

    def initialize(self) -> bool:
        """Инициализировать менеджер и все его компоненты.

        Вызывает initialize() у Dispatcher и start() у буфера (если есть).
        Наследники должны вызывать super().initialize() в начале своего initialize().
        """
        try:
            self._dispatcher.initialize()
            if self._buffer:
                self._buffer.start()
            self.is_initialized = True
            self._log_info(f"[{self.manager_name}] initialized")
            return True
        except Exception as e:
            self._log_error(f"[{self.manager_name}] initialization failed: {e}")
            return False

    def reconfigure(self, config: Union[Dict[str, Any], Any]) -> bool:
        """Пересобрать каналы/маршруты из нового конфига (validate-then-swap).

        Оркестрация (reuse существующих примитивов):
            normalize_config()    → привести dict/RegisterBase к dict (Dict at Boundary);
            _validate_config()    → хук наследника: разобрать новый конфиг ДО разрушения;
            flush()  → сбросить накопленный буфер старого набора каналов;
            _close_all_channels() → закрыть и очистить реестр каналов;
            _rebuild_from_config() → хук наследника, строящий новые каналы/маршруты.

        **R9 — порядок здесь и есть починка.** Раньше ``_close_all_channels()``
        стоял ПЕРЕД разбором конфига, а разбор жил внутри ``_rebuild_from_config``
        у наследника. Любой отвергнутый reload (одна опечатка в значении поля)
        оставлял менеджер с пустым реестром: воспроизведено 12 каналов → 0,
        ``system.log`` 0 байт. Отказ применить конфиг превращался в разрушение
        наблюдаемости — включая возможность узнать, что именно случилось.

        Два рубежа, и они защищают от разного:
          1. ``_validate_config`` — конфиг не разобрался: реестр НЕ тронут вовсе;
          2. откат — конфиг разобрался, но пересборка развалилась (сломанный
             путь, отказ ОС при открытии файла): каналы воссоздаются из
             последнего принятого конфига.

        Откат восстанавливает конфиг, а не рантайм-надстройки над ним: каналы,
        добавленные после reconfigure в обход конфига (``enable_module_logging``),
        в слепок не входят и будут потеряны. Проверено тестом
        ``test_rollback_loses_runtime_module_channel`` — записано как известное
        поведение отката, а не как гарантия обратного.

        Базовая реализация делает no-op rebuild и no-op валидацию (наследники
        переопределяют оба хука). Метод идемпотентен и безопасен до initialize():
        буфер может быть не запущен, flush() в этом случае ничего не делает.

        Args:
            config: None | dict | объект с build() — новый конфиг.

        Returns:
            True при успешной пересборке; False при невалидном конфиге или ошибке
            (процесс при этом НЕ роняется — ошибка логируется).
        """
        if config is None:
            self._log_warning(f"[{self.manager_name}] reconfigure: config=None — пропущено")
            return False

        # Ветка «не разобрался» отличается от «разобрался в пустой dict» ТОЛЬКО
        # маркером в default: normalize_config на любом отказе возвращает копию
        # default, и прежняя проверка `not isinstance(normalized, dict)` была
        # мёртвой — она не срабатывала никогда. Цена мёртвой проверки: мусор на
        # входе (`reconfigure(42)`) нормализовался в {} и применялся как валидный
        # пустой конфиг, то есть тихо сносил все каналы и рапортовал успех. Тот
        # же класс, что R9, только через другую дверь.
        normalized = normalize_config(config, default={_UNNORMALIZABLE: True})
        if _UNNORMALIZABLE in normalized:
            self._log_warning(f"[{self.manager_name}] reconfigure: невалидный config ({type(config)!r}) — пропущено")
            return False

        # Рубеж 1: разобрать новый конфиг ДО того, как закрыт хоть один канал.
        try:
            self._validate_config(normalized)
        except Exception as e:
            self._log_error(
                f"[{self.manager_name}] reconfigure отвергнут: {e}; "
                f"реестр не тронут ({len(self._channel_registry)} каналов)"
            )
            return False

        previous = self._last_applied_config
        try:
            self.flush()
            self._close_all_channels()
            self._config = normalized
            self._rebuild_from_config(normalized)
            self._last_applied_config = config
            self._log_info(f"[{self.manager_name}] reconfigured: {len(self._channel_registry)} каналов")
            return True
        except Exception as e:
            # Рубеж 2: конфиг прошёл валидацию, но пересборка развалилась на
            # полпути — реестр сейчас пуст или заполнен наполовину.
            self._log_error(f"[{self.manager_name}] reconfigure failed: {e}")
            self._rollback_to(previous, reason=str(e))
            return False

    def _rollback_to(self, previous: Optional[Union[Dict[str, Any], Any]], *, reason: str) -> bool:
        """Воссоздать каналы из последнего принятого конфига после сбоя пересборки.

        Сбой отката логируется отдельным сообщением и НЕ бросается наружу:
        ``reconfigure`` в этот момент уже возвращает False, а исключение из
        обработчика сбоя заменило бы понятную причину («не смог пересобрать»)
        на непонятную («не смог откатиться»).

        Returns:
            True если откат прошёл; False если менеджер остался без каналов —
            это худший исход, и он назван в логе явно.
        """
        if previous is None:
            self._log_error(
                f"[{self.manager_name}] откат невозможен: принятого конфига ещё не было; "
                f"каналов {len(self._channel_registry)}"
            )
            return False
        try:
            self._close_all_channels()
            self._config = normalize_config(previous)
            self._rebuild_from_config(previous)
            self._log_warning(
                f"[{self.manager_name}] откат к предыдущему конфигу после сбоя ({reason}): "
                f"{len(self._channel_registry)} каналов"
            )
            return True
        except Exception as rollback_error:
            self._log_error(
                f"[{self.manager_name}] ОТКАТ НЕ УДАЛСЯ ({rollback_error}) после сбоя ({reason}); "
                f"каналов {len(self._channel_registry)}"
            )
            return False

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """Хук проверки нового конфига ДО разрушения реестра (no-op по умолчанию).

        Контракт: наследник **бросает исключение**, если конфиг не годится.
        Возвращаемое значение игнорируется — результат разбора здесь намеренно
        не переиспользуется в ``_rebuild_from_config``: два независимых разбора
        стоят микросекунды на редком пути, а протаскивание готового объекта
        через сигнатуру хука сделало бы её третьим контрактом между базой и
        тремя наследниками.

        База не валидирует ничего: у ``StatsManager`` конфиг — свободный dict,
        у ``RouterManager`` (транспортный наследник) своего формата каналов нет.
        """

    def _rebuild_from_config(self, config: Dict[str, Any]) -> None:
        """Хук пересборки каналов/маршрутов из dict (no-op по умолчанию).

        Наследники переопределяют, чтобы воссоздать свой набор каналов из
        нового конфига после того как ``reconfigure`` закрыл старые. База ничего
        не строит — конкретные менеджеры (Logger/Stats/Error) знают свой формат.

        Зовётся и на откате (``_rollback_to``) — тогда аргументом приходит
        последний принятый конфиг в исходной форме, не обязательно dict.
        """

    def shutdown(self) -> bool:
        """Корректное завершение: flush → stop buffer → close channels → shutdown dispatcher."""
        try:
            self._log_info(f"[{self.manager_name}] shutting down")
            self.flush()
            if self._buffer:
                self._buffer.stop()
            self._close_all_channels()
            self._dispatcher.shutdown()
            self.is_initialized = False
            return True
        except Exception as e:
            self._log_error(f"[{self.manager_name}] shutdown error: {e}")
            return False

    # =========================================================================
    # УПРАВЛЕНИЕ КАНАЛАМИ  (IChannelRoutingManager)
    # =========================================================================

    def register_channel(self, channel: IChannel) -> bool:
        """Зарегистрировать канал.

        Сохраняет канал в реестре и регистрирует его write() (или buffered write)
        как обработчик в Dispatcher под ключом = channel.name.

        Returns:
            True если канал зарегистрирован успешно
        """
        if not self._channel_registry.register(channel):
            return False
        self._register_channel_handler(channel)
        return True

    def unregister_channel(self, name: str) -> bool:
        """Удалить канал по имени.

        Returns:
            True если канал был найден и удалён
        """
        return self._channel_registry.unregister(name)

    def get_channel(self, name: str) -> Optional[IChannel]:
        """Получить канал по имени или None."""
        return self._channel_registry.get(name)

    def get_all_channels(self) -> List[IChannel]:
        """Список всех зарегистрированных каналов."""
        return self._channel_registry.all()

    # =========================================================================
    # МАРШРУТИЗАЦИЯ  (IChannelRoutingManager)
    # =========================================================================

    def register_route(
        self,
        key: str,
        channel_name: str,
        strategy: Any = None,
        efficiency: int = 0,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Зарегистрировать правило маршрутизации: ключ → канал.

        После регистрации route(data) с data[key_field]==key будет писать в channel_name.

        Args:
            key:          Значение ключа для маршрутизации (напр. "INFO", "error")
            channel_name: Имя целевого канала (должен быть зарегистрирован)
            strategy:     DispatchStrategy (EXACT, PATTERN, CHAIN, FALLBACK)
            efficiency:   Приоритет (чем выше — тем предпочтительнее при конкурентных правилах)
            tags:         Теги для фильтрации/диагностики

        Returns:
            True если правило зарегистрировано
        """
        ch = self._channel_registry.get(channel_name)
        if ch is None:
            self._log_warning(f"[{self.manager_name}] register_route: channel '{channel_name}' not found")
            return False

        handler = self._make_handler(channel_name, ch)
        return self._dispatcher.register_handler(
            key,
            handler,
            expects_full_message=True,
            efficiency=efficiency,
            tags=tags or [],
            strategy=strategy,
        )

    def register_broadcast(
        self,
        key: str,
        channel_names: List[str],
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Зарегистрировать широковещательный маршрут: ключ → несколько каналов.

        Args:
            key:           Значение ключа для маршрутизации
            channel_names: Список имён целевых каналов
            tags:          Теги для фильтрации/диагностики

        Returns:
            True если все каналы найдены и маршрут зарегистрирован
        """
        channels: List[IChannel] = []
        for name in channel_names:
            ch = self._channel_registry.get(name)
            if ch is None:
                self._log_warning(f"[{self.manager_name}] register_broadcast: channel '{name}' not found")
                return False
            channels.append(ch)

        def _broadcast_handler(data: Dict[str, Any]) -> Dict[str, Any]:
            results = []
            for ch_name, ch in zip(channel_names, channels):
                try:
                    if self._buffer is not None:
                        self._buffer.enqueue(ch_name, data)
                        results.append({"channel": ch_name, "status": "queued"})
                    else:
                        res = ch.write(data)
                        results.append(res)
                except Exception as e:
                    results.append({"channel": ch_name, "status": "error", "error": str(e)})
            return {"status": "broadcast", "results": results}

        return self._dispatcher.register_handler(
            key,
            _broadcast_handler,
            expects_full_message=True,
            tags=tags or [],
        )

    def route(
        self,
        data: Dict[str, Any],
        key_field: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Маршрутизировать данные к подходящему каналу.

        Извлекает ключ из data[key_field] и вызывает соответствующий обработчик
        через Dispatcher. Результат возвращается напрямую.

        Args:
            data:      Словарь с данными (должен содержать поле key_field)
            key_field: Поле для извлечения ключа. None → self._key_field

        Returns:
            {"status": "success"|"error"|"unhandled", ...}
        """
        kf = key_field or self._key_field
        try:
            result = self._dispatcher.dispatch(data, key_field=kf)
            self._routed += 1
            if isinstance(result, dict):
                return result
            return {"status": "success"}
        except Exception as e:
            self._errors += 1
            self._log_error(f"[{self.manager_name}] route error: {e}")
            return {"status": "error", "error": str(e)}

    # =========================================================================
    # БУФЕРИЗАЦИЯ  (IChannelRoutingManager)
    # =========================================================================

    def flush(self) -> None:
        """Принудительно сбросить все буферизованные данные."""
        if self._buffer:
            self._buffer.flush()

    # =========================================================================
    # СТАТИСТИКА
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Статистика: базовая от BaseManager + каналы + буфер + роутинг."""
        stats = super().get_stats()
        stats.update(
            {
                "channel_count": len(self._channel_registry),
                "channels": self._channel_registry.names(),
                "channel_info": self._channel_registry.get_info(),
                "routed": self._routed,
                "errors": self._errors,
                "key_field": self._key_field,
            }
        )
        if self._buffer is not None:
            stats["buffer"] = self._buffer.stats
        stats.update(self._loss_counters_snapshot())
        return stats

    def _loss_counters_snapshot(self) -> Dict[str, Any]:
        """Четыре класса потери + разбивка по каналам — снимок под одним lock-ом.

        Ключи присутствуют ВСЕГДА (нулями), а не появляются по факту потери:
        «ключа нет» и «потерь нет» — разные факты, и потребитель
        ``introspect.observability`` не должен их путать. Отдельный метод, потому
        что ``LoggerCore.get_stats`` собирает свой словарь сам и обязан взять
        ровно те же ключи, а не свою копию перечня.
        """
        with self._miss_lock:
            snapshot: Dict[str, Any] = {key: self.stats[key] for key in LOSS_COUNTER_KEYS}
            snapshot["unresolved_channels"] = dict(self._unresolved_channels)
            snapshot["channel_write_errors_by_channel"] = dict(self._channel_write_errors)
            snapshot["channel_refused_by_channel"] = dict(self._channel_refused)
        return snapshot

    # =========================================================================
    # SINK CONTROL PLANE (Ф0.6 — общее хозяйство трёх плоскостей)
    # =========================================================================

    def set_sink_enabled(self, name: str, enabled: bool) -> bool:
        """Включить/выключить приёмник по имени на лету — IPC control-plane.

        Якорь ADR-CRM-006 п.3. До Ф0.6 метод жил только у ``LoggerCore``, и
        оператор мог снять приёмник логов, но не приёмник статистики: одна и
        та же операция была доступна одному брату из трёх.

        **Выключение полностью generic** — закрыть канал и снять с реестра;
        оно ничего не знает о том, откуда канал взялся. **Включение** требует
        пересоздать канал из конфига КОНКРЕТНОГО менеджера (у логгера это
        ``config.channels[name]``, у статистики — секция dict-конфига), и это
        единственная часть, которую наследник обязан реализовать сам —
        :meth:`_recreate_channel`.

        Returns:
            True при успехе; False если канал неизвестен (enable) или
            отсутствовал в реестре (disable).
        """
        if enabled:
            changed = self._recreate_channel(str(name))
            if changed:
                self._on_channels_changed()
            return changed

        channel = self._channel_registry.get(name)
        if channel is None:
            return False
        self._on_channel_removed(channel)
        try:
            channel.close()
        except Exception as exc:  # noqa: BLE001 — закрытие best-effort, не должно валить disable
            self._log_debug(f"[{self.manager_name}] close error on '{name}': {exc}")
        changed = self._channel_registry.unregister(name)
        if changed:
            self._forget_buffered_channel(str(name))
            self._on_channels_changed()
        return changed

    def _forget_buffered_channel(self, name: str) -> None:
        """Снять рабочее состояние ушедшего канала с буфера (резидуал F6).

        Буфер держит очередь и отметку времени НА КАЖДОЕ имя, которое хоть раз
        видел. Состав каналов у долгоживущего процесса меняется в рантайме
        (``sink.disable``, per-module каналы), и без этого вызова словари росли
        монотонно — замер: 500 имён → 500 пустых очередей.

        **Оговорка про наследников (находка графа, ревью Ф1).** Метод живёт в
        базе и зовётся у всех трёх плоскостей плюс ``RouterManager``, но
        ``forget_channel`` есть ТОЛЬКО у ``BatchBuffer``. У
        ``AsyncSenderBuffer`` (роутер) и ``AggregationWindow`` (статистика) его
        нет, и ``getattr`` тихо возвращает ``None`` — то есть резидуал F6
        фактически закрыт в одной плоскости из трёх, а не в базе «на всех».
        Практического роста там сегодня нет: имена каналов у роутера и
        статистики статичны, монотонно растущих словарей по динамическому имени
        у них не образуется. Но называть это «закрыто в базе» нельзя — это
        ровно паттерн «защита в базе мертва у наследника».

        Счётчики потерь по каналу не трогаются: их история обязана пережить
        снятие приёмника (урок ревью фазы Ф0, ``_absorbed_backpressure``).
        Неотправленное тоже не трогается — буфер откажется забыть канал с
        непустой очередью, и записи останутся видимы в ``pending``, а при
        следующем сбросе честно уедут в ``unresolved_channel_records``.
        Молча выбросить их здесь значило бы завести четвёртый, никем не
        считаемый класс потери.
        """
        buffer = getattr(self, "_buffer", None)
        forget = getattr(buffer, "forget_channel", None)
        if forget is None:
            return
        try:
            forget(name)
        except Exception as exc:  # noqa: BLE001 — уборка не имеет права уронить sink.disable
            self._log_debug(f"[{self.manager_name}] forget_channel('{name}') failed: {exc}")

    def _on_channel_removed(self, channel: IChannel) -> None:
        """Хук: КОНКРЕТНЫЙ канал покидает реестр (снят или пересобран).

        Отличается от :meth:`_on_channels_changed` тем, что отдаёт сам уходящий
        объект: наследнику может быть нужно забрать с него состояние, которое
        иначе уйдёт вместе с ним. Реальный случай — счётчики потерь консоли
        (R2): они живут на канале, а спрашивают их у менеджера, и снятие канала
        обнуляло историю ровно в тот момент, когда её смотрят (во время
        инцидента оператор как раз и жмёт ``sink.disable``).

        База ничего не делает: не всякому каналу есть что отдавать.
        """

    def _on_channels_changed(self) -> None:
        """Хук: состав каналов изменился в рантайме (Ф0.8).

        Зовётся ТОЛЬКО когда состав действительно поменялся — неудачный toggle
        (неизвестное имя) хук не дёргает: «ничего не произошло» не должно
        выглядеть как событие.

        Наследник, кэширующий что-либо, зависящее от состава каналов, обязан
        сбросить кэш здесь. Хук, а не переопределение публичного
        ``set_sink_enabled``: точка расширения одна, а плоскостей три, и
        каждая кэширует своё.
        """
        return None

    def _recreate_channel(self, name: str) -> bool:
        """Пересоздать и зарегистрировать канал по имени из собственного конфига.

        Хук для :meth:`set_sink_enabled` (``enabled=True``). База не знает
        формата конфига наследника, поэтому реализация — на наследнике.
        Базовый ответ «не умею» честнее, чем молчаливый ``True``: оператор
        увидит ``success=False``, а не «включил» при выключенном приёмнике.
        """
        return False

    def _fallback_log(self, level: str, message: str, module: str = "system") -> None:
        """Последний рубеж: написать через stdlib, когда штатный маршрут недоступен.

        Нужен всем троим и по одной причине: менеджер наблюдаемости не может
        сообщить о собственной поломке тем самым маршрутом, который сломан.
        До Ф0.6 был только у ``LoggerCore`` — сбой ``StatsManager`` при мёртвом
        логгере не оставлял следа вообще.

        Падать здесь запрещено: это уже аварийный путь.
        """
        try:
            _fallback_logger.warning("[%s] [%s] [%s] %s", level, self.manager_name, module, message)
        except Exception:  # nosec B110 — последний рубеж; исключение отсюда некуда деть
            pass

    # =========================================================================
    # TAP-ПРИЁМНИКИ (Ф0.6 — подъём из LoggerCore; Ф1 Task 1.5 по происхождению)
    # =========================================================================

    def add_tap(self, channel: Any, *, min_level: Any = "ERROR", name: Optional[str] = None) -> str:
        """Подключить tap: получать КАЖДУЮ эмитируемую запись с уровнем ≥ ``min_level``.

        В отличие от каналов реестра, tap не участвует в маршрутизации и не
        лежит в ``_channel_registry`` — значит переживает ``reconfigure()``
        (подписка на tail не рвётся при hot-reload). Идемпотентно по ``name``.

        Args:
            channel: приёмник (``write(dict)``), напр. RouterPushChannel.
            min_level: порог (``LogLevel`` или строка "ERROR"); ниже — не доставляем.
                       У плоскостей без уровней (статистика) порог не мешает:
                       записи без уровня получают ранг 0 и проходят при "DEBUG".
            name: имя tap'а (хэндл для remove); по умолчанию ``channel.name``.

        Returns:
            Имя tap'а.
        """
        tap_name = name or getattr(channel, "name", None) or f"tap_{len(self._tap_sinks)}"
        self._tap_sinks[tap_name] = (channel, level_rank(min_level))
        return tap_name

    def remove_tap(self, name: str) -> bool:
        """Отключить tap по имени. Возвращает True, если он был."""
        entry = self._tap_sinks.pop(name, None)
        if entry is None:
            return False
        try:
            entry[0].close()
        except Exception as exc:  # noqa: BLE001 — закрытие tap'а best-effort
            self._log_debug(f"[{self.manager_name}] tap close error on '{name}': {exc}")
        return True

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

    def _count_records_without_channels(self, level: Any = None) -> None:
        """Учесть запись, у которой не оказалось НИ ОДНОГО приёмника (Ф4.2).

        Отдельно от трёх классов «имя канала есть, но…»: здесь имени нет вовсе,
        и лечится это не тем же самым (пустой реестр или скоуп без списка
        каналов, а не опечатка и не сломанный сток).

        Предупреждение одноразовое — по уровню записи, а не по каналу: канала
        нет, привязать не к чему. Без ограничения оно само стало бы штормом
        ровно в тот момент, когда приёмников не осталось.
        """
        with self._miss_lock:
            self.stats["records_without_channels"] += 1
            first_time = not self._warned_without_channels
            self._warned_without_channels = True

        if first_time:
            self._fallback_log(
                "WARNING",
                f"запись уровня {getattr(level, 'value', level)} потеряна: у неё нет ни одного приёмника "
                f"(скоуп без списка каналов при пустом реестре; дальше считаем молча, "
                f"счётчик в get_stats['records_without_channels'])",
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

    def _write_record_to_channels(self, record: Any, channel_names: List[str]) -> int:
        """Записать запись напрямую в названные каналы (мимо буфера).

        Принимает и ``LogRecord``, и уже готовый dict: severity-путь
        ``ErrorManager`` строит запись сам и обязан идти сюда же, а не иметь
        свою копию цикла (в его копии не считались ни отказ, ни отсутствие
        канала — см. ``channel_refused_records``).

        Returns:
            Число каналов, принявших запись. Ноль означает «запись никуда не легла» —
            по этому признаку ``_write_error_record`` включает floor.
        """
        record_dict = record.to_dict() if hasattr(record, "to_dict") else record
        written = 0
        for ch_name in channel_names:
            ch = self._resolve_channel(ch_name)
            if ch is None:
                # Ф0.4: прямой путь теряет запись так же молча, как батчевый.
                self._count_unresolved_channel(ch_name)
                continue
            try:
                if channel_accepted(ch.write(record_dict)):
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

    def _resolve_channel(self, name: str) -> Optional[IChannel]:
        """Имя канала → объект. Хук: наследник может держать каналы и вне реестра.

        База знает только реестр. ``LoggerCore`` дополнительно смотрит в
        ``_module_channels`` — они живут отдельным словарём, и без хука подъём
        писателя в базу молча потерял бы записи module-каналов.
        """
        return self._channel_registry.get(name)

    def _emit_to_taps(self, record_dict: Dict[str, Any], level: Any = None) -> None:
        """Разослать запись всем tap'ам, чей порог ≤ уровня записи.

        Ошибка доставки в один tap не мешает остальным и не роняет эмитента:
        tail — наблюдение за работой, а не сама работа.
        """
        if not self._tap_sinks:
            return
        rank = level_rank(level)
        for channel, min_rank in list(self._tap_sinks.values()):
            if rank >= min_rank:
                try:
                    channel.write(record_dict)
                except Exception:  # nosec B110 — tail не должен влиять на наблюдаемое
                    pass

    # =========================================================================
    # ВНУТРЕННИЕ МЕТОДЫ (для использования наследниками)
    # =========================================================================

    def _make_handler(
        self,
        channel_name: str,
        channel: IChannel,
    ) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        """Создать обработчик для канала (с учётом буфера).

        Если buffer_strategy != None → enqueue в буфер.
        Иначе → прямой вызов channel.write().
        """
        if self._buffer is not None:
            buf = self._buffer
            ch_name = channel_name

            def _buffered(data: Dict[str, Any], *, _buf=buf, _name=ch_name) -> Dict[str, Any]:
                _buf.enqueue(_name, data)
                return {"status": "queued", "channel": _name}

            return _buffered
        else:
            return channel.write

    def _register_channel_handler(self, channel: IChannel) -> None:
        """Зарегистрировать обработчик канала в Dispatcher под ключом = channel.name."""
        handler = self._make_handler(channel.name, channel)
        self._dispatcher.register_handler(
            channel.name,
            handler,
            expects_full_message=True,
        )

    def _close_all_channels(self) -> None:
        """Закрыть все каналы при shutdown."""
        for ch in self._channel_registry.clear():
            self._on_channel_removed(ch)
            try:
                ch.close()
            except Exception as e:
                self._log_error(f"[{self.manager_name}] close error on '{ch.name}': {e}")

    def _write_to_channel(self, channel_name: str, data: Dict[str, Any]) -> None:
        """Записать данные напрямую в канал (минуя буфер). Используется flush_fn в BatchBuffer."""
        ch = self._channel_registry.get(channel_name)
        if ch is not None:
            ch.write(data)
