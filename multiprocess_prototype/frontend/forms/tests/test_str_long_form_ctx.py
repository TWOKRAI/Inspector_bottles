# -*- coding: utf-8 -*-
"""Тесты _build_str_long + FormContext (Task 2.6).

Три теста:
1. write через form_ctx — action попал в ActionBus (прямой setPlainText, минуя setter).
2. setter_no_write — вызов setter через editor.setter НЕ создаёт action (blockSignals).
3. legacy путь (без form_ctx) — isReadOnly=True, change_signal is not None.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pytest

from multiprocess_framework.modules.actions_module.bus import ActionBus
from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext
from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder
from multiprocess_prototype.frontend.actions.handlers.field_set_handler import FieldSetHandler
from multiprocess_prototype.frontend.forms.factory import _build_str_long
from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo


# ---------------------------------------------------------------------------
# Фейковые зависимости
# ---------------------------------------------------------------------------


@dataclass
class _FakeReg:
    """Регистр с текстовым полем description."""

    description: str = "initial text"


class _FakeRM:
    """Минимальный RM для тестов str_long."""

    def __init__(self) -> None:
        self._regs: dict[str, Any] = {"test_reg": _FakeReg(description="initial text")}
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
    """FormContext для тестов str_long."""
    return FormContext(
        registers_manager=fake_rm,
        action_bus=bus_with_handler,
        action_builder=V2ActionBuilder,
    )


def _make_fi(default: str = "initial text") -> FieldInfo:
    """Создать FieldInfo для длинной str-поля."""
    return FieldInfo(
        plugin_name="test_reg",
        field_name="description",
        field_type=str,
        default=default,
        meta=None,
        category="",
    )


# ---------------------------------------------------------------------------
# Тест 1: write через form_ctx — прямой setPlainText → action в ActionBus
# ---------------------------------------------------------------------------


def test_str_long_write_via_form_ctx(qapp, fake_rm, bus_with_handler, form_ctx):
    """Прямой te.setPlainText() (минуя setter) → textChanged → action в ActionBus."""
    fi = _make_fi(default="initial text")
    editor = _build_str_long(fi, form_ctx=form_ctx)

    # Прямой вызов (минуя setter — без blockSignals) → должен сработать write
    editor.widget.setPlainText("new text")

    assert bus_with_handler.last_action() is not None
    # change_signal=None (binding-aware путь)
    assert editor.change_signal is None


# ---------------------------------------------------------------------------
# Тест 2: setter НЕ вызывает write (blockSignals в setter)
# ---------------------------------------------------------------------------


def test_str_long_setter_no_write(qapp, fake_rm, bus_with_handler, form_ctx):
    """editor.setter('via setter') → blockSignals → write НЕ срабатывает."""
    fi = _make_fi(default="initial text")
    editor = _build_str_long(fi, form_ctx=form_ctx)

    # Вызов setter — blockSignals(True) предотвращает textChanged
    editor.setter("via setter")

    # Action не должен появиться в bus
    assert bus_with_handler.last_action() is None
    # Значение всё же установилось
    assert editor.getter() == "via setter"


# ---------------------------------------------------------------------------
# Тест 3: legacy путь — isReadOnly=True, change_signal is not None
# ---------------------------------------------------------------------------


def test_str_long_legacy_path_no_form_ctx(qapp):
    """_build_str_long без form_ctx → QPlainTextEdit, readonly, change_signal подключён."""
    from PySide6.QtWidgets import QPlainTextEdit

    fi = _make_fi(default="initial text")
    editor = _build_str_long(fi)

    assert isinstance(editor.widget, QPlainTextEdit)
    # Legacy путь: readonly
    assert editor.widget.isReadOnly() is True
    # change_signal подключён (RegisterView управляет write)
    assert editor.change_signal is not None
