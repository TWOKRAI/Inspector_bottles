# -*- coding: utf-8 -*-
"""
Автообнаружение классов регистров (Pydantic-моделей) в пакете.
Сканирует пакет, находит классы с суффиксом *Registers, строит маппинг имя_регистра -> класс.
"""
import re
import importlib
from typing import Dict, Type, Callable, Optional, Any
from pydantic import BaseModel


def _class_name_to_register_name(class_name: str) -> str:
    """DrawRegisters -> draw, FrameProcessRegisters -> frame_process. Оставлен для совместимости."""
    return _class_name_to_key(class_name, "Registers")


def _class_name_to_key(class_name: str, suffix: str) -> str:
    """
    Универсальное преобразование: CamelCaseName + suffix -> snake_case key.
    DrawRegisters + "Registers" -> draw; CameraData + "Data" -> camera; ChainStepData + "Data" -> chain_step.
    """
    if not suffix or not class_name.endswith(suffix):
        return class_name
    base = class_name[: -len(suffix)]
    if not base:
        return class_name.lower()
    return re.sub(r"(?<!^)(?=[A-Z])", "_", base).lower()


def discover_registers_from_package(
    package_name: str,
    name_from_class: Optional[Callable[[Type[BaseModel]], str]] = None,
    suffix: str = "Registers",
) -> Dict[str, Type[BaseModel]]:
    """
    Импортировать пакет и собрать все классы с заданным суффиксом (BaseModel).

    Универсально для *Registers и *Data: один и тот же механизм для разных процессов.

    Args:
        package_name: Имя пакета для импорта (например, "App.Registers.models.field_registers").
        name_from_class: Опциональная функция (model_class) -> key. Если None,
                         используется _class_name_to_key(name, suffix).
        suffix: Суффикс имени класса для отбора ("Registers", "Data" и т.д.).

    Returns:
        Словарь {key: model_class}, например {"draw": DrawRegisters} или {"camera": CameraData}.
    """
    try:
        pkg = importlib.import_module(package_name)
    except Exception:
        return {}

    result: Dict[str, Type[BaseModel]] = {}
    names = getattr(pkg, "__all__", None) or [x for x in dir(pkg) if not x.startswith("_")]

    for name in names:
        try:
            obj = getattr(pkg, name)
        except AttributeError:
            continue
        if not isinstance(obj, type) or not issubclass(obj, BaseModel):
            continue
        if not name.endswith(suffix):
            continue
        key = name_from_class(obj) if name_from_class else _class_name_to_key(name, suffix)
        result[key] = obj

    return result


def register_package_schemas(
    package_name: str,
    schema_registry: Optional[Any] = None,
    suffix: str = "Registers",
) -> bool:
    """
    Универсальный мост: discovery классов с суффиксом в пакете + регистрация в SchemaManager.
    Один и тот же вызов для регистров (*Registers) и для данных (*Data) в любом процессе.

    Args:
        package_name: Имя пакета (например, "App.Registers.models.field_registers" или "...field_data").
        schema_registry: Экземпляр SchemaManager; если None, используется SchemaManager.get_instance().
        suffix: Суффикс имени класса ("Registers", "Data" и т.д.).

    Returns:
        True если хотя бы одна схема зарегистрирована, False если реестр недоступен или discovery пуст.
    """
    register_map = discover_registers_from_package(package_name, suffix=suffix)
    if not register_map:
        return False
    if schema_registry is None:
        try:
            from .schema_registry import SchemaManager
            schema_registry = SchemaManager.get_instance()
        except Exception:
            return False
    if not getattr(schema_registry, "register", None):
        return False
    for name, model_class in register_map.items():
        try:
            schema_registry.register(name, model_class)
        except Exception:
            pass
    return True


# Обратная совместимость
register_package_registers = register_package_schemas
