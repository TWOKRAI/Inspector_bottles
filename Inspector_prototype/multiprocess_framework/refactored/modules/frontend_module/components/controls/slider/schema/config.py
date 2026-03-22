# -*- coding: utf-8 -*-
"""
Pydantic-схема конфигурации SliderControl (не путать со схемой регистра приложения).

Содержит привязку к полю (register_name, field_name, access_level) и опции UI.
Метаданные min, max, unit, default приходят из схемы регистра и `ResolvedMeta`.
"""
from __future__ import annotations

from typing import Annotated, Any, Optional

from data_schema_module import FieldMeta, SchemaBase


class SliderConfig(SchemaBase):
    """
    Конфигурация виджета SliderControl.

    Поля привязки дублируются в ``model_dump`` для ``BaseConfigurableWidget._config_to_dict``.
    """

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

    transfer_k: Annotated[
        Optional[float],
        FieldMeta("Коэффициент переноса", info="Шаг слайдера = 1/transfer_k"),
    ] = None

    round_k: Annotated[
        Optional[int],
        FieldMeta("Знаков после запятой", info="0 — целые числа"),
    ] = None

    ui_elements: Annotated[
        Optional[dict],
        FieldMeta("Словарь UI-элементов", info="Для сохранения element, value"),
    ] = None

    controls: Annotated[
        Optional[Any],
        FieldMeta("Словарь/список значений", info="Синхронизация с другими контролами"),
    ] = None

    callback: Annotated[
        Optional[Any],
        FieldMeta("Callback при изменении", info="Вызывается после set_field_value"),
    ] = None

    touch_keyboard_factory: Annotated[
        Optional[Any],
        FieldMeta("Фабрика touch-клавиатуры", info="Callable[[], keyboard_widget]"),
    ] = None
