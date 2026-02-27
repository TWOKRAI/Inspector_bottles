# -*- coding: utf-8 -*-
"""
Универсальные функции ввода/вывода для объектов «регистры» (model_dump_all / model_validate_all).
Не зависят от App; любой процесс может использовать с любой фабрикой экземпляров.
"""
import json
from typing import Dict, Any, Callable, TypeVar

T = TypeVar('T')


def registers_to_dict(registers: Any) -> Dict[str, Any]:
    """Экспорт в словарь (вызов model_dump_all())."""
    return registers.model_dump_all()


def registers_from_dict(data: Dict[str, Any], factory: Callable[[], T]) -> T:
    """Импорт из словаря: factory() -> экземпляр, затем model_validate_all(data)."""
    inst = factory()
    inst.model_validate_all(data)
    return inst


def registers_to_json(registers: Any, indent: int = 2, ensure_ascii: bool = False) -> str:
    """Экспорт в JSON строку."""
    return json.dumps(registers_to_dict(registers), indent=indent, ensure_ascii=ensure_ascii)


def registers_from_json(json_str: str, factory: Callable[[], T]) -> T:
    """Импорт из JSON строки."""
    return registers_from_dict(json.loads(json_str), factory)


def registers_to_yaml(registers: Any, default_flow_style: bool = False) -> str:
    """Экспорт в YAML строку. Требует pyyaml."""
    import yaml
    return yaml.dump(
        registers_to_dict(registers),
        allow_unicode=True,
        default_flow_style=default_flow_style,
        sort_keys=False,
    )


def registers_from_yaml(yaml_str: str, factory: Callable[[], T]) -> T:
    """Импорт из YAML строки. Требует pyyaml."""
    import yaml
    return registers_from_dict(yaml.safe_load(yaml_str), factory)


def registers_to_flat_dict(registers: Any, prefix: str = '') -> Dict[str, Any]:
    """Экспорт в плоский словарь (register_name.field_name -> value) для рецептов."""
    flat_dict = {}
    for register_name, register_data in registers_to_dict(registers).items():
        if isinstance(register_data, dict):
            for key, value in register_data.items():
                flat_key = f"{prefix}.{register_name}.{key}" if prefix else f"{register_name}.{key}"
                flat_dict[flat_key] = value
    return flat_dict


def registers_from_flat_dict(flat_dict: Dict[str, Any], factory: Callable[[], T], prefix: str = '') -> T:
    """Импорт из плоского словаря (register_name.field_name -> value)."""
    structured: Dict[str, Dict[str, Any]] = {}
    for flat_key, value in flat_dict.items():
        if prefix and flat_key.startswith(prefix + '.'):
            flat_key = flat_key[len(prefix) + 1:]
        parts = flat_key.split('.', 1)
        if len(parts) == 2:
            register_name, field_name = parts
            if register_name not in structured:
                structured[register_name] = {}
            structured[register_name][field_name] = value
    return registers_from_dict(structured, factory)
