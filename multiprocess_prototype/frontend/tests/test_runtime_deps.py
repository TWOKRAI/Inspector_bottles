# -*- coding: utf-8 -*-
"""Тесты двухслойного runtime-контракта FrameworkRuntime + RuntimeDeps (Ф5.8)."""

from __future__ import annotations

import dataclasses

from multiprocess_prototype.frontend.runtime_deps import FrameworkRuntime, RuntimeDeps

# Поля базового framework-слоя и app-extras — контракт расслоения.
_FRAMEWORK_FIELDS = {
    "command_sender",
    "topology_bridge",
    "bindings",
    "process_manager_proxy",
    "request_ui_restart",
    "data_bridge",
}
_APP_EXTRA_FIELDS = {
    "plugin_manager",
    "registers_manager",
    "auth_ctx",
    "image_panel",
    "persist_active_recipe",
}


def test_runtimedeps_is_frameworkruntime():
    """RuntimeDeps IS-A FrameworkRuntime — оболочка типизируется по базовому слою."""
    assert issubclass(RuntimeDeps, FrameworkRuntime)
    assert isinstance(RuntimeDeps(), FrameworkRuntime)


def test_framework_layer_fields():
    """Базовый слой содержит РОВНО framework-generic плумбинг."""
    assert {f.name for f in dataclasses.fields(FrameworkRuntime)} == _FRAMEWORK_FIELDS


def test_app_layer_extends_with_extras():
    """App-слой = базовый + app-extras, без потери и без пересечения."""
    app_fields = {f.name for f in dataclasses.fields(RuntimeDeps)}
    assert app_fields == _FRAMEWORK_FIELDS | _APP_EXTRA_FIELDS
    assert _FRAMEWORK_FIELDS.isdisjoint(_APP_EXTRA_FIELDS)


def test_defaults_all_none_minimal_app():
    """Все поля Optional/None — minimal_app поднимается без единого runtime-объекта."""
    fr = FrameworkRuntime()
    assert all(getattr(fr, name) is None for name in _FRAMEWORK_FIELDS)
    rd = RuntimeDeps()
    assert all(getattr(rd, name) is None for name in _FRAMEWORK_FIELDS | _APP_EXTRA_FIELDS)


def test_flat_construction_and_access_unchanged():
    """Потребители читают плоские поля обоих слоёв напрямую (наследование, ноль правок)."""
    rd = RuntimeDeps(command_sender="cs", plugin_manager="pm", data_bridge="db")
    assert rd.command_sender == "cs"  # framework-слой
    assert rd.plugin_manager == "pm"  # app-extra
    assert rd.data_bridge == "db"


def test_frozen():
    """Контракт неизменяем (frozen) — оба слоя."""
    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        FrameworkRuntime().command_sender = "x"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        RuntimeDeps().plugin_manager = "x"  # type: ignore[misc]
