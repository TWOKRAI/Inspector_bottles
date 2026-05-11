# -*- coding: utf-8 -*-
"""AuthContext — типизированная связка зависимостей auth-домена.

Выделен из app_context.py отдельным файлом, чтобы потребители auth-функционала
импортировали узкий контракт `AuthContext`, не подтягивая весь `AppContext`
с его 10+ доменами зависимостей. Это снижает fan-in на app_context.py
и делает зависимости каждой панели явными.

Использование (admin panels, login button и т.п.):

    from multiprocess_prototype.frontend.auth_context import AuthContext

    class UsersPanel(QWidget):
        def __init__(self, auth: AuthContext, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._auth = auth
            self._auth_manager = auth.manager
            self._auth_state = auth.state

Wiring (в tab_factory / app.py): `panel = UsersPanel(auth=ctx.auth)`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Services.auth.interfaces import IAuthManager
    from Services.auth.storage.audit_storage import SqliteAuditStorage
    from multiprocess_prototype.frontend.state.auth_state import AuthState


@dataclass(frozen=True)
class AuthContext:
    """Auth-домен: связка manager + state + audit-storage.

    Frozen dataclass — immutable, hashable, безопасно передавать.

    Attributes:
        manager: AuthManager (login/logout/role management).
        state: AuthState (текущий пользователь + AccessContext + сигналы).
        audit: SqliteAuditStorage (журнал входов/действий), опционален.
    """

    manager: "IAuthManager"
    state: "AuthState"
    audit: "SqliteAuditStorage | None" = None
