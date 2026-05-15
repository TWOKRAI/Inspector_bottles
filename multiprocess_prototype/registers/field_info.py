"""FieldInfo — re-export из framework.

Канонический модуль: multiprocess_framework.modules.registers_module.core.field_info.
Этот файл сохранён для обратной совместимости импортов в прототипе.
"""

from multiprocess_framework.modules.registers_module.core.field_info import (  # noqa: F401
    FieldInfo,
    extract_fields,
)

__all__ = ["FieldInfo", "extract_fields"]
