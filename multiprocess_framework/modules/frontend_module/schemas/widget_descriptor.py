# -*- coding: utf-8 -*-
"""
WidgetDescriptor — схема описания виджета для декларативной сборки UI.

Используется WidgetRegistry для создания виджетов по конфигу.
"""
from typing import Annotated, Any, Dict, List, Optional

from multiprocess_framework.modules.frontend_module.schema_adapter import FieldMeta, SchemaBase


class WidgetDescriptor(SchemaBase):
    """
    Описание виджета для фабрики.

    Позволяет создавать виджеты из конфига (YAML/JSON/dict) без кода.
    """

    widget_type: Annotated[
        str,
        FieldMeta("Тип виджета", info="slider, checkbox, table, ..."),
    ] = "slider"

    register_name: Annotated[
        str,
        FieldMeta("Имя регистра", info="draw, camera, processing, ..."),
    ] = ""

    field_name: Annotated[
        str,
        FieldMeta("Имя поля", info="dp, enabled, threshold, ..."),
    ] = ""

    label: Annotated[
        Optional[str],
        FieldMeta("Текст метки", info="Переопределяет описание из метаданных"),
    ] = None

    position: Annotated[
        str,
        FieldMeta("Расположение метки", info="top, bottom, left, right"),
    ] = "left"

    layout_hints: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta("Подсказки layout", info="stretch, min_width, alignment"),
    ] = None

    visibility_rules: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta("Правила видимости", info="Условия показа виджета"),
    ] = None

    extra: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta("Дополнительные параметры", info="Специфичные для типа виджета"),
    ] = None

    ui_elements: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta("Словарь UI-элементов", info="Для SliderControl — сохранение element, value"),
    ] = None

    controls: Annotated[
        Optional[Any],
        FieldMeta("Словарь/список значений", info="Для синхронизации с другими контролами"),
    ] = None

    def to_factory_kwargs(self) -> Dict[str, Any]:
        """Преобразовать в kwargs для WidgetFactory.create()."""
        d: Dict[str, Any] = {
            "register_name": self.register_name,
            "field_name": self.field_name,
        }
        if self.label is not None:
            d["label"] = self.label
        if self.position:
            d["position"] = self.position
        if self.ui_elements is not None:
            d["ui_elements"] = self.ui_elements
        if self.controls is not None:
            d["controls"] = self.controls
        if self.extra:
            d.update(self.extra)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WidgetDescriptor":
        """Создать из словаря (config_module, YAML)."""
        return cls.model_validate(data)


def widget_descriptor_from_dict(data: Dict[str, Any]) -> WidgetDescriptor:
    """Удобная функция для создания дескриптора из dict."""
    return WidgetDescriptor.model_validate(data)
