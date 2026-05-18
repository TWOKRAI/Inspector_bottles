# -*- coding: utf-8 -*-
"""Тесты ComboControl + FormContext + ActionBus.

Task 1.5.7: write via form_ctx, undo round-trip, legacy путь, access-level guard.

Паттерн фейков скопирован из test_spinbox_form_ctx.py (Task 1.1.4).
Отличия: поле регистра — mode (str), тестируется ComboControl.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any, Optional

import pytest

from multiprocess_framework.modules.actions_module.bus import ActionBus
from multiprocess_framework.modules.actions_module.schemas import Action
from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
from multiprocess_framework.modules.frontend_module.components.combo import (
    ComboControl,
    ComboViewConfig,
)
from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext


# ---------------------------------------------------------------------------
# Фейковые зависимости
# ---------------------------------------------------------------------------


@dataclass
class _FakeRegister:
    """Регистр со строковым полем mode."""

    mode: str = "auto"


class _FakeRegistersManager:
    """Минимальный RM: get_register, set_field_value, subscribe, unsubscribe, get_field_metadata."""

    def __init__(self) -> None:
        self._registers: dict[str, Any] = {
            "config": _FakeRegister(mode="auto"),
        }
        self._subs: dict[tuple[str, str], list] = {}
        self._meta: dict[tuple[str, str], dict] = {
            ("config", "mode"): {
                "description": "Режим работы",
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
    """FormContext для тестов ComboControl."""
    return FormContext(
        registers_manager=fake_rm,
        action_bus=bus_with_handler,
        action_builder=_FakeActionBuilder,
    )


# ---------------------------------------------------------------------------
# Тест 1: write через form_ctx → action попал в bus, RM обновлён
# ---------------------------------------------------------------------------


def test_combo_write_via_form_ctx(qapp, fake_rm, bus_with_handler, form_ctx):
    """presenter._on_changed → form_ctx.write → ActionBus → RM обновлён.

    Используем _on_changed непосредственно (combo пишет сразу при смене выбора).
    """
    result = ComboControl.create(
        fake_rm,
        BindingConfig("config", "mode"),
        ComboViewConfig(),
        current_access_level=0,
        items=["auto", "manual", "off"],
        form_ctx=form_ctx,
    )
    presenter = result.presenter

    # Начальное значение = "auto"
    assert fake_rm.get_register("config").mode == "auto"

    # Имитация смены выбора пользователем
    presenter._on_changed("manual")

    # RM обновлён
    assert fake_rm.get_register("config").mode == "manual"
    # Action попал в bus
    assert bus_with_handler.last_action() is not None


# ---------------------------------------------------------------------------
# Тест 2: undo round-trip → view вернулся к старому значению
# ---------------------------------------------------------------------------


def test_combo_undo_restores_view(qapp, fake_rm, bus_with_handler, form_ctx):
    """_on_changed("manual") → bus.undo() → RM вернулся к "auto" → view синхронизирован."""
    result = ComboControl.create(
        fake_rm,
        BindingConfig("config", "mode"),
        ComboViewConfig(),
        current_access_level=0,
        items=["auto", "manual", "off"],
        form_ctx=form_ctx,
    )
    presenter = result.presenter
    widget = result.widget

    # Начальное значение
    assert fake_rm.get_register("config").mode == "auto"

    # Запись нового значения
    presenter._on_changed("manual")
    assert fake_rm.get_register("config").mode == "manual"

    # Undo: revert → set_field_value("auto") → subscribe callback → view.set_value_silent("auto")
    undone = bus_with_handler.undo()
    assert undone is not None, "undo() вернул None — стек оказался пуст"

    # RM и view синхронизированы обратно
    assert fake_rm.get_register("config").mode == "auto"
    assert widget.get_value() == "auto"
    assert bus_with_handler.can_undo() is False


# ---------------------------------------------------------------------------
# Тест 3: legacy путь (без form_ctx) → прямая запись через SyncTrait
# ---------------------------------------------------------------------------


def test_combo_legacy_path_no_form_ctx(qapp, fake_rm):
    """ComboControl без form_ctx — write идёт через SyncTrait → RegisterAdapter."""
    result = ComboControl.create(
        fake_rm,
        BindingConfig("config", "mode"),
        items=["auto", "manual", "off"],
        # form_ctx не передаём — legacy путь
    )
    presenter = result.presenter

    # Начальное значение
    assert fake_rm.get_register("config").mode == "auto"

    # Прямая запись через legacy путь
    presenter._on_changed("off")

    # RM обновлён через SyncTrait
    assert fake_rm.get_register("config").mode == "off"


# ---------------------------------------------------------------------------
# Тест 4: access_level=3 при current_access_level=0 → write заблокирован
# ---------------------------------------------------------------------------


def test_combo_access_level_guard(qapp, fake_rm, form_ctx):
    """BindingConfig(access_level=3) + current_access_level=0 → виджет disabled, write не проходит."""
    result = ComboControl.create(
        fake_rm,
        BindingConfig("config", "mode", access_level=3),
        items=["auto", "manual", "off"],
        current_access_level=0,
        form_ctx=form_ctx,
    )
    presenter = result.presenter

    # Виджет должен быть disabled (AccessTrait.can_modify() == False)
    assert presenter._access.can_modify() is False

    # _on_changed при заблокированном доступе не должна обновить RM
    presenter._on_changed("off")
    assert fake_rm.get_register("config").mode == "auto"  # не изменилось

    # После повышения доступа — виджет enabled
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        presenter.set_access_level(3)

    assert presenter._access.can_modify() is True
