# -*- coding: utf-8 -*-
"""Тесты WindowRegistry и WindowConfig."""

from multiprocess_framework.modules.frontend_module.core.window_registry import WindowRegistry
from multiprocess_framework.modules.frontend_module.schemas.window_config import WindowConfig


class TestWindowRegistry:
    def test_register_and_create(self) -> None:
        registry = WindowRegistry()
        registry.register("test", lambda **kw: type("FakeWindow", (), {"title": kw.get("title", "")})())
        w = registry.create("test", title="Hello")
        assert w is not None
        assert w.title == "Hello"

    def test_singleton(self) -> None:
        registry = WindowRegistry()
        call_count = 0

        def factory(**kw):
            nonlocal call_count
            call_count += 1
            return object()

        registry.register("single", factory, singleton=True)
        w1 = registry.create("single")
        w2 = registry.create("single")
        assert w1 is w2
        assert call_count == 1

    def test_list_windows(self) -> None:
        registry = WindowRegistry()
        registry.register("a", lambda: None)
        registry.register("b", lambda: None)
        assert registry.list_windows() == ["a", "b"]


class TestWindowConfig:
    def test_from_dict(self) -> None:
        cfg = WindowConfig.model_validate(
            {
                "window_id": "main",
                "title": "TestApp",
                "width": 1024,
                "height": 768,
                "widgets": [
                    {"widget_type": "slider", "register_name": "draw", "field_name": "dp"},
                    {"widget_type": "checkbox", "register_name": "draw", "field_name": "circles"},
                ],
            }
        )
        assert cfg.window_id == "main"
        assert cfg.title == "TestApp"
        assert len(cfg.widgets) == 2
        assert cfg.widgets[0]["register_name"] == "draw"
