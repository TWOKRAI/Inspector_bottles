# -*- coding: utf-8 -*-
"""
Auto-discovery схем и регистров.

Объединяет два механизма обнаружения:
    1. discover_registers_from_package() — через importlib по имени пакета
    2. RegistersScanner — через файловую систему (.py файлы)

Оба механизма возвращают Dict[str, Type[BaseModel]] и совместимы
с RegistersContainer и SchemaRegistry.

"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Type

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# =============================================================================
# Утилиты именования
# =============================================================================

def _class_name_to_key(class_name: str, suffix: str) -> str:
    """
    Универсальное преобразование: CamelCaseName + suffix -> snake_case key.

    Examples:
        DrawRegisters + "Registers" -> draw
        CameraData + "Data" -> camera
        ChainStepData + "Data" -> chain_step
    """
    if not suffix or not class_name.endswith(suffix):
        return class_name
    base = class_name[: -len(suffix)]
    if not base:
        return class_name.lower()
    return re.sub(r"(?<!^)(?=[A-Z])", "_", base).lower()


def _class_name_to_register_name(class_name: str) -> str:
    """DrawRegisters -> draw. Оставлен для совместимости."""
    return _class_name_to_key(class_name, "Registers")


def _class_name_to_snake(class_name: str, suffix: str) -> str:
    """
    Преобразование CamelCase + suffix → snake_case (старое поведение RegistersScanner).

    Отличие от _class_name_to_key: при несовпадении суффикса возвращает class_name.lower().
    """
    if not suffix or not class_name.endswith(suffix):
        return class_name.lower()
    base = class_name[: -len(suffix)]
    if not base:
        return class_name.lower()
    return re.sub(r"(?<!^)(?=[A-Z])", "_", base).lower()


# =============================================================================
# Механизм 1: Discovery через importlib (по имени пакета)
# =============================================================================

def discover_registers_from_package(
    package_name: str,
    name_from_class: Optional[Callable[[Type[BaseModel]], str]] = None,
    suffix: str = "Registers",
) -> Dict[str, Type[BaseModel]]:
    """
    Импортировать пакет и собрать все классы с заданным суффиксом (BaseModel).

    Args:
        package_name:    Имя пакета (например, "App.Registers.models.field_registers").
        name_from_class: Опциональная функция (model_class) -> key.
                         Если None — используется _class_name_to_key(name, suffix).
        suffix:          Суффикс имени класса ("Registers", "Data" и т.д.).

    Returns:
        Словарь {key: model_class}, например {"draw": DrawRegisters}.
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
    Discovery классов с суффиксом в пакете + регистрация в SchemaRegistry.

    Args:
        package_name:    Имя пакета.
        schema_registry: Экземпляр SchemaRegistry; если None — default registry.
        suffix:          Суффикс имени класса ("Registers", "Data" и т.д.).

    Returns:
        True если хотя бы одна схема зарегистрирована.
    """
    register_map = discover_registers_from_package(package_name, suffix=suffix)
    if not register_map:
        return False
    if schema_registry is None:
        try:
            from .schema_registry import get_default_registry
            schema_registry = get_default_registry()
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


# Backward compatibility alias
register_package_registers = register_package_schemas


# =============================================================================
# Механизм 2: RegistersScanner — через файловую систему
# =============================================================================

class RegistersScanner:
    """
    Сканер RegisterBase-подклассов в директории.

    В отличие от discover_registers_from_package() (который читает __init__.py),
    сканер работает напрямую с .py файлами в директории.

    Преимущества:
        - Не нужно вручную обновлять __init__.py при добавлении нового регистра
        - Добавил файл VibrationRegisters.py → он появится в контейнере автоматически
        - Работает без изменений в других частях кода

    Все методы — статические. Класс не нужно инстанциировать.

    Использование:

        # Вариант 1: прямой путь к папке
        register_map = RegistersScanner.scan_directory("App/Registers/models/registers")

        # Вариант 2: из __init__.py пакета (передать __file__)
        register_map = RegistersScanner.scan_package_path(__file__)

        # Вариант 3: рекурсивный поиск в подпапках
        register_map = RegistersScanner.scan_directory(path, recursive=True)

        # Создать контейнер:
        from data_schema_module import RegistersContainer
        container = RegistersContainer(register_map)
    """

    @staticmethod
    def scan_directory(
        path: "Path | str",
        base_class: type = None,
        suffix: str = "Registers",
        recursive: bool = False,
        name_from_class: "Callable[[Type[BaseModel]], str] | None" = None,
        exclude_files: "list[str] | None" = None,
    ) -> "dict[str, Type[BaseModel]]":
        """
        Сканировать директорию и найти все подклассы base_class с данным суффиксом.

        Args:
            path:            Путь к директории с .py файлами.
            base_class:      Базовый класс для фильтрации (по умолч. SchemaBase).
                             Если None — принимается любой BaseModel-подкласс.
            suffix:          Суффикс имени класса: "Registers", "Data", "Config", ...
            recursive:       True — искать рекурсивно в подпапках.
            name_from_class: Функция (cls) → str для кастомного именования ключей.
            exclude_files:   Список имён файлов для исключения (без расширения).

        Returns:
            Словарь {key: class}, например {"draw": DrawRegisters}.
        """
        if base_class is None:
            from ..core.schema_base import SchemaBase
            base_class = SchemaBase

        scan_path = Path(path).resolve()
        if not scan_path.exists() or not scan_path.is_dir():
            logger.warning("RegistersScanner: директория не найдена: %s", scan_path)
            return {}

        _exclude = set(exclude_files or []) | {"__init__", "conftest"}
        pattern = "**/*.py" if recursive else "*.py"
        py_files = [
            f for f in scan_path.glob(pattern)
            if f.stem not in _exclude and not f.stem.startswith("_")
        ]

        result: dict[str, Type[BaseModel]] = {}

        for py_file in sorted(py_files):
            classes = RegistersScanner._extract_classes_from_file(
                py_file, base_class, suffix
            )
            for cls in classes:
                key = (
                    name_from_class(cls)
                    if name_from_class
                    else _class_name_to_key(cls.__name__, suffix)
                )
                if key in result:
                    logger.warning(
                        "RegistersScanner: дублирующийся ключ '%s' "
                        "(класс %s из %s), предыдущий будет перезаписан.",
                        key, cls.__name__, py_file.name,
                    )
                result[key] = cls
                logger.debug(
                    "RegistersScanner: найден %s → '%s' (%s)",
                    cls.__name__, key, py_file.name,
                )

        return result

    @staticmethod
    def scan_package_path(
        package_init_file: "str | Path",
        **kwargs: Any,
    ) -> "dict[str, Type[BaseModel]]":
        """
        Удобный вариант для вызова из __init__.py пакета.

        Передай __file__ из __init__.py пакета с регистрами:
            register_map = RegistersScanner.scan_package_path(__file__)
        """
        return RegistersScanner.scan_directory(
            Path(package_init_file).parent, **kwargs
        )

    @staticmethod
    def _extract_classes_from_file(
        py_file: Path,
        base_class: type,
        suffix: str,
    ) -> "list[Type[BaseModel]]":
        """
        Импортировать один .py файл и вернуть список подходящих классов.

        Использует importlib.util для прямой загрузки без пакетного контекста.
        """
        module_name = f"_scanner_tmp_{py_file.stem}_{id(py_file)}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                return []
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as exc:
            logger.warning(
                "RegistersScanner: не удалось импортировать %s: %s",
                py_file.name, exc,
            )
            return []
        finally:
            sys.modules.pop(module_name, None)

        found: list[Type[BaseModel]] = []
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if not name.endswith(suffix):
                continue
            if not issubclass(obj, base_class):
                continue
            if obj is base_class:
                continue
            if getattr(obj, "__module__", None) != module_name:
                continue
            found.append(obj)

        return found

    @staticmethod
    def list_files(
        path: "Path | str",
        recursive: bool = False,
        exclude_files: "list[str] | None" = None,
    ) -> list[Path]:
        """
        Вернуть список .py файлов в директории (без импорта).

        Удобно для предварительной проверки что именно будет просканировано.
        """
        scan_path = Path(path).resolve()
        if not scan_path.exists():
            return []
        _exclude = set(exclude_files or []) | {"__init__", "conftest"}
        pattern = "**/*.py" if recursive else "*.py"
        return sorted(
            f for f in scan_path.glob(pattern)
            if f.stem not in _exclude and not f.stem.startswith("_")
        )
