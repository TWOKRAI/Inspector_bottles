# -*- coding: utf-8 -*-
"""
adapters/auth — adapter для read-only auth-доступа.

Экспортирует AuthFacadeFromAuthState — тонкий wrapper над AuthState,
реализующий Protocol AuthFacade из domain/protocols/auth_facade.py.

Adapter read-only: мутации (login/logout) остаются за AuthManager / GUI.
Подключается в Phase D через AppServices DI-контейнер.
"""

from __future__ import annotations

from .auth_facade import AuthFacadeFromAuthState

__all__ = [
    "AuthFacadeFromAuthState",
]
