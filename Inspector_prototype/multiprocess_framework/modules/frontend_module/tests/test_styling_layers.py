# -*- coding: utf-8 -*-
"""Тесты каскада токенов и QSS."""
from __future__ import annotations

import pytest

from frontend_module.styling import (
    NamedStyleRegistry,
    StyleSession,
    merge_token_layers,
    render_qss,
)


@pytest.fixture
def qapp():
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_merge_token_layers_order() -> None:
    g = {"a": "1", "b": "1"}
    w = {"b": "2", "c": "2"}
    c = {"c": "3"}
    m = merge_token_layers(g, w, c)
    assert m == {"a": "1", "b": "2", "c": "3"}


def test_merge_token_layers_skips_none() -> None:
    assert merge_token_layers({"x": 1}, None, {"y": 2}) == {"x": 1, "y": 2}


def test_render_qss() -> None:
    assert render_qss("color: {c};", {"c": "#fff"}) == "color: #fff;"


def test_render_qss_missing_key_unchanged() -> None:
    assert render_qss("x: {missing};", {"other": 1}) == "x: {missing};"


def test_named_registry_and_session_refresh(qapp) -> None:
    from frontend_module.core.qt_imports import QWidget

    reg = NamedStyleRegistry()
    reg.register("box", "QWidget {{ background: {bg}; }}", {"bg": "#000000"})
    session = StyleSession(registry=reg)
    session.set_global_tokens({"bg": "#111111"})
    w = QWidget()
    reg_id = session.register(
        w,
        style_id="box",
        widget_layer={"bg": "#222222"},
        component_layer={"bg": "#333333"},
    )
    assert "#333333" in w.styleSheet()
    session.update_global_tokens({"bg": "#aaaaaa"})
    session.refresh("box")
    assert "#333333" in w.styleSheet()
    ok = session.update_registration(
        reg_id,
        component_layer={"bg": "#eeeeee"},
    )
    assert ok
    assert "#eeeeee" in w.styleSheet()


def test_framework_default_bundles_qss_on_disk() -> None:
    from frontend_module.styling.default_bundles import iter_bundle_specs

    for spec in iter_bundle_specs():
        assert spec.qss_path.is_file(), spec.qss_path


def test_create_app_style_session_registers_builtin_styles() -> None:
    from frontend_module.styling import create_app_style_session

    session = create_app_style_session()
    assert session.registry.has("app_slider_handle")
    assert len(list(session.registry.names())) == 7


def test_refresh_filters_by_style_id(qapp) -> None:
    from frontend_module.core.qt_imports import QWidget

    reg = NamedStyleRegistry()
    reg.register("a", "QWidget { color: {c}; }", {"c": "red"})
    reg.register("b", "QWidget { color: {c}; }", {"c": "blue"})
    session = StyleSession(registry=reg)
    wa = QWidget()
    wb = QWidget()
    session.register(wa, style_id="a")
    session.register(wb, style_id="b")
    session.set_global_tokens({"c": "green"})
    session.refresh("a")
    assert "green" in wa.styleSheet()
    assert "blue" in wb.styleSheet()
