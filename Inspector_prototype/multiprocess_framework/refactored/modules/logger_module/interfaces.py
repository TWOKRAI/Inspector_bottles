# -*- coding: utf-8 -*-
"""
Публичные контракты logger_module.

ILoggerManager — контракт менеджера системы логирования.
ILogChannel    — контракт любого канала записи логов.

Правило: внешние модули импортируют только из interfaces.py, не из core/.

Взаимодействие с другими модулями:
  - ObservableMixin: менеджеры регистрируют LoggerManager через
    `managers={'logger': logger_manager}`, после чего `self._log_info(...)` и
    `self._log_error(...)` автоматически маршрутизируются сюда.
  - RouterManager: LOG-сообщения от дочерних процессов приходят через
    router.channel='log' → logger.receive_message(msg_dict).
  - message_module: все межпроцессные LOG-сообщения — Message(type='log').
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ..base_manager.interfaces import IBaseManager
from ..channel_routing_module.interfaces import IChannel
from .core.log_config import LogLevel, LogScope


class ILogChannel(IChannel):
    """Контракт канала записи логов (наследует IChannel).

    Наследует IChannel — все лог-каналы автоматически являются IChannel
    и могут использоваться в ChannelRegistry и ChannelRoutingManager.

    IChannel уже определяет: name (property), write(), close(), get_info(),
    channel_type (property, default="generic").

    ILogChannel добавляет close() как обязательный метод.

    Реализуется для: файла (FileChannel), консоли (ConsoleChannel),
    HTTP (HttpChannel), и любых кастомных каналов.
    Каналы stateless относительно фильтрации — этим занимается LoggerManager.
    """

    @abstractmethod
    def close(self) -> None:
        """Закрыть канал, освободить ресурсы (файловые дескрипторы, соединения)."""

    def get_info(self) -> Dict[str, Any]:
        """Информация о состоянии канала для мониторинга."""
        return {"name": self.name, "active": True}


class ILoggerManager(IBaseManager, ABC):
    """Контракт менеджера системы логирования.

    LoggerManager является центральным хабом логирования:
    - Собирает логи от всех менеджеров через ObservableMixin (_log_info / _log_error)
    - Принимает LOG-сообщения от дочерних процессов через RouterManager
    - Записывает в множество каналов: файлы, консоль, HTTP

    Паттерн использования (ObservableMixin):
        # При инициализации любого менеджера:
        ObservableMixin.__init__(self, managers={'logger': logger_manager})

        # В теле методов — автоматически маршрутизируется в LoggerManager:
        self._log_info("starting")
        self._log_error("something failed")
        self._log_warning("slow query")

    Прямое использование (для критичных событий):
        logger.error("unhandled exception", module="router_module")
        logger.system(LogLevel.WARNING, "cpu spike", module="monitor")
    """

    # =========================================================================
    # Основной API логирования
    # =========================================================================

    @abstractmethod
    def log(
        self,
        scope: LogScope,
        level: LogLevel,
        message: str,
        module: str = "main",
        **extra: Any,
    ) -> None:
        """Базовый метод логирования с явным указанием scope и level.

        Args:
            scope:   Область логирования (SYSTEM, BUSINESS, DEBUG, ...).
            level:   Уровень важности (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            message: Текст сообщения.
            module:  Имя модуля/компонента-источника.
            **extra: Произвольные поля для контекста (trace_id, user_id, ...).
        """

    # ---- Быстрые методы по уровню (scope определяется автоматически) ----

    @abstractmethod
    def debug(self, message: str, module: str = "main", **extra: Any) -> None:
        """Отладочная информация. scope=DEBUG, level=DEBUG."""

    @abstractmethod
    def info(self, message: str, module: str = "main", **extra: Any) -> None:
        """Информационное сообщение. scope=BUSINESS, level=INFO."""

    @abstractmethod
    def warning(self, message: str, module: str = "main", **extra: Any) -> None:
        """Предупреждение. scope=SYSTEM, level=WARNING."""

    @abstractmethod
    def error(self, message: str, module: str = "main", **extra: Any) -> None:
        """Ошибка. scope=SYSTEM, level=ERROR."""

    @abstractmethod
    def critical(self, message: str, module: str = "main", **extra: Any) -> None:
        """Критическая ошибка. scope=SYSTEM, level=CRITICAL."""

    # ---- Методы по области (scope явный, level как параметр) ----

    @abstractmethod
    def system(self, level: LogLevel, message: str, module: str = "main", **extra: Any) -> None:
        """Системные события (запуск, остановка, конфигурация). scope=SYSTEM."""

    @abstractmethod
    def business(self, level: LogLevel, message: str, module: str = "main", **extra: Any) -> None:
        """Бизнес-логика (обработка данных, результаты). scope=BUSINESS."""

    @abstractmethod
    def performance(self, level: LogLevel, message: str, module: str = "main", **extra: Any) -> None:
        """Производительность (время выполнения, throughput). scope=PERFORMANCE."""

    @abstractmethod
    def audit(self, level: LogLevel, message: str, module: str = "main", **extra: Any) -> None:
        """Аудит (действия пользователей, изменения). scope=AUDIT."""

    @abstractmethod
    def security(self, level: LogLevel, message: str, module: str = "main", **extra: Any) -> None:
        """Безопасность (аутентификация, авторизация). scope=SECURITY."""

    # =========================================================================
    # Управление каналами
    # =========================================================================

    @abstractmethod
    def enable_module_logging(self, module_name: str, file_path: Optional[str] = None) -> None:
        """Включить отдельный файл логирования для модуля.

        Args:
            module_name: Имя модуля (будет ключом канала).
            file_path:   Путь к файлу. По умолчанию logs/{module_name}.log.
        """

    @abstractmethod
    def disable_module_logging(self, module_name: str) -> None:
        """Выключить отдельный файл логирования для модуля."""

    # =========================================================================
    # Контекстное логирование
    # =========================================================================

    @abstractmethod
    def push_context(self, **context_vars: Any) -> None:
        """Добавить поля в контекст текущего потока.

        Все последующие вызовы log() будут автоматически дополнены этими полями.

        Example:
            logger.push_context(request_id="abc-123", user="admin")
            logger.info("processing request")   # → extra = {request_id, user}
        """

    @abstractmethod
    def pop_context(self) -> None:
        """Удалить последний слой контекста."""

    # =========================================================================
    # Управление буфером
    # =========================================================================

    @abstractmethod
    def flush(self) -> None:
        """Принудительно сбросить все буферизованные записи (batching)."""

    # =========================================================================
    # Диагностика
    # =========================================================================

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Агрегированная статистика логирования.

        Returns:
            Словарь с полями: app_name, messages_processed, messages_skipped,
            messages_routed, channels_count, module_channels_count,
            batching_enabled и (если батчинг включён) messages_batched, batch_stats.
        """

    @abstractmethod
    def should_log(self, scope: LogScope, level: LogLevel, module: str) -> bool:
        """Проверить, нужно ли логировать это сообщение (кэшированная проверка).

        Используется внутренне, но полезен для внешних валидаций производительности.
        """
