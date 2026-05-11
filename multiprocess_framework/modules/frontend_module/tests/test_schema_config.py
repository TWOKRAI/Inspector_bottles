# -*- coding: utf-8 -*-
"""Тесты coerce_schema_config с SchemaBase-конфигами."""
from typing import Annotated, Literal, Optional

from multiprocess_framework.modules.frontend_module.schema_adapter import FieldMeta, SchemaBase, register_schema

from multiprocess_framework.modules.frontend_module.core.schema_config import coerce_schema_config


@register_schema("TestControlConfig")
class _TestControlConfig(SchemaBase):
    """Минимальный SchemaBase для тестов coerce_schema_config."""

    register_name: Annotated[Optional[str], FieldMeta("Регистр")] = None
    field_name: Annotated[Optional[str], FieldMeta("Поле")] = None
    label: Annotated[Optional[str], FieldMeta("Метка")] = None
    position: Annotated[Literal["left", "right"], FieldMeta("Позиция")] = "left"


class TestCoerceSchemaConfig:
    def test_none_returns_defaults(self) -> None:
        cfg = coerce_schema_config(None, _TestControlConfig)
        assert cfg.register_name is None
        assert cfg.field_name is None

    def test_instance_unchanged(self) -> None:
        original = _TestControlConfig(register_name="r", field_name="f")
        cfg = coerce_schema_config(original, _TestControlConfig)
        assert cfg is original

    def test_dict_validates(self) -> None:
        cfg = coerce_schema_config(
            {"register_name": "proc", "field_name": "x", "label": "L"},
            _TestControlConfig,
        )
        assert cfg.register_name == "proc"
        assert cfg.field_name == "x"
        assert cfg.label == "L"

    def test_position_dict(self) -> None:
        cfg = coerce_schema_config(
            {"register_name": "r", "field_name": "b", "position": "right"},
            _TestControlConfig,
        )
        assert cfg.position == "right"
