"""Тесты для RegistersStateAdapter — двунаправленный мост RegistersManager <-> StateProxy."""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from multiprocess_prototype.state_store.adapters.registers_adapter import RegistersStateAdapter
from multiprocess_prototype.state_store.core.delta import Delta, MISSING


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def path_mapping() -> dict[tuple[str, str], str]:
    """Типовой маппинг для тестов."""
    return {
        ("camera", "fps"): "cameras.0.config.fps",
        ("camera", "exposure"): "cameras.0.config.exposure",
        ("recipe", "threshold"): "recipe.threshold",
        ("system", "mode"): "system.mode",
    }


@pytest.fixture
def mock_rm() -> MagicMock:
    """Mock RegistersManager с нужными методами."""
    rm = MagicMock()
    rm.subscribe_all = MagicMock()
    rm.unsubscribe_all = MagicMock()
    rm.notify_field_changed = MagicMock()
    return rm


@pytest.fixture
def mock_proxy() -> MagicMock:
    """Mock StateProxy с нужными методами."""
    proxy = MagicMock()
    proxy.subscribe = MagicMock(return_value="sub-123")
    proxy.unsubscribe = MagicMock()
    proxy.set = MagicMock()
    return proxy


@pytest.fixture
def adapter(
    mock_rm: MagicMock,
    mock_proxy: MagicMock,
    path_mapping: dict,
) -> RegistersStateAdapter:
    """Адаптер с моками, не подключённый."""
    return RegistersStateAdapter(mock_rm, mock_proxy, path_mapping)


@pytest.fixture
def connected_adapter(adapter: RegistersStateAdapter) -> RegistersStateAdapter:
    """Адаптер, уже подключённый через connect()."""
    adapter.connect()
    return adapter


# ---------------------------------------------------------------------------
# Тесты: инициализация
# ---------------------------------------------------------------------------

class TestInit:
    """Тесты инициализации адаптера."""

    def test_not_connected_by_default(self, adapter: RegistersStateAdapter) -> None:
        """Адаптер не подключён по умолчанию."""
        assert adapter.is_connected is False

    def test_reverse_mapping_built(self, adapter: RegistersStateAdapter) -> None:
        """Обратный маппинг строится автоматически."""
        assert adapter._reverse_mapping["cameras.0.config.fps"] == ("camera", "fps")
        assert adapter._reverse_mapping["recipe.threshold"] == ("recipe", "threshold")

    def test_pending_paths_empty(self, adapter: RegistersStateAdapter) -> None:
        """Pending пути пусты при создании."""
        assert adapter.pending_paths == frozenset()


# ---------------------------------------------------------------------------
# Тесты: connect / disconnect
# ---------------------------------------------------------------------------

class TestConnectDisconnect:
    """Тесты подключения и отключения."""

    def test_connect_subscribes_rm(
        self, adapter: RegistersStateAdapter, mock_rm: MagicMock,
    ) -> None:
        """connect() вызывает subscribe_all на RegistersManager."""
        adapter.connect()
        mock_rm.subscribe_all.assert_called_once()

    def test_connect_subscribes_proxy(
        self, adapter: RegistersStateAdapter, mock_proxy: MagicMock,
    ) -> None:
        """connect() вызывает subscribe на StateProxy с паттерном '**'."""
        adapter.connect()
        mock_proxy.subscribe.assert_called_once()
        args, kwargs = mock_proxy.subscribe.call_args
        assert args[0] == "**"
        assert kwargs.get("exclude_self") is False

    def test_connect_sets_connected(self, adapter: RegistersStateAdapter) -> None:
        """connect() устанавливает is_connected = True."""
        adapter.connect()
        assert adapter.is_connected is True

    def test_double_connect_ignored(
        self, connected_adapter: RegistersStateAdapter, mock_rm: MagicMock,
    ) -> None:
        """Повторный connect() игнорируется."""
        connected_adapter.connect()
        # subscribe_all вызвана только один раз (из connected_adapter фикстуры)
        assert mock_rm.subscribe_all.call_count == 1

    def test_disconnect_unsubscribes_rm(
        self, connected_adapter: RegistersStateAdapter, mock_rm: MagicMock,
    ) -> None:
        """disconnect() вызывает unsubscribe_all на RegistersManager."""
        connected_adapter.disconnect()
        mock_rm.unsubscribe_all.assert_called_once()

    def test_disconnect_unsubscribes_proxy(
        self, connected_adapter: RegistersStateAdapter, mock_proxy: MagicMock,
    ) -> None:
        """disconnect() вызывает unsubscribe на StateProxy с корректным sub_id."""
        connected_adapter.disconnect()
        mock_proxy.unsubscribe.assert_called_once_with("sub-123")

    def test_disconnect_sets_not_connected(
        self, connected_adapter: RegistersStateAdapter,
    ) -> None:
        """disconnect() устанавливает is_connected = False."""
        connected_adapter.disconnect()
        assert connected_adapter.is_connected is False

    def test_disconnect_clears_pending(
        self, connected_adapter: RegistersStateAdapter,
    ) -> None:
        """disconnect() очищает pending_paths."""
        # Добавим pending вручную
        connected_adapter._pending_paths.add("cameras.0.config.fps")
        connected_adapter.disconnect()
        assert connected_adapter.pending_paths == frozenset()

    def test_double_disconnect_ignored(
        self, connected_adapter: RegistersStateAdapter, mock_rm: MagicMock,
    ) -> None:
        """Повторный disconnect() игнорируется."""
        connected_adapter.disconnect()
        connected_adapter.disconnect()
        assert mock_rm.unsubscribe_all.call_count == 1


# ---------------------------------------------------------------------------
# Тесты: Direction 1 — Widget -> StateStore
# ---------------------------------------------------------------------------

class TestWidgetToState:
    """Тесты направления Widget -> StateStore (через RegistersManager)."""

    def test_widget_change_calls_proxy_set(
        self, connected_adapter: RegistersStateAdapter, mock_proxy: MagicMock,
    ) -> None:
        """Изменение виджета вызывает proxy.set() с правильным path и value."""
        # Достаём callback, переданный в subscribe_all
        rm_callback = connected_adapter._rm.subscribe_all.call_args[0][0]
        rm_callback("camera", "fps", 30)
        mock_proxy.set.assert_called_once_with("cameras.0.config.fps", 30)

    def test_widget_change_adds_pending(
        self, connected_adapter: RegistersStateAdapter,
    ) -> None:
        """Изменение виджета добавляет путь в pending_paths."""
        rm_callback = connected_adapter._rm.subscribe_all.call_args[0][0]
        rm_callback("camera", "fps", 30)
        assert "cameras.0.config.fps" in connected_adapter.pending_paths

    def test_unmapped_field_ignored(
        self, connected_adapter: RegistersStateAdapter, mock_proxy: MagicMock,
    ) -> None:
        """Поле без маппинга не вызывает proxy.set()."""
        rm_callback = connected_adapter._rm.subscribe_all.call_args[0][0]
        rm_callback("unknown_register", "unknown_field", 42)
        mock_proxy.set.assert_not_called()

    def test_proxy_set_error_clears_pending(
        self, connected_adapter: RegistersStateAdapter, mock_proxy: MagicMock,
    ) -> None:
        """Если proxy.set() бросает исключение — путь убирается из pending."""
        mock_proxy.set.side_effect = RuntimeError("IPC error")
        rm_callback = connected_adapter._rm.subscribe_all.call_args[0][0]
        rm_callback("camera", "fps", 30)
        # Pending должен быть очищен после ошибки
        assert "cameras.0.config.fps" not in connected_adapter.pending_paths

    def test_multiple_fields_independent(
        self, connected_adapter: RegistersStateAdapter, mock_proxy: MagicMock,
    ) -> None:
        """Несколько полей обрабатываются независимо."""
        rm_callback = connected_adapter._rm.subscribe_all.call_args[0][0]
        rm_callback("camera", "fps", 30)
        rm_callback("recipe", "threshold", 0.8)
        assert mock_proxy.set.call_count == 2
        mock_proxy.set.assert_any_call("cameras.0.config.fps", 30)
        mock_proxy.set.assert_any_call("recipe.threshold", 0.8)


# ---------------------------------------------------------------------------
# Тесты: Direction 2 — StateStore -> Widget
# ---------------------------------------------------------------------------

class TestStateToWidget:
    """Тесты направления StateStore -> Widget (через StateProxy deltas)."""

    def test_delta_calls_notify(
        self, connected_adapter: RegistersStateAdapter, mock_rm: MagicMock,
    ) -> None:
        """Дельта от StateProxy вызывает notify_field_changed на RegistersManager."""
        proxy_callback = connected_adapter._proxy.subscribe.call_args[0][1]
        delta = Delta(
            path="cameras.0.config.fps",
            old_value=25,
            new_value=30,
            source="camera_0",
        )
        proxy_callback([delta])
        mock_rm.notify_field_changed.assert_called_once_with("camera", "fps", 30)

    def test_unmapped_delta_ignored(
        self, connected_adapter: RegistersStateAdapter, mock_rm: MagicMock,
    ) -> None:
        """Дельта с немаппленным путём игнорируется."""
        proxy_callback = connected_adapter._proxy.subscribe.call_args[0][1]
        delta = Delta(
            path="some.unknown.path",
            old_value=None,
            new_value=42,
            source="backend",
        )
        proxy_callback([delta])
        mock_rm.notify_field_changed.assert_not_called()

    def test_multiple_deltas_processed(
        self, connected_adapter: RegistersStateAdapter, mock_rm: MagicMock,
    ) -> None:
        """Несколько дельт обрабатываются за один вызов."""
        proxy_callback = connected_adapter._proxy.subscribe.call_args[0][1]
        deltas = [
            Delta(path="cameras.0.config.fps", old_value=25, new_value=30, source="be"),
            Delta(path="recipe.threshold", old_value=0.5, new_value=0.8, source="be"),
        ]
        proxy_callback(deltas)
        assert mock_rm.notify_field_changed.call_count == 2
        mock_rm.notify_field_changed.assert_any_call("camera", "fps", 30)
        mock_rm.notify_field_changed.assert_any_call("recipe", "threshold", 0.8)

    def test_notify_error_does_not_break_others(
        self, connected_adapter: RegistersStateAdapter, mock_rm: MagicMock,
    ) -> None:
        """Ошибка в notify_field_changed не прерывает обработку остальных дельт."""
        mock_rm.notify_field_changed.side_effect = [
            RuntimeError("widget error"),
            None,
        ]
        proxy_callback = connected_adapter._proxy.subscribe.call_args[0][1]
        deltas = [
            Delta(path="cameras.0.config.fps", old_value=25, new_value=30, source="be"),
            Delta(path="recipe.threshold", old_value=0.5, new_value=0.8, source="be"),
        ]
        proxy_callback(deltas)
        # Второй вызов всё равно произошёл
        assert mock_rm.notify_field_changed.call_count == 2


# ---------------------------------------------------------------------------
# Тесты: Anti-loop protection
# ---------------------------------------------------------------------------

class TestAntiLoop:
    """Тесты anti-loop механизма через _pending_paths."""

    def test_echo_skipped(
        self, connected_adapter: RegistersStateAdapter, mock_rm: MagicMock,
    ) -> None:
        """Эхо от собственного set() НЕ вызывает notify_field_changed."""
        rm_callback = connected_adapter._rm.subscribe_all.call_args[0][0]
        proxy_callback = connected_adapter._proxy.subscribe.call_args[0][1]

        # Шаг 1: виджет меняет fps -> pending добавлен
        rm_callback("camera", "fps", 30)
        assert "cameras.0.config.fps" in connected_adapter.pending_paths

        # Шаг 2: приходит эхо-дельта -> должна быть пропущена
        echo_delta = Delta(
            path="cameras.0.config.fps",
            old_value=25,
            new_value=30,
            source="gui",
        )
        proxy_callback([echo_delta])

        # notify_field_changed НЕ вызван
        mock_rm.notify_field_changed.assert_not_called()
        # Путь убран из pending
        assert "cameras.0.config.fps" not in connected_adapter.pending_paths

    def test_external_change_after_echo(
        self, connected_adapter: RegistersStateAdapter, mock_rm: MagicMock,
    ) -> None:
        """После обработки эхо, внешнее изменение по тому же пути проходит."""
        rm_callback = connected_adapter._rm.subscribe_all.call_args[0][0]
        proxy_callback = connected_adapter._proxy.subscribe.call_args[0][1]

        # Виджет -> set (добавляет pending)
        rm_callback("camera", "fps", 30)

        # Эхо (убирает pending)
        proxy_callback([Delta(
            path="cameras.0.config.fps", old_value=25, new_value=30, source="gui",
        )])
        mock_rm.notify_field_changed.assert_not_called()

        # Внешнее изменение (pending пуст — должно пройти)
        proxy_callback([Delta(
            path="cameras.0.config.fps", old_value=30, new_value=60, source="camera_0",
        )])
        mock_rm.notify_field_changed.assert_called_once_with("camera", "fps", 60)

    def test_no_pending_for_unmapped(
        self, connected_adapter: RegistersStateAdapter,
    ) -> None:
        """Немаппленные поля не добавляют pending."""
        rm_callback = connected_adapter._rm.subscribe_all.call_args[0][0]
        rm_callback("unknown", "field", 42)
        assert len(connected_adapter.pending_paths) == 0

    def test_mixed_pending_and_external(
        self, connected_adapter: RegistersStateAdapter, mock_rm: MagicMock,
    ) -> None:
        """В одном batch: одна дельта — эхо (skip), другая — внешняя (pass)."""
        rm_callback = connected_adapter._rm.subscribe_all.call_args[0][0]
        proxy_callback = connected_adapter._proxy.subscribe.call_args[0][1]

        # Виджет меняет fps -> pending
        rm_callback("camera", "fps", 30)

        # Приходит batch: эхо fps + внешний threshold
        deltas = [
            Delta(path="cameras.0.config.fps", old_value=25, new_value=30, source="gui"),
            Delta(path="recipe.threshold", old_value=0.5, new_value=0.9, source="backend"),
        ]
        proxy_callback(deltas)

        # fps пропущен (эхо), threshold прошёл
        mock_rm.notify_field_changed.assert_called_once_with("recipe", "threshold", 0.9)


# ---------------------------------------------------------------------------
# Тесты: edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Краевые случаи."""

    def test_empty_mapping(self, mock_rm: MagicMock, mock_proxy: MagicMock) -> None:
        """Адаптер с пустым маппингом корректно создаётся и подключается."""
        adapter = RegistersStateAdapter(mock_rm, mock_proxy, {})
        adapter.connect()
        assert adapter.is_connected is True
        adapter.disconnect()
        assert adapter.is_connected is False

    def test_none_value_handled(
        self, connected_adapter: RegistersStateAdapter, mock_proxy: MagicMock,
    ) -> None:
        """None как значение корректно передаётся через адаптер."""
        rm_callback = connected_adapter._rm.subscribe_all.call_args[0][0]
        rm_callback("camera", "fps", None)
        mock_proxy.set.assert_called_once_with("cameras.0.config.fps", None)

    def test_delete_delta_passes_missing(
        self, connected_adapter: RegistersStateAdapter, mock_rm: MagicMock,
    ) -> None:
        """Дельта удаления (new_value=MISSING) передаёт MISSING в notify."""
        proxy_callback = connected_adapter._proxy.subscribe.call_args[0][1]
        delta = Delta(
            path="cameras.0.config.fps",
            old_value=30,
            new_value=MISSING,
            source="cleanup",
        )
        proxy_callback([delta])
        mock_rm.notify_field_changed.assert_called_once_with("camera", "fps", MISSING)
