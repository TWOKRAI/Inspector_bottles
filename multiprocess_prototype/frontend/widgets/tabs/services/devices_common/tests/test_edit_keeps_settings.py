# -*- coding: utf-8 -*-
"""Кнопка «Изменить» устройства не теряет настройки; отказ hub виден (Task 2.12, раунд 2)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox

from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.add_page import (
    AddDevicePage,
)
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.crud_actions import (
    DeviceCrudActions,
)
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.device_form import (
    DeviceFormWidget,
)
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.editor_dialog import (
    DeviceEditorDialog,
)
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.presenter import (
    DevicesPresenter,
)


def _form(qtbot, kind: str, transport: dict, robot_devices: list[dict] | None = None) -> DeviceFormWidget:
    existing = {"id": "dev1", "name": "Устройство", "kind": kind, "transport": transport}
    form = DeviceFormWidget(kind=kind, existing=existing, robot_devices=robot_devices)
    qtbot.addWidget(form)
    return form


# --- R1: ключи, которых форма не показывает ---


def test_unchanged_type_keeps_hidden_keys_and_form_values_win(qtbot) -> None:
    form = _form(
        qtbot,
        "robot",
        {"type": "tcp", "host": "10.0.0.1", "port": 502, "unit_id": 2, "timeout_sec": 2.5, "retries": 3},
    )
    form._tcp_host.setText("10.0.0.9")

    assert form.get_entry()["transport"] == {
        "type": "tcp",
        "host": "10.0.0.9",
        "port": 502,
        "unit_id": 2,
        "timeout_sec": 2.5,
        "retries": 3,
    }


def test_changed_type_takes_only_new_type_fields(qtbot) -> None:
    form = _form(
        qtbot,
        "vfd",
        {"type": "tcp", "host": "10.0.0.1", "port": 502, "unit_id": 1, "timeout_sec": 2.5},
        robot_devices=[{"id": "rob", "name": "R"}],
    )
    form._combo_transport.setCurrentText("bridge")

    assert form.get_entry()["transport"] == {"type": "bridge", "bridge": "rob"}


# --- R2: умолчания и загрузка ---


@pytest.mark.parametrize(("kind", "unit_id"), [("robot", 2), ("generic_modbus", 1)])
def test_tcp_without_unit_id_gets_new_form_default(qtbot, kind: str, unit_id: int) -> None:
    form = _form(qtbot, kind, {"type": "tcp", "host": "10.0.0.1", "port": 502})

    assert form.get_entry()["transport"]["unit_id"] == unit_id


@pytest.mark.parametrize("baudrate", [19200, 230400])
def test_rtu_loads_own_serial_and_baudrate(qtbot, baudrate: int) -> None:
    form = _form(qtbot, "vfd", {"type": "rtu", "serial": "COM7", "baudrate": baudrate})

    assert form.get_entry()["transport"] == {"type": "rtu", "serial": "COM7", "baudrate": baudrate}


@pytest.mark.parametrize("robots", [[{"id": "rob", "name": "R"}], []], ids=["other-robot", "no-robots"])
def test_bridge_with_absent_carrier_is_not_replaced(qtbot, robots: list[dict]) -> None:
    form = _form(qtbot, "vfd", {"type": "bridge", "bridge": "ghost"}, robot_devices=robots)

    assert form.get_entry()["transport"] == {"type": "bridge", "bridge": "ghost"}


# --- Сквозной путь «Изменить» → OK: настоящие crud/presenter/диалог ---


class _ImmediateRunner:
    def submit(self, fn, on_result) -> None:
        on_result(fn())


class _Recipe:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    def has_active(self) -> bool:
        return True

    def active_slug(self) -> str:
        return "demo"

    def upsert(self, entry: dict) -> None:
        self.saved.append(entry)

    def remove(self, device_id: str) -> None:
        pass


def _envelope(result: Any, *, success: bool = True) -> dict:
    """Настоящий конверт роутера."""
    return {
        "type": "response",
        "command": "command.response",
        "sender": "devices",
        "targets": ["gui"],
        "queue_type": "system",
        "request_id": "r1",
        "success": success,
        "result": result,
    }


def _crud(replies: dict[str, dict], recipe: _Recipe) -> tuple[DeviceCrudActions, MagicMock]:
    sender = MagicMock()
    sender.request_command.side_effect = lambda target, cmd, args: replies.get(cmd, _envelope({"status": "ok"}))
    presenter = DevicesPresenter(command_sender=sender, request_runner=_ImmediateRunner())
    return DeviceCrudActions(kind="robot", presenter=presenter, recipe_store=recipe), sender


@pytest.fixture
def warnings(monkeypatch) -> list[str]:
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda parent, title, text: shown.append(text)))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(DeviceEditorDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    return shown


@pytest.fixture
def warnings_only(monkeypatch) -> list[str]:
    """Перехват предупреждений без подмены exec: диалог настоящий."""
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda parent, title, text: shown.append(text)))
    return shown


def test_edit_then_ok_saves_transport_unchanged(qtbot, warnings) -> None:
    transport = {"type": "tcp", "host": "10.0.0.5", "port": 502, "timeout_sec": 2.5}
    entry = {"id": "rob", "name": "R", "kind": "robot", "protocol": "p", "transport": transport, "params": {}}
    recipe = _Recipe()
    crud, _ = _crud({"device_describe": _envelope({"status": "ok", "entry": entry})}, recipe)

    crud.on_edit_clicked("rob")

    assert [d["transport"] for d in recipe.saved] == [
        {"type": "tcp", "host": "10.0.0.5", "port": 502, "unit_id": 2, "timeout_sec": 2.5}
    ]
    assert warnings == []


# --- R3: отказ hub виден ---

_PREFIX = "Рецепт обновлён, но процесс устройств вернул ошибку: "


def _run_remove(crud: DeviceCrudActions) -> None:
    crud.on_remove_clicked("rob")


def _run_add(crud: DeviceCrudActions) -> None:
    crud.on_add_clicked()


_ACTIONS = [
    pytest.param("device_remove", _run_remove, id="remove"),
    pytest.param("device_upsert", _run_add, id="upsert"),
]


@pytest.fixture
def add_entry(monkeypatch) -> None:
    monkeypatch.setattr(DeviceEditorDialog, "get_entry", lambda self: {"id": "rob", "kind": "robot"})


@pytest.mark.parametrize(("command", "run"), _ACTIONS)
def test_refusal_envelope_warns(qtbot, warnings, add_entry, command, run) -> None:
    crud, _ = _crud({command: _envelope(None, success=False)}, _Recipe())

    run(crud)

    assert len(warnings) == 1
    assert warnings[0].startswith(_PREFIX)


@pytest.mark.parametrize(("command", "run"), _ACTIONS)
def test_error_status_inside_envelope_warns_with_message(qtbot, warnings, add_entry, command, run) -> None:
    reply = _envelope({"status": "error", "message": "boom"}, success=False)
    crud, _ = _crud({command: reply}, _Recipe())

    run(crud)

    assert warnings == [_PREFIX + "boom"]


@pytest.mark.parametrize(("command", "run"), _ACTIONS)
def test_ok_envelope_does_not_warn(qtbot, warnings, add_entry, command, run) -> None:
    crud, sender = _crud({command: _envelope({"status": "ok"})}, _Recipe())

    run(crud)

    assert command in [c.args[1] for c in sender.request_command.call_args_list]
    assert warnings == []


@pytest.mark.parametrize(
    "info",
    [{"success": False, "result": None}, {"status": "error", "message": "boom"}, {}],
    ids=["refusal-envelope", "error-status", "empty"],
)
def test_describe_refusal_warns_and_opens_no_dialog(monkeypatch, info: dict) -> None:
    presenter = MagicMock()
    actions = DeviceCrudActions(kind="vfd", presenter=presenter, recipe_store=MagicMock(), refresh_cb=None)
    warnings: list[str] = []
    monkeypatch.setattr(actions, "_warn", warnings.append)

    actions._on_describe_for_edit("dev1", info)

    assert len(warnings) == 1
    presenter.device_protocols.assert_not_called()


# --- A: пустая строка в type — это отсутствующий тип ---


def test_empty_transport_type_keeps_own_values(qtbot) -> None:
    form = _form(qtbot, "generic_modbus", {"type": "", "host": "h", "port": 5, "x": 1})

    assert form.get_entry()["transport"] == {"type": "tcp", "host": "h", "port": 5, "unit_id": 1, "x": 1}


# --- B: нечитаемые params не сохраняются как {} ---

_PARAMS_ERROR = "Параметры не разбираются: нужен словарь YAML/JSON."
_BAD_PARAMS = ["{broken", "[1, 2]", "просто строка"]


@pytest.mark.parametrize("text", _BAD_PARAMS)
def test_unreadable_params_are_reported(qtbot, text: str) -> None:
    form = _form(qtbot, "robot", {"type": "tcp"})
    form._params_edit.setPlainText(text)

    assert form.params_error() == _PARAMS_ERROR


@pytest.mark.parametrize(
    ("text", "params"),
    [("", {}), ("  \n ", {}), ('{"a": 1}', {"a": 1}), ("a: 1", {"a": 1})],
    ids=["empty", "blank", "json", "yaml"],
)
def test_readable_params_have_no_error(qtbot, text: str, params: dict) -> None:
    form = _form(qtbot, "robot", {"type": "tcp"})
    form._params_edit.setPlainText(text)

    assert form.params_error() is None
    assert form.get_entry()["params"] == params


def _press_ok(qtbot, text: str) -> DeviceEditorDialog:
    dialog = DeviceEditorDialog(kind="robot", existing={"id": "rob", "kind": "robot", "params": {"a": 1}})
    qtbot.addWidget(dialog)
    dialog._form._params_edit.setPlainText(text)
    dialog.show()
    dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
    return dialog


@pytest.mark.parametrize("text", _BAD_PARAMS)
def test_dialog_with_unreadable_params_warns_and_stays_open(qtbot, warnings_only, text: str) -> None:
    dialog = _press_ok(qtbot, text)

    assert warnings_only == [_PARAMS_ERROR]
    assert dialog.isVisible()
    assert dialog.result() != QDialog.DialogCode.Accepted


def test_dialog_with_readable_params_is_accepted(qtbot, warnings_only) -> None:
    dialog = _press_ok(qtbot, "a: 2")

    assert warnings_only == []
    assert dialog.result() == QDialog.DialogCode.Accepted


def _add_page(qtbot, text: str) -> tuple[AddDevicePage, MagicMock, _Recipe, list[str]]:
    sender = MagicMock()
    sender.request_command.return_value = _envelope({"status": "ok"})
    presenter = DevicesPresenter(command_sender=sender, request_runner=_ImmediateRunner())
    recipe = _Recipe()
    committed: list[str] = []
    page = AddDevicePage(kind="robot", presenter=presenter, recipe_store=recipe, on_committed=committed.append)
    qtbot.addWidget(page)
    page._form.set_id("rob")
    page._form._params_edit.setPlainText(text)
    return page, sender, recipe, committed


def _sent(sender: MagicMock) -> list[str]:
    return [c.args[1] for c in sender.request_command.call_args_list]


@pytest.mark.parametrize("text", _BAD_PARAMS)
def test_add_page_commit_with_unreadable_params_saves_nothing(qtbot, text: str) -> None:
    page, sender, recipe, committed = _add_page(qtbot, text)

    page._btn_add.click()

    assert recipe.saved == []
    assert committed == []
    assert "device_upsert" not in _sent(sender)
    assert page._status.text() == _PARAMS_ERROR


@pytest.mark.parametrize("text", _BAD_PARAMS)
def test_add_page_check_with_unreadable_params_sends_nothing(qtbot, text: str) -> None:
    page, sender, recipe, _ = _add_page(qtbot, text)

    page._btn_check.click()

    assert "device_upsert" not in _sent(sender)
    assert "device_connect" not in _sent(sender)
    assert page._status.text() == _PARAMS_ERROR
