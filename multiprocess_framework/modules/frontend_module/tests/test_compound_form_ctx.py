# -*- coding: utf-8 -*-
"""Тесты CompoundNumericControl + FormContext + ActionBus.

Task 1.4.4: write через form_ctx для sub-control, undo round-trip, legacy путь, access-level guard.

Паттерн фейков скопирован из test_spinbox_form_ctx.py (Task 1.1.4).
Отличия: поле регистра — speed (float), тестируется sub-control index=0 (R-канал).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any, Optional

import pytest

from multiprocess_framework.modules.actions_module.bus import ActionBus
from multiprocess_framework.modules.actions_module.schemas import Action
from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
from multiprocess_framework.modules.frontend_module.components.compound import (
    CompoundNumericConfig,
    CompoundNumericControl,
)
from multiprocess_framework.modules.frontend_module.components.numeric.config import NumericViewConfig
from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext


# ---------------------------------------------------------------------------
# Фейковые зависимости
# ---------------------------------------------------------------------------


@dataclass
class _FakeRegister:
    """Регистр с числовым полем speed (float, используется как R-канал color)."""

    speed: float = 0.0


class _FakeRegistersManager:
    """Минимальный RM: get_register, set_field_value, subscribe, unsubscribe, get_field_metadata."""

    def __init__(self) -> None:
        self._registers: dict[str, Any] = {
            "motor": _FakeRegister(speed=0.0),
        }
        self._subs: dict[tuple[str, str], list] = {}
        self._meta: dict[tuple[str, str], dict] = {
            ("motor", "speed"): {
                "min": 0,
                "max": 255,
                "description": "Канал цвета",
                "transfer_k": 1.0,
                "round_k": 0,
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
    """FormContext для тестов CompoundNumericControl."""
    return FormContext(
        registers_manager=fake_rm,
        action_bus=bus_with_handler,
        action_builder=_FakeActionBuilder,
    )


def _make_config(access_level: int = 0) -> CompoundNumericConfig:
    """Вспомогательная функция: CompoundNumericConfig для тестов."""
    return CompoundNumericConfig(
        binding=BindingConfig("motor", "speed", access_level=access_level),
        labels=["R", "G", "B"],
        view_config=NumericViewConfig(view_type="spinbox", min_val=0.0, max_val=255.0),
    )


# ---------------------------------------------------------------------------
# Тест 1: write sub-control через form_ctx → action попал в bus, RM обновлён
# ---------------------------------------------------------------------------


def test_compound_write_sub_control_via_form_ctx(qapp, fake_rm, bus_with_handler, form_ctx):
    """_on_finished на sub-control[0] → form_ctx.write → ActionBus → RM обновлён.

    Sub-control index=0 соответствует R-каналу (label "R").
    """
    result = CompoundNumericControl.create(
        fake_rm,
        _make_config(),
        current_access_level=0,
        form_ctx=form_ctx,
    )

    # Начальное значение = 0
    assert fake_rm.get_register("motor").speed == pytest.approx(0.0)

    # _on_finished имитирует Enter/LostFocus для sub-control[0]
    result.results[0].presenter._on_finished(128.0)

    # RM обновлён
    assert fake_rm.get_register("motor").speed == pytest.approx(128.0)
    # Action попал в bus
    assert bus_with_handler.last_action() is not None


# ---------------------------------------------------------------------------
# Тест 2: undo round-trip → RM вернулся к старому значению
# ---------------------------------------------------------------------------


def test_compound_undo_restores_sub_control(qapp, fake_rm, bus_with_handler, form_ctx):
    """_on_finished → bus.undo() → RM вернулся к 0.0."""
    result = CompoundNumericControl.create(
        fake_rm,
        _make_config(),
        current_access_level=0,
        form_ctx=form_ctx,
    )

    # Запись нового значения через sub-control[0]
    result.results[0].presenter._on_finished(200.0)
    assert fake_rm.get_register("motor").speed == pytest.approx(200.0)

    # Undo: revert → set_field_value(0.0) → subscribe callback → view обновлён
    undone = bus_with_handler.undo()
    assert undone is not None, "undo() вернул None — стек оказался пуст"

    # RM вернулся к 0.0
    assert fake_rm.get_register("motor").speed == pytest.approx(0.0)
    assert bus_with_handler.can_undo() is False


# ---------------------------------------------------------------------------
# Тест 3: legacy путь (без form_ctx) → прямая запись через SyncTrait
# ---------------------------------------------------------------------------


def test_compound_legacy_path_no_form_ctx(qapp, fake_rm):
    """CompoundNumericControl без form_ctx — write идёт через SyncTrait → RegisterAdapter.

    RegisterAdapter с index=0 записывает значение как список [value] (обновляет элемент списка).
    Проверяем что RM обновлён: speed содержит список где speed[0] == 200.0.
    """
    result = CompoundNumericControl.create(
        fake_rm,
        _make_config(),
        current_access_level=0,
        # form_ctx не передаём — legacy путь
    )

    assert fake_rm.get_register("motor").speed == pytest.approx(0.0)

    # Прямая запись через legacy путь sub-control[0]
    result.results[0].presenter._on_finished(200.0)

    # RegisterAdapter при index=0 формирует список [200.0] и записывает его в поле.
    speed_val = fake_rm.get_register("motor").speed
    if isinstance(speed_val, list):
        # Список: проверяем элемент с index=0
        assert speed_val[0] == pytest.approx(200.0)
    else:
        assert speed_val == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Тест 4: access_level=5 при current_access_level=0 → write заблокирован
# ---------------------------------------------------------------------------


def test_compound_access_level_guard(qapp, fake_rm, form_ctx):
    """BindingConfig(access_level=5) + current_access_level=0 → все sub-controls disabled, write не проходит."""
    result = CompoundNumericControl.create(
        fake_rm,
        _make_config(access_level=5),
        current_access_level=0,
        form_ctx=form_ctx,
    )

    # Все 3 sub-controls должны быть disabled
    for sub in result.results:
        assert sub.presenter._access.can_modify() is False

    # _on_finished при заблокированном доступе не должна обновить RM
    result.results[0].presenter._on_finished(100.0)
    assert fake_rm.get_register("motor").speed == pytest.approx(0.0)  # не изменилось

    # После повышения доступа — sub-control[0] enabled
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result.results[0].presenter.set_access_level(5)

    assert result.results[0].presenter._access.can_modify() is True
