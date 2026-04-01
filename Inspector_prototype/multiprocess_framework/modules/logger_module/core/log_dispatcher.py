# -*- coding: utf-8 -*-
"""
LogDispatcher — маршрутизация записей лога по каналам.

Два режима маршрутизации (аналог channel_dispatcher в RouterManager):

  1. channel-based  — route_log(record, channel_names)
     Явный список каналов → пишет напрямую через self.channel_handlers.
     Используется LoggerManager при scope-driven конфигурации.

  2. level-based    — route_by_level(record)
     Dispatcher маршрутизирует по record['level'] как ключу.
     Позволяет: ERROR → errors.log, WARNING → system.log, "*" → console.
     Регистрация через register_level_route(level, channel_name, handler).

Почему channel-based вызывает handler напрямую, а level-based — через Dispatcher?
  В channel-based список каналов уже известен (LoggerScopeSchema); Dispatcher здесь
  лишний посредник. В level-based ключ определяется динамически → Dispatcher
  нужен для flexibel routing (EXACT + PATTERN + FALLBACK).
"""
import time
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass

from ...dispatch_module import Dispatcher, DispatchStrategy
from .log_config import LogLevel, LogScope


@dataclass
class LogRecord:
    """Запись лога — внутренний формат LoggerManager.

    Используется внутри процесса. При передаче через RouterManager
    конвертируется в Message(type=LOG) через to_dict().
    """
    timestamp: float
    level: LogLevel
    scope: LogScope
    message: str
    module: str
    extra: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация для передачи через каналы / BatchManager."""
        return {
            'timestamp': self.timestamp,
            'level': self.level.value,       # str: "ERROR", "INFO", ...
            'scope': self.scope.value,        # str: "system", "business", ...
            'message': self.message,
            'module': self.module,
            'extra': self.extra,
        }


class LogDispatcher:
    """Маршрутизатор логов — hub between LoggerManager и log channels.

    Аналог RouterManager.channel_dispatcher, но для записей лога.

    Жизненный цикл:
        dispatcher = LogDispatcher("my_app")
        dispatcher.initialize()

        # Режим 1 — channel-based (явный список каналов):
        dispatcher.register_channel_handler("console", console_ch.write)
        dispatcher.route_log(record, ["console"])

        # Режим 2 — level-based (Dispatcher по ключу level):
        dispatcher.register_level_route("ERROR",    "errors_file", errors_ch.write)
        dispatcher.register_level_route("WARNING",  "system_file", system_ch.write)
        dispatcher.register_level_route(r".*",      "console",     console_ch.write,
                                        strategy=DispatchStrategy.PATTERN_MATCH)
        dispatcher.route_by_level(record)

        dispatcher.shutdown()
    """

    def __init__(self, app_name: str, process: Optional[Any] = None) -> None:
        """
        Args:
            app_name: Имя приложения — используется как префикс dispatcher'а.
            process:  Ссылка на родительский менеджер (для ObservableMixin).
        """
        self.app_name = app_name
        self.dispatcher = Dispatcher(
            manager_name=f"{app_name}_log_dispatcher",
            process=process,
            default_strategy=DispatchStrategy.EXACT_MATCH,
        )
        # channel_name → write-callable (прямой доступ без Dispatcher-overhead)
        self.channel_handlers: Dict[str, Callable] = {}
        # level → [channel_name, ...] (метаданные для level-based routing)
        self._level_routes: Dict[str, List[str]] = {}

    # ------------------------------------------------------------------ #
    # Жизненный цикл
    # ------------------------------------------------------------------ #

    def initialize(self) -> bool:
        """Инициализировать внутренний Dispatcher."""
        return self.dispatcher.initialize()

    def shutdown(self) -> bool:
        """Завершить работу Dispatcher."""
        return self.dispatcher.shutdown()

    # ------------------------------------------------------------------ #
    # Регистрация — channel-based
    # ------------------------------------------------------------------ #

    def register_channel_handler(self, channel_name: str, handler: Callable) -> None:
        """Зарегистрировать write-обработчик канала.

        Используется LoggerManager для channel-based режима (route_log).

        Args:
            channel_name: Уникальное имя канала ("console", "errors_file", ...).
            handler:      fn(record_dict: dict) → dict с {"status": "success"|"error"}.
        """
        self.channel_handlers[channel_name] = handler

    # ------------------------------------------------------------------ #
    # Регистрация — level-based
    # ------------------------------------------------------------------ #

    def register_level_route(
        self,
        level: str,
        channel_name: str,
        handler: Callable,
        strategy: DispatchStrategy = DispatchStrategy.EXACT_MATCH,
    ) -> None:
        """Привязать уровень лога к каналу через Dispatcher.

        Аналог RouterManager.register_route(key, channel_name):
          "ERROR"   → errors_file_channel.write
          "WARNING" → system_file_channel.write
          r".*"     → console_channel.write   (PATTERN_MATCH — catch-all)

        Args:
            level:        Ключ уровня: "DEBUG", "INFO", "WARNING", "ERROR",
                          "CRITICAL", или regex-паттерн при PATTERN_MATCH.
            channel_name: Имя канала (для метаданных и get_level_routes()).
            handler:      fn(record_dict: dict) → dict.
            strategy:     EXACT_MATCH (по умолчанию) или PATTERN_MATCH
                          (для catch-all паттернов типа r".*").
        """
        self.channel_handlers[channel_name] = handler

        key = level.upper() if strategy == DispatchStrategy.EXACT_MATCH else level
        self.dispatcher.register_handler(
            key=key,
            handler=handler,
            metadata={'channel': channel_name, 'level': level},
            strategy=strategy,
        )

        if key not in self._level_routes:
            self._level_routes[key] = []
        if channel_name not in self._level_routes[key]:
            self._level_routes[key].append(channel_name)

    # ------------------------------------------------------------------ #
    # Маршрутизация — channel-based
    # ------------------------------------------------------------------ #

    def route_log(self, record: LogRecord, channel_names: List[str]) -> Dict[str, Any]:
        """Записать лог в явно указанные каналы.

        Вызывает write-handler напрямую (без Dispatcher-overhead),
        т.к. целевые каналы уже определены вызывающим кодом.

        Args:
            record:        Запись лога.
            channel_names: Список каналов для записи.

        Returns:
            {"channel_name": {"status": "success"|"error", ...}, ...}
        """
        results: Dict[str, Any] = {}
        record_dict = record.to_dict()

        for channel_name in channel_names:
            handler = self.channel_handlers.get(channel_name)
            if handler is None:
                results[channel_name] = {
                    'status': 'error',
                    'error': f"channel '{channel_name}' not registered",
                }
                continue
            try:
                result = handler(record_dict)
                results[channel_name] = result or {'status': 'success', 'channel': channel_name}
            except Exception as exc:
                results[channel_name] = {'status': 'error', 'error': str(exc)}

        return results

    # ------------------------------------------------------------------ #
    # Маршрутизация — level-based
    # ------------------------------------------------------------------ #

    def route_by_level(self, record: LogRecord) -> Dict[str, Any]:
        """Маршрутизировать запись по уровню через Dispatcher.

        Использует dispatch_module корректно:
            dispatch(record_dict, key_field='level')
        → Dispatcher ищет зарегистрированный handler по record_dict['level'].

        Аналог RouterManager.send() → channel_dispatcher.dispatch(msg, key_field='command').

        Args:
            record: Запись лога.

        Returns:
            Результат Dispatcher.dispatch() или {"status": "no_route"}.
        """
        record_dict = record.to_dict()
        result = self.dispatcher.dispatch(record_dict, key_field='level')
        return result if result else {'status': 'no_route', 'level': record_dict.get('level')}

    # ------------------------------------------------------------------ #
    # Интроспекция
    # ------------------------------------------------------------------ #

    def get_level_routes(self) -> Dict[str, List[str]]:
        """Вернуть маппинг level → [channel_name, ...] (level-based routing)."""
        return dict(self._level_routes)

    def get_channel_names(self) -> List[str]:
        """Вернуть список зарегистрированных каналов."""
        return list(self.channel_handlers.keys())

