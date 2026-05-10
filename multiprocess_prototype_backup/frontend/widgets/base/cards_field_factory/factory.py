# multiprocess_prototype/frontend/widgets/cards_field_factory/factory.py
"""Фабрика виджетов для карточного представления: тип значения -> редактируемый виджет + getter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QCheckBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QWidget,
)


def create_field_widget(
    row: dict, parent: QWidget | None = None
) -> tuple[QWidget, Callable[[], Any]]:
    """
    Маппинг тип значения -> редактируемый виджет + getter текущего значения.

    Не подключает сигналы -- это делает вызывающий код.
    """
    value = row.get("value")
    editable = row.get("_value_editable", True)

    widget: QWidget
    getter: Callable[[], Any]

    if isinstance(value, bool):
        cb = QCheckBox(parent)
        cb.setChecked(value)
        if not editable:
            cb.setEnabled(False)
        widget = cb
        getter = lambda: cb.isChecked()  # noqa: E731

    elif isinstance(value, int):
        sb = QSpinBox(parent)
        sb.setRange(-999999, 999999)
        sb.setValue(value)
        if not editable:
            sb.setEnabled(False)
        widget = sb
        getter = lambda: sb.value()  # noqa: E731

    elif isinstance(value, float):
        dsb = QDoubleSpinBox(parent)
        dsb.setRange(-1e9, 1e9)
        dsb.setDecimals(6)
        dsb.setValue(value)
        if not editable:
            dsb.setEnabled(False)
        widget = dsb
        getter = lambda: dsb.value()  # noqa: E731

    elif isinstance(value, str):
        if len(value) > 120:
            te = QPlainTextEdit(parent)
            te.setPlainText(value)
            te.setReadOnly(True)
            te.setFixedHeight(60)
            if not editable:
                te.setEnabled(False)
            widget = te
            getter = lambda: te.toPlainText()  # noqa: E731
        else:
            le = QLineEdit(parent)
            le.setText(value)
            if not editable:
                le.setEnabled(False)
            widget = le
            getter = lambda: le.text()  # noqa: E731

    else:
        lbl = QLabel(str(value), parent)
        lbl.setEnabled(False)
        widget = lbl
        captured = value
        getter = lambda: captured  # noqa: E731

    return widget, getter
