# -*- coding: utf-8 -*-
"""
Backward-compatible re-export.

RegistersScanner перемещён в registry/discovery.py.

Используйте новый путь:
    from data_schema_module.registry.discovery import RegistersScanner
    from data_schema_module.registry import RegistersScanner
    from data_schema_module import RegistersScanner
"""
from .discovery import RegistersScanner, _class_name_to_key


def _class_name_to_snake(class_name: str, suffix: str) -> str:
    """
    Backward-compatible версия _class_name_to_key.

    Отличие от _class_name_to_key: при несовпадении суффикса возвращает
    class_name.lower() (старое поведение RegistersScanner).
    """
    if not suffix or not class_name.endswith(suffix):
        return class_name.lower()
    base = class_name[: -len(suffix)]
    if not base:
        return class_name.lower()
    import re
    return re.sub(r"(?<!^)(?=[A-Z])", "_", base).lower()


__all__ = ["RegistersScanner", "_class_name_to_snake", "_class_name_to_key"]
