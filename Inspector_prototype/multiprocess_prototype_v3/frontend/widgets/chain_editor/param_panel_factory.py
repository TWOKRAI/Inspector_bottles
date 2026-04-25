"""
Фабрика панелей параметров операций для Chain Editor.

Генерирует QWidget с QFormLayout на основе Pydantic-схемы (ProcessingParamsBase).
Обратная операция: collect_params_from_panel — собирает значения из виджетов в dict.
"""
from __future__ import annotations

import importlib
from typing import Any, get_args, get_origin

try:
    from multiprocess_framework.modules.frontend_module.core.qt_imports import (
        QCheckBox,
        QDoubleSpinBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QSpinBox,
        QWidget,
    )
except ImportError:
    from PyQt5.QtWidgets import (  # type: ignore[no-reattr]
        QCheckBox,
        QDoubleSpinBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QSpinBox,
        QWidget,
    )

from multiprocess_framework.modules.data_schema_module import FieldMeta

# Ключ атрибута для хранения маппинга field_name → виджет (или список виджетов)
_FIELD_WIDGET_MAP_ATTR = "_field_widget_map"

# Максимальный диапазон для int-полей без явного min/max
_INT_MIN_DEFAULT = 0
_INT_MAX_DEFAULT = 999_999


def _load_schema_class(params_schema_path: str) -> type:
    """Загрузить класс схемы по dotted path.

    Последний сегмент — имя класса, остальное — путь к модулю.
    """
    if "." not in params_schema_path:
        raise ImportError(
            f"Некорректный params_schema_path '{params_schema_path}': "
            "ожидается полный dotted path вида 'package.module.ClassName'."
        )
    module_dotted, class_name = params_schema_path.rsplit(".", maxsplit=1)
    try:
        module = importlib.import_module(module_dotted)
    except ModuleNotFoundError as exc:
        raise ImportError(
            f"Модуль '{module_dotted}' не найден (params_schema_path='{params_schema_path}')."
        ) from exc
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ImportError(
            f"Класс '{class_name}' не найден в модуле '{module_dotted}'."
        )
    return cls


def _extract_field_meta(field_info: Any) -> FieldMeta | None:
    """Извлечь первый FieldMeta из metadata поля Pydantic v2."""
    for item in getattr(field_info, "metadata", []):
        if isinstance(item, FieldMeta):
            return item
    return None


def _is_list_int(annotation: Any) -> bool:
    """Проверить, является ли аннотация List[int]."""
    origin = get_origin(annotation)
    if origin is list:
        args = get_args(annotation)
        return bool(args) and args[0] is int
    return False


def _make_bgr_widget(label_text: str, current_value: list[int] | None) -> tuple[QWidget, list[QSpinBox]]:
    """Создать виджет для BGR-поля: контейнер с 3 QSpinBox (0..255).

    Возвращает (контейнер, список спинбоксов [B, G, R]).
    """
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    # Значения по умолчанию: [0, 0, 0] или из current_value
    values = current_value if (current_value and len(current_value) == 3) else [0, 0, 0]
    spinboxes: list[QSpinBox] = []

    for ch_label, val in zip(("B", "G", "R"), values):
        lbl = QLabel(ch_label)
        layout.addWidget(lbl)
        sb = QSpinBox()
        sb.setRange(0, 255)
        sb.setValue(int(val))
        layout.addWidget(sb)
        spinboxes.append(sb)

    return container, spinboxes


def _make_int_widget(meta: FieldMeta | None, current_value: int | None) -> QSpinBox:
    """Создать QSpinBox для int-поля с учётом FieldMeta.min / FieldMeta.max."""
    sb = QSpinBox()
    lo = int(meta.min) if (meta and meta.min is not None) else _INT_MIN_DEFAULT
    hi = int(meta.max) if (meta and meta.max is not None) else _INT_MAX_DEFAULT
    sb.setRange(lo, hi)
    if current_value is not None:
        sb.setValue(int(current_value))
    return sb


def _make_float_widget(meta: FieldMeta | None, current_value: float | None) -> QDoubleSpinBox:
    """Создать QDoubleSpinBox для float-поля."""
    dsb = QDoubleSpinBox()
    dsb.setDecimals(3)
    if meta:
        if meta.min is not None:
            dsb.setMinimum(float(meta.min))
        if meta.max is not None:
            dsb.setMaximum(float(meta.max))
    if current_value is not None:
        dsb.setValue(float(current_value))
    return dsb


def _make_bool_widget(label_text: str, current_value: bool | None) -> QCheckBox:
    """Создать QCheckBox для bool-поля."""
    cb = QCheckBox()
    cb.setChecked(bool(current_value) if current_value is not None else False)
    return cb


def build_param_panel(params_schema_path: str, current_params: dict | None = None) -> QWidget:
    """Построить QWidget с параметрами операции по dotted path к схеме.

    Загружает класс схемы, инстанцирует его с current_params (или дефолтами),
    затем для каждого поля (кроме 'type') создаёт подходящий виджет.

    Маппинг field_name → виджет сохраняется в атрибуте панели через setattr.

    Args:
        params_schema_path: Dotted path до класса схемы, напр.
            'registers.processor.processings.color_detection.ColorDetectionParams'
        current_params: Текущие параметры (словарь) или None для дефолтов.

    Returns:
        QWidget с QFormLayout, содержащий виджеты всех редактируемых полей.
    """
    # --- Загрузка класса и инстанцирование ---
    schema_cls = _load_schema_class(params_schema_path)
    if current_params:
        # Игнорируем лишние ключи через model_validate
        instance = schema_cls.model_validate(current_params)
    else:
        instance = schema_cls()

    # --- Создание панели ---
    panel = QWidget()
    form = QFormLayout(panel)
    form.setContentsMargins(4, 4, 4, 4)
    form.setSpacing(6)

    # Маппинг: field_name → виджет или список виджетов для BGR
    field_widget_map: dict[str, Any] = {}

    for field_name, field_info in schema_cls.model_fields.items():
        # Поле 'type' (Literal) не показываем в UI
        if field_name == "type":
            continue

        meta = _extract_field_meta(field_info)
        # Лейбл: описание из FieldMeta или имя поля
        row_label = meta.description if (meta and meta.description) else field_name
        # Текущее значение из инстанца схемы
        current_value = getattr(instance, field_name, None)

        # Определяем тип поля через аннотацию (Annotated → раскрываем внутренний тип)
        annotation = field_info.annotation
        # Pydantic v2 хранит «голый» тип без Annotated в field_info.annotation
        # (Annotated уже разобран — metadata вынесены в field_info.metadata)

        if _is_list_int(annotation):
            # BGR-поле: 3 QSpinBox
            container, spinboxes = _make_bgr_widget(row_label, current_value)
            form.addRow(QLabel(row_label), container)
            field_widget_map[field_name] = spinboxes  # list[QSpinBox]

        elif annotation is int or annotation == int:
            widget = _make_int_widget(meta, current_value)
            form.addRow(QLabel(row_label), widget)
            field_widget_map[field_name] = widget

        elif annotation is float or annotation == float:
            widget = _make_float_widget(meta, current_value)
            form.addRow(QLabel(row_label), widget)
            field_widget_map[field_name] = widget

        elif annotation is bool or annotation == bool:
            widget = _make_bool_widget(row_label, current_value)
            form.addRow(QLabel(row_label), widget)
            field_widget_map[field_name] = widget

        else:
            # Fallback: строковый ввод
            widget = QLineEdit()
            if current_value is not None:
                widget.setText(str(current_value))
            form.addRow(QLabel(row_label), widget)
            field_widget_map[field_name] = widget

    # Сохраняем маппинг как атрибут панели
    setattr(panel, _FIELD_WIDGET_MAP_ATTR, field_widget_map)
    return panel


def collect_params_from_panel(panel: QWidget) -> dict:
    """Собрать значения параметров из виджетов панели в словарь.

    Обратная операция к build_param_panel.

    Args:
        panel: QWidget, созданный через build_param_panel.

    Returns:
        dict с текущими значениями всех редактируемых полей.

    Raises:
        AttributeError: Если panel не содержит маппинга (создан не через build_param_panel).
    """
    field_widget_map: dict[str, Any] = getattr(panel, _FIELD_WIDGET_MAP_ATTR, None)
    if field_widget_map is None:
        raise AttributeError(
            "Панель не содержит маппинга виджетов. "
            "Убедитесь, что виджет создан через build_param_panel()."
        )

    result: dict = {}
    for field_name, widget in field_widget_map.items():
        if isinstance(widget, list):
            # BGR: список из 3 QSpinBox → list[int]
            result[field_name] = [sb.value() for sb in widget]
        elif isinstance(widget, QSpinBox) or isinstance(widget, QDoubleSpinBox):
            result[field_name] = widget.value()
        elif isinstance(widget, QCheckBox):
            result[field_name] = widget.isChecked()
        elif isinstance(widget, QLineEdit):
            result[field_name] = widget.text()
        # Неизвестный тип виджета — пропускаем

    return result


__all__ = ["build_param_panel", "collect_params_from_panel"]
