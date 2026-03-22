# -*- coding: utf-8 -*-
"""
Pydantic-схема конфигурации CheckboxControl.

Привязка к регистру и минимальные опции отображения (позиция подписи).
Текст подписи и описание по умолчанию — из метаданных поля регистра.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional

from data_schema_module import FieldMeta, SchemaBase


class CheckboxConfig(SchemaBase):
    """Конфигурация виджета CheckboxControl."""

    register_name: Annotated[
        Optional[str],
        FieldMeta("Имя регистра", info="Ключ в RegistersManager."),
    ] = None

    field_name: Annotated[
        Optional[str],
        FieldMeta("Имя поля", info="Поле в схеме регистра."),
    ] = None

    access_level: Annotated[
        int,
        FieldMeta("Уровень доступа", info="Минимальный уровень для редактирования."),
    ] = 0

    label: Annotated[
        Optional[str],
        FieldMeta("Текст метки", info="Переопределяет описание из метаданных регистра"),
    ] = None

    position: Annotated[
        Literal["left", "right", "top", "bottom"],
        FieldMeta("Расположение", info="Позиция метки относительно чекбокса"),
    ] = "left"
