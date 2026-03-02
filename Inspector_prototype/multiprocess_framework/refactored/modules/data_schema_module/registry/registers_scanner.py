# -*- coding: utf-8 -*-
"""
RegistersScanner — автообнаружение RegisterBase-подклассов по файловой системе.

В отличие от discover_registers_from_package() (который читает __init__.py),
сканер работает напрямую с .py файлами в директории.

Преимущества:
    - Не нужно вручную обновлять __init__.py при добавлении нового регистра
    - Добавил файл VibrationRegisters.py → он появится в контейнере автоматически
    - Работает без изменений в других частях кода

Будущее (TODO):
    - RegistersScanner.rescan(container) — горячая перезагрузка новых моделей
      во время работы приложения без перезапуска.
      Пример: file-watcher обнаружил vibration.py →
              scanner.rescan(rm) → rm теперь включает VibrationRegisters.

Использование:

    # Вариант 1: прямой путь к папке
    from multiprocess_framework.refactored.modules.data_schema_module import RegistersScanner
    register_map = RegistersScanner.scan_directory("App/Registers/models/registers")

    # Вариант 2: из __init__.py пакета (передать __file__)
    register_map = RegistersScanner.scan_package_path(__file__)

    # Вариант 3: рекурсивный поиск в подпапках
    register_map = RegistersScanner.scan_directory(path, recursive=True)

    # Создать контейнер:
    from multiprocess_framework.refactored.modules.data_schema_module import RegistersContainer
    container = RegistersContainer(register_map)
"""
from __future__ import annotations

import importlib.util
import inspect
import logging
import re
import sys
from pathlib import Path
from typing import Any, Callable, Type

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def _class_name_to_snake(class_name: str, suffix: str) -> str:
    """
    CamelCaseName + suffix → snake_case key.
    DrawRegisters + "Registers" → draw
    FrameProcessRegisters + "Registers" → frame_process
    """
    if not suffix or not class_name.endswith(suffix):
        return class_name.lower()
    base = class_name[: -len(suffix)]
    if not base:
        return class_name.lower()
    return re.sub(r"(?<!^)(?=[A-Z])", "_", base).lower()


class RegistersScanner:
    """
    Сканер RegisterBase-подклассов в директории.

    Все методы — статические. Класс не нужно инстанциировать.

    TODO (будущее): добавить метод rescan(container) для горячей
    перезагрузки новых моделей во время работы приложения:
        scanner = RegistersScanner()
        # ... позже, при обнаружении нового файла file-watcher'ом:
        new_classes = scanner.rescan(base_path, existing_container)
        # existing_container обновляется без перезапуска
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
            path:           Путь к директории с .py файлами.
            base_class:     Базовый класс для фильтрации (по умолч. RegisterBase).
                            Если None — принимается любой BaseModel-подкласс.
            suffix:         Суффикс имени класса: "Registers", "Data", "Config", ...
            recursive:      True — искать рекурсивно в подпапках.
            name_from_class: Функция (cls) → str для кастомного именования ключей.
                             Если None — используется snake_case от суффикса.
            exclude_files:  Список имён файлов для исключения (без расширения).
                            По умолч.: ["__init__", "conftest"].

        Returns:
            Словарь {key: class}, например {"draw": DrawRegisters}.
            Пустой dict если директория не существует или классы не найдены.
        """
        # Отложенный импорт чтобы не было circular dependency
        if base_class is None:
            from ..fields.register_base import RegisterBase
            base_class = RegisterBase

        scan_path = Path(path).resolve()
        if not scan_path.exists() or not scan_path.is_dir():
            logger.warning(
                "RegistersScanner: директория не найдена: %s", scan_path
            )
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
                    else _class_name_to_snake(cls.__name__, suffix)
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
            # Эквивалент scan_directory(Path(__file__).parent, ...)

        Args:
            package_init_file: Путь к __init__.py пакета (обычно передают __file__).
            **kwargs:          Остальные параметры scan_directory.

        Returns:
            Словарь {key: class}.
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
        Классы фильтруются по:
            - наследование от base_class
            - имя заканчивается на suffix
            - класс определён именно в этом файле (не импортирован из другого)
        """
        module_name = f"_scanner_tmp_{py_file.stem}_{id(py_file)}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                return []
            module = importlib.util.module_from_spec(spec)
            # Регистрируем временно, чтобы относительные импорты внутри файла работали
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
            # Проверяем что класс определён именно в этом модуле (не импортирован).
            # Используем __module__, т.к. после sys.modules.pop inspect.getfile
            # не может найти модуль по имени и бросает TypeError.
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
