# -*- coding: utf-8 -*-
"""Тесты _build_str_short + FormContext (Task 2.5).

Три теста:
1. write через form_ctx — action попал в ActionBus.
2. legacy путь (без form_ctx) — change_signal is not None.
3. correct value — в action записано правильное значение.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pytest

from multiprocess_framework.modules.actions_module.bus import ActionBus
from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext
from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder
from multiprocess_prototype.frontend.actions.handlers.field_set_handler import FieldSetHandler
from multiprocess_prototype.frontend.forms.factory import _build_str_short
from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo


# ---------------------------------------------------------------------------
# Фейковые зависимости
# ---------------------------------------------------------------------------


@dataclass
class _FakeReg:
    """Регистр с полем label."""

    label: str = "hello"


class _FakeRM:
    """Минимальный RM для тестов str_short."""

    def __init__(self) -> None:
        self._regs: dict[str, Any] = {"test_reg": _FakeReg(label="hello")}
        self._subs: dict[tuple[str, str], list] = {}

    def get_register(self, name: str) -> Any:
        return self._regs.get(name)

    def get_field_metadata(self, register_name: str, field_name: str, **kw: Any) -> dict:
        return {}

    def set_field_value(self, register_name: str, field_name: str, value: Any) -> tuple[bool, Optional[str]]:
        reg = self.get_register(register_name)
        if not reg:
            return False, "no register"
        setattr(reg, field_name, value)
        for cb in list(self._subs.get((register_name, field_name), [])):
            cb(value)
        return True, None

    def subscribe(self, reg: str, field: str, cb: Any) -> None:
        self._subs.setdefault((reg, field), []).append(cb)

    def unsubscribe(self, reg: str, field: str, cb: Any) -> None:
        lst = self._subs.get((reg, field))
        if lst and cb in lst:
            lst.remove(cb)


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
    return _FakeRM()


@pytest.fixture
def bus_with_handler(fake_rm):
    """ActionBus с зарегистрированным FieldSetHandler."""
    bus = ActionBus(fake_rm, max_history=50)
    bus.register_handler("field_set", FieldSetHandler())
    return bus


@pytest.fixture
def form_ctx(fake_rm, bus_with_handler):
    """FormContext для тестов str_short."""
    return FormContext(
        registers_manager=fake_rm,
        action_bus=bus_with_handler,
        action_builder=V2ActionBuilder,
    )


def _make_fi(default: str = "hello") -> FieldInfo:
    """Создать FieldInfo для str-поля."""
    return FieldInfo(
        plugin_name="test_reg",
        field_name="label",
        field_type=str,
        default=default,
        meta=None,
        category="",
    )


# ---------------------------------------------------------------------------
# Тест 1: write через form_ctx → action попал в ActionBus
# ---------------------------------------------------------------------------


def test_str_short_write_via_form_ctx(qapp, fake_rm, bus_with_handler, form_ctx):
    """editingFinished.emit() → form_ctx.write → action в ActionBus, RM обновлён."""
    fi = _make_fi(default="hello")
    editor = _build_str_short(fi, form_ctx=form_ctx)

    # Устанавливаем новое значение
    editor.widget.setText("world")
    # Эмулируем потерю фокуса / Enter
    editor.widget.editingFinished.emit()

    # Action попал в bus
    assert bus_with_handler.last_action() is not None
    # change_signal=None (binding-aware путь не дублирует write через RegisterView)
    assert editor.change_signal is None


# ---------------------------------------------------------------------------
# Тест 2: legacy путь (без form_ctx) → change_signal is not None
# ---------------------------------------------------------------------------


def test_str_short_legacy_path_no_form_ctx(qapp):
    """_build_str_short без form_ctx → QLineEdit с textChanged (legacy)."""
    from PySide6.QtWidgets import QLineEdit

    fi = _make_fi(default="hello")
    editor = _build_str_short(fi)

    assert isinstance(editor.widget, QLineEdit)
    # Legacy путь: change_signal подключён (RegisterView управляет write)
    assert editor.change_signal is not None


# ---------------------------------------------------------------------------
# Тест 3: в action записано правильное значение
# ---------------------------------------------------------------------------


def test_str_short_emits_correct_value(qapp, fake_rm, bus_with_handler, form_ctx):
    """После setText('new_value') + editingFinished → action.forward_patch['value'] == 'new_value'."""
    fi = _make_fi(default="hello")
    editor = _build_str_short(fi, form_ctx=form_ctx)

    editor.widget.setText("new_value")
    editor.widget.editingFinished.emit()

    last = bus_with_handler.last_action()
    assert last is not None
    assert last.forward_patch["value"] == "new_value"
