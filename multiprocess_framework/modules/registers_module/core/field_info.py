# -*- coding: utf-8 -*-
"""FieldInfo — описание одного поля регистра для GUI.

Извлекает метаданные из Pydantic model_fields + FieldMeta.
Используется RegistersManager.get_fields() и прикладными GUI-фабриками.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...data_schema_module import FieldMeta


@dataclass(frozen=True)
class FieldInfo:
    """Описание одного поля регистра для GUI-генерации."""

    plugin_name: str
    field_name: str
    field_type: type
    default: Any
    meta: FieldMeta | None = None
    category: str = ""

    @property
    def title(self) -> str:
        """Человекочитаемое название поля."""
        if self.meta and self.meta.description:
            return self.meta.description
        return self.field_name

    @property
    def min_value(self) -> float | int | None:
        """Минимальное значение из FieldMeta."""
        return self.meta.min if self.meta else None

    @property
    def max_value(self) -> float | int | None:
        """Максимальное значение из FieldMeta."""
        return self.meta.max if self.meta else None

    @property
    def unit(self) -> str:
        """Единица измерения."""
        return getattr(self.meta, "unit", "") or "" if self.meta else ""

    @property
    def ui_group(self) -> str | None:
        """Группа для визуальной компоновки формы (build_form_for_schema)."""
        return self.meta.ui_group if self.meta else None

    @property
    def ui_order(self) -> int | None:
        """Порядок поля внутри формы (build_form_for_schema)."""
        return self.meta.ui_order if self.meta else None

    @property
    def ui_hidden(self) -> bool:
        """True — поле не должно показываться в сгенерированной форме."""
        return bool(self.meta.ui_hidden) if self.meta else False

    @property
    def ui_widget(self) -> str:
        """Widget-hint для резолвера kinds — алиас FieldMeta.widget (единый источник)."""
        return getattr(self.meta, "widget", "") or "" if self.meta else ""


def extract_fields(plugin_name: str, register_cls: type, category: str = "") -> list[FieldInfo]:
    """Извлечь FieldInfo из register-класса (Pydantic model).

    Args:
        plugin_name: Имя плагина-владельца.
        register_cls: SchemaBase-класс регистра.
        category: Категория плагина (source/processing/output).

    Returns:
        Список FieldInfo для всех полей модели.
    """
    result: list[FieldInfo] = []

    for name, field_info in register_cls.model_fields.items():
        # Извлечь FieldMeta из Annotated metadata
        meta = None
        for m in field_info.metadata:
            if isinstance(m, FieldMeta):
                meta = m
                break

        result.append(
            FieldInfo(
                plugin_name=plugin_name,
                field_name=name,
                field_type=field_info.annotation or type(None),
                default=field_info.default,
                meta=meta,
                category=category,
            )
        )

    return result
