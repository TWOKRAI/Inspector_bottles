"""Legacy-builders фабрики форм (raw Qt-виджеты) + комбинированные диспетчеры.

Выделено из `forms/factory.py` (Task F.5, дословный перенос). Каждый публичный
`_build_X` — комбинированный диспетчер: при form_ctx != None делегирует в
binding-aware путь (`builders_binding`), иначе строит raw Qt-виджет (ЖИВОЙ
прод-путь по вердикту №5 G0).

Импорт `builders_binding` — односторонний (legacy → binding); обратной
зависимости нет (общий `_make_label` вынесен в `_common`), поэтому цикла нет.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, get_args

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext
from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo

from ..field_editor import FieldEditor
from ._common import _make_label
from .builders_binding import (
    _build_bool_binding_aware,
    _build_color3_binding_aware,
    _build_float_binding_aware,
    _build_int_binding_aware,
    _build_literal_binding_aware,
    _build_path_binding_aware,
    _build_slider_binding_aware,
    _build_str_long_binding_aware,
    _build_str_short_binding_aware,
)
from .kinds import _safe_default, _unwrap_optional


def _build_bool(
    field_info: FieldInfo,
    parent: QWidget | None = None,
    form_ctx: FormContext | None = None,
) -> FieldEditor:
    """Binding-aware CheckboxControl (form_ctx) или legacy QCheckBox."""
    if form_ctx is not None:
        return _build_bool_binding_aware(field_info, form_ctx, parent)

    # Legacy путь — QCheckBox без binding-aware моста.
    # Callers без form_ctx (InspectorPanel, ServicesTab, settings) намеренно остаются
    # на этом пути: DeprecationWarning не вводится (решение зафиксировано в track-0).
    from PySide6.QtWidgets import QCheckBox

    cb = QCheckBox(parent)
    default = _safe_default(field_info, False)
    cb.setChecked(bool(default))
    label = _make_label(field_info)
    return FieldEditor(
        field_info=field_info,
        widget=cb,
        getter=cb.isChecked,
        setter=lambda v: cb.setChecked(bool(v)),
        change_signal=cb.toggled,
        label=label,
    )


def _build_literal(
    field_info: FieldInfo,
    parent: QWidget | None = None,
    *,
    form_ctx: FormContext | None = None,
) -> FieldEditor:
    """QComboBox для Literal["a", "b", "c"] (legacy) или ComboControl (binding-aware).

    Legacy путь (form_ctx=None): raw QComboBox без binding-aware моста.
    Callers без form_ctx (SettingsSystem, GUI-локальные формы) намеренно остаются на этом пути.
    """
    if form_ctx is not None:
        return _build_literal_binding_aware(field_info, form_ctx, parent)

    # Legacy путь: raw QComboBox без binding
    combo = QComboBox(parent)
    t = _unwrap_optional(field_info.field_type)
    items = list(get_args(t))
    for item in items:
        combo.addItem(str(item))
    default = _safe_default(field_info)
    if default is not None and str(default) in [str(i) for i in items]:
        combo.setCurrentText(str(default))
    label = _make_label(field_info)
    return FieldEditor(
        field_info=field_info,
        widget=combo,
        getter=combo.currentText,
        setter=lambda v: combo.setCurrentText(str(v)),
        change_signal=combo.currentTextChanged,
        label=label,
    )


def _build_color3(
    field_info: FieldInfo,
    parent: QWidget | None = None,
    *,
    form_ctx: FormContext | None = None,
) -> FieldEditor:
    """CompoundNumericControl для tuple[int,int,int] (binding-aware) или legacy путь.

    Legacy путь (form_ctx=None) создаёт 3 raw QSpinBox в HBoxLayout без ActionBus-binding.
    Используется для GUI-локальных форм без plugin binding.
    """
    if form_ctx is not None:
        return _build_color3_binding_aware(field_info, form_ctx, parent)

    # Legacy путь: 3 raw QSpinBox без binding (аналог ColorTripletWidget).
    # ColorTripletWidget удалён — воспроизводим минимальный inline.
    from PySide6.QtWidgets import QHBoxLayout, QSpinBox

    container = QWidget(parent)
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    spins: list[QSpinBox] = []
    for _ in range(3):
        spin = QSpinBox(container)
        spin.setRange(0, 255)
        layout.addWidget(spin)
        spins.append(spin)
    default = _safe_default(field_info, (0, 0, 0))
    if isinstance(default, (tuple, list)) and len(default) == 3:
        for spin, val in zip(spins, default):
            spin.setValue(int(val))
    label = _make_label(field_info)
    return FieldEditor(
        field_info=field_info,
        widget=container,
        getter=lambda: tuple(s.value() for s in spins),
        setter=lambda v: [s.setValue(int(v[i])) for i, s in enumerate(spins)] if v else None,
        change_signal=None,  # type: ignore[arg-type]
        label=label,
    )


def _build_int(
    field_info: FieldInfo,
    parent: QWidget | None = None,
    *,
    form_ctx: FormContext | None = None,
) -> FieldEditor:
    """QSpinBox для int (legacy) или SpinBoxControl/SliderControl (binding-aware, если form_ctx передан).

    Dispatch по meta.widget: "slider" → SliderControl, иначе → SpinBoxControl.
    Legacy callers без form_ctx (SettingsSystem, GUI-локальные формы) остаются на raw QSpinBox.
    """
    meta = field_info.meta
    is_slider = meta is not None and getattr(meta, "widget", None) == "slider"

    if form_ctx is not None:
        if is_slider:
            return _build_slider_binding_aware(field_info, form_ctx, parent)
        return _build_int_binding_aware(field_info, form_ctx, parent)

    # Legacy путь — raw QSpinBox без binding-aware моста.
    # Callers без form_ctx (SettingsSystem, GUI-локальные формы) намеренно
    # остаются на этом пути.
    spin = QSpinBox(parent)

    min_val = field_info.min_value
    max_val = field_info.max_value
    spin.setRange(
        int(min_val) if min_val is not None else -(2**31),
        int(max_val) if max_val is not None else 2**31 - 1,
    )

    # singleStep из meta.transfer_k
    meta = field_info.meta
    if meta and hasattr(meta, "transfer_k") and meta.transfer_k:
        step = int(meta.transfer_k) if meta.transfer_k >= 1 else 1
        spin.setSingleStep(step)

    # suffix из unit
    unit = field_info.unit
    if unit:
        spin.setSuffix(f" {unit}")

    default = _safe_default(field_info, 0)
    if isinstance(default, (int, float)):
        spin.setValue(int(default))
    else:
        spin.setValue(int(min_val) if min_val is not None else 0)

    label = _make_label(field_info)
    return FieldEditor(
        field_info=field_info,
        widget=spin,
        getter=spin.value,
        setter=lambda v: spin.setValue(int(v)),
        change_signal=spin.valueChanged,
        label=label,
    )


def _build_float(
    field_info: FieldInfo,
    parent: QWidget | None = None,
    *,
    form_ctx: FormContext | None = None,
) -> FieldEditor:
    """QDoubleSpinBox для float (legacy) или NumericControl spinbox (binding-aware, если form_ctx передан).

    Legacy callers без form_ctx (SettingsSystem, GUI-локальные формы) остаются на raw QDoubleSpinBox.
    """
    if form_ctx is not None:
        return _build_float_binding_aware(field_info, form_ctx, parent)

    # Legacy путь — raw QDoubleSpinBox без binding-aware моста.
    dsb = QDoubleSpinBox(parent)

    min_val = field_info.min_value
    max_val = field_info.max_value
    dsb.setRange(
        float(min_val) if min_val is not None else -1e9,
        float(max_val) if max_val is not None else 1e9,
    )

    # decimals из meta.round_k
    meta = field_info.meta
    decimals = 6  # по умолчанию
    if meta and hasattr(meta, "round_k") and meta.round_k is not None:
        decimals = meta.round_k
    dsb.setDecimals(decimals)

    # singleStep из meta.transfer_k
    if meta and hasattr(meta, "transfer_k") and meta.transfer_k:
        dsb.setSingleStep(meta.transfer_k)

    # suffix из unit
    unit = field_info.unit
    if unit:
        dsb.setSuffix(f" {unit}")

    default = _safe_default(field_info, 0.0)
    if isinstance(default, (int, float)):
        dsb.setValue(float(default))
    else:
        dsb.setValue(float(min_val) if min_val is not None else 0.0)

    label = _make_label(field_info)
    return FieldEditor(
        field_info=field_info,
        widget=dsb,
        getter=dsb.value,
        setter=lambda v: dsb.setValue(float(v)),
        change_signal=dsb.valueChanged,
        label=label,
    )


def _build_str_short(
    field_info: FieldInfo,
    parent: QWidget | None = None,
    form_ctx: FormContext | None = None,
) -> FieldEditor:
    """QLineEdit для короткой строки (binding-aware если form_ctx передан)."""
    if form_ctx is not None:
        return _build_str_short_binding_aware(field_info, form_ctx, parent)

    # Legacy путь — QLineEdit без binding-aware моста.
    le = QLineEdit(parent)
    default = _safe_default(field_info, "")
    le.setText(str(default))

    # placeholder из description (meta.info)
    meta = field_info.meta
    if meta and meta.info:
        le.setPlaceholderText(meta.info)

    label = _make_label(field_info)
    return FieldEditor(
        field_info=field_info,
        widget=le,
        getter=le.text,
        setter=lambda v: le.setText(str(v)),
        change_signal=le.textChanged,
        label=label,
    )


def _build_str_long(
    field_info: FieldInfo,
    parent: QWidget | None = None,
    form_ctx: FormContext | None = None,
) -> FieldEditor:
    """QPlainTextEdit для длинной строки (binding-aware если form_ctx передан)."""
    if form_ctx is not None:
        return _build_str_long_binding_aware(field_info, form_ctx, parent)

    # Legacy путь — QPlainTextEdit readonly без binding-aware моста.
    te = QPlainTextEdit(parent)
    default = _safe_default(field_info, "")
    te.setPlainText(str(default))
    te.setReadOnly(True)
    te.setFixedHeight(60)
    label = _make_label(field_info)
    return FieldEditor(
        field_info=field_info,
        widget=te,
        getter=te.toPlainText,
        setter=lambda v: te.setPlainText(str(v)),
        change_signal=te.textChanged,
        label=label,
    )


def _build_path(
    field_info: FieldInfo,
    parent: QWidget | None = None,
    form_ctx: FormContext | None = None,
) -> FieldEditor:
    """QLineEdit для Path (binding-aware если form_ctx передан; picker — Phase 10B)."""
    if form_ctx is not None:
        return _build_path_binding_aware(field_info, form_ctx, parent)

    # Legacy путь — QLineEdit без binding-aware моста.
    le = QLineEdit(parent)
    default = _safe_default(field_info, "")
    le.setText(default.as_posix() if isinstance(default, Path) else str(default))
    label = _make_label(field_info)
    return FieldEditor(
        field_info=field_info,
        widget=le,
        getter=lambda: le.text(),
        setter=lambda v: le.setText(str(v)),
        change_signal=le.textChanged,
        label=label,
    )


def _build_unsupported(
    field_info: FieldInfo,
    parent: QWidget | None = None,
    form_ctx: FormContext | None = None,
) -> FieldEditor:
    """Disabled QLabel для неподдерживаемых типов. form_ctx зарезервирован, но не используется (readonly)."""
    default = _safe_default(field_info)
    lbl_widget = QLabel(repr(default), parent)
    lbl_widget.setEnabled(False)
    label = _make_label(field_info)
    captured_default = default
    return FieldEditor(
        field_info=field_info,
        widget=lbl_widget,
        getter=lambda: captured_default,
        setter=lambda _v: None,  # noop для unsupported
        change_signal=None,  # type: ignore[arg-type]  # нет сигнала
        label=label,
    )
