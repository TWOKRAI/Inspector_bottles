"""Monitor-контрол только для чтения: set_control / emit_control отвечают ошибкой, без эмита и записи значения."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from Services.control_panel.controls import parse_controls

# Оба признака monitor: source == monitor (type любой) и type == monitor (source любой).
_MONITOR_SPECS = {
    "source_monitor": {"id": "m", "type": "text", "source": "monitor", "state_path": "a.b.c", "port": "out_1"},
    "type_monitor": {"id": "m", "type": "monitor", "port": "out_1"},
}
_READ_ONLY_ERROR = {"status": "error", "message": "контрол только для чтения (monitor)"}


def _make_plugin(controls):
    from Services.control_panel.plugin.plugin import ControlPanelPlugin

    p = ControlPanelPlugin()
    p._ctx = SimpleNamespace(process_name="pult", log_info=lambda *a: None)
    p._panel_id = "pult"
    p._controls = parse_controls(controls)
    assert len(p._controls) == 1, "parse_controls уронил monitor-контрол: тест был бы пустым"
    p._state_proxy = None
    p._pending = []
    p._lock = threading.Lock()
    return p


@pytest.mark.parametrize("kind", sorted(_MONITOR_SPECS))
def test_set_control_rejected_for_monitor(kind: str) -> None:
    p = _make_plugin([_MONITOR_SPECS[kind]])
    before = p._controls[0].value

    assert p.cmd_set_control({"id": "m", "value": "hack"}) == _READ_ONLY_ERROR

    assert p._controls[0].value == before  # значение не изменено
    assert p.produce() == []  # эмита не было


@pytest.mark.parametrize("kind", sorted(_MONITOR_SPECS))
def test_emit_control_rejected_for_monitor(kind: str) -> None:
    p = _make_plugin([_MONITOR_SPECS[kind]])

    assert p.cmd_emit_control({"id": "m"}) == _READ_ONLY_ERROR

    assert p.produce() == []


def test_operable_control_still_emits_next_to_monitor() -> None:
    """Регресс: рядом с monitor обычный контрол по-прежнему эмитит (проверка не глушит всё)."""
    p = _make_plugin([{"id": "x", "type": "number", "port": "out_1", "min": 0, "max": 100}])
    assert p.cmd_set_control({"id": "x", "value": 7})["status"] == "ok"
    assert len(p.produce()) == 1
