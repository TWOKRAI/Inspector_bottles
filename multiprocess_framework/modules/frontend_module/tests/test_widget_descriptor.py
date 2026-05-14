# -*- coding: utf-8 -*-
"""Тесты WidgetDescriptor."""

from multiprocess_framework.modules.frontend_module.schemas.widget_descriptor import (
    WidgetDescriptor,
    widget_descriptor_from_dict,
)


class TestWidgetDescriptor:
    def test_from_dict(self) -> None:
        d = widget_descriptor_from_dict(
            {
                "widget_type": "slider",
                "register_name": "draw",
                "field_name": "dp",
            }
        )
        assert d.widget_type == "slider"
        assert d.register_name == "draw"
        assert d.field_name == "dp"

    def test_to_factory_kwargs(self) -> None:
        d = WidgetDescriptor(
            widget_type="checkbox",
            register_name="camera",
            field_name="enabled",
            label="Камера",
        )
        kwargs = d.to_factory_kwargs()
        assert kwargs["register_name"] == "camera"
        assert kwargs["field_name"] == "enabled"
        assert kwargs["label"] == "Камера"
