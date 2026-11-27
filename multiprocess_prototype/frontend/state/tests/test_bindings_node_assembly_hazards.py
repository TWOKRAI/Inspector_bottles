"""Тесты опасных мест Task 2.8f (пишет автор реализации).

Реентерабельность flush (bind/unbind из callback, callback крутит цикл Qt), уничтоженный
владелец, пустая пачка, ``gui_local_metric``, порядок снятия пары при точном пути.
Объекты настоящие: ``DataReceiverBridge``, ``GuiStateBindings``, ``TelemetryViewModel``.
Из главного потока ``bridge.dispatch`` доставляет синхронно.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest
import shiboken6
from PySide6.QtWidgets import QApplication, QWidget

from multiprocess_framework.modules.frontend_module import TelemetryViewModel
from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from multiprocess_prototype.frontend.bridge_impl import DataReceiverBridge
from multiprocess_prototype.frontend.process import GuiProcess
from multiprocess_prototype.frontend.state.bindings import DELETED, GuiStateBindings
from multiprocess_prototype.frontend.state.delta_message import (
    state_batch_end_message,
    state_delta_message,
)

pytestmark = pytest.mark.usefixtures("qapp")

NODE = "devices.state.vfd1.status"
OTHER_NODE = "devices.state.vfd2.status"


def _delta(path: str, value: Any) -> Delta:
    return Delta(path=path, old_value=MISSING, new_value=value, source="test")


class _Gui:
    def __init__(self) -> None:
        self.released: list[str] = []
        self.bridge = DataReceiverBridge()
        self.vm = TelemetryViewModel()
        self.bindings = GuiStateBindings(self.bridge, read_model=self.vm, release_subscription=self.released.append)
        self.bridge.add_state_listener(self.vm.on_state_delta)

    def put(self, path: str, value: Any) -> None:
        self.bridge.dispatch(state_delta_message(_delta(path, value)))

    def end(self) -> None:
        self.bridge.dispatch(state_batch_end_message())


def _collect(calls: list[tuple[str, Any]]):
    return lambda path, value: calls.append((path, value))


def test_bind_from_callback_during_flush_gets_only_replay() -> None:
    """Подписка, созданная из callback, получает replay и не получает вызов от текущего маркера."""
    gui = _Gui()
    late: list[tuple[str, Any]] = []

    def binding_callback(path: str, value: Any) -> None:
        if not late:
            gui.bindings.bind_fanout(NODE, _collect(late))

    gui.bindings.bind_fanout(NODE, binding_callback)
    gui.put(f"{NODE}.a", 1)
    gui.end()

    assert late == [("devices.state.vfd1.status", {"a": 1})]


def test_rebind_self_from_callback_during_flush() -> None:
    """Callback снимает себя и подписывается на другой узел: старый узел больше не приходит."""
    gui = _Gui()
    old_calls: list[str] = []
    new_calls: list[tuple[str, Any]] = []
    handles: list[Any] = []

    def switching(path: str, value: Any) -> None:
        old_calls.append(path)
        gui.bindings.unbind_fanout(handles[0])
        gui.bindings.bind_fanout(OTHER_NODE, _collect(new_calls))

    handles.append(gui.bindings.bind_fanout("devices.state.*.status", switching))
    gui.put(f"{NODE}.a", 1)
    gui.put(f"{OTHER_NODE}.b", 2)
    gui.end()
    gui.put(f"{NODE}.a", 3)
    gui.end()

    assert old_calls == ["devices.state.vfd1.status"]
    # Один вызов — replay при привязке: read-model к этому моменту уже знает vfd2.
    assert new_calls == [("devices.state.vfd2.status", {"b": 2})]


def test_callback_spinning_event_loop_loses_nothing(qtbot) -> None:
    """Callback крутит цикл Qt: следующая пачка доставляется вложенно, потерь и падений нет."""
    gui = _Gui()
    seen: list[tuple[str, Any]] = []
    spun: list[bool] = []

    def spinning(path: str, value: Any) -> None:
        seen.append((path, value))
        if spun:
            return
        spun.append(True)
        deltas = [_delta(f"{NODE}.a", 2), _delta(f"{OTHER_NODE}.a", 20)]
        worker = threading.Thread(
            target=GuiProcess._on_state_deltas_to_bridge,
            args=(SimpleNamespace(_bridge=gui.bridge), deltas),
            daemon=True,
        )
        worker.start()
        worker.join(timeout=5.0)
        assert not worker.is_alive()
        QApplication.processEvents()

    gui.bindings.bind_fanout("devices.state.*.status", spinning)
    gui.put(f"{NODE}.a", 1)
    gui.put(f"{OTHER_NODE}.a", 10)
    gui.end()

    # Вложенный flush отдал обе новые версии; внешний цикл потом отдаёт свой остаток (vfd2)
    # уже свежим значением: повтор допустим, устаревшее значение — нет.
    assert seen == [
        ("devices.state.vfd1.status", {"a": 1}),
        ("devices.state.vfd1.status", {"a": 2}),
        ("devices.state.vfd2.status", {"a": 20}),
        ("devices.state.vfd2.status", {"a": 20}),
    ]


def test_owner_destroyed_between_delta_and_marker() -> None:
    gui = _Gui()
    calls: list[tuple[str, Any]] = []
    owner = QWidget()
    gui.bindings.bind_fanout(NODE, _collect(calls), owner=owner)

    gui.put(f"{NODE}.a", 1)
    shiboken6.delete(owner)
    gui.end()

    assert calls == []
    assert gui.released == [NODE]


def test_empty_batch_sends_no_marker() -> None:
    sent: list[dict] = []
    stand_in = SimpleNamespace(_bridge=SimpleNamespace(dispatch=sent.append))

    GuiProcess._on_state_deltas_to_bridge(stand_in, [])

    assert sent == []


def test_batch_sends_exactly_one_marker_last() -> None:
    sent: list[dict] = []
    stand_in = SimpleNamespace(_bridge=SimpleNamespace(dispatch=sent.append))

    GuiProcess._on_state_deltas_to_bridge(stand_in, [_delta("a.b", 1), _delta("a.c", 2)])

    assert [m["data_type"] for m in sent] == ["state_delta", "state_delta", "state_batch_end"]


def test_marker_goes_to_state_consumers_not_command() -> None:
    gui = _Gui()
    state: list[dict] = []
    command: list[dict] = []
    gui.bridge.add_state_listener(state.append)
    gui.bridge.set_command_callback(command.append)

    gui.end()

    assert state == [{"data_type": "state_batch_end"}]
    assert command == []


def test_gui_local_metric_does_not_mark_nodes() -> None:
    """За GUI-локальной метрикой маркера нет: она не копит вызов до чужой пачки."""
    gui = _Gui()
    calls: list[tuple[str, Any]] = []
    gui.bindings.bind_fanout("system.*", _collect(calls))

    gui.bridge.dispatch({"data_type": "gui_local_metric", "path": "system.trace.depth", "value": 3})
    gui.end()

    assert calls == []


def test_gui_local_metric_between_delta_and_marker_keeps_pending_node() -> None:
    gui = _Gui()
    calls: list[tuple[str, Any]] = []
    gui.bindings.bind_fanout(NODE, _collect(calls))

    gui.put(f"{NODE}.a", 1)
    gui.bridge.dispatch({"data_type": "gui_local_metric", "path": "system.chain_fps", "value": 30.0})
    gui.end()

    assert calls == [("devices.state.vfd1.status", {"a": 1})]


def test_leaf_fed_from_exact_set_callback_marks_node_again() -> None:
    """Пара снимается ДО callback точного пути, иначе дельта из него потерялась бы."""
    gui = _Gui()
    calls: list[tuple[str, Any]] = []

    def feeding(path: str, value: Any) -> None:
        calls.append((path, value))
        if len(calls) == 1:
            gui.put(f"{NODE}.a", 1)

    gui.bindings.bind_fanout(NODE, feeding)
    gui.put(NODE, {"b": 2})
    gui.end()

    # Значение второго вызова — {"b": 2}: дельта подана СИНХРОННО изнутри обработки set, поэтому
    # read-model получает её раньше внешнего set, и тот заменяет поддерево. Проверяется сам вызов.
    assert calls == [
        ("devices.state.vfd1.status", {"b": 2}),
        ("devices.state.vfd1.status", {"b": 2}),
    ]


def test_repeated_leaves_keep_first_mark_order() -> None:
    gui = _Gui()
    order: list[str] = []
    gui.bindings.bind_fanout("devices.state.*.status", lambda path, _value: order.append(path))

    gui.put(f"{NODE}.a", 1)
    gui.put(f"{OTHER_NODE}.a", 1)
    gui.put(f"{NODE}.a", 2)
    gui.end()

    assert order == ["devices.state.vfd1.status", "devices.state.vfd2.status"]


def test_failing_node_read_does_not_drop_neighbour() -> None:
    gui = _Gui()
    calls: list[tuple[str, Any]] = []
    real_get_node = gui.vm.get_node

    def flaky(path: str, default: Any = None) -> Any:
        if path == NODE:
            raise ValueError("boom")
        return real_get_node(path, default)

    gui.vm.get_node = flaky  # type: ignore[method-assign]
    gui.bindings.bind_fanout("devices.state.*.status", _collect(calls))
    gui.put(f"{NODE}.a", 1)
    gui.put(f"{OTHER_NODE}.a", 2)
    gui.end()

    assert calls == [("devices.state.vfd2.status", {"a": 2})]


def test_ancestor_delete_after_leaf_gives_deleted_on_marker() -> None:
    gui = _Gui()
    calls: list[tuple[str, Any]] = []
    gui.bindings.bind_fanout(NODE, _collect(calls))

    gui.put(f"{NODE}.a", 1)
    gui.bridge.dispatch(
        state_delta_message(Delta(path="devices.state.vfd1", old_value=0, new_value=MISSING, source="test"))
    )
    gui.end()

    assert calls == [("devices.state.vfd1.status", DELETED)]


def test_vfd_device_switch_releases_fanout_subscription(qtbot) -> None:
    """П.8: хэндл fanout снят через unbind_fanout, подписка в proxy отпущена, дублей нет."""
    from unittest.mock import MagicMock

    from multiprocess_prototype.frontend.widgets.tabs.services.vfd.controller import (
        VfdWidgetController,
    )
    from multiprocess_prototype.frontend.widgets.tabs.services.vfd.widget import (
        VfdControlWidget,
    )

    gui = _Gui()
    widget = VfdControlWidget()
    qtbot.addWidget(widget)
    controller = VfdWidgetController(widget, MagicMock(), bindings=gui.bindings)

    controller.set_device("old")
    controller.set_device("new")
    assert gui.released.count("devices.state.old.status") == 1

    controller.unbind()
    assert gui.released.count("devices.state.new.status") == 1
    assert gui.bindings._fanouts == []
