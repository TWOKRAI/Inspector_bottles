"""test_state_adapter_base.py -- Unit-тесты для IStateAdapter Protocol и StateAdapterBase ABC.

Покрытие:
    1. IStateAdapter -- runtime_checkable isinstance-проверка
    2. StateAdapterBase -- lifecycle bind/unbind
    3. StateAdapterBase -- lifecycle connect/disconnect
    4. StateAdapterBase -- anti-loop через _pending_paths
    5. StateAdapterBase -- logger silent fallback (logger=None)
    6. StateAdapterBase -- logger вызывается когда передан
    7. StateAdapterBase -- connect без bind игнорируется
    8. StateAdapterBase -- повторный connect игнорируется
    9. StateAdapterBase -- bind при подключённом адаптере отключает старый
    10. StateAdapterBase -- issubclass проверка
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.state_store_module.adapters import (
    IStateAdapter,
    StateAdapterBase,
)


# ---------------------------------------------------------------------------
# Фикстуры и вспомогательные классы
# ---------------------------------------------------------------------------


class ConcreteAdapter(StateAdapterBase):
    """Минимальный конкретный адаптер для тестирования базового класса."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Счётчики вызовов для проверки шаблонных методов
        self.subscribe_all_calls = 0
        self.unsubscribe_all_calls = 0
        self.sync_d2s_calls = 0
        self.sync_s2d_calls = 0

    def _subscribe_all(self) -> None:
        self.subscribe_all_calls += 1
        # Имитируем создание подписки
        self._sub_ids.append("sub_test_001")

    def _unsubscribe_all(self) -> None:
        self.unsubscribe_all_calls += 1
        # Имитируем отписку
        if self._proxy is not None:
            for sub_id in self._sub_ids:
                self._proxy.unsubscribe(sub_id)

    def sync_domain_to_state(self) -> None:
        self.sync_d2s_calls += 1

    def sync_state_to_domain(self) -> None:
        self.sync_s2d_calls += 1


@pytest.fixture
def mock_proxy() -> MagicMock:
    """Фейковый StateProxy для тестов."""
    proxy = MagicMock()
    proxy.subscribe.return_value = "sub_mock_001"
    return proxy


@pytest.fixture
def adapter() -> ConcreteAdapter:
    """Адаптер без привязки к прокси."""
    return ConcreteAdapter()


@pytest.fixture
def bound_adapter(mock_proxy: MagicMock) -> ConcreteAdapter:
    """Адаптер, привязанный к mock-прокси."""
    a = ConcreteAdapter()
    a.bind(mock_proxy)
    return a


# ---------------------------------------------------------------------------
# 1. IStateAdapter -- runtime_checkable Protocol
# ---------------------------------------------------------------------------


class TestIStateAdapterProtocol:
    """Проверяем что IStateAdapter -- runtime_checkable Protocol."""

    def test_isinstance_concrete_adapter(self, bound_adapter: ConcreteAdapter) -> None:
        """ConcreteAdapter (наследник StateAdapterBase) удовлетворяет IStateAdapter."""
        assert isinstance(bound_adapter, IStateAdapter)

    def test_isinstance_duck_typing(self) -> None:
        """Объект с нужными методами удовлетворяет IStateAdapter (duck-typing)."""

        class DuckAdapter:
            def bind(self, state_proxy: Any) -> None: ...
            def unbind(self) -> None: ...
            def sync_domain_to_state(self) -> None: ...
            def sync_state_to_domain(self) -> None: ...

            @property
            def is_bound(self) -> bool:
                return False

        duck = DuckAdapter()
        assert isinstance(duck, IStateAdapter)

    def test_not_isinstance_missing_method(self) -> None:
        """Объект без одного из методов НЕ удовлетворяет IStateAdapter."""

        class IncompleteAdapter:
            def bind(self, state_proxy: Any) -> None: ...
            def unbind(self) -> None: ...

            # Нет sync_domain_to_state, sync_state_to_domain, is_bound

        obj = IncompleteAdapter()
        assert not isinstance(obj, IStateAdapter)


# ---------------------------------------------------------------------------
# 2. issubclass -- проверка наследования
# ---------------------------------------------------------------------------


class TestIsSubclass:
    """Проверяем issubclass для ConcreteAdapter."""

    def test_issubclass_state_adapter_base(self) -> None:
        """ConcreteAdapter -- подкласс StateAdapterBase."""
        assert issubclass(ConcreteAdapter, StateAdapterBase)


# ---------------------------------------------------------------------------
# 3. Lifecycle bind / unbind
# ---------------------------------------------------------------------------


class TestBindUnbind:
    """Тесты lifecycle: bind и unbind."""

    def test_initial_state_not_bound(self, adapter: ConcreteAdapter) -> None:
        """Адаптер создан без прокси -- не привязан."""
        assert not adapter.is_bound
        assert adapter._proxy is None

    def test_bind_sets_proxy(
        self,
        adapter: ConcreteAdapter,
        mock_proxy: MagicMock,
    ) -> None:
        """bind() устанавливает прокси и is_bound = True."""
        adapter.bind(mock_proxy)
        assert adapter.is_bound
        assert adapter._proxy is mock_proxy

    def test_unbind_clears_proxy(self, bound_adapter: ConcreteAdapter) -> None:
        """unbind() убирает прокси и is_bound = False."""
        bound_adapter.unbind()
        assert not bound_adapter.is_bound
        assert bound_adapter._proxy is None

    def test_bind_with_initial_proxy(self, mock_proxy: MagicMock) -> None:
        """Передача state_proxy в конструктор -- адаптер сразу привязан."""
        a = ConcreteAdapter(state_proxy=mock_proxy)
        assert a.is_bound
        assert a._proxy is mock_proxy

    def test_bind_while_connected_disconnects_first(
        self,
        bound_adapter: ConcreteAdapter,
        mock_proxy: MagicMock,
    ) -> None:
        """bind() при подключённом адаптере сначала вызывает disconnect()."""
        bound_adapter.connect()
        assert bound_adapter.is_connected

        new_proxy = MagicMock()
        bound_adapter.bind(new_proxy)

        # Старое соединение должно быть разорвано
        assert not bound_adapter.is_connected
        assert bound_adapter._proxy is new_proxy
        assert bound_adapter.unsubscribe_all_calls == 1


# ---------------------------------------------------------------------------
# 4. Lifecycle connect / disconnect
# ---------------------------------------------------------------------------


class TestConnectDisconnect:
    """Тесты lifecycle: connect и disconnect."""

    def test_connect_calls_subscribe_all(
        self,
        bound_adapter: ConcreteAdapter,
    ) -> None:
        """connect() вызывает _subscribe_all() и is_connected = True."""
        bound_adapter.connect()
        assert bound_adapter.is_connected
        assert bound_adapter.subscribe_all_calls == 1
        assert len(bound_adapter._sub_ids) == 1

    def test_disconnect_calls_unsubscribe_all(
        self,
        bound_adapter: ConcreteAdapter,
    ) -> None:
        """disconnect() вызывает _unsubscribe_all() и очищает sub_ids."""
        bound_adapter.connect()
        bound_adapter.disconnect()
        assert not bound_adapter.is_connected
        assert bound_adapter.unsubscribe_all_calls == 1
        assert len(bound_adapter._sub_ids) == 0

    def test_connect_without_bind_ignored(self, adapter: ConcreteAdapter) -> None:
        """connect() без bind -- игнорируется (не подключается)."""
        adapter.connect()
        assert not adapter.is_connected
        assert adapter.subscribe_all_calls == 0

    def test_double_connect_ignored(self, bound_adapter: ConcreteAdapter) -> None:
        """Повторный connect() игнорируется."""
        bound_adapter.connect()
        bound_adapter.connect()
        assert bound_adapter.subscribe_all_calls == 1

    def test_disconnect_without_connect_ignored(
        self,
        bound_adapter: ConcreteAdapter,
    ) -> None:
        """disconnect() без connect -- игнорируется."""
        bound_adapter.disconnect()
        assert bound_adapter.unsubscribe_all_calls == 0


# ---------------------------------------------------------------------------
# 5. Anti-loop через _pending_paths
# ---------------------------------------------------------------------------


class TestAntiLoop:
    """Тесты anti-loop защиты через _pending_paths."""

    def test_mark_pending_adds_path(self, adapter: ConcreteAdapter) -> None:
        """_mark_pending() добавляет путь в _pending_paths."""
        adapter._mark_pending("cameras.0.config.fps")
        assert "cameras.0.config.fps" in adapter._pending_paths

    def test_check_and_clear_pending_returns_true_for_pending(
        self,
        adapter: ConcreteAdapter,
    ) -> None:
        """_check_and_clear_pending() возвращает True и убирает путь."""
        adapter._mark_pending("cameras.0.config.fps")
        result = adapter._check_and_clear_pending("cameras.0.config.fps")
        assert result is True
        assert "cameras.0.config.fps" not in adapter._pending_paths

    def test_check_and_clear_pending_returns_false_for_external(
        self,
        adapter: ConcreteAdapter,
    ) -> None:
        """_check_and_clear_pending() возвращает False для внешнего изменения."""
        result = adapter._check_and_clear_pending("cameras.0.config.fps")
        assert result is False

    def test_pending_paths_cleared_on_disconnect(
        self,
        bound_adapter: ConcreteAdapter,
    ) -> None:
        """disconnect() очищает _pending_paths."""
        bound_adapter.connect()
        bound_adapter._mark_pending("a.b.c")
        bound_adapter._mark_pending("x.y.z")
        assert len(bound_adapter._pending_paths) == 2

        bound_adapter.disconnect()
        assert len(bound_adapter._pending_paths) == 0

    def test_pending_paths_property_returns_frozenset(
        self,
        adapter: ConcreteAdapter,
    ) -> None:
        """pending_paths property возвращает frozenset (иммутабельную копию)."""
        adapter._mark_pending("a.b")
        result = adapter.pending_paths
        assert isinstance(result, frozenset)
        assert "a.b" in result


# ---------------------------------------------------------------------------
# 6. Logger -- silent fallback
# ---------------------------------------------------------------------------


class TestLoggerFallback:
    """Тесты логирования: silent fallback и вызов инжектированного logger."""

    def test_log_without_logger_no_error(self, adapter: ConcreteAdapter) -> None:
        """_log_info/warning/error без logger -- ничего не происходит (нет ошибки)."""
        # Не должно бросать исключений
        adapter._log_info("тестовое сообщение %s", "arg")
        adapter._log_warning("предупреждение %d", 42)
        adapter._log_error("ошибка %s %s", "a", "b")

    def test_log_with_logger_calls_methods(self) -> None:
        """_log_info/warning/error вызывают соответствующие методы logger."""
        mock_logger = MagicMock()
        a = ConcreteAdapter(logger=mock_logger)

        a._log_info("info сообщение")
        mock_logger.log_info.assert_called_once_with("info сообщение")

        a._log_warning("warning %d", 42)
        mock_logger.log_warning.assert_called_once_with("warning 42")

        a._log_error("error %s", "test")
        mock_logger.log_error.assert_called_once_with("error test")

    def test_log_info_with_format_args(self) -> None:
        """_log_info корректно форматирует строку с аргументами."""
        mock_logger = MagicMock()
        a = ConcreteAdapter(logger=mock_logger)

        a._log_info("подписок=%d", 5)
        mock_logger.log_info.assert_called_once_with("подписок=5")


# ---------------------------------------------------------------------------
# 7. Инжекция managers
# ---------------------------------------------------------------------------


class TestManagersInjection:
    """Тесты инжекции managers через конструктор."""

    def test_all_managers_stored(self) -> None:
        """Все переданные managers сохраняются в атрибутах."""
        logger = MagicMock()
        stats = MagicMock()
        error = MagicMock()
        a = ConcreteAdapter(logger=logger, stats=stats, error=error)

        assert a._logger is logger
        assert a._stats is stats
        assert a._error is error

    def test_default_managers_none(self, adapter: ConcreteAdapter) -> None:
        """По умолчанию все managers -- None."""
        assert adapter._logger is None
        assert adapter._stats is None
        assert adapter._error is None


# ---------------------------------------------------------------------------
# 8. Полный lifecycle (integration-like)
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    """Интеграционный тест полного жизненного цикла адаптера."""

    def test_full_lifecycle(self, mock_proxy: MagicMock) -> None:
        """Полный цикл: create -> bind -> connect -> sync -> disconnect -> unbind."""
        a = ConcreteAdapter()

        # create -- ничего не привязано
        assert not a.is_bound
        assert not a.is_connected

        # bind
        a.bind(mock_proxy)
        assert a.is_bound
        assert not a.is_connected

        # connect
        a.connect()
        assert a.is_connected
        assert a.subscribe_all_calls == 1

        # sync
        a.sync_domain_to_state()
        a.sync_state_to_domain()
        assert a.sync_d2s_calls == 1
        assert a.sync_s2d_calls == 1

        # disconnect
        a.disconnect()
        assert not a.is_connected
        assert a.unsubscribe_all_calls == 1

        # unbind
        a.unbind()
        assert not a.is_bound
        assert a._proxy is None
