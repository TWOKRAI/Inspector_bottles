# multiprocess_framework/modules/frontend_module/widgets/tabs/numeric_bind_or_lineedit.py
"""
NumericControl bound to a register field, or QLineEdit fallback when rm is missing.

Shared by feature widgets (e.g. Hikvision) to avoid duplicating bind vs fallback branches.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Protocol, Sequence

from multiprocess_framework.modules.frontend_module.components import BindingConfig, NumericControl, NumericViewConfig
from multiprocess_framework.modules.frontend_module.components.base.touch_keyboard_config import coerce_touch_keyboard
from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from .binding_context import RegisterBindingContext


class RegisterSpinboxRowSpec(Protocol):
    """Minimal shape for a spinbox row (register field + limits)."""

    register_field: str
    min_val: float
    max_val: float


def append_spinbox_numeric_or_line_fallback(
    layout: QVBoxLayout,
    *,
    binding: RegisterBindingContext,
    register_name: str,
    row_specs: Sequence[RegisterSpinboxRowSpec],
    label_for_row: Callable[[RegisterSpinboxRowSpec], str],
    placeholders: Sequence[str],
    line_edit_max_width: int,
    touch_keyboard: Any | None = None,
    host_widget: Optional[QWidget] = None,
) -> List[Optional[QLineEdit]]:
    """
    Append rows: NumericControl when binding.can_bind else QLineEdit per row.

    ``touch_keyboard`` — dict / None → ``NumericViewConfig`` (mini/full) или fallback LineEdit.

    Returns parallel list of QLineEdit (or None where NumericControl is used).
    """
    tk_cfg = coerce_touch_keyboard(touch_keyboard)
    line_edits: List[Optional[QLineEdit]] = []
    if binding.can_bind and binding.rm is not None:
        rm = binding.rm
        for spec in row_specs:
            label = label_for_row(spec)
            result = NumericControl.create(
                rm,
                BindingConfig(register_name, spec.register_field),
                NumericViewConfig(
                    view_type="spinbox",
                    label=label,
                    min_val=spec.min_val,
                    max_val=spec.max_val,
                    touch_keyboard=tk_cfg,
                ),
            )
            layout.addWidget(result.widget)
        line_edits = [None] * len(row_specs)
    else:
        from multiprocess_framework.modules.frontend_module.widgets.keyboard.touch_keyboard import (
            install_touch_keyboard_on_line_edit,
        )

        for spec, ph in zip(row_specs, placeholders):
            row = QHBoxLayout()
            row.addWidget(QLabel(label_for_row(spec)))
            edit = QLineEdit()
            edit.setPlaceholderText(ph)
            edit.setMaximumWidth(line_edit_max_width)
            row.addWidget(edit)
            layout.addLayout(row)
            host = host_widget if host_widget is not None else edit
            cfg = coerce_touch_keyboard(touch_keyboard)
            if cfg is not None:
                install_touch_keyboard_on_line_edit(
                    host,
                    edit,
                    cfg,
                    lambda e=edit: e.clearFocus(),
                )
            line_edits.append(edit)
    return line_edits
