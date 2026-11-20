"""Task 6.3 (тесты автора): опасные места пересвязки monitor-подписей.

  * М4 — пересборка набора происходит ИЗ цикла дельт ``GuiStateBindings._on_state_msg``:
    одно state-сообщение несёт и новый набор контролов, и значение, которое показывают
    новые monitor-подписи; соседний monitor на ДРУГОМ пути (шаблоне) тоже получает значение;
  * М9 — набор с monitor сменился ПУСТЫМ набором: привязок на пути не остаётся сразу
    (не «когда-нибудь по destroyed»), а старая подпись больше не обновляется дельтой.

Read-model — настоящий TelemetryViewModel; порядок потребителей как в app.py:
сначала bindings, затем VM (§11.15).
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QLabel, QPushButton
import shiboken6
from shiboken6 import isValid

from multiprocess_prototype.domain.commands import SetPluginConfig
from multiprocess_framework.modules.frontend_module.state.telemetry_view_model import TelemetryViewModel
from multiprocess_prototype.frontend.state.bindings import GuiStateBindings
from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.section import (
    build_control_panel_section,
)

_CTL = "processes.ctl.state.control_panel.controls"
_CONN = "devices.state.robot_main.conn"


def _monitor(cid: str, path: str, key: str = "", label: str = "") -> dict:
    return {
        "id": cid,
        "type": "text",
        "label": label or cid,
        "source": "monitor",
        "target_process": "devices",
        "state_path": path,
        "value_key": key,
    }


class _Rig:
    def __init__(self, qtbot, *, add_widget: bool = True) -> None:
        self.qtbot = qtbot
        self.vm = TelemetryViewModel()
        self.bindings = GuiStateBindings(MagicMock(), read_model=self.vm)
        self.bridge = MagicMock()
        self.services = SimpleNamespace(commands=MagicMock(), topology=None)
        runtime = SimpleNamespace(bindings=self.bindings, topology_bridge=self.bridge)
        self.section = build_control_panel_section(self.services, runtime).factory(None)
        self.widget = self.section.widget()
        if add_widget:  # тесты, сами уничтожающие виджет, не отдают его pytest-qt
            qtbot.addWidget(self.widget)

    def publish(self, path: str, value) -> None:
        msg = {"data_type": "state_delta", "path": path, "value": value}
        self.bindings._on_state_msg(msg)  # первый потребитель
        self.vm.on_state_delta(msg)  # второй потребитель (read-model)

    def texts(self) -> list[str]:
        return [lbl.text() for lbl in self.widget.findChildren(QLabel)]

    def handles_on(self, pattern: str) -> int:
        return sum(1 for h in self.bindings._bindings if h.pattern == pattern)


def test_one_message_with_new_set_and_monitor_value_updates_both_monitors(qtbot) -> None:
    # Монитор-подписи смотрят на ТОТ ЖЕ путь, что и набор: одна дельта = и новый набор, и значение.
    # Две подписи с РАЗНЫМИ шаблонами (литерал и glob) — соседние handle одной пересвязки.
    rig = _Rig(qtbot)
    glob_path = "processes.*.state.control_panel.controls"
    old_set = [_monitor("old_a", _CTL, label="OA"), _monitor("old_b", glob_path, label="OB")]
    rig.publish(_CTL, old_set)
    qtbot.waitUntil(lambda: rig.handles_on(_CTL) == 1, timeout=2000)  # monitor «литерал»
    assert rig.handles_on(glob_path) == 2  # набор (его шаблон = glob) + monitor «glob»

    new_set = [_monitor("a", _CTL, label="NA"), _monitor("b", glob_path, label="NB")]
    rig.publish(_CTL, new_set)  # ОДНО сообщение: внутри цикла дельт пересобирается набор
    expected = "[{'id': 'a', 'type': 'text', 'label': 'NA', 'source': 'monitor', 'target_process': 'devices', 'state_path': 'processes.ctl.state.control_panel.controls', 'value_key': ''}, {'id': 'b', 'type': 'text', 'label': 'NB', 'source': 'monitor', 'target_process': 'devices', 'state_path': 'processes.*.state.control_panel.controls', 'value_key': ''}]"  # noqa: E501
    qtbot.waitUntil(lambda: rig.texts().count(expected) == 2, timeout=2000)  # обе новые подписи
    assert rig.handles_on(_CTL) == 1  # ровно один handle на литерале: старый снят, новый один
    assert rig.handles_on(glob_path) == 2  # набор + новый monitor «glob» (старый снят)


def test_empty_set_after_monitor_set_drops_handles_and_stops_updates(qtbot) -> None:
    rig = _Rig(qtbot)
    rig.publish(_CTL, [_monitor("conn", _CONN, key="conn", label="Связь")])
    rig.publish(_CONN, {"conn": "connected", "ts": 7})
    qtbot.waitUntil(lambda: "connected" in rig.texts(), timeout=2000)
    old_label = next(lbl for lbl in rig.widget.findChildren(QLabel) if lbl.text() == "connected")
    assert rig.handles_on(_CONN) == 1

    rig.publish(_CTL, [])  # пустой набор
    qtbot.wait(30)  # отложенная пересвязка отработала; очередь deleteLater НЕ принудительно
    assert rig.handles_on(_CONN) == 0
    rig.publish(_CONN, {"conn": "STALE", "ts": 99})
    qtbot.wait(30)
    assert not isValid(old_label) or old_label.text() == "connected"  # старая подпись дельтой не тронута
    assert "STALE" not in rig.texts()


def test_empty_set_drops_handles_of_label_that_outlives_its_row(qtbot) -> None:
    # Привязки снимает пересвязка секции, а не только авто-уборка по destroyed: подпись,
    # пережившая удаление ряда (переехала к другому родителю), после пустого набора не обновляется.
    rig = _Rig(qtbot)
    rig.publish(_CTL, [_monitor("conn", _CONN, key="conn", label="Связь")])
    rig.publish(_CONN, {"conn": "connected", "ts": 7})
    qtbot.waitUntil(lambda: "connected" in rig.texts(), timeout=2000)
    old_label = next(lbl for lbl in rig.widget.findChildren(QLabel) if lbl.text() == "connected")
    old_label.setParent(rig.widget)  # ряд удалят, подпись останется жить
    old_label.hide()

    rig.publish(_CTL, [])
    qtbot.wait(30)
    assert rig.handles_on(_CONN) == 0
    rig.publish(_CONN, {"conn": "STALE", "ts": 99})
    qtbot.wait(30)
    assert old_label.text() == "connected"


def test_type_monitor_without_source_is_read_only_label(qtbot) -> None:
    # F1: ``type: monitor`` БЕЗ source (дефолт local) — тоже подпись, а не кнопка с эмитом в pipeline.
    rig = _Rig(qtbot)
    spec = {"id": "conn", "type": "monitor", "label": "Связь", "state_path": _CONN, "value_key": "conn"}
    rig.publish(_CTL, [spec])
    qtbot.waitUntil(lambda: rig.handles_on(_CONN) == 1, timeout=2000)
    rig.publish(_CONN, {"conn": "connected", "ts": 7})
    qtbot.waitUntil(lambda: "connected" in rig.texts(), timeout=2000)

    assert [b.text() for b in rig.widget.findChildren(QPushButton) if b.text() == "Связь"] == []
    rig.widget.control_operated.emit("conn", True)  # даже прямой эмит ничего не шлёт
    qtbot.wait(30)
    assert rig.bridge.mock_calls == []
    assert rig.services.commands.dispatch.call_count == 0
    assert not [c for c in rig.services.commands.dispatch.call_args_list if isinstance(c.args[0], SetPluginConfig)]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "\u2014"),  # «—»: значения нет
        ({"ts": 7}, "?"),  # dict без value_key
        ({}, "?"),
        ({"conn": None}, "\u2014"),  # None после извлечения
        ({"conn": "ok"}, "ok"),
        ("idle", "idle"),
    ],
)
def test_monitor_formatter_literals(qtbot, value, expected: str) -> None:
    rig = _Rig(qtbot)
    rig.publish(_CTL, [_monitor("conn", _CONN, key="conn", label="Связь")])
    qtbot.waitUntil(lambda: rig.handles_on(_CONN) == 1, timeout=2000)
    rig.publish(_CONN, "first")  # не «—», чтобы None/{...} реально поменяли текст
    qtbot.waitUntil(lambda: "first" in rig.texts(), timeout=2000)
    rig.publish(_CONN, value)
    qtbot.waitUntil(lambda: "first" not in rig.texts(), timeout=2000)
    labels = [lbl for lbl in rig.widget.findChildren(QLabel) if lbl.toolTip() == ""]
    assert expected in [lbl.text() for lbl in labels]


def test_monitor_without_state_path_shows_dash_and_tooltip(qtbot) -> None:
    rig = _Rig(qtbot)
    rig.publish(_CTL, [_monitor("old", "", label="Старый")])
    qtbot.waitUntil(
        lambda: any(lbl.toolTip() == "нет state_path" for lbl in rig.widget.findChildren(QLabel)), timeout=2000
    )
    tipped = [lbl for lbl in rig.widget.findChildren(QLabel) if lbl.toolTip() == "нет state_path"]
    assert [lbl.text() for lbl in tipped] == ["\u2014"]


def _destroy_by_deferred_delete(widget) -> None:
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _destroy_by_shiboken(widget) -> None:
    shiboken6.delete(widget)


@pytest.mark.parametrize("destroy", [_destroy_by_deferred_delete, _destroy_by_shiboken])
def test_widget_destroyed_before_deferred_rebind_is_harmless(qtbot, destroy) -> None:
    # F2: set_controls запланировал пересвязку, окно закрыли до срабатывания таймера.
    rig = _Rig(qtbot, add_widget=False)
    rig.publish(_CTL, [_monitor("conn", _CONN, key="conn", label="Связь")])  # singleShot(0) в очереди
    destroy(rig.widget)
    assert not isValid(rig.widget)
    qtbot.wait(30)  # исключение в слоте таймера pytest-qt превратил бы в падение теста
    assert rig.handles_on(_CONN) == 0
    assert rig.section._monitor_handles == []
