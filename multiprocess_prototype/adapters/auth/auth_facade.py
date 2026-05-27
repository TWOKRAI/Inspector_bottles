# -*- coding: utf-8 -*-
"""
adapters/auth/auth_facade.py — тонкий read-only wrapper над AuthState.

AuthFacadeFromAuthState реализует Protocol AuthFacade из
multiprocess_prototype.domain.protocols.auth_facade.

Источник данных:
    - access_level    → auth_state.access_context.level
    - is_authenticated → auth_state.is_authenticated
    - has_permission   → auth_state.access_context.has_permission(key)

Примечания по дизайну:
    - AuthManager (IAuthManager) не используется для проверки прав в этом
      adapter'е: IAuthManager — менеджер мутаций (login/logout/create_user),
      а не read-only источник. Реальная проверка прав хранится в AccessContext,
      который живёт в AuthState.access_context.

    - Adapter read-only: мутации (login/logout) находятся вне scope (Phase D/E).

    - AuthState — QObject (PySide6). Adapter принимает duck-typed объект
      (достаточно наличия .access_context.level, .is_authenticated,
      .access_context.has_permission). Это позволяет использовать plain fakes
      в unit-тестах без Qt-окружения.

Phase D подключит этот adapter к AppServices:
    services.auth = AuthFacadeFromAuthState(auth_state=ctx.auth.state)
"""

from __future__ import annotations

from typing import Any


class AuthFacadeFromAuthState:
    """Adapter поверх AuthState для read-only auth-доступа.

    Реализует Protocol AuthFacade из domain/protocols/auth_facade.py.
    Делегирует все запросы к AccessContext, хранящемуся в AuthState.

    Args:
        auth_state: объект с атрибутами is_authenticated (bool-property)
                    и access_context (AccessContext-like). В prod — AuthState.
    """

    def __init__(self, auth_state: Any) -> None:
        self._state = auth_state

    @property
    def access_level(self) -> int:
        """Текущий числовой уровень доступа (0 = гость).

        Делегирует к auth_state.access_context.level.
        """
        return self._state.access_context.level  # type: ignore[no-any-return]

    def is_authenticated(self) -> bool:
        """True если пользователь аутентифицирован.

        Делегирует к auth_state.is_authenticated.
        """
        return bool(self._state.is_authenticated)

    def has_permission(self, key: str) -> bool:
        """Проверить наличие именованного права по ключу.

        Делегирует к auth_state.access_context.has_permission(key).
        Wildcard '*' в permissions — означает все права (dev-роль).

        Args:
            key: строковый ключ права, например 'tabs.pipeline.edit'.
        """
        return bool(self._state.access_context.has_permission(key))
