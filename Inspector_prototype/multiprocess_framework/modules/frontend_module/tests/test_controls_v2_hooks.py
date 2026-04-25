# -*- coding: utf-8 -*-
"""Хуки ControlHooks и smoke SliderControl/SpinBoxControl после выделения presenter."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import pytest
from unittest.mock import patch

from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
from multiprocess_framework.modules.frontend_module.components.base.control_hooks import (
    ControlAccessDeniedEvent,
    ControlHooks,
    ControlWriteCommittedEvent,
    ControlWriteRejectedEvent,
)
from multiprocess_framework.modules.frontend_module.components.checkbox import CheckboxControl
from multiprocess_framework.modules.frontend_module.components.slider import SliderControl, SliderConfig
from multiprocess_framework.modules.frontend_module.components.spinbox import SpinBoxControl, SpinBoxConfig


@dataclass
class _Field:
    value: Any


@dataclass
class _FakeRegister:
    min_area: _Field
    flag: _Field


class _FakeRMRejectWrite:
    def __init__(self) -> None:
        self._registers: Dict[str, Any] = {
            "processor": _FakeRegister(min_area=_Field(10), flag=_Field(False)),
        }
        self._subs: Dict[tuple, List[Callable[[Any], None]]] = {}
        self._meta: Dict[tuple, dict] = {
            ("processor", "min_area"): {
                "min": 0,
                "max": 100,
                "description": "Area",
                "transfer_k": 1.0,
                "round_k": 0,
            },
            ("processor", "flag"): {"description": "F"},
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
        return False, "rejected by fake"

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


class _FakeRMOk:
    """Пишет значения; для теста committed."""

    def __init__(self) -> None:
        self._registers: Dict[str, Any] = {
            "processor": _FakeRegister(min_area=_Field(10), flag=_Field(False)),
        }
        self._subs: Dict[tuple, List[Callable[[Any], None]]] = {}
        self._meta: Dict[tuple, dict] = {
            ("processor", "min_area"): {
                "min": 0,
                "max": 100,
                "transfer_k": 1.0,
                "round_k": 0,
            },
            ("processor", "flag"): {},
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


@pytest.fixture
def qapp():
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestCheckboxHooks:
    def test_write_rejected_hook(self, qapp) -> None:
        rm = _FakeRMRejectWrite()
        rejected: list[ControlWriteRejectedEvent] = []

        def on_rejected(ev: ControlWriteRejectedEvent) -> None:
            rejected.append(ev)

        r = CheckboxControl.create(
            rm,
            BindingConfig("processor", "flag"),
            hooks=ControlHooks(on_write_rejected=on_rejected),
        )
        from multiprocess_framework.modules.frontend_module.components.checkbox.view import CheckboxView

        assert isinstance(r.widget, CheckboxView)
        with patch(
            "frontend_module.components.checkbox.view.QMessageBox.warning"
        ):
            r.widget._checkbox.setChecked(True)
        assert len(rejected) >= 1
        assert rejected[0].control_kind == "checkbox"
        assert rejected[0].register_name == "processor"

    def test_write_committed_hook(self, qapp) -> None:
        rm = _FakeRMOk()
        committed: list[ControlWriteCommittedEvent] = []

        r = CheckboxControl.create(
            rm,
            BindingConfig("processor", "flag"),
            hooks=ControlHooks(on_write_committed=committed.append),
        )
        r.widget._checkbox.setChecked(True)
        assert len(committed) >= 1
        assert committed[0].value is True


class TestAccessDeniedHook:
    def test_checkbox_access_denied(self, qapp) -> None:
        rm = _FakeRMOk()
        denied: list[ControlAccessDeniedEvent] = []
        r = CheckboxControl.create(
            rm,
            BindingConfig("processor", "flag", access_level=5),
            hooks=ControlHooks(on_access_denied=denied.append),
            current_access_level=0,
        )
        from multiprocess_framework.modules.frontend_module.components.checkbox.view import CheckboxView

        assert isinstance(r.widget, CheckboxView)
        r.widget._checkbox.setChecked(True)
        assert len(denied) == 1
        assert denied[0].control_kind == "checkbox"
        assert denied[0].attempted_value is True

    def test_slider_access_denied_on_finished(self, qapp) -> None:
        rm = _FakeRMOk()
        denied: list[ControlAccessDeniedEvent] = []
        r = SliderControl.create(
            rm,
            BindingConfig("processor", "min_area", access_level=9),
            hooks=ControlHooks(on_access_denied=denied.append),
            current_access_level=0,
        )
        r.presenter._on_finished(3.0)
        assert len(denied) == 1
        assert denied[0].control_kind == "slider"
        assert denied[0].attempted_value == 3.0


class TestSliderSpinboxHooksAndTypes:
    def test_slider_rejected_hook(self, qapp) -> None:
        rm = _FakeRMRejectWrite()
        rejected: list[ControlWriteRejectedEvent] = []

        r = SliderControl.create(
            rm,
            BindingConfig("processor", "min_area"),
            SliderConfig(),
            hooks=ControlHooks(on_write_rejected=rejected.append),
        )
        from multiprocess_framework.modules.frontend_module.components.slider.presenter import SliderPresenter

        assert isinstance(r.presenter, SliderPresenter)
        with patch(
            "frontend_module.components.group.view.QMessageBox.warning"
        ):
            r.presenter._on_finished(5.0)
        assert len(rejected) >= 1
        assert rejected[0].control_kind == "slider"

    def test_spinbox_presenter_type(self, qapp) -> None:
        rm = _FakeRMRejectWrite()
        r = SpinBoxControl.create(
            rm,
            BindingConfig("processor", "min_area"),
            SpinBoxConfig(),
        )
        from multiprocess_framework.modules.frontend_module.components.spinbox.presenter import SpinBoxPresenter

        assert isinstance(r.presenter, SpinBoxPresenter)
