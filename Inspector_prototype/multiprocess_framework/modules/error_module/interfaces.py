# -*- coding: utf-8 -*-
"""
Публичные контракты error_module.

IErrorManager — контракт менеджера ошибок.

Правило: внешние модули импортируют только из interfaces.py, не из core/.

error_module — специализация logger_module для обработки исключений:
  - По умолчанию default_level=ERROR, файл logs/errors.log
  - Дополнительный метод log_exception() с форматированием traceback
  - Принимает config как dict, ErrorManagerConfig, LoggerManagerConfig или объект с build()

Пример использования:
    from error_module.interfaces import IErrorManager

    class MyHandler:
        def __init__(self, errors: IErrorManager):
            self._errors = errors

        def process(self, data):
            try:
                ...
            except Exception as exc:
                self._errors.log_exception(exc, "processing failed", module="my_handler")
"""
from typing import Any, Dict, Optional, Union, Protocol, runtime_checkable


@runtime_checkable
class IErrorManager(Protocol):
    """Контракт менеджера ошибок.

    Специализация ILoggerManager с фокусом на обработку исключений.
    Реализуется классом ErrorManager (наследником LoggerManager).

    Паттерн использования через ObservableMixin:
        ObservableMixin.__init__(self, managers={'errors': error_manager})
        self._track_error(exc, context={"method": "process"})

    Прямое использование:
        error_manager.log_exception(exc, "context message", module="my_module")
        error_manager.error("manual error message", module="my_module")
    """

    # =========================================================================
    # Жизненный цикл
    # =========================================================================

    def initialize(self) -> bool:
        """Инициализация менеджера. Возвращает True при успехе."""
        ...

    def shutdown(self) -> bool:
        """Корректное завершение работы. Сбрасывает буфер перед остановкой."""
        ...

    # =========================================================================
    # Основные методы логирования
    # =========================================================================

    def error(self, message: str, module: str = "errors", **extra: Any) -> None:
        """Записать сообщение уровня ERROR.

        Args:
            message: Текст ошибки.
            module:  Модуль-источник ошибки.
            **extra: Дополнительный контекст (trace_id, user_id, ...).
        """
        ...

    def warning(self, message: str, module: str = "errors", **extra: Any) -> None:
        """Записать предупреждение уровня WARNING.

        Используется для некритичных ошибок, которые нужно отслеживать.
        """
        ...

    def critical(self, message: str, module: str = "errors", **extra: Any) -> None:
        """Записать критическую ошибку. Немедленный flush батчинга."""
        ...

    def info(self, message: str, module: str = "errors", **extra: Any) -> None:
        """Информационное сообщение (recovery, retry success, ...).

        Полезно для логирования восстановления после ошибки.
        """
        ...

    # =========================================================================
    # Специфичный метод для исключений
    # =========================================================================

    def log_exception(
        self,
        exc: BaseException,
        message: str = "",
        module: str = "errors",
        include_stacktrace: Optional[bool] = None,
    ) -> None:
        """Логировать исключение с опциональным traceback.

        Args:
            exc:               Объект исключения.
            message:           Дополнительное контекстное сообщение.
            module:            Модуль-источник исключения.
            include_stacktrace: True/False переопределяет глобальный флаг.
                               None → использует значение из конфига.

        Example:
            try:
                result = risky_operation()
            except ValueError as e:
                error_manager.log_exception(
                    e, "invalid input data", module="validator"
                )
        """
        ...

    # =========================================================================
    # Диагностика
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Статистика работы менеджера ошибок.

        Returns:
            Словарь с полями: app_name, messages_processed, messages_skipped,
            channels_count, batching_enabled, include_stacktrace.
        """
        ...


# ---------------------------------------------------------------------------
# Type aliases для аннотаций конфигурации
# ---------------------------------------------------------------------------

ErrorConfigLike = Union[Dict[str, Any], Any]
"""Допустимые форматы конфига ErrorManager (Dict at Boundary):

  - ``None`` → встроенный дефолт (см. ``_DEFAULT_CONFIG`` в core/error_manager)
  - ``dict`` → ``expand_error_manager_config`` → ``LoggerManagerConfig.model_validate``
  - ``ErrorManagerConfig`` → ``model_dump()`` + expand (см. ADR-107)
  - ``LoggerManagerConfig`` → используется как есть
  - объект с ``build() -> (str, dict)`` → dict из build + expand (совместимость)
"""
