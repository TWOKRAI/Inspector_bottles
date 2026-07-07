"""Общие Qt-хелперы фабрики форм (лист-модуль пакета).

Выделено из `forms/factory.py` (Task F.5). Держит `_make_label` отдельно, чтобы
им могли пользоваться и legacy-, и binding-, и json-builders без циклического
импорта между builders_legacy ↔ builders_binding.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo


def _make_label(field_info: FieldInfo) -> QLabel:
    """Создать QLabel для поля (title + unit)."""
    text = field_info.title
    unit = field_info.unit
    if unit:
        text = f"{text} ({unit})"
    return QLabel(text)
