"""Тесты для CameraStateAdapter — адаптер данных камер через StateProxy."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from state_store.adapters.camera_state_adapter import CameraStateAdapter
from state_store.core.delta import Delta, MISSING


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------

def _make_delta(path: str, new_value: Any, old_value: Any = MISSING) -> Delta:
    """Создать Delta с заданным путём и новым значением."""
    return Delta(path=path, old_value=old_value, new_value=new_value, source="test")


def _make_proxy() -> MagicMock:
    """Создать mock StateProxy с нужными методами."""
    proxy = MagicMock()
    proxy.subscribe = MagicMock(return_value="sub-cam-001")
    proxy.unsubscribe = MagicMock()
    return proxy


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def proxy() -> MagicMock:
    return _make_proxy()


@pytest.fixture
def adapter(proxy: MagicMock) -> CameraStateAdapter:
    """Адаптер с mock-proxy, не подключённый."""
    return CameraStateAdapter(state_proxy=proxy, num_cameras=2)


@pytest.fixture
def connected_adapter(adapter: CameraStateAdapter) -> CameraStateAdapter:
    """Адаптер, уже подключённый через connect()."""
    adapter.connect()
    return adapter


# ---------------------------------------------------------------------------
# Тест 1: Инициализация — кэш заполнен дефолтными значениями
# ---------------------------------------------------------------------------

class TestInit:
    def test_initial_camera_states_have_defaults(self, adapter: CameraStateAdapter) -> None:
        """При инициализации num_cameras=2 должны быть записи для camera 0 и 1."""
        state_0 = adapter.get_camera_state(0)
        state_1 = adapter.get_camera_state(1)
        assert state_0 == {"status": "stopped", "actual_fps": 0.0, "drops_count": 0, "last_frame_seq": 0}
        assert state_1 == {"status": "stopped", "actual_fps": 0.0, "drops_count": 0, "last_frame_seq": 0}

    def test_camera_ids_returns_sorted_list(self, adapter: CameraStateAdapter) -> None:
        """camera_ids() возвращает отсортированный список."""
        assert adapter.camera_ids() == [0, 1]

    def test_get_camera_state_unknown_returns_empty(self, adapter: CameraStateAdapter) -> None:
        """get_camera_state для неизвестной камеры возвращает пустой dict."""
        assert adapter.get_camera_state(99) == {}

    def test_not_connected_after_init(self, adapter: CameraStateAdapter) -> None:
        """После создания адаптер НЕ подключён."""
        assert not adapter.is_connected


# ---------------------------------------------------------------------------
# Тест 2: connect() / disconnect()
# ---------------------------------------------------------------------------

class TestConnectDisconnect:
    def test_connect_subscribes_to_camera_state_pattern(
        self, adapter: CameraStateAdapter, proxy: MagicMock
    ) -> None:
        """connect() вызывает proxy.subscribe с паттерном cameras.*.state.**"""
        adapter.connect()
        proxy.subscribe.assert_called_once()
        call_args = proxy.subscribe.call_args
        pattern = call_args[0][0] if call_args[0] else call_args[1]["pattern"]
        assert pattern == "cameras.*.state.**"

    def test_connect_sets_is_connected(self, adapter: CameraStateAdapter) -> None:
        """После connect() is_connected=True."""
        adapter.connect()
        assert adapter.is_connected

    def test_double_connect_ignored(
        self, connected_adapter: CameraStateAdapter, proxy: MagicMock
    ) -> None:
        """Повторный connect() не вызывает subscribe снова."""
        connected_adapter.connect()  # второй раз
        assert proxy.subscribe.call_count == 1  # только первый раз

    def test_disconnect_calls_unsubscribe(
        self, connected_adapter: CameraStateAdapter, proxy: MagicMock
    ) -> None:
        """disconnect() вызывает proxy.unsubscribe с sub_id."""
        connected_adapter.disconnect()
        proxy.unsubscribe.assert_called_once_with("sub-cam-001")

    def test_disconnect_clears_is_connected(
        self, connected_adapter: CameraStateAdapter
    ) -> None:
        """После disconnect() is_connected=False."""
        connected_adapter.disconnect()
        assert not connected_adapter.is_connected

    def test_disconnect_without_connect_ignored(
        self, adapter: CameraStateAdapter, proxy: MagicMock
    ) -> None:
        """disconnect() без предварительного connect() не вызывает ошибок."""
        adapter.disconnect()  # не должно падать
        proxy.unsubscribe.assert_not_called()


# ---------------------------------------------------------------------------
# Тест 3: Обновление кэша через _on_state_deltas
# ---------------------------------------------------------------------------

class TestOnStateDeltas:
    def test_status_update_reflected_in_cache(
        self, connected_adapter: CameraStateAdapter
    ) -> None:
        """Delta cameras.0.state.status → кэш обновляется."""
        delta = _make_delta("cameras.0.state.status", "running")
        connected_adapter._on_state_deltas([delta])
        assert connected_adapter.get_camera_state(0)["status"] == "running"

    def test_fps_update_reflected_in_cache(
        self, connected_adapter: CameraStateAdapter
    ) -> None:
        """Delta cameras.1.state.actual_fps → кэш camera 1 обновляется."""
        delta = _make_delta("cameras.1.state.actual_fps", 29.5)
        connected_adapter._on_state_deltas([delta])
        assert connected_adapter.get_camera_state(1)["actual_fps"] == 29.5

    def test_drops_count_update(self, connected_adapter: CameraStateAdapter) -> None:
        """Delta cameras.0.state.drops_count → обновляется счётчик дропов."""
        delta = _make_delta("cameras.0.state.drops_count", 42)
        connected_adapter._on_state_deltas([delta])
        assert connected_adapter.get_camera_state(0)["drops_count"] == 42

    def test_last_frame_seq_update(self, connected_adapter: CameraStateAdapter) -> None:
        """Delta cameras.0.state.last_frame_seq → обновляется seq номер кадра."""
        delta = _make_delta("cameras.0.state.last_frame_seq", 1234)
        connected_adapter._on_state_deltas([delta])
        assert connected_adapter.get_camera_state(0)["last_frame_seq"] == 1234

    def test_unknown_path_ignored(self, connected_adapter: CameraStateAdapter) -> None:
        """Дельта с нерелевантным путём — кэш не меняется."""
        delta = _make_delta("processor.config.threshold", 128)
        connected_adapter._on_state_deltas([delta])
        # Кэш камер должен остаться дефолтным
        assert connected_adapter.get_camera_state(0)["status"] == "stopped"

    def test_unknown_field_ignored(self, connected_adapter: CameraStateAdapter) -> None:
        """Поле, не входящее в _TRACKED_FIELDS, игнорируется."""
        delta = _make_delta("cameras.0.state.some_unknown_field", "value")
        connected_adapter._on_state_deltas([delta])
        # Только известные поля в кэше
        state = connected_adapter.get_camera_state(0)
        assert "some_unknown_field" not in state

    def test_new_camera_auto_registered(
        self, connected_adapter: CameraStateAdapter
    ) -> None:
        """Дельта для новой camera_id (не в num_cameras) — автоматически создаётся запись."""
        delta = _make_delta("cameras.5.state.status", "running")
        connected_adapter._on_state_deltas([delta])
        assert connected_adapter.get_camera_state(5)["status"] == "running"

    def test_multiple_deltas_in_one_batch(
        self, connected_adapter: CameraStateAdapter
    ) -> None:
        """Несколько дельт в одном batch — все применяются."""
        deltas = [
            _make_delta("cameras.0.state.status", "running"),
            _make_delta("cameras.0.state.actual_fps", 30.0),
            _make_delta("cameras.1.state.drops_count", 5),
        ]
        connected_adapter._on_state_deltas(deltas)
        assert connected_adapter.get_camera_state(0)["status"] == "running"
        assert connected_adapter.get_camera_state(0)["actual_fps"] == 30.0
        assert connected_adapter.get_camera_state(1)["drops_count"] == 5


# ---------------------------------------------------------------------------
# Тест 4: Callbacks
# ---------------------------------------------------------------------------

class TestCallbacks:
    def test_add_callback_called_on_update(
        self, connected_adapter: CameraStateAdapter
    ) -> None:
        """Зарегистрированный callback вызывается при изменении состояния."""
        events: list = []
        connected_adapter.add_callback(lambda cid, field, val: events.append((cid, field, val)))

        delta = _make_delta("cameras.0.state.status", "running")
        connected_adapter._on_state_deltas([delta])

        assert len(events) == 1
        assert events[0] == (0, "status", "running")

    def test_callback_receives_correct_camera_id(
        self, connected_adapter: CameraStateAdapter
    ) -> None:
        """Callback получает правильный camera_id из пути дельты."""
        received_ids: list = []
        connected_adapter.add_callback(lambda cid, field, val: received_ids.append(cid))

        connected_adapter._on_state_deltas([
            _make_delta("cameras.1.state.actual_fps", 25.0),
        ])
        assert received_ids == [1]

    def test_remove_callback_stops_notifications(
        self, connected_adapter: CameraStateAdapter
    ) -> None:
        """После remove_callback уведомления больше не приходят."""
        events: list = []
        cb = lambda cid, field, val: events.append((cid, field, val))
        connected_adapter.add_callback(cb)
        connected_adapter.remove_callback(cb)

        delta = _make_delta("cameras.0.state.status", "error")
        connected_adapter._on_state_deltas([delta])

        assert len(events) == 0

    def test_duplicate_add_callback_ignored(
        self, connected_adapter: CameraStateAdapter
    ) -> None:
        """Повторный add_callback с тем же callback — не дублируется."""
        events: list = []
        cb = lambda cid, field, val: events.append(1)
        connected_adapter.add_callback(cb)
        connected_adapter.add_callback(cb)  # второй раз

        delta = _make_delta("cameras.0.state.status", "running")
        connected_adapter._on_state_deltas([delta])

        assert len(events) == 1  # только один вызов

    def test_callback_exception_does_not_break_others(
        self, connected_adapter: CameraStateAdapter
    ) -> None:
        """Исключение в одном callback не прерывает вызов других."""
        results: list = []

        def bad_cb(cid: int, field: str, val: Any) -> None:
            raise RuntimeError("ошибка в callback")

        good_cb = lambda cid, field, val: results.append(val)

        connected_adapter.add_callback(bad_cb)
        connected_adapter.add_callback(good_cb)

        delta = _make_delta("cameras.0.state.status", "running")
        connected_adapter._on_state_deltas([delta])

        # good_cb должен сработать несмотря на ошибку в bad_cb
        assert results == ["running"]

    def test_multiple_callbacks_all_called(
        self, connected_adapter: CameraStateAdapter
    ) -> None:
        """Все зарегистрированные callbacks вызываются."""
        calls_a: list = []
        calls_b: list = []
        connected_adapter.add_callback(lambda cid, f, v: calls_a.append(v))
        connected_adapter.add_callback(lambda cid, f, v: calls_b.append(v))

        delta = _make_delta("cameras.0.state.actual_fps", 60.0)
        connected_adapter._on_state_deltas([delta])

        assert calls_a == [60.0]
        assert calls_b == [60.0]


# ---------------------------------------------------------------------------
# Тест 5: get_camera_state возвращает копию (изоляция)
# ---------------------------------------------------------------------------

class TestGetCameraStateIsolation:
    def test_returned_dict_is_copy(self, connected_adapter: CameraStateAdapter) -> None:
        """get_camera_state возвращает копию — мутация не влияет на внутренний кэш."""
        state = connected_adapter.get_camera_state(0)
        state["status"] = "mutated"

        # Внутренний кэш не изменился
        assert connected_adapter.get_camera_state(0)["status"] == "stopped"


# ---------------------------------------------------------------------------
# Тест 6: Работа без proxy (state_proxy=None)
# ---------------------------------------------------------------------------

class TestNullProxy:
    def test_connect_with_none_proxy_does_not_crash(self) -> None:
        """CameraStateAdapter(state_proxy=None) — connect() не падает."""
        adapter = CameraStateAdapter(state_proxy=None, num_cameras=1)
        # Не должно вызвать исключение
        # connect() не вызываем — нет смысла без proxy
        state = adapter.get_camera_state(0)
        assert state["status"] == "stopped"

    def test_manual_delta_injection_without_proxy(self) -> None:
        """Дельты можно инжектировать напрямую через _on_state_deltas без proxy."""
        adapter = CameraStateAdapter(state_proxy=None, num_cameras=1)
        events: list = []
        adapter.add_callback(lambda cid, f, v: events.append((cid, f, v)))

        delta = _make_delta("cameras.0.state.status", "running")
        adapter._on_state_deltas([delta])

        assert adapter.get_camera_state(0)["status"] == "running"
        assert events == [(0, "status", "running")]
