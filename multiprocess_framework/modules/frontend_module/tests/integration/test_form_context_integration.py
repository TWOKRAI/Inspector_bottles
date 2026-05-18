# -*- coding: utf-8 -*-
"""Integration-тесты CheckboxControl + FormContext + ActionBus.

Task 0.1: round-trip click → write → undo → rollback через реальный QApplication,
          реальный ActionBus, фейковый RegistersManager.
Task 0.3: блокировка UI по access_level через BindingConfig + AccessTrait.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any, Optional

import pytest

from multiprocess_framework.modules.actions_module.bus import ActionBus
from multiprocess_framework.modules.actions_module.schemas import Action
from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
from multiprocess_framework.modules.frontend_module.components.checkbox import (
    CheckboxControl,
    CheckboxViewConfig,
)
from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext


# ---------------------------------------------------------------------------
# Фейковые зависимости (по образцу test_form_context_write.py)
# ---------------------------------------------------------------------------


@dataclass
class _FakeRegister:
    """Регистр с полем enabled и полем admin_only."""

    enabled: bool = False
    admin_only: bool = False


class _FakeRegistersManager:
    """Минимальный RM: get_register, set_field_value, subscribe, unsubscribe, get_field_metadata."""

    def __init__(self) -> None:
        self._registers: dict[str, Any] = {
            "robot_control": _FakeRegister(enabled=False),
            "pilot_widgets": _FakeRegister(admin_only=False),
        }
        self._subs: dict[tuple[str, str], list] = {}

    def get_register(self, name: str) -> Any:
        return self._registers.get(name)

    def get_field_metadata(self, register_name: str, field_name: str, **kwargs: Any) -> dict:
        return {}

    def set_field_value(self, register_name: str, field_name: str, value: Any) -> tuple[bool, Optional[str]]:
        reg = self.get_register(register_name)
        if not reg:
            return False, "no register"
        setattr(reg, field_name, value)
        for cb in list(self._subs.get((register_name, field_name), [])):
            cb(value)
        return True, None

    def subscribe(self, register_name: str, field_name: str, callback: Any) -> None:
        key = (register_name, field_name)
        self._subs.setdefault(key, []).append(callback)

    def unsubscribe(self, register_name: str, field_name: str, callback: Any) -> None:
        key = (register_name, field_name)
        lst = self._subs.get(key)
        if lst and callback in lst:
            lst.remove(callback)


class _FakeActionBuilder:
    """ActionBuilder без зависимости от V2ActionBuilder."""

    @staticmethod
    def field_set_timed(
        register_name: str,
        field_name: str,
        new_value: Any,
        old_value: Any,
    ) -> Action:
        return Action(
            action_type="field_set",
            register_name=register_name,
            field_name=field_name,
            forward_patch={"value": new_value},
            backward_patch={"value": old_value},
            undoable=True,
        )


class _FakeFieldSetHandler:
    """Обработчик field_set: apply/revert через rm.set_field_value."""

    def apply(self, action: Action, rm: Any) -> None:
        value = action.forward_patch.get("value")
        rm.set_field_value(action.register_name, action.field_name, value)

    def revert(self, action: Action, rm: Any) -> None:
        value = action.backward_patch.get("value")
        rm.set_field_value(action.register_name, action.field_name, value)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def qapp():
    """QApplication-синглтон для headless Qt-тестов."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def fake_rm():
    return _FakeRegistersManager()


@pytest.fixture
def bus_with_handler(fake_rm):
    """ActionBus с зарегистрированным _FakeFieldSetHandler."""
    bus = ActionBus(fake_rm, max_history=50)
    bus.register_handler("field_set", _FakeFieldSetHandler())
    return bus


@pytest.fixture
def form_ctx(fake_rm, bus_with_handler):
    """FormContext для integration-тестов."""
    return FormContext(
        registers_manager=fake_rm,
        action_bus=bus_with_handler,
        action_builder=_FakeActionBuilder,
    )


# ---------------------------------------------------------------------------
# Task 0.1 — round-trip: click → write → undo → rollback
# ---------------------------------------------------------------------------


def test_checkbox_form_ctx_roundtrip(qapp, fake_rm, bus_with_handler, form_ctx):
    """View → action → undo → rollback через реальный QApplication и ActionBus.

    Сценарий:
    1. Начальное значение enabled=False в RM.
    2. setChecked(True) → stateChanged → presenter._on_changed(True) → form_ctx.write → ActionBus.
    3. Assert: RM обновлён, action в undo_stack.
    4. bus.undo() → revert → set_field_value(False) → subscribe-callback → view.set_value_silent(False).
    5. Assert: view и RM синхронизированы обратно.
    """
    result = CheckboxControl.create(
        fake_rm,
        BindingConfig("robot_control", "enabled"),
        CheckboxViewConfig(position="left"),
        current_access_level=0,
        form_ctx=form_ctx,
    )
    view = result.widget

    # Начальное значение: enabled=False
    assert view.get_value() is False
    assert fake_rm.get_register("robot_control").enabled is False

    # Клик: setChecked(True) — триггерит stateChanged → presenter._on_changed(True)
    view._checkbox.setChecked(True)

    # После click: RM обновлён, action в bus
    assert fake_rm.get_register("robot_control").enabled is True
    last = bus_with_handler.last_action()
    assert last is not None

    # Undo: revert → set_field_value(False) → subscribe → view.set_value_silent(False)
    undone = bus_with_handler.undo()
    assert undone is not None, "undo() вернул None — стек оказался пуст, не было реальной операции"

    # После undo: view и RM синхронизированы обратно
    assert view.get_value() is False
    assert fake_rm.get_register("robot_control").enabled is False
    assert bus_with_handler.can_undo() is False, "после одного undo стек должен быть пуст"


# ---------------------------------------------------------------------------
# Task 0.3 — Access-level UI guard: admin_only заблокировано при user_level=0
# ---------------------------------------------------------------------------


def test_checkbox_disabled_when_user_level_below_access_level(qapp, fake_rm, form_ctx):
    """CheckboxControl с access_level=5 создаёт disabled checkbox при current_access_level=0.

    Сценарий:
    1. BindingConfig(access_level=5) + current_access_level=0 → checkbox disabled.
    2. set_access_level(5) → checkbox enabled.
    3. set_access_level(4) → checkbox disabled (граничный: строго меньше, не равно).
    """
    result = CheckboxControl.create(
        fake_rm,
        BindingConfig("pilot_widgets", "admin_only", access_level=5),
        CheckboxViewConfig(position="left"),
        current_access_level=0,
        form_ctx=form_ctx,
    )
    view = result.widget
    presenter = result.presenter

    # При level=0 < required=5 — checkbox должен быть disabled
    assert view._checkbox.isEnabled() is False

    # После set_access_level(5): level == required → enabled
    # set_access_level вызывает update(int) внутри AccessTrait — подавляем DeprecationWarning
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        presenter.set_access_level(5)

    assert view._checkbox.isEnabled() is True

    # Граничный случай: level=4 < required=5 → снова disabled
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        presenter.set_access_level(4)

    assert view._checkbox.isEnabled() is False
