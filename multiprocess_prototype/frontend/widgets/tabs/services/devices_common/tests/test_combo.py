# -*- coding: utf-8 -*-
"""Тесты DeviceComboController — push-подписка и pull-fallback (pytest-qt)."""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.combo import (
    DeviceComboController,
)
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.presenter import (
    DevicesPresenter,
)


class ImmediateRunner:
    """RequestRunner-стаб: исполняет синхронно."""

    def submit(self, fn, on_result) -> None:
        on_result(fn())


def make_combo(qtbot, *, kind: str = "robot", with_bindings: bool = False):
    sender = MagicMock()
    runner = ImmediateRunner()
    presenter = DevicesPresenter(command_sender=sender, request_runner=runner)
    changes: list = []

    bindings = None
    if with_bindings:
        bindings = MagicMock()
        # bind_fanout: запомним callbacks для ручного вызова
        bindings._fanout_cbs = []

        def fake_fanout(pattern, cb, owner=None):
            bindings._fanout_cbs.append((pattern, cb))

        bindings.bind_fanout = fake_fanout

    combo = DeviceComboController(
        kind=kind,
        presenter=presenter,
        bindings=bindings,
        on_device_changed=changes.append,
    )
    qtbot.addWidget(combo.widget())
    return combo, sender, changes, bindings


def test_pull_refresh_populates_combo(qtbot) -> None:
    """refresh() через device_list заполняет комбо."""
    combo, sender, changes, _ = make_combo(qtbot)
    sender.request_command.return_value = {
        "devices": [{"id": "r1", "kind": "robot", "name": "Робот 1"}],
    }
    combo.refresh()
    assert combo._combo.count() == 1
    assert combo.current_device_id() == "r1"
    assert "Робот 1" in combo._combo.currentText()


def test_push_registry_delta_adds_device(qtbot) -> None:
    """bind_fanout на devices.registry.* добавляет устройство в комбо."""
    combo, _sender, changes, bindings = make_combo(qtbot, with_bindings=True)
    # Найти callback для registry
    registry_cb = None
    for pattern, cb in bindings._fanout_cbs:
        if "registry" in pattern:
            registry_cb = cb
            break
    assert registry_cb is not None

    # Симулировать push
    registry_cb("devices.registry.r1", {"id": "r1", "kind": "robot", "name": "Робот"})
    assert combo._combo.count() == 1
    assert combo.current_device_id() == "r1"


def test_push_filters_by_kind(qtbot) -> None:
    """Устройства другого kind не попадают в комбо."""
    combo, _sender, _changes, bindings = make_combo(qtbot, kind="robot", with_bindings=True)
    registry_cb = None
    for pattern, cb in bindings._fanout_cbs:
        if "registry" in pattern:
            registry_cb = cb
            break

    # VFD-устройство — не должно попасть
    registry_cb("devices.registry.v1", {"id": "v1", "kind": "vfd", "name": "ПЧ"})
    assert combo._combo.count() == 0

    # Робот — должен попасть
    registry_cb("devices.registry.r1", {"id": "r1", "kind": "robot", "name": "Робот"})
    assert combo._combo.count() == 1


def test_conn_delta_updates_label(qtbot) -> None:
    """Подписка на conn обновляет текст элемента комбо."""
    combo, _sender, _changes, bindings = make_combo(qtbot, with_bindings=True)
    registry_cb = conn_cb = None
    for pattern, cb in bindings._fanout_cbs:
        if "registry" in pattern:
            registry_cb = cb
        elif "conn" in pattern:
            conn_cb = cb

    # Добавить устройство
    registry_cb("devices.registry.r1", {"id": "r1", "kind": "robot", "name": "Робот"})
    # Обновить conn
    conn_cb("devices.state.r1.conn", {"conn": "connected"})
    assert "connected" in combo._combo.currentText()


def test_connect_button_calls_presenter(qtbot) -> None:
    """Кнопка Подключить вызывает device_connect."""
    combo, sender, _changes, _ = make_combo(qtbot)
    sender.request_command.return_value = {
        "devices": [{"id": "r1", "kind": "robot", "name": "Робот"}],
    }
    combo.refresh()
    sender.reset_mock()
    sender.request_command.return_value = {"status": "ok", "conn": "connecting"}

    combo._btn_connect.click()
    sender.request_command.assert_called_once()
    call_args = sender.request_command.call_args
    assert call_args[0][1] == "device_connect"
    assert call_args[0][2]["device_id"] == "r1"


def test_disconnect_button_calls_presenter(qtbot) -> None:
    """Кнопка Отключить вызывает device_disconnect."""
    combo, sender, _changes, _ = make_combo(qtbot)
    sender.request_command.return_value = {
        "devices": [{"id": "r1", "kind": "robot", "name": "Робот"}],
    }
    combo.refresh()
    sender.reset_mock()
    sender.request_command.return_value = {"status": "ok", "conn": "disconnecting"}

    combo._btn_disconnect.click()
    sender.request_command.assert_called_once()
    call_args = sender.request_command.call_args
    assert call_args[0][1] == "device_disconnect"


def test_remove_button_calls_presenter(qtbot) -> None:
    """Кнопка Удалить вызывает device_remove."""
    combo, sender, _changes, _ = make_combo(qtbot)
    sender.request_command.return_value = {
        "devices": [{"id": "r1", "kind": "robot", "name": "Робот"}],
    }
    combo.refresh()
    sender.reset_mock()
    sender.request_command.return_value = {"status": "ok"}

    combo._btn_remove.click()
    sender.request_command.assert_called_once()
    call_args = sender.request_command.call_args
    assert call_args[0][1] == "device_remove"


def test_on_device_changed_fires(qtbot) -> None:
    """Смена устройства в комбо вызывает callback on_device_changed."""
    combo, sender, changes, _ = make_combo(qtbot)
    sender.request_command.return_value = {
        "devices": [
            {"id": "r1", "kind": "robot", "name": "Робот 1"},
            {"id": "r2", "kind": "robot", "name": "Робот 2"},
        ],
    }
    combo.refresh()
    # Выбрать второй
    combo._combo.setCurrentIndex(1)
    assert combo.current_device_id() == "r2"
    # callback вызван хотя бы раз с "r2"
    assert "r2" in changes
