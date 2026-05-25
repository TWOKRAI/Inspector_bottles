"""SqlService — минимальный shell-класс для ServiceRegistry.

Реализует интерфейс IService (Phase 3): start / stop / get_status.
Детальная реализация с реальным подключением к БД — Phase 4+.
"""

from __future__ import annotations

from multiprocess_framework.modules.service_module import IService, register_service


@register_service(name="sql")
class SqlService:
    """Shell-сервис для работы с базой данных.

    Хранит статус соединения; реальный бэкенд подключается в Phase 4+.

    Атрибуты:
        name   — идентификатор сервиса для ServiceRegistry.
        status — текущее состояние ("stopped" | "running").
    """

    name: str = "sql"

    def __init__(self) -> None:
        """Инициализация."""
        self.status: str = "stopped"

    # ------------------------------------------------------------------
    # Публичный API (IService-совместимый)
    # ------------------------------------------------------------------

    def start(self, config: dict) -> bool:
        """Запустить сервис с заданной конфигурацией.

        Args:
            config: параметры подключения (host, port, db и т.п.).

        Returns:
            True при успехе (shell всегда возвращает True).
        """
        # TODO Phase 4+: реальное подключение к БД
        self.status = "running"
        return True

    def stop(self) -> bool:
        """Остановить сервис.

        Returns:
            True при успехе (shell всегда возвращает True).
        """
        # TODO Phase 4+: закрыть соединение с БД
        self.status = "stopped"
        return True

    def get_status(self) -> dict:
        """Вернуть текущее состояние сервиса.

        Returns:
            Словарь с ключами state и service.
        """
        return {"state": self.status, "service": self.name}

    def __repr__(self) -> str:
        return f"SqlService(status={self.status!r})"


# Явная проверка структурной совместимости (runtime, не ABC)
assert isinstance(SqlService(), IService), "SqlService не удовлетворяет IService Protocol"
