"""Task 6.3 (тесты автора): monitor на РЕАЛЬНОМ TelemetryViewModel и жизненный цикл секции.

Дополняет блок «Task 6.3» в test_dashboard.py (там read-model — фейк):
  * replay атомарного dict ``{"conn": ...}`` на точном пути через настоящие
    ``TelemetryViewModel`` (листья ``LeafCopy``) + ``project_leaves`` (ADR-SS-024 A3);
  * ``on_deactivated`` / ``on_activated``: привязки monitor-подписей снимаются и
    возвращаются, значение приходит заново.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtWidgets import QLabel

from multiprocess_framework.modules.frontend_module.state.telemetry_view_model import TelemetryViewModel
from multiprocess_prototype.frontend.state.bindings import GuiStateBindings
from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.section import (
    build_control_panel_section,
)

_CTL_PATH = "processes.ctl.state.control_panel.controls"
_CONN = "devices.state.robot_main.conn"
_PARK = "devices.state.robot_main.park.state"


def _monitor(cid: str, path: str, key: str, label: str) -> dict:
    return {
        "id": cid,
        "type": "text",
        "label": label,
        "source": "monitor",
        "target_process": "devices",
        "state_path": path,
        "value_key": key,
    }


class _Rig:
    """Настоящие секция + GuiStateBindings + TelemetryViewModel (как в app.py: VM — read_model)."""

    def __init__(self, qtbot) -> None:
        self.qtbot = qtbot
        self.vm = TelemetryViewModel()
        self.bindings = GuiStateBindings(MagicMock(), read_model=self.vm)
        runtime = SimpleNamespace(bindings=self.bindings, topology_bridge=None)
        services = SimpleNamespace(commands=MagicMock(), topology=None)
        self.section = build_control_panel_section(services, runtime).factory(None)

    def publish(self, path: str, value) -> None:
        msg = {"data_type": "state_delta", "path": path, "value": value}
        self.bindings._on_state_msg(msg)  # слот bindings (первый потребитель, §11.15)
        self.vm.on_state_delta(msg)  # VM — второй потребитель, пишет read-model

    def open(self):
        widget = self.section.widget()
        self.qtbot.addWidget(widget)
        return widget

    def settle(self) -> None:
        self.qtbot.wait(30)

    def texts(self, widget) -> list[str]:
        return [lbl.text() for lbl in widget.findChildren(QLabel)]


def test_real_read_model_replays_atomic_dict_whole_under_exact_path(qtbot) -> None:
    # Дельты прошли ДО открытия вкладки: replay идёт из настоящего read-model (листья LeafCopy).
    rig = _Rig(qtbot)
    rig.publish(_CTL_PATH, [_monitor("conn", _CONN, "conn", "Связь")])
    rig.publish(_CONN, {"conn": "connected", "ts": 7})
    # read-model хранит ЛИСТЬЯ, а не dict целиком — это и проверяет тест ниже через replay.
    assert rig.vm.snapshot(_CONN) == {f"{_CONN}.conn": "connected", f"{_CONN}.ts": 7}

    widget = rig.open()
    qtbot.waitUntil(lambda: "connected" in rig.texts(widget), timeout=2000)
    assert "7" not in rig.texts(widget)  # показан value["conn"], а не весь dict


def test_real_read_model_replays_leaf_without_value_key(qtbot) -> None:
    rig = _Rig(qtbot)
    rig.publish(_CTL_PATH, [_monitor("park", _PARK, "", "Парковка")])
    rig.publish(_PARK, "parked")
    widget = rig.open()
    qtbot.waitUntil(lambda: "parked" in rig.texts(widget), timeout=2000)


def test_real_read_model_replay_follows_latest_dict_not_stale_keys(qtbot) -> None:
    # Новая dict-дельта заменяет поддерево: старый ключ не должен «протечь» в replay.
    rig = _Rig(qtbot)
    rig.publish(_CTL_PATH, [_monitor("conn", _CONN, "conn", "Связь")])
    rig.publish(_CONN, {"conn": "connected", "ts": 7})
    rig.publish(_CONN, {"conn": "ready"})
    widget = rig.open()
    qtbot.waitUntil(lambda: "ready" in rig.texts(widget), timeout=2000)
    assert "connected" not in rig.texts(widget)


def test_monitor_survives_deactivate_activate_and_gets_value_again(qtbot) -> None:
    rig = _Rig(qtbot)
    rig.publish(_CTL_PATH, [_monitor("conn", _CONN, "conn", "Связь")])
    widget = rig.open()
    rig.publish(_CONN, {"conn": "connected", "ts": 1})
    qtbot.waitUntil(lambda: "connected" in rig.texts(widget), timeout=2000)
    assert sum(1 for h in rig.bindings._bindings if h.pattern == _CONN) == 1

    rig.section.on_deactivated()
    assert [h for h in rig.bindings._bindings if h.pattern in (_CONN, _CTL_PATH)] == []  # всё снято
    rig.publish(_CONN, {"conn": "lost", "ts": 2})  # пока вкладка скрыта — подпись не трогается
    rig.settle()
    assert "lost" not in rig.texts(widget)

    rig.section.on_activated()  # вернулись: набор и monitor привязаны заново, replay отдаёт последнее
    qtbot.waitUntil(lambda: "lost" in rig.texts(widget), timeout=2000)
    assert sum(1 for h in rig.bindings._bindings if h.pattern == _CONN) == 1  # ровно один handle
    rig.publish(_CONN, {"conn": "connected", "ts": 3})
    qtbot.waitUntil(lambda: "connected" in rig.texts(widget), timeout=2000)


def test_deactivate_before_deferred_rebind_leaves_no_handles(qtbot) -> None:
    # set_controls запланировал пересвязку, а вкладку скрыли до её срабатывания.
    rig = _Rig(qtbot)
    widget = rig.open()
    rig.publish(_CTL_PATH, [_monitor("conn", _CONN, "conn", "Связь")])
    rig.section.on_deactivated()  # singleShot(0) ещё не отработал
    rig.settle()
    assert [h for h in rig.bindings._bindings if h.pattern == _CONN] == []
    assert widget is not None
