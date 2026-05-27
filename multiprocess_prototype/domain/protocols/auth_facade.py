# -*- coding: utf-8 -*-
"""
domain/protocols/auth_facade.py — Protocol для read-only доступа к auth-состоянию.

AuthFacade — минимальный read-only контракт для permission-gating в presenter'ах.
Эквивалент текущего ctx.auth.state.access_context.level, упакованный в Protocol.

Phase C создаст адаптер AuthFacadeAdapter поверх существующих IAuthManager + AuthState.

NB: Auth-сигналы (смена пользователя, смена уровня доступа) идут через EventBus
через отдельные доменные события (AuthLevelChanged, UserLoggedIn/UserLoggedOut —
Phase D). Не через Qt-signals в domain.
"""

from __future__ import annotations

from typing import Protocol


class AuthFacade(Protocol):
    """Контракт для read-only доступа к auth-состоянию.

    Реализации: AuthFacadeAdapter (Phase C), _FakeAuthFacade (тесты).
    """

    @property
    def access_level(self) -> int:
        """Текущий уровень доступа (0 = гость, выше = больше прав)."""
        ...

    def is_authenticated(self) -> bool:
        """Возвращает True если пользователь аутентифицирован."""
        ...

    def has_permission(self, key: str) -> bool:
        """Проверить наличие конкретного разрешения по ключу."""
        ...


__all__ = [
    "AuthFacade",
]
