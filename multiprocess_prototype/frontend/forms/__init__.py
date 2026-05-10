"""forms — фабрика Qt-виджетов из Pydantic-метаданных + два представления (Cards/Table).

Re-exports:
    CardsFieldFactory  — фабрика виджетов по FieldInfo
    FieldEditor        — дата-контейнер (widget, getter, setter, signal, label)
    ViewMode           — enum Cards / Table
    ViewModeToggle     — переключатель режима
    RegisterView       — QStackedWidget (cards | table) + toggle
    build_form_for_register  — cards-представление (standalone)
    build_table_for_register — table-представление (standalone)
"""

from .factory import CardsFieldFactory
from .field_editor import FieldEditor
from .form_builder import build_form_for_register, build_table_for_register
from .register_view import RegisterView
from .view_mode_toggle import ViewMode, ViewModeToggle

__all__ = [
    "CardsFieldFactory",
    "FieldEditor",
    "ViewMode",
    "ViewModeToggle",
    "RegisterView",
    "build_form_for_register",
    "build_table_for_register",
]
