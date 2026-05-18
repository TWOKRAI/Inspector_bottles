# -*- coding: utf-8 -*-
"""Тесты NumericControl(view_type="spinbox") + FormContext + ActionBus для float-полей.

Task 1.3.3: write via form_ctx, undo round-trip, legacy путь, access-level guard.

NumericControl с view_type="spinbox" используется для float-полей (round_k > 0 →
presenter вызовет set_validator_float() → QDoubleSpinBox с decimals=4).

Структура фейков идентична test_spinbox_form_ctx.py (Task 1.1.4).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any, Optional

import pytest

from multiprocess_framework.modules.actions_module.bus import ActionBus
from multiprocess_framework.modules.actions_module.schemas import Action
from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
from multiprocess_framework.modules.frontend_module.components.numeric import (
    NumericControl,
    NumericViewConfig,
)
from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext


# ---------------------------------------------------------------------------
# Фейковые зависимости
# ---------------------------------------------------------------------------


@dataclass
class _FakeRegister:
    """Регистр с float-полем threshold."""

    threshold: float = 0.5


class _FakeRegistersManager:
    """Минимальный RM: get_register, set_field_value, subscribe, unsubscribe, get_field_metadata."""

    def __init__(self) -> None:
        self._registers: dict[str, Any] = {
            "detector": _FakeRegister(threshold=0.5),
        }
        self._subs: dict[tuple[str, str], list] = {}
        self._meta: dict[tuple[str, str], dict] = {
            ("detector", "threshold"): {
                "min": 0.0,
                "max": 1.0,
                "description": "Порог детектора",
                "transfer_k": 1.0,  # без масштабирования: UI == storage
                "round_k": 4,  # float-validator (decimals > 0, set_validator_float)
            },
        }

    def get_register(self, name: str) -> Any:
        return self._registers.get(name)

    def get_field_metadata(self, register_name: str, field_name: str, **kwargs: Any) -> dict:
        return self._meta.get((register_name, field_name), {})

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
    """ActionBuilder — создаёт Action с forward/backward patch."""

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
    """FormContext для тестов NumericControl float."""
    return FormContext(
        registers_manager=fake_rm,
        action_bus=bus_with_handler,
        action_builder=_FakeActionBuilder,
    )


# ---------------------------------------------------------------------------
# Тест 1: write через form_ctx → action попал в bus, RM обновлён
# ---------------------------------------------------------------------------


def test_numeric_form_ctx_roundtrip(qapp, fake_rm, bus_with_handler, form_ctx):
    """_on_finished → form_ctx.write → ActionBus → RM обновлён.

    Проверяет round-trip: threshold=0.5 → write 0.75 → undo → 0.5.
    Используем _on_finished для немедленной записи (обход debounce).
    """
    result = NumericControl.create(
        fake_rm,
        BindingConfig("detector", "threshold"),
        NumericViewConfig(view_type="spinbox", min_val=0.0, max_val=1.0),
        current_access_level=0,
        form_ctx=form_ctx,
    )
    presenter = result.presenter
    widget = result.widget

    # Начальное значение = 0.5 (из _FakeRegister)
    initial = fake_rm.get_register("detector").threshold
    assert initial == pytest.approx(0.5)

    # Запись нового значения через form_ctx
    presenter._on_finished(0.75)

    # RM обновлён
    assert fake_rm.get_register("detector").threshold == pytest.approx(0.75)
    # Action попал в bus
    assert bus_with_handler.last_action() is not None

    # Undo: revert → set_field_value(0.5) → subscribe callback → view.set_value_silent(0.5)
    undone = bus_with_handler.undo()
    assert undone is not None, "undo() вернул None — стек оказался пуст"

    # RM и view синхронизированы обратно
    assert fake_rm.get_register("detector").threshold == pytest.approx(0.5)
    assert widget.get_value() == pytest.approx(0.5)
    assert bus_with_handler.can_undo() is False


# ---------------------------------------------------------------------------
# Тест 2: legacy путь (без form_ctx) → прямая запись через SyncTrait
# ---------------------------------------------------------------------------


def test_numeric_form_ctx_legacy_path(qapp, fake_rm):
    """NumericControl без form_ctx — write идёт через SyncTrait → RegisterAdapter.

    Bus не участвует: можно не передавать его вообще.
    """
    result = NumericControl.create(
        fake_rm,
        BindingConfig("detector", "threshold"),
        NumericViewConfig(view_type="spinbox", min_val=0.0, max_val=1.0),
        current_access_level=0,
        # form_ctx не передаём — legacy путь
    )
    presenter = result.presenter

    # Начальное значение из RM
    assert fake_rm.get_register("detector").threshold == pytest.approx(0.5)

    # Прямая запись через legacy путь
    presenter._on_finished(0.3)

    # RM обновлён через SyncTrait
    assert fake_rm.get_register("detector").threshold == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# Тест 3: action действительно записывается в bus (dual-write verification)
# ---------------------------------------------------------------------------


def test_numeric_dual_write_with_form_ctx(qapp, fake_rm, bus_with_handler, form_ctx):
    """Два последовательных write — оба action попали в bus, оба доступны для undo."""
    result = NumericControl.create(
        fake_rm,
        BindingConfig("detector", "threshold"),
        NumericViewConfig(view_type="spinbox", min_val=0.0, max_val=1.0),
        current_access_level=0,
        form_ctx=form_ctx,
    )
    presenter = result.presenter

    # Первая запись
    presenter._on_finished(0.6)
    assert fake_rm.get_register("detector").threshold == pytest.approx(0.6)
    assert bus_with_handler.can_undo() is True

    # Вторая запись
    presenter._on_finished(0.8)
    assert fake_rm.get_register("detector").threshold == pytest.approx(0.8)

    # Undo первого шага: 0.8 → 0.6
    bus_with_handler.undo()
    assert fake_rm.get_register("detector").threshold == pytest.approx(0.6)

    # Undo второго шага: 0.6 → 0.5 (начальное)
    bus_with_handler.undo()
    assert fake_rm.get_register("detector").threshold == pytest.approx(0.5)

    assert bus_with_handler.can_undo() is False


# ---------------------------------------------------------------------------
# Тест 4: access_level=5 при current_access_level=0 → write заблокирован
# ---------------------------------------------------------------------------


def test_numeric_access_level_guard(qapp, fake_rm, form_ctx):
    """BindingConfig(access_level=5) + current_access_level=0 → виджет disabled, write не проходит."""
    result = NumericControl.create(
        fake_rm,
        BindingConfig("detector", "threshold", access_level=5),
        NumericViewConfig(view_type="spinbox", min_val=0.0, max_val=1.0),
        current_access_level=0,
        form_ctx=form_ctx,
    )
    presenter = result.presenter
    widget = result.widget

    # Виджет должен быть disabled (AccessTrait.can_modify() == False)
    assert presenter._access.can_modify() is False
    # set_enabled отключает внутренний QDoubleSpinBox (не контейнер-виджет)
    assert widget._value_view._spinbox.isEnabled() is False

    # _on_finished при заблокированном доступе не должна обновить RM
    presenter._on_finished(0.99)
    assert fake_rm.get_register("detector").threshold == pytest.approx(0.5)  # не изменилось

    # После повышения доступа — виджет enabled
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        presenter.set_access_level(5)

    assert presenter._access.can_modify() is True
    assert widget._value_view._spinbox.isEnabled() is True
