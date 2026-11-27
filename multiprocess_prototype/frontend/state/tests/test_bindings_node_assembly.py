"""Приёмочные тесты Task 2.8f: GUI собирает узел состояния из листовых дельт (REDS 1-10).

Написаны до реализации по ``plans/2026-10-27_system-run-state/tasks/2.8f.md``.
Объекты настоящие: ``DataReceiverBridge``, ``GuiStateBindings``, ``TelemetryViewModel``.
Порядок подключения как в приложении: сначала bindings, потом read-model слушателем.

Из главного потока ``bridge.dispatch`` доставляет синхронно, поэтому все тесты, кроме
REDS 10, проверяют результат сразу после вызова.

Маркер конца пачки подаётся литералом из задачи (так красный тест падает на поведении,
а не на отсутствующем имени); сборщик ``state_batch_end_message`` закреплён отдельно.
"""

from __future__ import annotations

import copy
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtWidgets import QLabel

from multiprocess_framework.modules.frontend_module import TelemetryViewModel
from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from multiprocess_prototype.frontend.bridge_impl import DataReceiverBridge
from multiprocess_prototype.frontend.state import delta_message
from multiprocess_prototype.frontend.state.bindings import DELETED, GuiStateBindings
from multiprocess_prototype.frontend.state.delta_message import state_delta_message

pytestmark = pytest.mark.usefixtures("qapp")

NODE = "devices.state.vfd1.status"
OTHER_NODE = "devices.state.vfd2.status"


def _delta(path: str, value: Any) -> Delta:
    return Delta(path=path, old_value=MISSING, new_value=value, source="test")


class _Gui:
    """Проводка настоящих объектов GUI без процесса."""

    def __init__(self, *, with_read_model: bool = True) -> None:
        self.bridge = DataReceiverBridge()
        self.vm = TelemetryViewModel() if with_read_model else None
        self.bindings = GuiStateBindings(self.bridge, read_model=self.vm)
        if self.vm is not None:
            self.bridge.add_state_listener(self.vm.on_state_delta)

    def put(self, path: str, value: Any) -> None:
        self.bridge.dispatch(state_delta_message(_delta(path, value)))

    def delete(self, path: str) -> None:
        delta = Delta(path=path, old_value=0, new_value=MISSING, source="test")
        self.bridge.dispatch(state_delta_message(delta))

    def end(self) -> None:
        """Маркер конца пачки."""
        self.bridge.dispatch({"data_type": "state_batch_end"})


class _Recorder:
    """Подписчик fan-out: копит то, что получил."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def __call__(self, path: str, value: Any) -> None:
        self.calls.append((path, value if value is DELETED else copy.deepcopy(value)))


def _subscribe(gui: _Gui, pattern: str) -> _Recorder:
    recorder = _Recorder()
    gui.bindings.bind_fanout(pattern, recorder)
    return recorder


# --------------------------------------------------------------------------- REDS 1


def test_state_batch_end_message_is_the_literal_envelope() -> None:
    assert delta_message.state_batch_end_message() == {"data_type": "state_batch_end"}


def test_four_leaf_deltas_give_one_node_call_after_marker() -> None:
    gui = _Gui()
    sub = _subscribe(gui, NODE)

    gui.put(f"{NODE}.a", 1)
    gui.put(f"{NODE}.b", 2.5)
    gui.put(f"{NODE}.c", True)
    gui.put(f"{NODE}.d", "x")
    assert sub.calls == []

    gui.end()
    assert sub.calls == [("devices.state.vfd1.status", {"a": 1, "b": 2.5, "c": True, "d": "x"})]


# --------------------------------------------------------------------------- REDS 2


def test_wildcard_gets_one_call_per_device_in_first_delta_order() -> None:
    gui = _Gui()
    sub = _subscribe(gui, "devices.registry.*")

    # Первая дельта: zeta, потом alpha (не по алфавиту); последняя снова у zeta.
    gui.put("devices.registry.zeta.kind", "vfd")
    gui.put("devices.registry.alpha.kind", "robot")
    gui.put("devices.registry.zeta.enabled", True)
    gui.end()

    assert sub.calls == [
        ("devices.registry.zeta", {"kind": "vfd", "enabled": True}),
        ("devices.registry.alpha", {"kind": "robot"}),
    ]


# --------------------------------------------------------------------------- REDS 3


@pytest.mark.parametrize("second_pattern", [NODE, "devices.state.*.status"], ids=["same_pattern", "wildcard"])
def test_two_subscribers_of_one_node_both_get_it(second_pattern: str) -> None:
    gui = _Gui()
    first = _subscribe(gui, NODE)
    second = _subscribe(gui, second_pattern)

    gui.put(f"{NODE}.a", 1)
    gui.end()

    assert first.calls == [("devices.state.vfd1.status", {"a": 1})]
    assert second.calls == [("devices.state.vfd1.status", {"a": 1})]


# --------------------------------------------------------------------------- REDS 4


def test_deleted_leaf_leaves_node_without_that_key() -> None:
    gui = _Gui()
    sub = _subscribe(gui, NODE)
    gui.put(f"{NODE}.a", 1)
    gui.put(f"{NODE}.b", 2)
    gui.end()
    sub.calls.clear()

    gui.delete(f"{NODE}.b")
    gui.end()

    assert sub.calls == [("devices.state.vfd1.status", {"a": 1})]


def test_all_leaves_deleted_give_one_deleted_call() -> None:
    gui = _Gui()
    sub = _subscribe(gui, NODE)
    gui.put(f"{NODE}.a", 1)
    gui.put(f"{NODE}.b", 2)
    gui.end()
    sub.calls.clear()

    gui.delete(f"{NODE}.a")
    gui.delete(f"{NODE}.b")
    gui.end()

    assert sub.calls == [("devices.state.vfd1.status", DELETED)]


# --------------------------------------------------------------------------- REDS 5


def test_leaf_then_exact_node_set_gives_one_call() -> None:
    gui = _Gui()
    sub = _subscribe(gui, NODE)

    gui.put(f"{NODE}.a", 1)
    gui.put(NODE, {"b": 2})
    gui.end()

    assert sub.calls == [("devices.state.vfd1.status", {"b": 2})]


def test_exact_node_set_then_leaf_gives_two_calls_second_merged() -> None:
    gui = _Gui()
    sub = _subscribe(gui, NODE)

    gui.put(NODE, {"b": 2})
    gui.put(f"{NODE}.a", 1)
    gui.end()

    assert sub.calls == [
        ("devices.state.vfd1.status", {"b": 2}),
        ("devices.state.vfd1.status", {"a": 1, "b": 2}),
    ]


def test_leaf_then_node_delete_gives_one_deleted_call() -> None:
    gui = _Gui()
    sub = _subscribe(gui, NODE)

    gui.put(f"{NODE}.a", 1)
    gui.delete(NODE)
    gui.end()

    assert sub.calls == [("devices.state.vfd1.status", DELETED)]


# --------------------------------------------------------------------------- REDS 6


def test_unbind_between_delta_and_marker_drops_only_that_subscriber() -> None:
    gui = _Gui()
    kept = _subscribe(gui, NODE)
    gone = _Recorder()
    handle = gui.bindings.bind_fanout(NODE, gone)

    gui.put(f"{NODE}.a", 1)
    gui.bindings.unbind_fanout(handle)
    gui.end()

    assert gone.calls == []
    assert kept.calls == [("devices.state.vfd1.status", {"a": 1})]


@pytest.mark.parametrize("how", ["unbind_fanout", "clear"])
def test_first_callback_removing_second_handle_during_flush_stops_second_call(how: str) -> None:
    gui = _Gui()
    first = _Recorder()
    second = _Recorder()
    handles: list[Any] = []

    def first_callback(path: str, value: Any) -> None:
        first(path, value)
        if how == "clear":
            gui.bindings.clear()
        else:
            gui.bindings.unbind_fanout(handles[0])

    # Разные узлы: порядок пар задан порядком дельт (vfd1 раньше vfd2).
    gui.bindings.bind_fanout(NODE, first_callback)
    handles.append(gui.bindings.bind_fanout(OTHER_NODE, second))

    gui.put(f"{NODE}.a", 1)
    gui.put(f"{OTHER_NODE}.a", 2)
    gui.end()

    assert first.calls == [("devices.state.vfd1.status", {"a": 1})]
    assert second.calls == []


# --------------------------------------------------------------------------- REDS 7


@pytest.mark.parametrize("second_node", [NODE, OTHER_NODE], ids=["same_node", "other_node"])
def test_raising_first_callback_does_not_stop_second(second_node: str) -> None:
    gui = _Gui()
    first = _Recorder()

    def raising(path: str, value: Any) -> None:
        first(path, value)
        raise RuntimeError("boom")

    gui.bindings.bind_fanout(NODE, raising)
    second = _subscribe(gui, second_node)

    gui.put(f"{NODE}.a", 1)
    if second_node != NODE:
        gui.put(f"{second_node}.a", 1)
    gui.end()

    assert first.calls == [("devices.state.vfd1.status", {"a": 1})]
    assert second.calls == [(second_node, {"a": 1})]


def test_delta_fed_from_callback_arrives_only_on_next_marker() -> None:
    gui = _Gui()
    sub = _Recorder()

    def feeding(path: str, value: Any) -> None:
        sub(path, value)
        if len(sub.calls) == 1:
            gui.put(f"{NODE}.a", 2)

    gui.bindings.bind_fanout(NODE, feeding)

    gui.put(f"{NODE}.a", 1)
    gui.end()
    assert sub.calls == [("devices.state.vfd1.status", {"a": 1})]

    gui.end()
    assert sub.calls == [
        ("devices.state.vfd1.status", {"a": 1}),
        ("devices.state.vfd1.status", {"a": 2}),
    ]


# --------------------------------------------------------------------------- REDS 8


def test_marker_without_dirty_nodes_calls_nothing() -> None:
    gui = _Gui()
    sub = _subscribe(gui, NODE)

    gui.end()
    # Соседние пути узел не помечают.
    gui.put("devices.state.vfd1.conn.x", 1)
    gui.put("devices.state.vfd1.status_other.a", 1)
    gui.end()

    assert sub.calls == []


def test_second_marker_after_flush_adds_no_call() -> None:
    gui = _Gui()
    sub = _subscribe(gui, NODE)

    gui.put(f"{NODE}.a", 1)
    gui.end()
    gui.end()

    assert sub.calls == [("devices.state.vfd1.status", {"a": 1})]


def test_widget_bind_on_node_still_receives_nothing(qtbot) -> None:
    gui = _Gui()
    label = QLabel("start")
    qtbot.addWidget(label)
    received: list[Any] = []

    def formatter(value: Any) -> str:
        received.append(value)
        return str(value)

    gui.bindings.bind(NODE, label, "text", formatter=formatter)

    gui.put(f"{NODE}.a", 1)
    gui.put(f"{NODE}.b", 2)
    gui.end()

    assert received == []
    assert label.text() == "start"


def test_trailing_double_star_still_gets_only_leaf_calls() -> None:
    gui = _Gui()
    sub = _subscribe(gui, "devices.state.**")

    gui.put(f"{NODE}.a", 1)
    gui.put(f"{NODE}.b", 2)
    gui.end()

    assert sub.calls == [
        ("devices.state.vfd1.status.a", 1),
        ("devices.state.vfd1.status.b", 2),
    ]


def test_inner_double_star_pattern_gets_no_node_call() -> None:
    gui = _Gui()
    # Префикс листа длиной в 4 сегмента этот шаблон матчит, сам лист - нет.
    sub = _subscribe(gui, "devices.state.**.status")

    gui.put(f"{NODE}.a", 1)
    gui.end()

    assert sub.calls == []


def test_without_read_model_node_subscriber_gets_nothing() -> None:
    gui = _Gui(with_read_model=False)
    sub = _subscribe(gui, NODE)

    gui.put(f"{NODE}.a", 1)
    gui.end()

    assert sub.calls == []


# --------------------------------------------------------------------------- REDS 9


def test_leaf_two_levels_deep_gives_nested_node() -> None:
    gui = _Gui()
    sub = _subscribe(gui, NODE)

    gui.put(f"{NODE}.pose.x", 12.5)
    gui.end()

    assert sub.calls == [("devices.state.vfd1.status", {"pose": {"x": 12.5}})]


# --------------------------------------------------------------------------- REDS 10


def test_two_batches_from_io_thread_give_two_node_calls(qtbot) -> None:
    """Настоящая проводка GuiProcess -> мост -> bindings; маркер тест не шлёт."""
    from multiprocess_prototype.frontend.process import GuiProcess

    gui = _Gui()
    sub = _subscribe(gui, NODE)
    process_stand_in = SimpleNamespace(_bridge=gui.bridge)
    batches = [
        [_delta(f"{NODE}.a", 1), _delta(f"{NODE}.b", 1)],
        [_delta(f"{NODE}.a", 2), _delta(f"{NODE}.b", 2)],
    ]
    errors: list[BaseException] = []

    def io_thread() -> None:
        try:
            for batch in batches:
                GuiProcess._on_state_deltas_to_bridge(process_stand_in, batch)
        except BaseException as exc:  # noqa: BLE001 - переносим в главный поток
            errors.append(exc)

    worker = threading.Thread(target=io_thread, daemon=True)
    worker.start()
    worker.join(timeout=5.0)  # обе пачки в очереди Qt: события ещё не обрабатывались
    assert not worker.is_alive()
    assert errors == []
    assert sub.calls == []

    deadline = time.monotonic() + 3.0
    while len(sub.calls) < 2 and time.monotonic() < deadline:
        qtbot.wait(10)
    qtbot.wait(50)  # лишний третий вызов, если он есть, успевает прийти

    assert [path for path, _ in sub.calls] == ["devices.state.vfd1.status", "devices.state.vfd1.status"]
    first, second = sub.calls[0][1], sub.calls[1][1]
    assert set(first) == {"a", "b"}
    assert first["a"] in (1, 2) and first["b"] in (1, 2)
    assert second == {"a": 2, "b": 2}
