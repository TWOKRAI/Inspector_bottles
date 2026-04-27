# multiprocess_prototype_v3/frontend/widgets/settings_tab/settings_cards.py
"""Карточное представление настроек: группы (QGroupBox) с QFormLayout полей."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    Signal,
)

from ...base.cards_field_factory import create_field_widget


class SettingsCardsView(QWidget):
    """Карточное представление: группировка по schema_name / register_name."""

    value_changed = Signal(str, object)  # (field_id, new_value)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._widgets: dict[str, QWidget] = {}  # field_id -> виджет поля
        self._getters: dict[str, Callable[[], Any]] = {}  # field_id -> getter

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._inner = QWidget()
        self._inner_layout = QVBoxLayout(self._inner)
        self._scroll.setWidget(self._inner)
        layout.addWidget(self._scroll)

    def load_from_rows(self, rows: list[dict]) -> None:
        """Полная перестройка карточек из списка row-dict."""
        # Очистить старое содержимое
        self._widgets.clear()
        self._getters.clear()
        # QScrollArea.setWidget() сам удаляет предыдущий — НЕ вызываем deleteLater на old_inner
        self._inner = QWidget()
        self._inner_layout = QVBoxLayout(self._inner)
        self._scroll.setWidget(self._inner)

        # Группировка: schema_name предпочтительнее, иначе register_name
        group_key = "schema_name" if any("schema_name" in r for r in rows) else "register_name"
        groups: OrderedDict[str, list[dict]] = OrderedDict()
        for r in rows:
            g = str(r.get(group_key, ""))
            groups.setdefault(g, []).append(r)

        for group_name, group_rows in groups.items():
            box = QGroupBox(group_name)
            form = QFormLayout(box)

            for row in group_rows:
                field_id = str(row.get("field_id", ""))
                param = str(row.get("param", ""))
                label_text = param.split(".")[-1] if "." in param else param
                tooltip = str(row.get("info", ""))

                widget, getter = create_field_widget(row, parent=box)
                if tooltip:
                    widget.setToolTip(tooltip)

                label = QLabel(label_text)
                if tooltip:
                    label.setToolTip(tooltip)

                form.addRow(label, widget)

                self._widgets[field_id] = widget
                self._getters[field_id] = getter

                # Подключить сигнал изменения
                self._connect_widget_signal(field_id, widget)

            self._inner_layout.addWidget(box)

        self._inner_layout.addStretch()

    def set_leaf_value(self, field_id: str, value: object) -> None:
        """Обновить виджет поля без полного rebuild."""
        widget = self._widgets.get(field_id)
        if widget is None:
            return

        widget.blockSignals(True)
        try:
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(value))  # type: ignore[arg-type]
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(value))  # type: ignore[arg-type]
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value))
        finally:
            widget.blockSignals(False)

    def _on_field_changed(self, field_id: str) -> None:
        getter = self._getters.get(field_id)
        if getter is not None:
            self.value_changed.emit(field_id, getter())

    def _connect_widget_signal(self, field_id: str, widget: QWidget) -> None:
        """Подключить сигнал виджета к _on_field_changed по field_id."""
        fid = field_id  # замкнуть в лямбду
        if isinstance(widget, QCheckBox):
            widget.toggled.connect(lambda _: self._on_field_changed(fid))
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.valueChanged.connect(lambda _: self._on_field_changed(fid))
        elif isinstance(widget, QLineEdit):
            widget.editingFinished.connect(lambda: self._on_field_changed(fid))
