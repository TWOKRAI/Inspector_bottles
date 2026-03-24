# multiprocess_prototype/frontend/widgets/hikvision_widget/line_params.py
"""Утилиты для чтения/записи тройки параметров через QLineEdit (fallback без регистра)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from frontend_module.core.qt_imports import QLineEdit

from .schemas import HikvisionUiConfig

_DEFAULT_TRIPLE = (25.0, 10000.0, 0.0)


def parse_triple_from_line_edits(
    ui: HikvisionUiConfig,
    line_edits: List[Optional[QLineEdit]],
) -> tuple[float, float, float]:
    """(frame_rate, exposure, gain) из пар api_map ↔ QLineEdit."""
    if not line_edits:
        return _DEFAULT_TRIPLE
    try:
        vals: list[float] = []
        for m, ed in zip(ui.hikvision_api_to_register, line_edits):
            if ed is None:
                return _DEFAULT_TRIPLE
            vals.append(float(ed.text() or m.parse_empty_default))
        return (vals[0], vals[1], vals[2])
    except (ValueError, IndexError):
        return _DEFAULT_TRIPLE


def apply_params_to_line_edits(
    ui: HikvisionUiConfig,
    line_edits: List[Optional[QLineEdit]],
    params: Dict[str, Any],
) -> None:
    """Заполнить QLineEdit из словаря ответа камеры (только где ed не None)."""
    for m, ed in zip(ui.hikvision_api_to_register, line_edits):
        if ed is None:
            continue
        raw = float(params.get(m.api_key, 0))
        ed.setText(format(raw, m.line_edit_format_spec))
