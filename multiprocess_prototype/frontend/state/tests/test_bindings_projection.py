"""RED-тесты П3 (Task 2.8a2): replay копии-листьев через ``project_leaves``.

Настоящие ``TelemetryReadModel`` (копия наполняется ``ingest`` листьев) и
``GuiStateBindings``; bridge — объект с ``set_state_callback`` (MagicMock).
Ожидаемые значения — литералы.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QLabel

from multiprocess_framework.modules.telemetry_readmodel_module.telemetry_read_model import (
    TelemetryReadModel,
)
from multiprocess_prototype.frontend.state.bindings import GuiStateBindings


def _model(leaves: list[tuple[str, object]]) -> TelemetryReadModel:
    """Read-model, наполненный листьями через ingest (порядок = порядок списка)."""
    model = TelemetryReadModel()
    for path, value in leaves:
        model.ingest(path, value)
    return model


def _bindings(model: TelemetryReadModel) -> GuiStateBindings:
    return GuiStateBindings(MagicMock(), read_model=model)


_REGISTRY = [
    ("devices.registry.vfd1.id", "vfd1"),
    ("devices.registry.vfd1.name", "ПЧ-1"),
    ("devices.registry.r1.id", "r1"),
]


@pytest.mark.timeout(10)
def test_second_node_binding_gets_node():
    """Привязка на узел status приходит одним вызовом с dict-ом из листьев."""
    model = _model(
        [
            ("devices.state.vfd1.status.running", True),
            ("devices.state.vfd1.status.heartbeat", 9),
        ]
    )
    calls: list[tuple[str, object]] = []
    _bindings(model).bind_fanout("devices.state.vfd1.status", lambda p, v: calls.append((p, v)))
    assert calls == [("devices.state.vfd1.status", {"running": True, "heartbeat": 9})]


@pytest.mark.timeout(10)
def test_registry_star_gives_records():
    """`devices.registry.*`: каждая запись приходит dict-ом, в порядке вставки."""
    calls: list[tuple[str, object]] = []
    _bindings(_model(_REGISTRY)).bind_fanout("devices.registry.*", lambda p, v: calls.append((p, v)))
    assert calls == [
        ("devices.registry.vfd1", {"id": "vfd1", "name": "ПЧ-1"}),
        ("devices.registry.r1", {"id": "r1"}),
    ]


@pytest.mark.timeout(10)
def test_bind_widget_on_conn_node(qtbot):
    """bind на узел conn: formatter получает dict из двух листьев."""
    model = _model(
        [
            ("devices.state.vfd1.conn.conn", "connected"),
            ("devices.state.vfd1.conn.ts", 7),
        ]
    )
    label = QLabel()
    qtbot.addWidget(label)
    _bindings(model).bind(
        "devices.state.vfd1.conn",
        label,
        "text",
        formatter=lambda v: repr(sorted(v)),
    )
    assert label.text() == "['conn', 'ts']"


@pytest.mark.timeout(10)
def test_registry_doublestar_unchanged():
    """Контроль: `devices.registry.**` по-прежнему три вызова листьями в порядке вставки."""
    calls: list[tuple[str, object]] = []
    _bindings(_model(_REGISTRY)).bind_fanout("devices.registry.**", lambda p, v: calls.append((p, v)))
    assert calls == [
        ("devices.registry.vfd1.id", "vfd1"),
        ("devices.registry.vfd1.name", "ПЧ-1"),
        ("devices.registry.r1.id", "r1"),
    ]
