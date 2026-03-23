# -*- coding: utf-8 -*-
"""Тесты tabs/callbacks_base: callback_no_args и dataclass ↔ dict."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

import pytest

from frontend_module.components.tabs import (
    callback_no_args,
    tab_callbacks_from_dict,
    tab_callbacks_to_dict,
)


def test_callback_no_args_invokes_without_qt_args() -> None:
    called: list[int] = []

    def fn() -> None:
        called.append(1)

    wrapped = callback_no_args(fn)
    wrapped(False)
    wrapped(True, extra="x")
    assert called == [1, 1]


def test_callback_no_args_none_is_noop() -> None:
    wrapped = callback_no_args(None)
    wrapped(1, 2, 3)


@dataclass(frozen=True)
class _SampleCallbacks:
    on_a: Optional[Callable[[], None]] = None
    on_b: Optional[Callable[[int], None]] = None


def test_tab_callbacks_from_dict_uses_dataclass_fields() -> None:
    d: dict[str, Any] = {"on_a": None, "on_b": None, "extra": 1}
    c = tab_callbacks_from_dict(_SampleCallbacks, d)
    assert isinstance(c, _SampleCallbacks)
    assert c.on_a is None and c.on_b is None


def test_tab_callbacks_to_dict_uses_dataclass_fields() -> None:
    c = _SampleCallbacks(on_a=lambda: None)
    out = tab_callbacks_to_dict(c)
    assert set(out.keys()) == {"on_a", "on_b"}
    assert out["on_b"] is None
    assert callable(out["on_a"])


def test_tab_callbacks_explicit_field_names_subset() -> None:
    c = tab_callbacks_from_dict(_SampleCallbacks, {}, field_names=("on_a",))
    assert c.on_a is None and c.on_b is None  # on_b default from dataclass


def test_tab_callbacks_from_dict_rejects_non_dataclass() -> None:
    class NotDc:
        pass

    with pytest.raises(TypeError):
        tab_callbacks_from_dict(NotDc, {})  # type: ignore[type-var]
