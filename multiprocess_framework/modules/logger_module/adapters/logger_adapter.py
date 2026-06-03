# -*- coding: utf-8 -*-
"""
Адаптер для LoggerManager (Refactored).

Предоставляет упрощенный интерфейс для логирования.
"""

from typing import Any, Optional, Dict, Union

from ...base_manager.adapters.base_adapter import BaseAdapter
from ..core.log_config import LogLevel, LogScope


class LoggerAdapter(BaseAdapter):
    """
    Адаптер для LoggerManager (инструмент интеграции с процессом).

    Предоставляет дополнительную функциональность для LoggerManager:
    - Конвертация уровней логирования (строка -> LogLevel)
    - Автоматическое определение scope по умолчанию
    """

    def __init__(self, logger_manager: Any, process: Optional[Any] = None):
        """
        Инициализация адаптера логгера.

        Args:
            logger_manager: Экземпляр LoggerManager
            process: Ссылка на родительский процесс
        """
        super().__init__(logger_manager, process, "LoggerAdapter")

    def setup(self) -> bool:
        """
        Настройка адаптера логгера.

        Returns:
            bool: True если настройка успешна
        """
        try:
            if not self.manager:
                self._log("error", "Manager is not set")
                return False

            self._initialized = True
            self._log("info", "LoggerAdapter initialized")
            return True

        except Exception as e:
            self._log("error", f"Setup failed - {e}")
            return False

    def log_with_auto_scope(
        self, level: Union[str, LogLevel], message: str, context: str = None, scope: Optional[LogScope] = None, **kwargs
    ) -> bool:
        """
        Удобный метод логирования с автоматическим определением scope и конвертацией уровня.

        Args:
            level: Уровень логирования (строка или LogLevel)
            message: Текст сообщения
            context: Контекст/модуль
            scope: Область логирования (опционально, определяется автоматически если не указано)
            **kwargs: Дополнительные параметры

        Returns:
            bool: True если логирование успешно
        """
        try:
            if not self.manager:
                return False

            # Конвертируем уровень в LogLevel если нужно
            log_level = self._convert_level(level)
            if log_level is None:
                return False

            # Определяем область логирования автоматически если не указана
            if scope is None:
                scope = self._get_default_scope(log_level)

            # Определяем модуль
            module = context or self._get_default_module()

            # Логируем через менеджер
            self.manager.log(scope, log_level, message, module, **kwargs)

            return True

        except Exception as e:
            self._log("error", f"Log failed - {e}")
            return False

    def _convert_level(self, level: Union[str, LogLevel]) -> Optional[LogLevel]:
        """Конвертировать строку или LogLevel в LogLevel.

        Использует встроенный enum-lookup `LogLevel[name.upper()]`.
        Дополнительного маппинга не нужно — enum имена совпадают с верхним регистром.

        Returns:
            LogLevel, или None если имя не распознано.
        """
        if isinstance(level, LogLevel):
            return level
        if isinstance(level, str):
            try:
                return LogLevel[level.upper()]
            except KeyError:
                return None
        return None

    def _get_default_scope(self, level: LogLevel) -> LogScope:
        """Определить LogScope по уровню.

        WARNING, ERROR, CRITICAL → SYSTEM (влияют на стабильность системы).
        INFO, DEBUG              → BUSINESS (бизнес-логика).
        """
        if level in {LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL}:
            return LogScope.SYSTEM
        return LogScope.BUSINESS

    def _get_default_module(self) -> str:
        """Получает модуль по умолчанию из контекста процесса."""
        if self.process and hasattr(self.process, "name"):
            return self.process.name
        return "app"

    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики адаптера.

        Returns:
            Dict[str, Any]: Статистика адаптера и менеджера
        """
        stats = super().get_stats()

        # Добавляем статистику менеджера если доступна
        if self.manager and hasattr(self.manager, "get_stats"):
            try:
                manager_stats = self.manager.get_stats()
                stats["manager_stats"] = manager_stats
            except Exception:
                pass

        return stats
