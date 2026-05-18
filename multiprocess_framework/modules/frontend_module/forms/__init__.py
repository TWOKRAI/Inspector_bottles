"""forms — контексты и схемы для построения form-виджетов (framework-уровень).

Re-exports:
    FormContext    — единый контекст для создания form-виджетов
"""

from .form_context import ActionBuilderProtocol, FormContext

__all__ = [
    "ActionBuilderProtocol",
    "FormContext",
]
