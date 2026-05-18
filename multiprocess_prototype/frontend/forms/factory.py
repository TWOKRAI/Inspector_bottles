"""CardsFieldFactory — универсальная фабрика Qt-виджетов из Pydantic FieldInfo.

Маппинг type → widget выполняется в порядке, определённом в _resolve_kind().
Фабрика вызывается ТОЛЬКО из Qt main thread.

Расширение: ``CardsFieldFactory.register_type("color3", custom_builder)``
переопределит встроенный builder для данного kind.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, get_args, get_origin

from PySide6.QtWidgets import (
    QCheckBox,
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

from .field_editor import FieldEditor

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Sentinel для pydantic_core.PydanticUndefined (чтобы не тянуть зависимость)
# ---------------------------------------------------------------------------
_UNDEFINED_TYPES: tuple[type, ...] = ()
try:
    from pydantic_core import PydanticUndefined  # type: ignore[attr-defined]

    _UNDEFINED_TYPES = (type(PydanticUndefined),)
except ImportError:
    pass


def _is_undefined(value: Any) -> bool:
    """True если value — PydanticUndefined или None."""
    if value is None:
        return True
    if _UNDEFINED_TYPES and isinstance(value, _UNDEFINED_TYPES):
        return True
    # Проверка по repr на случай другой версии pydantic
    return repr(value) == "PydanticUndefined"


# ---------------------------------------------------------------------------
# Резолвер kind из field_type
# ---------------------------------------------------------------------------

# Возможные kind-ы (порядок резолва критичен — см. _resolve_kind)
_KIND_BOOL = "bool"
_KIND_LITERAL = "literal"
_KIND_COLOR3 = "color3"
_KIND_INT = "int"
_KIND_FLOAT = "float"
_KIND_STR_SHORT = "str_short"
_KIND_STR_LONG = "str_long"
_KIND_PATH = "path"
_KIND_UNSUPPORTED = "unsupported"


def _unwrap_optional(t: type) -> type:
    """Снять Optional[X] → X. Если не Optional — вернуть as-is."""
    origin = get_origin(t)
    if origin is type(None):
        return type(None)
    # Union[X, None] — это Optional[X]
    import types as _types

    _union_reprs = ("typing.Union", "<class 'types.UnionType'>")
    if origin is _types.UnionType or (origin is not None and repr(origin) in _union_reprs):
        args = get_args(t)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return t


def _is_tuple_3int(t: type) -> bool:
    """Проверить, что тип == tuple[int, int, int]."""
    origin = get_origin(t)
    if origin is not tuple:
        return False
    args = get_args(t)
    return len(args) == 3 and all(a is int for a in args)


# Маппинг канонических widget → внутренняя kind-константа.
# Алиасы (combo/spinbox/numeric) нормализуются в FieldMeta.__init__ —
# здесь только канонические значения + slider (отдельный UI hint для Phase 2.4).
_WIDGET_TO_KIND: dict[str, str] = {
    "checkbox": _KIND_BOOL,
    "literal": _KIND_LITERAL,
    "color3": _KIND_COLOR3,
    "slider": _KIND_INT,  # slider — UI variant int, до Phase 2.4 рендерится как _build_int
    "int": _KIND_INT,
    "float": _KIND_FLOAT,
    "str": _KIND_STR_SHORT,
    "text": _KIND_STR_LONG,
    "path": _KIND_PATH,
    "label": _KIND_UNSUPPORTED,
}


def _resolve_kind(field_info: FieldInfo) -> str:
    """Определить kind виджета по типу поля.

    Порядок проверок критичен — более специфичные типы проверяются первыми.
    Перед type-based dispatch проверяется FieldMeta.widget — явный override
    позволяет требовать slider для int с диапазоном или label для bool.
    """
    # 0. Явный FieldMeta.widget перекрывает type-dispatch.
    # FieldMeta.__init__ нормализует алиасы (combo→literal, spinbox→int, numeric→float),
    # поэтому здесь всегда каноническое значение.
    meta = field_info.meta
    widget = getattr(meta, "widget", "") if meta is not None else ""
    if widget:
        # Неизвестный widget → graceful fallback на type-dispatch.
        kind = _WIDGET_TO_KIND.get(widget)
        if kind is not None:
            return kind

    t = _unwrap_optional(field_info.field_type)

    # 1. bool ДО int (bool — подкласс int в Python)
    if t is bool:
        return _KIND_BOOL

    # 2. Literal
    if get_origin(t) is Literal:
        return _KIND_LITERAL

    # 3. tuple[int, int, int] — цветовой триплет
    if _is_tuple_3int(t):
        return _KIND_COLOR3

    # 4. int
    if t is int:
        return _KIND_INT

    # 5. float
    if t is float:
        return _KIND_FLOAT

    # 6. str (короткая / длинная)
    if t is str:
        default = field_info.default
        if isinstance(default, str) and len(default) > 120:
            return _KIND_STR_LONG
        return _KIND_STR_SHORT

    # 7. Path
    if t is Path:
        return _KIND_PATH

    # 8. Всё остальное
    return _KIND_UNSUPPORTED


# ---------------------------------------------------------------------------
# Внутренние builders по kind-у
# ---------------------------------------------------------------------------


def _make_label(field_info: FieldInfo) -> QLabel:
    """Создать QLabel для поля (title + unit)."""
    text = field_info.title
    unit = field_info.unit
    if unit:
        text = f"{text} ({unit})"
    return QLabel(text)


def _safe_default(field_info: FieldInfo, fallback: Any = None) -> Any:
    """Получить default или fallback, если default == PydanticUndefined / None."""
    val = field_info.default
    if _is_undefined(val):
        return fallback
    return val


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
        # old_value берём из RM если доступен, иначе пустая строка.
        old_value = ""
        try:
            reg = form_ctx.registers_manager.get_register(register_name)
            if reg is not None:
                raw = getattr(reg, field_name, None)
                old_value = str(raw) if raw is not None else ""
        except (AttributeError, KeyError, TypeError):
            # RM не отдал регистр/поле — fallback на "" допустим: write всё равно
            # пройдёт, ActionBus возьмёт текущее как old при coalescing.
            pass
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
        old_value = ""
        try:
            reg = form_ctx.registers_manager.get_register(register_name)
            if reg is not None:
                raw = getattr(reg, field_name, None)
                old_value = str(raw) if raw is not None else ""
        except (AttributeError, KeyError, TypeError):
            # RM не отдал регистр/поле — fallback на "" допустим: write всё равно
            # пройдёт, ActionBus возьмёт текущее как old при coalescing.
            pass
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
    le = QLineEdit(parent)
    default = _safe_default(field_info, "")
    le.setText(default.as_posix() if isinstance(default, Path) else str(default))

    register_name = field_info.plugin_name or ""
    field_name = field_info.field_name or ""

    def _on_editing_finished() -> None:
        new_value = le.text()
        old_value = ""
        try:
            reg = form_ctx.registers_manager.get_register(register_name)
            if reg is not None:
                raw = getattr(reg, field_name, None)
                old_value = str(raw) if raw is not None else ""
        except (AttributeError, KeyError, TypeError):
            # RM не отдал регистр/поле — fallback на "" допустим: write всё равно
            # пройдёт, ActionBus возьмёт текущее как old при coalescing.
            pass
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


# ---------------------------------------------------------------------------
# Реестр builders (kind → builder function)
# ---------------------------------------------------------------------------

_BUILDERS: dict[str, Any] = {
    _KIND_BOOL: _build_bool,
    _KIND_LITERAL: _build_literal,
    _KIND_COLOR3: _build_color3,
    _KIND_INT: _build_int,
    _KIND_FLOAT: _build_float,
    _KIND_STR_SHORT: _build_str_short,
    _KIND_STR_LONG: _build_str_long,
    _KIND_PATH: _build_path,
    _KIND_UNSUPPORTED: _build_unsupported,
}


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------


class CardsFieldFactory:
    """Фабрика Qt-виджетов из Pydantic FieldInfo.

    Использование:
        editor = CardsFieldFactory.create(field_info)
        editor.widget   # → QSpinBox / QCheckBox / ...
        editor.getter() # → текущее значение
        editor.setter(42)

    Расширение:
        CardsFieldFactory.register_type("color3", my_custom_builder)
    """

    @classmethod
    def create(
        cls,
        field_info: FieldInfo,
        parent: QWidget | None = None,
        form_ctx: FormContext | None = None,
    ) -> FieldEditor:
        """Создать FieldEditor для данного FieldInfo.

        Определяет kind по типу поля и вызывает соответствующий builder.

        Args:
            field_info: Метаданные поля.
            parent: Родительский Qt-виджет.
            form_ctx: FormContext — единый контекст binding-aware сборки.
                Если передан — bool-поля рендерятся через CheckboxControl,
                int-поля через SpinBoxControl (оба через FormContext.write +
                ActionBus). Legacy callers без form_ctx продолжают работать
                (bool → QCheckBox, int → QSpinBox).
        """
        kind = _resolve_kind(field_info)
        builder = _BUILDERS.get(kind, _build_unsupported)

        # Binding-aware dispatch: bool, int, float, color3 и literal с form_ctx → control-виджеты через ActionBus.
        # Проверяем что builder не был переопределён через register_type().
        if kind == _KIND_BOOL and builder is _build_bool:
            return _build_bool(field_info, parent, form_ctx)
        if kind == _KIND_INT and builder is _build_int:
            return _build_int(field_info, parent, form_ctx=form_ctx)
        if kind == _KIND_FLOAT and builder is _build_float:
            return _build_float(field_info, parent, form_ctx=form_ctx)
        # color3-поля (tuple[int,int,int]) рендерятся через CompoundNumericControl
        # (через FormContext.write + ActionBus) если form_ctx передан.
        if kind == _KIND_COLOR3 and builder is _build_color3:
            return _build_color3(field_info, parent, form_ctx=form_ctx)
        # Literal-поля рендерятся через ComboControl (form_ctx + ActionBus) если form_ctx передан.
        if kind == _KIND_LITERAL and builder is _build_literal:
            return _build_literal(field_info, parent, form_ctx=form_ctx)
        # str/text/path — thin binding wrapper напрямую в factory (без FW-компонента).
        if kind == _KIND_STR_SHORT and builder is _build_str_short:
            return _build_str_short(field_info, parent, form_ctx)
        if kind == _KIND_STR_LONG and builder is _build_str_long:
            return _build_str_long(field_info, parent, form_ctx)
        if kind == _KIND_PATH and builder is _build_path:
            return _build_path(field_info, parent, form_ctx)

        # Fallback: builders без binding-aware пути (unsupported и переопределённые через register_type)
        return builder(field_info, parent)

    @classmethod
    def register_type(
        cls,
        type_key: str,
        builder: Any,
    ) -> None:
        """Зарегистрировать или переопределить builder для kind.

        Аргументы:
            type_key: строковый ключ kind (например, "color3", "int").
            builder: функция (field_info, parent) -> FieldEditor.
        """
        _BUILDERS[type_key] = builder

    @classmethod
    def resolve_kind(cls, field_info: FieldInfo) -> str:
        """Публичный доступ к определению kind (для тестирования)."""
        return _resolve_kind(field_info)
