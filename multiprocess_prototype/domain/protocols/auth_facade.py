# -*- coding: utf-8 -*-
"""
domain/protocols/auth_facade.py — Protocol для read-only доступа к auth-состоянию.

AuthFacade — минимальный read-only контракт для permission-gating в presenter'ах
и реактивной подписки на смену прав доступа.

Реализации:
  - AuthFacadeFromAuthState (adapters/auth/auth_facade.py) — prod-адаптер над AuthState.
  - FakeAuthFacade (domain/tests/_fakes.py) — тестовая реализация без Qt.

Реактивность через domain-pure callback (не Qt-signals в domain):
  - on_access_changed(callback) — adapter мостит Qt-сигнал AuthState → callback.
  - Fakes/тесты без сигналов — no-op или сохраняют callback для ручного тригера.
"""

from __future__ import annotations

from typing import Callable, Protocol


class AuthFacade(Protocol):
    """Контракт для read-only доступа к auth-состоянию с реактивной подпиской.

    Реализации: AuthFacadeFromAuthState (adapters), FakeAuthFacade (тесты).
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

    def on_access_changed(self, callback: Callable[[], None]) -> None:
        """Подписаться на изменение прав доступа (смена роли/пользователя).

        callback вызывается без аргументов при каждом изменении access-контекста.
        Реализация (adapter) мостит Qt-сигнал AuthState.access_context_changed →
        callback; domain остаётся UI-agnostic. Fake/тесты без сигнала — no-op
        или сохраняют callback для ручного тригера.
        """
        ...


__all__ = [
    "AuthFacade",
]
