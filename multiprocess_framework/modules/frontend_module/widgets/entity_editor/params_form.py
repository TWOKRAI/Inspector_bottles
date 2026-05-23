"""ParamsForm — авто-генерируемая форма параметров из Pydantic-схемы.

Строит виджеты по типам полей params_class:
  - bool       -> QCheckBox
  - int        -> QSpinBox (range из FieldMeta.min/max)
  - float      -> QDoubleSpinBox (decimals=3, suffix из FieldMeta.unit)
  - Literal[…] -> QComboBox
  - List[int] длины 3 -> 3 QSpinBox в горизонтальном layout
  - str        -> QLineEdit
  - остальное  -> readonly QLabel «(неподдерживаемый тип)»

Сигнал params_changed(dict) испускается при любом изменении виджета.
"""

from __future__ import annotations

import logging
import typing
from copy import deepcopy
from typing import Any, get_args, get_origin

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
    Signal,
)

logger = logging.getLogger(__name__)

# Границы по умолчанию для числовых виджетов без FieldMeta min/max
_DEFAULT_INT_MIN = -1_000_000_000
_DEFAULT_INT_MAX = 1_000_000_000
_DEFAULT_FLOAT_MIN = -1e9
_DEFAULT_FLOAT_MAX = 1e9


def _get_literal_args(annotation: Any) -> tuple[Any, ...] | None:
    """Извлечь аргументы Literal[...] из аннотации. None если не Literal."""
    origin = get_origin(annotation)
    if origin is typing.Literal:
        return get_args(annotation)
    return None


def _is_list_int(annotation: Any) -> bool:
    """Проверить что аннотация это List[int]."""
    origin = get_origin(annotation)
    if origin is list:
        args = get_args(annotation)
        if args and args[0] is int:
            return True
    return False


class ParamsForm(QWidget):
    """Авто-генерируемая форма параметров операции.

    Строит виджеты по Pydantic-модели (params_class) с учётом FieldMeta.
    При изменении любого виджета испускает params_changed с полным dict параметров.
    """

    params_changed = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QFormLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        # Текущие параметры (полный dict)
        self._current_params: dict[str, Any] = {}
        # Маппинг имя_поля → виджет (для чтения значений)
        self._field_widgets: dict[str, QWidget] = {}
        # Блокировка рекурсивных сигналов
        self._suppress_signals = False

    def set_schema(
        self,
        params_class: type | None,
        current_params: dict[str, Any],
    ) -> None:
        """Построить форму по params_class и заполнить текущими значениями.

        Args:
            params_class: Pydantic-модель параметров (или None — нет параметров).
            current_params: Текущие значения параметров из ProcessingNode.params.
        """
        self._clear_form()
        self._current_params = deepcopy(current_params)
        self._field_widgets.clear()

        if params_class is None:
            placeholder = QLabel("Нет параметров")
            placeholder.setObjectName("MutedLabel")
            self._layout.addRow(placeholder)
            return

        # Получаем FieldMeta для всех полей (если класс наследует SchemaBase)
        fields_meta: dict[str, Any] = {}
        if hasattr(params_class, "get_all_fields_meta"):
            fields_meta = params_class.get_all_fields_meta()

        # Получаем Pydantic model_fields
        model_fields = params_class.model_fields

        for field_name, field_info in model_fields.items():
            # Пропускаем поле 'type' — это discriminator literal
            if field_name == "type":
                continue

            meta = fields_meta.get(field_name)
            annotation = field_info.annotation
            default_value = current_params.get(field_name, field_info.default)

            # Подпись поля: FieldMeta.description (label) или snake_case имя
            label = meta.description if meta and meta.description else field_name
            tooltip = meta.info if meta and meta.info else ""

            widget = self._create_widget(
                field_name=field_name,
                annotation=annotation,
                meta=meta,
                current_value=default_value,
            )

            if widget is not None:
                if tooltip:
                    widget.setToolTip(tooltip)
                self._field_widgets[field_name] = widget
                self._layout.addRow(label, widget)

    def _create_widget(
        self,
        field_name: str,
        annotation: Any,
        meta: Any,
        current_value: Any,
    ) -> QWidget | None:
        """Создать виджет по типу поля."""

        # 1. Literal[...] -> QComboBox
        literal_args = _get_literal_args(annotation)
        if literal_args is not None:
            return self._make_combo(field_name, literal_args, current_value)

        # 2. bool -> QCheckBox
        if annotation is bool:
            return self._make_checkbox(field_name, current_value)

        # 3. int -> QSpinBox
        if annotation is int:
            return self._make_spinbox(field_name, meta, current_value)

        # 4. float -> QDoubleSpinBox
        if annotation is float:
            return self._make_double_spinbox(field_name, meta, current_value)

        # 5. List[int] -> 3 QSpinBox или QLineEdit fallback
        if _is_list_int(annotation):
            return self._make_list_int_widget(field_name, meta, current_value)

        # 6. str -> QLineEdit
        if annotation is str:
            return self._make_line_edit(field_name, current_value)

        # 7. Неподдерживаемый тип
        lbl = QLabel("(неподдерживаемый тип)")
        lbl.setObjectName("MutedLabel")
        return lbl

    # ------------------------------------------------------------------
    # Фабрики виджетов
    # ------------------------------------------------------------------

    def _make_combo(
        self,
        field_name: str,
        args: tuple[Any, ...],
        current: Any,
    ) -> QComboBox:
        combo = QComboBox()
        for arg in args:
            combo.addItem(str(arg), arg)
        if current is not None:
            idx = combo.findData(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.currentIndexChanged.connect(
            lambda _idx, fn=field_name: self._on_widget_changed(fn),
        )
        return combo

    def _make_checkbox(
        self,
        field_name: str,
        current: Any,
    ) -> QCheckBox:
        cb = QCheckBox()
        cb.setChecked(bool(current) if current is not None else False)
        cb.toggled.connect(
            lambda _val, fn=field_name: self._on_widget_changed(fn),
        )
        return cb

    def _make_spinbox(
        self,
        field_name: str,
        meta: Any,
        current: Any,
    ) -> QSpinBox:
        sb = QSpinBox()
        min_val = int(meta.min) if meta and meta.min is not None else _DEFAULT_INT_MIN
        max_val = int(meta.max) if meta and meta.max is not None else _DEFAULT_INT_MAX
        sb.setRange(min_val, max_val)
        if meta and meta.unit:
            sb.setSuffix(f" {meta.unit}")
        sb.setValue(int(current) if current is not None else 0)
        sb.valueChanged.connect(
            lambda _val, fn=field_name: self._on_widget_changed(fn),
        )
        return sb

    def _make_double_spinbox(
        self,
        field_name: str,
        meta: Any,
        current: Any,
    ) -> QDoubleSpinBox:
        dsb = QDoubleSpinBox()
        dsb.setDecimals(3)
        min_val = float(meta.min) if meta and meta.min is not None else _DEFAULT_FLOAT_MIN
        max_val = float(meta.max) if meta and meta.max is not None else _DEFAULT_FLOAT_MAX
        dsb.setRange(min_val, max_val)
        if meta and meta.unit:
            dsb.setSuffix(f" {meta.unit}")
        dsb.setValue(float(current) if current is not None else 0.0)
        dsb.valueChanged.connect(
            lambda _val, fn=field_name: self._on_widget_changed(fn),
        )
        return dsb

    def _make_list_int_widget(
        self,
        field_name: str,
        meta: Any,
        current: Any,
    ) -> QWidget:
        """List[int] — если длина == 3, создаём 3 QSpinBox; иначе QLineEdit (CSV)."""
        current_list = list(current) if current else []

        if len(current_list) == 3:
            container = QWidget()
            hbox = QHBoxLayout(container)
            hbox.setContentsMargins(0, 0, 0, 0)

            spinboxes: list[QSpinBox] = []
            for i, val in enumerate(current_list):
                sb = QSpinBox()
                sb.setRange(0, 255)  # BGR значения
                sb.setValue(int(val))
                sb.valueChanged.connect(
                    lambda _val, fn=field_name: self._on_widget_changed(fn),
                )
                spinboxes.append(sb)
                hbox.addWidget(sb)

            # Сохраняем список спинбоксов как атрибут контейнера для чтения
            container._spinboxes = spinboxes  # type: ignore[attr-defined]
            return container

        # Fallback: QLineEdit с CSV
        le = QLineEdit()
        le.setText(",".join(str(v) for v in current_list))
        le.editingFinished.connect(
            lambda fn=field_name: self._on_widget_changed(fn),
        )
        return le

    def _make_line_edit(
        self,
        field_name: str,
        current: Any,
    ) -> QLineEdit:
        le = QLineEdit()
        le.setText(str(current) if current is not None else "")
        le.editingFinished.connect(
            lambda fn=field_name: self._on_widget_changed(fn),
        )
        return le

    # ------------------------------------------------------------------
    # Чтение значений из виджетов
    # ------------------------------------------------------------------

    def _read_widget_value(self, field_name: str) -> Any:
        """Прочитать текущее значение виджета по имени поля."""
        widget = self._field_widgets.get(field_name)
        if widget is None:
            return self._current_params.get(field_name)

        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QComboBox):
            return widget.currentData()
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QDoubleSpinBox):
            return widget.value()
        if isinstance(widget, QLineEdit):
            return widget.text()

        # List[int] container с _spinboxes
        if hasattr(widget, "_spinboxes"):
            return [sb.value() for sb in widget._spinboxes]

        return self._current_params.get(field_name)

    def _collect_all_params(self) -> dict[str, Any]:
        """Собрать полный dict параметров из всех виджетов."""
        result = deepcopy(self._current_params)
        for field_name in self._field_widgets:
            result[field_name] = self._read_widget_value(field_name)
        return result

    # ------------------------------------------------------------------
    # Обработка изменений
    # ------------------------------------------------------------------

    def _on_widget_changed(self, field_name: str) -> None:
        """Вызывается при изменении любого виджета."""
        if self._suppress_signals:
            return
        new_params = self._collect_all_params()
        self._current_params = deepcopy(new_params)
        self.params_changed.emit(new_params)

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    def _clear_form(self) -> None:
        """Удалить все строки из QFormLayout."""
        while self._layout.rowCount() > 0:
            self._layout.removeRow(0)

    def set_values_silent(self, params: dict[str, Any]) -> None:
        """Установить значения виджетов без испускания сигнала (для undo/redo refresh)."""
        self._suppress_signals = True
        try:
            self._current_params = deepcopy(params)
            for field_name, widget in self._field_widgets.items():
                val = params.get(field_name)
                if val is None:
                    continue
                if isinstance(widget, QCheckBox):
                    widget.setChecked(bool(val))
                elif isinstance(widget, QComboBox):
                    idx = widget.findData(val)
                    if idx >= 0:
                        widget.setCurrentIndex(idx)
                elif isinstance(widget, QSpinBox):
                    widget.setValue(int(val))
                elif isinstance(widget, QDoubleSpinBox):
                    widget.setValue(float(val))
                elif isinstance(widget, QLineEdit):
                    widget.setText(str(val))
                elif hasattr(widget, "_spinboxes") and isinstance(val, list):
                    for i, sb in enumerate(widget._spinboxes):
                        if i < len(val):
                            sb.setValue(int(val[i]))
        finally:
            self._suppress_signals = False


__all__ = ["ParamsForm"]
