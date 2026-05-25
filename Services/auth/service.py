"""AuthService — минимальный shell-класс для ServiceRegistry.

Реализует интерфейс IService (Phase 3): start / stop / get_status.
Детальная реализация с реальной аутентификацией (JWT, LDAP и т.п.) — Phase 4+.
"""

from __future__ import annotations

from multiprocess_framework.modules.service_module import IService, register_service


@register_service(name="auth")
class AuthService:
    """Shell-сервис аутентификации и авторизации.

    Хранит статус; реальный бэкенд (JWT, LDAP, OAuth) — Phase 4+.

    Атрибуты:
        name   — идентификатор сервиса для ServiceRegistry.
        status — текущее состояние ("stopped" | "running").
    """

    name: str = "auth"

    def __init__(self) -> None:
        """Инициализация."""
        self.status: str = "stopped"

    # ------------------------------------------------------------------
    # Публичный API (IService-совместимый)
    # ------------------------------------------------------------------

    def start(self, config: dict) -> bool:
        """Запустить сервис с заданной конфигурацией.

        Args:
            config: параметры (secret_key, token_ttl, provider и т.п.).

        Returns:
            True при успехе (shell всегда возвращает True).
        """
        # TODO Phase 4+: инициализация провайдера аутентификации
        self.status = "running"
        return True

    def stop(self) -> bool:
        """Остановить сервис.

        Returns:
            True при успехе (shell всегда возвращает True).
        """
        # TODO Phase 4+: очистка сессий и токенов
        self.status = "stopped"
        return True

    def get_status(self) -> dict:
        """Вернуть текущее состояние сервиса.

        Returns:
            Словарь с ключами state и service.
        """
        return {"state": self.status, "service": self.name}

    def __repr__(self) -> str:
        return f"AuthService(status={self.status!r})"


# Явная проверка структурной совместимости (runtime, не ABC)
assert isinstance(AuthService(), IService), "AuthService не удовлетворяет IService Protocol"
