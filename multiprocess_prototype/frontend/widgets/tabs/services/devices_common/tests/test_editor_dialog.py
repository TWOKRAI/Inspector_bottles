# -*- coding: utf-8 -*-
"""Тесты DeviceEditorDialog — сборка entry dict (pytest-qt)."""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.editor_dialog import (
    DeviceEditorDialog,
)


def test_create_mode_tcp_entry(qtbot) -> None:
    """Диалог в режиме создания: TCP-транспорт, entry содержит все поля."""
    dlg = DeviceEditorDialog(
        kind="robot",
        protocols=["delta_universal3"],
    )
    qtbot.addWidget(dlg)

    dlg._edit_id.setText("robot_main")
    dlg._edit_name.setText("Робот Delta")
    dlg._combo_protocol.setCurrentText("delta_universal3")
    dlg._combo_transport.setCurrentIndex(0)  # tcp
    dlg._tcp_host.setText("192.168.1.7")
    dlg._tcp_port.setValue(502)
    dlg._tcp_unit.setValue(2)

    entry = dlg.get_entry()
    assert entry["id"] == "robot_main"
    assert entry["name"] == "Робот Delta"
    assert entry["kind"] == "robot"
    assert entry["protocol"] == "delta_universal3"
    assert entry["transport"]["type"] == "tcp"
    assert entry["transport"]["host"] == "192.168.1.7"
    assert entry["transport"]["port"] == 502
    assert entry["transport"]["unit_id"] == 2


def test_create_mode_bridge_entry(qtbot) -> None:
    """Диалог в режиме создания: bridge-транспорт через робота-носителя."""
    dlg = DeviceEditorDialog(
        kind="vfd",
        protocols=["gd20_bridge"],
        robot_devices=[{"id": "robot_main", "name": "Робот Delta"}],
    )
    qtbot.addWidget(dlg)

    dlg._edit_id.setText("vfd_belt")
    dlg._edit_name.setText("ПЧ лента")
    dlg._combo_transport.setCurrentIndex(1)  # bridge

    entry = dlg.get_entry()
    assert entry["transport"]["type"] == "bridge"
    assert entry["transport"]["bridge"] == "robot_main"


def test_edit_mode_id_disabled(qtbot) -> None:
    """Режим редактирования: поле ID заблокировано."""
    existing = {
        "id": "robot_main",
        "name": "Робот Delta",
        "kind": "robot",
        "protocol": "delta_universal3",
        "transport": {"type": "tcp", "host": "10.0.0.1", "port": 502, "unit_id": 1},
        "params": {"speed": 100},
    }
    dlg = DeviceEditorDialog(kind="robot", existing=existing)
    qtbot.addWidget(dlg)

    assert not dlg._edit_id.isEnabled()
    assert dlg._edit_id.text() == "robot_main"
    assert dlg._tcp_host.text() == "10.0.0.1"

    entry = dlg.get_entry()
    assert entry["id"] == "robot_main"
    assert entry["transport"]["host"] == "10.0.0.1"


def test_rtu_page_fields_disabled(qtbot) -> None:
    """RTU-страница: поля disabled (заглушка)."""
    dlg = DeviceEditorDialog(kind="vfd")
    qtbot.addWidget(dlg)

    dlg._combo_transport.setCurrentIndex(2)  # rtu
    assert not dlg._rtu_serial.isEnabled()
    assert not dlg._rtu_baud.isEnabled()

    entry = dlg.get_entry()
    assert entry["transport"]["type"] == "rtu"


def test_params_json_parsing(qtbot) -> None:
    """Парс JSON из текстового поля params."""
    dlg = DeviceEditorDialog(kind="robot")
    qtbot.addWidget(dlg)

    dlg._params_edit.setPlainText('{"speed": 100, "home_x": 0.0}')
    entry = dlg.get_entry()
    assert entry["params"]["speed"] == 100
    assert entry["params"]["home_x"] == 0.0


def test_params_empty_returns_empty_dict(qtbot) -> None:
    """Пустое поле params -> пустой dict."""
    dlg = DeviceEditorDialog(kind="vfd")
    qtbot.addWidget(dlg)

    entry = dlg.get_entry()
    assert entry["params"] == {}


def test_combo_shows_protocols(qtbot) -> None:
    """Комбо протоколов заполняется из переданного списка."""
    dlg = DeviceEditorDialog(
        kind="vfd",
        protocols=["gd20_bridge", "gd20_direct"],
    )
    qtbot.addWidget(dlg)

    assert dlg._combo_protocol.count() == 2
    assert dlg._combo_protocol.itemText(0) == "gd20_bridge"
    assert dlg._combo_protocol.itemText(1) == "gd20_direct"
