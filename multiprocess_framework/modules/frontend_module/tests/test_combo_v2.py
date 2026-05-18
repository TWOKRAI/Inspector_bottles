# -*- coding: utf-8 -*-
"""Тесты combo v2: presenter без Qt, smoke фасада с QApplication.

Task 1.5.5: presenter write, external sync, items init, Signal(str), facade create, access-denied.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import pytest

from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
from multiprocess_framework.modules.frontend_module.components.base.infrastructure.register_adapter import (
    RegisterAdapter,
)
from multiprocess_framework.modules.frontend_module.components.combo import (
    ComboControl,
    ComboPresenter,
    ComboViewConfig,
)
from multiprocess_framework.modules.frontend_module.components.combo.registers import ComboRegister


# ---------------------------------------------------------------------------
# Фейковые зависимости
# ---------------------------------------------------------------------------


@dataclass
class _Field:
    value: Any


@dataclass
class _ConfigReg:
    mode: _Field


class _FakeRegistersManager:
    def __init__(self) -> None:
        self._registers: Dict[str, Any] = {
            "config": _ConfigReg(mode=_Field("auto")),
        }
        self._subs: Dict[tuple, List[Callable[[Any], None]]] = {}
        self._meta: Dict[tuple, dict] = {
            ("config", "mode"): {"description": "Режим работы"},
        }

    def get_register(self, name: str) -> Any:
        return self._registers.get(name)

    def get_field_metadata(self, register_name: str, field_name: str) -> Optional[dict]:
        return self._meta.get((register_name, field_name))

    def set_field_value(self, register_name: str, field_name: str, value: Any) -> tuple[bool, Optional[str]]:
        reg = self.get_register(register_name)
        if not reg:
            return False, "no register"
        setattr(reg, field_name, _Field(value))
        key = (register_name, field_name)
        for cb in list(self._subs.get(key, [])):
            cb(value)
        return True, None

    def subscribe(self, register_name: str, field_name: str, callback: Callable[[Any], None]) -> None:
        key = (register_name, field_name)
        self._subs.setdefault(key, []).append(callback)

    def unsubscribe(self, register_name: str, field_name: str, callback: Callable[[Any], None]) -> None:
        key = (register_name, field_name)
        lst = self._subs.get(key)
        if lst and callback in lst:
            lst.remove(callback)


class _FakeStrView:
    """IControlView[str] без Qt."""

    def __init__(self) -> None:
        self.label = ""
        self.tooltip = ""
        self.enabled_flag = True
        self.value = ""
        self.items: List[str] = []
        self.errors: List[str] = []
        self._on_changed: Optional[Callable[[str], None]] = None

    def setup(self, label: str, tooltip: str, enabled: bool) -> None:
        self.label = label
        self.tooltip = tooltip
        self.enabled_flag = enabled

    def set_items(self, items: List[str]) -> None:
        """Сохраняет список items для проверки в тестах."""
        self.items = list(items)

    def set_value(self, value: str) -> None:
        self.value = str(value)

    def set_value_silent(self, value: str) -> None:
        self.value = str(value)

    def get_value(self) -> str:
        return self.value

    def set_enabled(self, enabled: bool) -> None:
        self.enabled_flag = enabled

    def on_changed(self, callback: Callable[[str], None]) -> None:
        self._on_changed = callback

    def on_finished(self, callback: Callable[[str], None]) -> None:
        pass

    def show_error(self, message: str) -> None:
        self.errors.append(message)

    def user_select(self, new_value: str) -> None:
        """Имитация выбора пользователем."""
        if self._on_changed:
            self._on_changed(new_value)


# ---------------------------------------------------------------------------
# Тесты presenter
# ---------------------------------------------------------------------------


class TestComboPresenter:
    def test_write_on_change(self) -> None:
        """user_select → presenter._on_changed → RM обновлён."""
        rm = _FakeRegistersManager()
        adapter = RegisterAdapter(rm)
        binding = BindingConfig("config", "mode", access_level=0)
        p = ComboPresenter(
            binding,
            adapter,
            ComboViewConfig(label="Режим"),
            current_access_level=0,
            items=["auto", "manual", "off"],
        )
        view = _FakeStrView()
        p.attach_view(view)
        assert view.label == "Режим"

        view.user_select("manual")

        reg = rm.get_register("config")
        assert reg is not None
        assert reg.mode.value == "manual"
        assert view.value == "manual"

    def test_external_sync_updates_view(self) -> None:
        """Внешнее изменение регистра → view обновлён через subscribe callback."""
        rm = _FakeRegistersManager()
        adapter = RegisterAdapter(rm)
        p = ComboPresenter(
            BindingConfig("config", "mode"),
            adapter,
            items=["auto", "manual", "off"],
        )
        view = _FakeStrView()
        p.attach_view(view)

        rm.set_field_value("config", "mode", "off")
        assert view.value == "off"

    def test_items_set_on_attach_view(self) -> None:
        """items передаются в view.set_items при attach_view."""
        rm = _FakeRegistersManager()
        adapter = RegisterAdapter(rm)
        p = ComboPresenter(
            BindingConfig("config", "mode"),
            adapter,
            items=["a", "b", "c"],
        )
        view = _FakeStrView()
        p.attach_view(view)

        assert view.items == ["a", "b", "c"]

    def test_access_denied_no_write(self) -> None:
        """access_level=5 + current_access_level=0 → виджет disabled, write не проходит."""
        rm = _FakeRegistersManager()
        adapter = RegisterAdapter(rm)
        p = ComboPresenter(
            BindingConfig("config", "mode", access_level=5),
            adapter,
            current_access_level=0,
            items=["auto", "manual", "off"],
        )
        view = _FakeStrView()
        p.attach_view(view)

        # view должен быть disabled
        assert view.enabled_flag is False

        view.user_select("manual")

        # RM не изменился — write заблокирован
        reg = rm.get_register("config")
        assert reg.mode.value == "auto"


# ---------------------------------------------------------------------------
# Тесты с Qt (Signal + facade)
# ---------------------------------------------------------------------------


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestComboViewValueChangedSignal:
    """Тест на публичный сигнал value_changed: Signal(str)."""

    def test_value_changed_emits_str_on_select(self, qapp) -> None:
        """value_changed эмитит str при программном изменении выбора."""
        from multiprocess_framework.modules.frontend_module.components.combo.view import ComboView

        view = ComboView()
        view.set_items(["x", "y", "z"])
        received: list[str] = []
        view.value_changed.connect(lambda v: received.append(v))

        # set_value (не silent) — триггерит currentTextChanged → value_changed
        view.set_value("y")
        assert "y" in received

    def test_set_value_silent_no_signal(self, qapp) -> None:
        """set_value_silent НЕ эмитит value_changed."""
        from multiprocess_framework.modules.frontend_module.components.combo.view import ComboView

        view = ComboView()
        view.set_items(["a", "b"])
        received: list[str] = []
        view.value_changed.connect(lambda v: received.append(v))

        view.set_value_silent("b")
        assert received == []


class TestComboControlFacade:
    def test_create_returns_widget_and_presenter(self, qapp) -> None:
        """ComboControl.create → result.widget is not None, result.presenter is not None."""
        rm = _FakeRegistersManager()
        result = ComboControl.create(
            rm,
            BindingConfig("config", "mode"),
            items=["auto", "manual"],
        )
        assert result.widget is not None
        assert result.presenter is not None


class TestComboRegister:
    """Атрибуты класса ComboRegister должны быть стабильны."""

    def test_python_type_is_str(self) -> None:
        assert ComboRegister.python_type is str

    def test_widget_is_combo(self) -> None:
        assert ComboRegister.widget == "combo"
