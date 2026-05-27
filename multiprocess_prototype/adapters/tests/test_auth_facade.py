# -*- coding: utf-8 -*-
"""
Тесты для AuthFacadeFromAuthState (Task C.2).

Все тесты используют plain in-memory fakes — без PySide6/Qt,
без реального AuthManager или AuthState (QObject).

FakeAccessContext имитирует AccessContext из
multiprocess_framework/modules/frontend_module/managers/access_context.py:
    - атрибут level: int
    - метод has_permission(name: str) -> bool  (wildcard '*' поддержан)

FakeAuthState имитирует AuthState:
    - property access_context -> FakeAccessContext
    - property is_authenticated -> bool
"""

from __future__ import annotations


from multiprocess_prototype.adapters.auth import AuthFacadeFromAuthState
from multiprocess_prototype.domain.protocols.auth_facade import AuthFacade


# =============================================================================
# Plain fakes (без PySide6)
# =============================================================================


class FakeAccessContext:
    """Минимальный AccessContext-like объект для тестов."""

    def __init__(self, level: int = 0, permissions: frozenset[str] = frozenset()) -> None:
        self.level = level
        self._permissions = permissions

    def has_permission(self, name: str) -> bool:
        """Wildcard '*' означает все права."""
        return "*" in self._permissions or name in self._permissions


class FakeAuthState:
    """Минимальный AuthState-like объект для тестов (без QObject)."""

    def __init__(
        self,
        level: int = 0,
        authenticated: bool = False,
        permissions: frozenset[str] = frozenset(),
    ) -> None:
        self._access_context = FakeAccessContext(level=level, permissions=permissions)
        self._authenticated = authenticated

    @property
    def access_context(self) -> FakeAccessContext:
        return self._access_context

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated


# =============================================================================
# Тесты
# =============================================================================


class TestAuthFacadeAccessLevel:
    """Проверяем делегирование access_level к state.access_context.level."""

    def test_access_level_returns_state_level_50(self) -> None:
        """Adapter.access_level возвращает значение из access_context.level."""
        state = FakeAuthState(level=50, authenticated=True)
        adapter = AuthFacadeFromAuthState(auth_state=state)

        assert adapter.access_level == 50

    def test_access_level_default_zero_for_guest(self) -> None:
        """Неаутентифицированный пользователь: уровень 0 (гость)."""
        state = FakeAuthState(level=0, authenticated=False)
        adapter = AuthFacadeFromAuthState(auth_state=state)

        assert adapter.access_level == 0

    def test_access_level_high_admin(self) -> None:
        """Высокий уровень доступа (100) передаётся без изменений."""
        state = FakeAuthState(level=100, authenticated=True)
        adapter = AuthFacadeFromAuthState(auth_state=state)

        assert adapter.access_level == 100


class TestAuthFacadeIsAuthenticated:
    """Проверяем делегирование is_authenticated к state.is_authenticated."""

    def test_is_authenticated_true_when_user_logged_in(self) -> None:
        """Авторизованный пользователь: is_authenticated() == True."""
        state = FakeAuthState(authenticated=True, level=10)
        adapter = AuthFacadeFromAuthState(auth_state=state)

        assert adapter.is_authenticated() is True

    def test_is_authenticated_false_when_not_logged_in(self) -> None:
        """Не авторизован: is_authenticated() == False."""
        state = FakeAuthState(authenticated=False)
        adapter = AuthFacadeFromAuthState(auth_state=state)

        assert adapter.is_authenticated() is False


class TestAuthFacadeHasPermission:
    """Проверяем делегирование has_permission к access_context.has_permission."""

    def test_has_permission_true_when_key_in_permissions(self) -> None:
        """Ключ присутствует в permissions: has_permission() == True."""
        state = FakeAuthState(
            permissions=frozenset(["tabs.pipeline.edit", "recipes.view"]),
            authenticated=True,
        )
        adapter = AuthFacadeFromAuthState(auth_state=state)

        assert adapter.has_permission("tabs.pipeline.edit") is True

    def test_has_permission_false_when_key_missing(self) -> None:
        """Ключ отсутствует в permissions: has_permission() == False."""
        state = FakeAuthState(
            permissions=frozenset(["recipes.view"]),
            authenticated=True,
        )
        adapter = AuthFacadeFromAuthState(auth_state=state)

        assert adapter.has_permission("tabs.pipeline.edit") is False

    def test_has_permission_wildcard_grants_all(self) -> None:
        """Wildcard '*' в permissions: любой ключ разрешён (dev-роль)."""
        state = FakeAuthState(
            permissions=frozenset(["*"]),
            authenticated=True,
        )
        adapter = AuthFacadeFromAuthState(auth_state=state)

        assert adapter.has_permission("tabs.pipeline.edit") is True
        assert adapter.has_permission("admin.users.delete") is True
        assert adapter.has_permission("any.arbitrary.key") is True

    def test_has_permission_empty_set_denies_all(self) -> None:
        """Пустой набор permissions: все права запрещены."""
        state = FakeAuthState(
            permissions=frozenset(),
            authenticated=True,
        )
        adapter = AuthFacadeFromAuthState(auth_state=state)

        assert adapter.has_permission("tabs.pipeline.edit") is False


class TestAuthFacadeSatisfiesProtocol:
    """Структурная проверка: adapter удовлетворяет AuthFacade Protocol."""

    def test_satisfies_auth_facade_protocol(self) -> None:
        """AuthFacadeFromAuthState структурно совместим с AuthFacade Protocol.

        Проверка через type-annotation assignment: если _check() принимает
        AuthFacade, а adapter передаётся без ошибки — структурный контракт выполнен.
        (runtime-проверка, не статическая — Protocol не @runtime_checkable)
        """

        def _check(f: AuthFacade) -> None:
            # Вызываем все 3 метода Protocol для runtime-валидации
            _ = f.access_level
            _ = f.is_authenticated()
            _ = f.has_permission("test.key")

        state = FakeAuthState(level=10, authenticated=True, permissions=frozenset(["*"]))
        adapter = AuthFacadeFromAuthState(auth_state=state)

        # Не должно бросать TypeError при использовании как AuthFacade
        _check(adapter)

    def test_adapter_has_all_protocol_methods(self) -> None:
        """Adapter имеет все 3 атрибута из Protocol: access_level, is_authenticated, has_permission."""
        state = FakeAuthState()
        adapter = AuthFacadeFromAuthState(auth_state=state)

        assert hasattr(adapter, "access_level"), "Отсутствует property access_level"
        assert hasattr(adapter, "is_authenticated"), "Отсутствует метод is_authenticated"
        assert hasattr(adapter, "has_permission"), "Отсутствует метод has_permission"
        assert callable(adapter.is_authenticated), "is_authenticated должен быть callable"
        assert callable(adapter.has_permission), "has_permission должен быть callable"
