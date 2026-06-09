"""Кастомный виджет `model_picker` — динамический выпадающий список моделей.

В отличие от Literal-combo (статический список в схеме), значения вычисляются в
runtime: сканируем `data/models` через ModelRegistry и показываем доступные модели.
Добавил модель в папку → она появляется в списке без правок кода.

Регистрируется в CardsFieldFactory через register_model_picker() (см. forms/__init__).
Слой: prototype (composition root) → Services.ml_inference.core (ModelRegistry).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import QComboBox, QLabel, QWidget

from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo
from Services.ml_inference.core.registry import ModelRegistry

from .field_editor import FieldEditor

logger = logging.getLogger(__name__)

# .../multiprocess_prototype/frontend/forms/model_picker.py → parents[3] = корень проекта.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_MODELS_DIR = _PROJECT_ROOT / "data" / "models"

_EMPTY = ""  # пункт «модель не выбрана»


def _scan_models() -> list[str]:
    """Список id моделей из data/models (пустой при ошибке/отсутствии папки)."""
    try:
        reg = ModelRegistry(_MODELS_DIR)
        reg.scan()
        return reg.names()
    except Exception as exc:  # noqa: BLE001 — GUI не должен падать из-за каталога
        logger.warning("model_picker: ошибка скана %s: %s", _MODELS_DIR, exc)
        return []


def build_model_picker(field_info: FieldInfo, parent: QWidget | None = None) -> FieldEditor:
    """Builder для kind 'model_picker': QComboBox с моделями из data/models."""
    combo = QComboBox(parent)
    combo.addItem(_EMPTY)  # всегда есть «не выбрана»
    for model_id in _scan_models():
        combo.addItem(model_id)

    default = field_info.default if isinstance(field_info.default, str) else _EMPTY
    if default and combo.findText(default) >= 0:
        combo.setCurrentText(default)

    title = field_info.title
    unit = getattr(field_info, "unit", "")
    label = QLabel(f"{title} ({unit})" if unit else title)

    return FieldEditor(
        field_info=field_info,
        widget=combo,
        getter=combo.currentText,
        setter=lambda v: combo.setCurrentText(str(v)),
        change_signal=combo.currentTextChanged,
        label=label,
    )


def register_model_picker() -> None:
    """Зарегистрировать builder в CardsFieldFactory (идемпотентно)."""
    from .factory import CardsFieldFactory

    CardsFieldFactory.register_type("model_picker", build_model_picker)
