"""FieldEditor — дата-контейнер для одного редактируемого поля формы.

Хранит виджет, getter/setter и сигнал изменения.
Используется CardsFieldFactory и form_builder / table_builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtCore import SignalInstance
    from PySide6.QtWidgets import QLabel, QWidget

    from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo


@dataclass
class FieldEditor:
    """Редактор одного поля регистра.

    Атрибуты:
        field_info: метаданные поля (тип, диапазон, единица, описание).
        widget: Qt-виджет для редактирования значения.
        getter: функция → текущее значение виджета.
        setter: функция(value) → установить значение в виджет.
        change_signal: SignalInstance, эмитится при изменении значения пользователем.
        label: QLabel с человекочитаемым названием поля.
    """

    field_info: FieldInfo
    widget: QWidget
    getter: Callable[[], Any]
    setter: Callable[[Any], None]
    change_signal: SignalInstance
    label: QLabel
