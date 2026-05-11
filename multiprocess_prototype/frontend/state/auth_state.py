"""AuthState — реактивное состояние авторизации (primary source of truth).

AuthState — QObject с сигналами для уведомления виджетов о смене пользователя
и контекста прав. Все виджеты, которым нужен AccessContext, подписываются
на сигналы этого объекта напрямую.

Архитектурная роль:
    AuthState — primary source of truth для состояния авторизации.
    WindowManager (когда будет подключён к prototype) — optional consumer:
    слушает access_context_changed и пропагирует в зарегистрированные окна.
    Прямая интеграция через wire_auth_state_to_window_manager() — см. ниже.

Пока WindowManager не подключён в prototype — AuthState работает автономно.
После подключения WindowManager — переписывать виджеты НЕ нужно: AuthState
остаётся источником истины, WindowManager — потребителем и усилителем.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from multiprocess_framework.modules.frontend_module.managers.access_context import (
    AccessContext,
)

if TYPE_CHECKING:
    pass  # WindowManager — forward-compat, импортируется при wire-up


class AuthState(QObject):
    """Primary source of truth для состояния авторизации.

    Виджеты подписываются напрямую на сигналы этого объекта.
    WindowManager (когда будет подключён к prototype) — optional consumer:
    слушает access_context_changed и пропагирует в зарегистрированные окна.
    Прямая интеграция через wire_auth_state_to_window_manager() — см. ниже.
    """

    # Эмитируется при смене пользователя (login/logout).
    # Аргумент: dict | None (Dict at Boundary — результат login()).
    current_user_changed = Signal(object)

    # Эмитируется при смене контекста прав (login/logout/role_change).
    # Сигнатура совместима с WindowManager.set_access_context(ctx: AccessContext):
    # один аргумент AccessContext — прямой connect без адаптера.
    access_context_changed = Signal(AccessContext)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._current_user: dict | None = None
        self._access_context: AccessContext = AccessContext()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def current_user(self) -> dict | None:
        """Текущий пользователь (dict) или None если не авторизован."""
        return self._current_user

    @property
    def access_context(self) -> AccessContext:
        """Текущий контекст прав."""
        return self._access_context

    @property
    def is_authenticated(self) -> bool:
        """True если пользователь авторизован."""
        return self._current_user is not None

    # ------------------------------------------------------------------
    # Мутации
    # ------------------------------------------------------------------

    def set_user(self, user_dict: dict, access_context: AccessContext) -> None:
        """Установить нового пользователя. Эмитирует оба сигнала.

        Args:
            user_dict: результат AuthManager.login() (Dict at Boundary).
            access_context: построенный AccessContext (не dict).
        """
        self._current_user = user_dict
        self._access_context = access_context
        self.current_user_changed.emit(user_dict)
        self.access_context_changed.emit(access_context)

    def clear(self) -> None:
        """Сбросить состояние (logout). Устанавливает дефолтный AccessContext."""
        self._current_user = None
        self._access_context = AccessContext()
        self.current_user_changed.emit(None)
        self.access_context_changed.emit(self._access_context)


def wire_auth_state_to_window_manager(
    auth_state: AuthState,
    window_manager: object,
) -> None:
    """Опциональная интеграция AuthState с WindowManager.

    В PR2 НЕ ВЫЗЫВАЕТСЯ — WindowManager в prototype отсутствует.
    При подключении WindowManager к prototype — добавить вызов в run_gui():
        wire_auth_state_to_window_manager(auth_state, window_manager)
    Переписывать виджеты при этом не нужно: AuthState остаётся primary source,
    WindowManager — consumer/propagator для окон, зарегистрированных в нём.
    """
    auth_state.access_context_changed.connect(window_manager.set_access_context)  # type: ignore[attr-defined]
