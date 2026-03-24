# -*- coding: utf-8 -*-
"""Тесты checkbox v2: presenter без Qt, smoke фасада с QApplication."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import pytest

from frontend_module.components.base.config import BindingConfig
from frontend_module.components.base.infrastructure.register_adapter import (
    RegisterAdapter,
)
from frontend_module.components.checkbox import (
    CheckboxControl,
    CheckboxPresenter,
    CheckboxViewConfig,
)


@dataclass
class _Field:
    value: Any


@dataclass
class _RendererReg:
    show_mask: _Field


class _FakeRegistersManager:
    def __init__(self) -> None:
        self._registers: Dict[str, Any] = {
            "renderer": _RendererReg(show_mask=_Field(False)),
        }
        self._subs: Dict[tuple, List[Callable[[Any], None]]] = {}
        self._meta: Dict[tuple, dict] = {
            ("renderer", "show_mask"): {"description": "Показать маску"},
        }

    def get_register(self, name: str) -> Any:
        return self._registers.get(name)

    def get_field_metadata(
        self, register_name: str, field_name: str
    ) -> Optional[dict]:
        return self._meta.get((register_name, field_name))

    def set_field_value(
        self, register_name: str, field_name: str, value: Any
    ) -> tuple[bool, Optional[str]]:
        reg = self.get_register(register_name)
        if not reg:
            return False, "no register"
        setattr(reg, field_name, _Field(value))
        key = (register_name, field_name)
        for cb in list(self._subs.get(key, [])):
            cb(value)
        return True, None

    def subscribe(
        self, register_name: str, field_name: str, callback: Callable[[Any], None]
    ) -> None:
        key = (register_name, field_name)
        self._subs.setdefault(key, []).append(callback)

    def unsubscribe(
        self, register_name: str, field_name: str, callback: Callable[[Any], None]
    ) -> None:
        key = (register_name, field_name)
        lst = self._subs.get(key)
        if lst and callback in lst:
            lst.remove(callback)


class _FakeBoolView:
    """IControlView[bool] без Qt."""

    def __init__(self) -> None:
        self.label = ""
        self.tooltip = ""
        self.enabled_flag = True
        self.value = False
        self.errors: List[str] = []
        self._on_changed: Optional[Callable[[bool], None]] = None

    def setup(self, label: str, tooltip: str, enabled: bool) -> None:
        self.label = label
        self.tooltip = tooltip
        self.enabled_flag = enabled

    def set_value(self, value: bool) -> None:
        self.value = value

    def set_value_silent(self, value: bool) -> None:
        self.value = value

    def get_value(self) -> bool:
        return self.value

    def set_enabled(self, enabled: bool) -> None:
        self.enabled_flag = enabled

    def on_changed(self, callback: Callable[[bool], None]) -> None:
        self._on_changed = callback

    def on_finished(self, callback: Callable[[bool], None]) -> None:
        pass

    def show_error(self, message: str) -> None:
        self.errors.append(message)

    def user_toggle(self, new_value: bool) -> None:
        if self._on_changed:
            self._on_changed(new_value)


class TestCheckboxPresenter:
    def test_write_on_change(self) -> None:
        rm = _FakeRegistersManager()
        adapter = RegisterAdapter(rm)
        binding = BindingConfig("renderer", "show_mask", access_level=0)
        p = CheckboxPresenter(
            binding,
            adapter,
            CheckboxViewConfig(label="Маска"),
            current_access_level=0,
        )
        view = _FakeBoolView()
        p.attach_view(view)
        assert view.label == "Маска"
        view.user_toggle(True)
        reg = rm.get_register("renderer")
        assert reg is not None
        assert reg.show_mask.value is True
        assert view.value is True

    def test_external_sync_updates_view(self) -> None:
        rm = _FakeRegistersManager()
        adapter = RegisterAdapter(rm)
        p = CheckboxPresenter(
            BindingConfig("renderer", "show_mask"),
            adapter,
        )
        view = _FakeBoolView()
        p.attach_view(view)
        rm.set_field_value("renderer", "show_mask", True)
        assert view.value is True

    def test_set_access_level_without_view_safe(self) -> None:
        p = CheckboxPresenter(
            BindingConfig("renderer", "show_mask"),
            RegisterAdapter(_FakeRegistersManager()),
        )
        p.set_access_level(5)


@pytest.fixture
def qapp():
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestCheckboxControlFacade:
    def test_create_returns_widget_and_presenter(self, qapp) -> None:
        rm = _FakeRegistersManager()
        r = CheckboxControl.create(
            rm,
            BindingConfig("renderer", "show_mask"),
            CheckboxViewConfig(position="left"),
        )
        assert r.widget is not None
        assert r.presenter is not None
