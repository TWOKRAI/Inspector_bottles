# -*- coding: utf-8 -*-
"""Тесты _build_path + FormContext (Task 2.7).

Три теста:
1. write через form_ctx — action попал в ActionBus.
2. legacy путь (без form_ctx) — change_signal is not None, виджет содержит строку пути.
3. correct str value — в action записана строка (не Path-объект).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pytest

from multiprocess_framework.modules.actions_module.bus import ActionBus
from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext
from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder
from multiprocess_prototype.frontend.actions.handlers.field_set_handler import FieldSetHandler
from multiprocess_prototype.frontend.forms.factory import _build_path
from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo


# ---------------------------------------------------------------------------
# Фейковые зависимости
# ---------------------------------------------------------------------------


@dataclass
class _FakeReg:
    """Регистр с path-полем output_dir."""

    output_dir: str = "/some/path"


class _FakeRM:
    """Минимальный RM для тестов path."""

    def __init__(self) -> None:
        self._regs: dict[str, Any] = {"test_reg": _FakeReg(output_dir="/some/path")}
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
    """FormContext для тестов path."""
    return FormContext(
        registers_manager=fake_rm,
        action_bus=bus_with_handler,
        action_builder=V2ActionBuilder,
    )


def _make_fi(default: Any = Path("/some/path")) -> FieldInfo:
    """Создать FieldInfo для Path-поля."""
    return FieldInfo(
        plugin_name="test_reg",
        field_name="output_dir",
        field_type=Path,
        default=default,
        meta=None,
        category="",
    )


# ---------------------------------------------------------------------------
# Тест 1: write через form_ctx → action попал в ActionBus
# ---------------------------------------------------------------------------


def test_path_write_via_form_ctx(qapp, fake_rm, bus_with_handler, form_ctx):
    """editingFinished.emit() → form_ctx.write → action в ActionBus."""
    fi = _make_fi(default=Path("/some/path"))
    editor = _build_path(fi, form_ctx=form_ctx)

    # Эмулируем Enter/потерю фокуса
    editor.widget.editingFinished.emit()

    assert bus_with_handler.last_action() is not None
    # change_signal=None (binding-aware путь не дублирует write)
    assert editor.change_signal is None


# ---------------------------------------------------------------------------
# Тест 2: legacy путь — change_signal is not None, виджет содержит строку пути
# ---------------------------------------------------------------------------


def test_path_legacy_path_no_form_ctx(qapp):
    """_build_path без form_ctx → QLineEdit, change_signal подключён, text() — строка."""
    from PySide6.QtWidgets import QLineEdit

    fi = _make_fi(default=Path("/some/path"))
    editor = _build_path(fi)

    assert isinstance(editor.widget, QLineEdit)
    # Legacy путь: change_signal подключён
    assert editor.change_signal is not None
    # Виджет содержит строковое представление пути (posix forward-slashes)
    text = editor.widget.text()
    assert isinstance(text, str)
    assert "some" in text  # кроссплатформенная проверка без зависимости от OS-слеша


# ---------------------------------------------------------------------------
# Тест 3: в action записана строка (не Path)
# ---------------------------------------------------------------------------


def test_path_emits_str_value(qapp, fake_rm, bus_with_handler, form_ctx):
    """После setText('/new/path') + editingFinished → action.forward_patch['value'] == '/new/path'."""
    fi = _make_fi(default=Path("/some/path"))
    editor = _build_path(fi, form_ctx=form_ctx)

    editor.widget.setText("/new/path")
    editor.widget.editingFinished.emit()

    last = bus_with_handler.last_action()
    assert last is not None
    # write возвращает str, не Path — ответственность handler'а в RM
    assert last.forward_patch["value"] == "/new/path"
    assert isinstance(last.forward_patch["value"], str)
