"""Binding-aware builders фабрики форм (FW-компоненты + FormContext).

Выделено из `forms/factory.py` (Task F.5, дословный перенос). Эти builders
пишут значения через `FormContext.write` + ActionBus (coalescing, undo/redo,
IPC bridge). change_signal=None во всех — RegisterView НЕ должен дублировать
write.

Н-5: тройная копия чтения old_value из RM (`_on_editing_finished` в str_short/
str_long/path) заменена одним helper'ом `_rm_old_value`.

Зависимость на builders_legacy отсутствует (общий `_make_label` — в `_common`),
поэтому builders_legacy может импортировать этот модуль без цикла.
"""

from __future__ import annotations

from typing import Any, get_args

from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QWidget

from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext
from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo

from ..field_editor import FieldEditor
from ._common import _make_label
from .kinds import _safe_default, _unwrap_optional


def _rm_old_value(form_ctx: FormContext, register_name: str, field_name: str) -> str:
    """Прочитать текущее значение поля из RM как old_value для write.

    Общий helper для thin-wrapper builders (str_short/str_long/path): RM
    недоступен или поле отсутствует → "" (fallback допустим: write всё равно
    пройдёт, ActionBus возьмёт текущее как old при coalescing).
    """
    try:
        reg = form_ctx.registers_manager.get_register(register_name)
        if reg is not None:
            raw = getattr(reg, field_name, None)
            return str(raw) if raw is not None else ""
    except (AttributeError, KeyError, TypeError):
        pass
    return ""


def _build_bool_binding_aware(
    field_info: FieldInfo,
    form_ctx: FormContext,
    parent: QWidget | None = None,
) -> FieldEditor:
    """CheckboxControl через FormContext.write — binding-aware путь.

    Coalescing, undo/redo, IPC bridge — автоматически через ActionBus.
    """
    from multiprocess_framework.modules.frontend_module.components.base.config import (
        BindingConfig,
    )
    from multiprocess_framework.modules.frontend_module.components.checkbox import (
        CheckboxControl,
        CheckboxViewConfig,
    )

    binding = BindingConfig(
        field_info.plugin_name or "",
        field_info.field_name or "",
    )
    view_config = CheckboxViewConfig(
        label=field_info.title,
        position="left",
    )

    result = CheckboxControl.create(
        form_ctx.registers_manager,
        binding,
        view_config,
        current_access_level=form_ctx.access_level,
        form_ctx=form_ctx,
    )

    label = _make_label(field_info)
    # change_signal=None: binding-aware путь пишет через presenter →
    # FormContext.write, RegisterView НЕ должен дублировать write
    # через _on_editor_changed → field_changed → PluginsTab._on_field_changed.
    # Без этого один user-click создавал два action в undo_stack.
    return FieldEditor(
        field_info=field_info,
        widget=result.widget,
        getter=result.widget.get_value,
        setter=result.widget.set_value_silent,
        change_signal=None,  # type: ignore[arg-type]
        label=label,
    )


def _build_int_binding_aware(
    field_info: FieldInfo,
    form_ctx: FormContext,
    parent: QWidget | None = None,
) -> FieldEditor:
    """SpinBoxControl через FormContext.write — binding-aware путь для int.

    Coalescing, undo/redo, IPC bridge — автоматически через ActionBus.

    NOTE: единица измерения (unit) в этом пути берётся из метаданных регистра
    (FieldMeta.unit через SchemaTrait), а не из SpinBoxConfig — SpinBoxConfig
    не имеет поля suffix. Убедись что FieldMeta корректно заполнен в RM.
    """
    from multiprocess_framework.modules.frontend_module.components.base.config import (
        BindingConfig,
    )
    from multiprocess_framework.modules.frontend_module.components.spinbox import (
        SpinBoxConfig,
        SpinBoxControl,
    )

    binding = BindingConfig(
        field_info.plugin_name or "",
        field_info.field_name or "",
    )
    view_config = SpinBoxConfig(
        label=field_info.title,
        min_val=float(field_info.min_value) if field_info.min_value is not None else None,
        max_val=float(field_info.max_value) if field_info.max_value is not None else None,
    )

    result = SpinBoxControl.create(
        form_ctx.registers_manager,
        binding,
        view_config,
        current_access_level=form_ctx.access_level,
        form_ctx=form_ctx,
    )

    label = _make_label(field_info)
    # change_signal=None: binding-aware путь пишет через presenter →
    # FormContext.write, RegisterView НЕ должен дублировать write.
    return FieldEditor(
        field_info=field_info,
        widget=result.widget,
        getter=result.widget.get_value,
        setter=result.widget.set_value_silent,
        change_signal=None,  # type: ignore[arg-type]
        label=label,
    )


def _build_slider_binding_aware(
    field_info: FieldInfo,
    form_ctx: FormContext,
    parent: QWidget | None = None,
) -> FieldEditor:
    """SliderControl через FormContext.write — binding-aware путь для int-полей c widget="slider".

    Coalescing, undo/redo, IPC bridge — автоматически через ActionBus.

    NOTE: unit в этом пути берётся из метаданных регистра (FieldMeta.unit через SchemaTrait),
    а не из SliderConfig — SliderConfig не имеет поля suffix.
    Убедись что FieldMeta корректно заполнен в RM.
    """
    from multiprocess_framework.modules.frontend_module.components.base.config import (
        BindingConfig,
    )
    from multiprocess_framework.modules.frontend_module.components.slider import (
        SliderConfig,
        SliderControl,
    )

    binding = BindingConfig(
        field_info.plugin_name or "",
        field_info.field_name or "",
    )
    view_config = SliderConfig(
        label=field_info.title,
        min_val=float(field_info.min_value) if field_info.min_value is not None else None,
        max_val=float(field_info.max_value) if field_info.max_value is not None else None,
    )

    result = SliderControl.create(
        form_ctx.registers_manager,
        binding,
        view_config,
        current_access_level=form_ctx.access_level,
        form_ctx=form_ctx,
    )

    label = _make_label(field_info)
    # change_signal=None: binding-aware путь пишет через presenter →
    # FormContext.write, RegisterView НЕ должен дублировать write.
    return FieldEditor(
        field_info=field_info,
        widget=result.widget,
        getter=result.widget.get_value,
        setter=result.widget.set_value_silent,
        change_signal=None,  # type: ignore[arg-type]
        label=label,
    )


def _build_color3_binding_aware(
    field_info: FieldInfo,
    form_ctx: FormContext,
    parent: QWidget | None = None,
) -> FieldEditor:
    """CompoundNumericControl через FormContext.write — binding-aware путь для tuple[int,int,int].

    Создаёт 3 NumericControl (spinbox, 0..255) для R, G, B sub-полей по index=0,1,2.
    Coalescing, undo/redo, IPC bridge — автоматически через ActionBus в каждом sub-control.

    NOTE: CompoundNumericControl.create принимает CompoundNumericConfig (не BindingConfig напрямую).
    Binding с index=i создаётся внутри CompoundNumericControl — каждый sub-control пишет
    отдельный элемент tuple по своему индексу.
    """
    from multiprocess_framework.modules.frontend_module.components.base.config import (
        BindingConfig,
    )
    from multiprocess_framework.modules.frontend_module.components.compound import (
        CompoundNumericConfig,
        CompoundNumericControl,
    )
    from multiprocess_framework.modules.frontend_module.components.numeric.config import (
        NumericViewConfig,
    )

    binding = BindingConfig(
        field_info.plugin_name or "",
        field_info.field_name or "",
    )
    view_config = NumericViewConfig(
        view_type="spinbox",  # RGB-каналы отображаются как QDoubleSpinBox (0-255)
        min_val=0.0,
        max_val=255.0,
    )
    config = CompoundNumericConfig(
        binding=binding,
        labels=["R", "G", "B"],
        view_config=view_config,
    )

    result = CompoundNumericControl.create(
        form_ctx.registers_manager,
        config,
        current_access_level=form_ctx.access_level,
        form_ctx=form_ctx,
    )

    label = _make_label(field_info)
    # getter/setter работают через агрегацию sub-контролов.
    # change_signal=None: каждый sub-control пишет через presenter → FormContext.write.
    return FieldEditor(
        field_info=field_info,
        widget=result.widget,
        getter=lambda: tuple(r.widget.get_value() for r in result.results),
        setter=lambda v: (
            [r.widget.set_value_silent(v[i]) for i, r in enumerate(result.results)] if v is not None else None
        ),
        change_signal=None,  # type: ignore[arg-type]
        label=label,
    )


def _build_literal_binding_aware(
    field_info: FieldInfo,
    form_ctx: FormContext,
    parent: QWidget | None = None,
) -> FieldEditor:
    """ComboControl через FormContext.write — binding-aware путь для Literal["a","b","c"].

    Items берутся из Literal-аргументов типа поля.
    Coalescing, undo/redo, IPC bridge — автоматически через ActionBus.
    """
    from multiprocess_framework.modules.frontend_module.components.base.config import (
        BindingConfig,
    )
    from multiprocess_framework.modules.frontend_module.components.combo import (
        ComboControl,
        ComboViewConfig,
    )

    binding = BindingConfig(
        field_info.plugin_name or "",
        field_info.field_name or "",
    )
    t = _unwrap_optional(field_info.field_type)
    items = [str(x) for x in get_args(t)]

    result = ComboControl.create(
        form_ctx.registers_manager,
        binding,
        ComboViewConfig(label=field_info.title),
        current_access_level=form_ctx.access_level,
        items=items,
        form_ctx=form_ctx,
    )

    label = _make_label(field_info)
    return FieldEditor(
        field_info=field_info,
        widget=result.widget,
        getter=result.widget.get_value,
        setter=result.widget.set_value_silent,
        change_signal=None,  # type: ignore[arg-type]
        label=label,
    )


def _build_float_binding_aware(
    field_info: FieldInfo,
    form_ctx: FormContext,
    parent: QWidget | None = None,
) -> FieldEditor:
    """NumericControl(view_type="spinbox") через FormContext.write — binding-aware путь для float.

    Coalescing, undo/redo, IPC bridge — автоматически через ActionBus.

    NOTE: явно задаём view_type="spinbox" — иначе NumericViewConfig даст дефолт "slider"
    и вместо QDoubleSpinBox отрендерится ползунок. Поле float → round_k > 0 →
    presenter вызовет set_validator_float().

    NOTE: label берётся из метаданных регистра (FieldMeta.label через SchemaTrait),
    а не из NumericViewConfig — поэтому field_info.title передаём в view_config.label
    как fallback (SchemaTrait имеет приоритет если RM возвращает корректный label).
    """
    from multiprocess_framework.modules.frontend_module.components.base.config import (
        BindingConfig,
    )
    from multiprocess_framework.modules.frontend_module.components.numeric import (
        NumericControl,
        NumericViewConfig,
    )

    binding = BindingConfig(
        field_info.plugin_name or "",
        field_info.field_name or "",
    )
    view_config = NumericViewConfig(
        view_type="spinbox",  # КРИТИЧНО: без этого дефолт "slider" даст Slider UI
        label=field_info.title,
        min_val=float(field_info.min_value) if field_info.min_value is not None else None,
        max_val=float(field_info.max_value) if field_info.max_value is not None else None,
    )

    result = NumericControl.create(
        form_ctx.registers_manager,
        binding,
        view_config,
        current_access_level=form_ctx.access_level,
        form_ctx=form_ctx,
    )

    label = _make_label(field_info)
    # change_signal=None: binding-aware путь пишет через presenter →
    # FormContext.write, RegisterView НЕ должен дублировать write.
    return FieldEditor(
        field_info=field_info,
        widget=result.widget,
        getter=result.widget.get_value,
        setter=result.widget.set_value_silent,
        change_signal=None,  # type: ignore[arg-type]
        label=label,
    )


def _build_str_short_binding_aware(
    field_info: FieldInfo,
    form_ctx: FormContext,
    parent: QWidget | None = None,
) -> FieldEditor:
    """QLineEdit для короткой строки с прямой подпиской на FormContext.write.

    NOTE: thin wrapper — нет FW-компонента, нет presenter, нет undo-subscribe.
    Undo попадает в RM, но виджет не обновляется автоматически (ограничение
    текущей фазы; устраняется при создании StringControl в будущей задаче).
    """
    le = QLineEdit(parent)
    default = _safe_default(field_info, "")
    le.setText(str(default))

    meta = field_info.meta
    if meta and meta.info:
        le.setPlaceholderText(meta.info)

    register_name = field_info.plugin_name or ""
    field_name = field_info.field_name or ""

    def _on_editing_finished() -> None:
        new_value = le.text()
        old_value = _rm_old_value(form_ctx, register_name, field_name)
        form_ctx.write(register_name, field_name, new_value, old_value)

    le.editingFinished.connect(_on_editing_finished)

    label = _make_label(field_info)
    # change_signal=None: binding-aware путь пишет через _on_editing_finished →
    # form_ctx.write; RegisterView НЕ должен дублировать write.
    return FieldEditor(
        field_info=field_info,
        widget=le,
        getter=le.text,
        setter=lambda v: le.setText(str(v)),
        change_signal=None,  # type: ignore[arg-type]
        label=label,
    )


def _build_str_long_binding_aware(
    field_info: FieldInfo,
    form_ctx: FormContext,
    parent: QWidget | None = None,
) -> FieldEditor:
    """QPlainTextEdit с прямой подпиской textChanged на FormContext.write.

    NOTE: thin wrapper — нет editingFinished у QPlainTextEdit, write на каждый символ.
    ActionBus coalescing смягчает нагрузку. В binding-aware режиме поле не readonly.
    NOTE: setter использует blockSignals чтобы избежать write-loop при загрузке из RM.
    NOTE: undo-subscribe отсутствует (ограничение thin wrapper, устраняется в StringControl).
    """
    te = QPlainTextEdit(parent)
    default = _safe_default(field_info, "")
    te.setPlainText(str(default))
    te.setFixedHeight(60)
    # В binding-aware режиме не ставим setReadOnly(True) — caller ожидает редактирование.

    register_name = field_info.plugin_name or ""
    field_name = field_info.field_name or ""

    def _on_text_changed() -> None:
        new_value = te.toPlainText()
        old_value = _rm_old_value(form_ctx, register_name, field_name)
        form_ctx.write(register_name, field_name, new_value, old_value)

    te.textChanged.connect(_on_text_changed)

    label = _make_label(field_info)

    def _setter_no_signal(v: Any) -> None:
        """Установить значение без испускания textChanged (защита от write-loop)."""
        te.blockSignals(True)
        te.setPlainText(str(v))
        te.blockSignals(False)

    return FieldEditor(
        field_info=field_info,
        widget=te,
        getter=te.toPlainText,
        setter=_setter_no_signal,
        change_signal=None,  # type: ignore[arg-type]
        label=label,
    )


def _build_path_binding_aware(
    field_info: FieldInfo,
    form_ctx: FormContext,
    parent: QWidget | None = None,
) -> FieldEditor:
    """QLineEdit для Path с прямой подпиской editingFinished на FormContext.write.

    NOTE: thin wrapper — полный picker (QFileDialog) отложен на Phase 10B.
    NOTE: write возвращает str; преобразование в Path — ответственность handler'а в RM.
    NOTE: undo-subscribe отсутствует (ограничение thin wrapper).
    """
    from pathlib import Path

    le = QLineEdit(parent)
    default = _safe_default(field_info, "")
    le.setText(default.as_posix() if isinstance(default, Path) else str(default))

    register_name = field_info.plugin_name or ""
    field_name = field_info.field_name or ""

    def _on_editing_finished() -> None:
        new_value = le.text()
        old_value = _rm_old_value(form_ctx, register_name, field_name)
        form_ctx.write(register_name, field_name, new_value, old_value)

    le.editingFinished.connect(_on_editing_finished)

    label = _make_label(field_info)
    return FieldEditor(
        field_info=field_info,
        widget=le,
        getter=lambda: le.text(),
        setter=lambda v: le.setText(v.as_posix() if isinstance(v, Path) else str(v)),
        change_signal=None,  # type: ignore[arg-type]
        label=label,
    )
