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
from multiprocess_prototype.registers.field_info import FieldInfo

from .field_editor import FieldEditor
from .widgets.color_picker import ColorTripletWidget

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
    # TODO Phase 2.6: re-enable DeprecationWarning when form_ctx becomes mandatory.
    # Сейчас десятки callers (InspectorPanel, ServicesTab, settings) не передают
    # form_ctx → warning зашумляет логи без пользы.
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
    """CheckboxControl через ActionBusRegistersManager — binding-aware путь.

    Coalescing, undo/redo, IPC bridge — автоматически через ActionBus.
    """
    from multiprocess_framework.modules.frontend_module.components.base.config import (
        BindingConfig,
    )
    from multiprocess_framework.modules.frontend_module.components.checkbox import (
        CheckboxControl,
        CheckboxViewConfig,
    )

    from multiprocess_prototype.frontend.actions.action_bus_register_adapter import (
        ActionBusRegistersManager,
    )

    # Собрать мост для фреймворк-фасада
    bus_rm = ActionBusRegistersManager(
        form_ctx.registers_manager,
        form_ctx.action_bus,
        form_ctx.action_builder,
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
        bus_rm,
        binding,
        view_config,
        current_access_level=form_ctx.access_level,
    )

    label = _make_label(field_info)
    # change_signal=None: binding-aware путь пишет через presenter →
    # ActionBusRegistersManager, RegisterView НЕ должен дублировать write
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


def _build_literal(field_info: FieldInfo, parent: QWidget | None = None) -> FieldEditor:
    """QComboBox для Literal["a", "b", "c"]."""
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


def _build_color3(field_info: FieldInfo, parent: QWidget | None = None) -> FieldEditor:
    """ColorTripletWidget для tuple[int, int, int]."""
    w = ColorTripletWidget(parent)
    default = _safe_default(field_info, (0, 0, 0))
    if isinstance(default, (tuple, list)) and len(default) == 3:
        w.set_value(tuple(default))  # type: ignore[arg-type]
    label = _make_label(field_info)
    return FieldEditor(
        field_info=field_info,
        widget=w,
        getter=w.get_value,
        setter=w.set_value,
        change_signal=w.value_changed,
        label=label,
    )


def _build_int(field_info: FieldInfo, parent: QWidget | None = None) -> FieldEditor:
    """QSpinBox для int с range из FieldMeta и suffix из unit."""
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


def _build_float(field_info: FieldInfo, parent: QWidget | None = None) -> FieldEditor:
    """QDoubleSpinBox для float с decimals и range из FieldMeta."""
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


def _build_str_short(field_info: FieldInfo, parent: QWidget | None = None) -> FieldEditor:
    """QLineEdit для короткой строки (default <= 120 символов)."""
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


def _build_str_long(field_info: FieldInfo, parent: QWidget | None = None) -> FieldEditor:
    """QPlainTextEdit (read-only, h=60) для длинной строки (> 120 символов)."""
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


def _build_path(field_info: FieldInfo, parent: QWidget | None = None) -> FieldEditor:
    """QLineEdit для Path (полный picker — Phase 10B)."""
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


def _build_unsupported(field_info: FieldInfo, parent: QWidget | None = None) -> FieldEditor:
    """Disabled QLabel для неподдерживаемых типов."""
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
                Если передан — bool-поля рендерятся через CheckboxControl +
                ActionBusRegistersManager. Остальные builders (int/float/...)
                пока игнорируют form_ctx. Legacy callers без form_ctx
                продолжают работать (bool → QCheckBox).
        """
        kind = _resolve_kind(field_info)
        builder = _BUILDERS.get(kind, _build_unsupported)

        # Phase 2.0 pilot: bool с form_ctx → binding-aware CheckboxControl.
        # Проверяем, что builder не был переопределён через register_type().
        if kind == _KIND_BOOL and builder is _build_bool:
            return _build_bool(field_info, parent, form_ctx)

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
