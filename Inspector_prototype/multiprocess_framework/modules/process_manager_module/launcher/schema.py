"""
Схема proc_dict для process_manager_module.

DEFAULT_PROCESS_SCHEMA — эталонная структура, с которой нормализуется
входящий proc_dict через merge_with_defaults. Каждый consumer определяет
свой формат; недостающие ключи заполняются из default.

Полный контракт: docs/CONFIG_CONTRACT.md
"""

from typing import Any, Dict

# Эталонная структура proc_dict для add_process().
# merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA) гарантирует
# наличие всех ожидаемых ключей.
DEFAULT_PROCESS_SCHEMA: Dict[str, Any] = {
    "class": "",
    "queues": {},
    "priority": "normal",
    "workers": {},
}
