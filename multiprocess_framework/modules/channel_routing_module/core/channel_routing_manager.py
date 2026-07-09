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

from typing import Any, Callable, Dict, List, Optional, Union

from ...base_manager import BaseManager, ObservableMixin
from ...dispatch_module import Dispatcher, DispatchStrategy
from ..interfaces import IChannel, IBufferStrategy, IChannelRoutingManager
from .channel_registry import ChannelRegistry
from .config_normalizer import normalize_config


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

        self._routed: int = 0
        self._errors: int = 0

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
        """Пересобрать каналы/маршруты из нового конфига (full-rebuild).

        Оркестрация (reuse существующих примитивов):
            flush()  → сбросить накопленный буфер старого набора каналов;
            _close_all_channels() → закрыть и очистить реестр каналов;
            normalize_config()    → привести dict/RegisterBase к dict (Dict at Boundary);
            _rebuild_from_config() → хук наследника, строящий новые каналы/маршруты.

        Базовая реализация делает no-op rebuild (наследники переопределяют
        ``_rebuild_from_config``). Метод идемпотентен и безопасен до initialize():
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

        normalized = normalize_config(config)
        if not isinstance(normalized, dict):
            self._log_warning(f"[{self.manager_name}] reconfigure: невалидный config ({type(config)!r}) — пропущено")
            return False

        try:
            self.flush()
            self._close_all_channels()
            self._config = normalized
            self._rebuild_from_config(normalized)
            self._log_info(f"[{self.manager_name}] reconfigured: {len(self._channel_registry)} каналов")
            return True
        except Exception as e:
            self._log_error(f"[{self.manager_name}] reconfigure failed: {e}")
            return False

    def _rebuild_from_config(self, config: Dict[str, Any]) -> None:
        """Хук пересборки каналов/маршрутов из dict (no-op по умолчанию).

        Наследники переопределяют, чтобы воссоздать свой набор каналов из
        нового конфига после того как ``reconfigure`` закрыл старые. База ничего
        не строит — конкретные менеджеры (Logger/Stats/Error) знают свой формат.
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
        return stats

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
            try:
                ch.close()
            except Exception as e:
                self._log_error(f"[{self.manager_name}] close error on '{ch.name}': {e}")

    def _write_to_channel(self, channel_name: str, data: Dict[str, Any]) -> None:
        """Записать данные напрямую в канал (минуя буфер). Используется flush_fn в BatchBuffer."""
        ch = self._channel_registry.get(channel_name)
        if ch is not None:
            ch.write(data)
