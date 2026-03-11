"""
Скрипт валидации фреймворка.

Проверяет:
1. Все модули импортируются без ошибок
2. Нет sys.path.insert в production-коде
3. Все __init__.py существуют
4. interfaces.py существует в модулях из REQUIRED_INTERFACES

Запуск: python scripts/validate.py
"""

import sys
import importlib
import subprocess
from pathlib import Path

BASE = Path(__file__).parent.parent
MODULES_ROOT = BASE / "multiprocess_framework" / "refactored" / "modules"

MODULES = [
    "base_manager",
    "command_module",
    "config_module",
    "console_module",
    "data_schema_module",
    "dispatch_module",
    "error_module",
    "logger_module",
    "message_module",
    "process_manager_module",
    "process_module",
    "registers_module",
    "router_module",
    "shared_resources_module",
]

# Модули, которые обязаны иметь interfaces.py
REQUIRED_INTERFACES = [
    "base_manager",
    "command_module",
    "config_module",
    "console_module",
    "dispatch_module",
    "error_module",
    "logger_module",
    "message_module",
    "registers_module",
    "router_module",
    "shared_resources_module",
]

# Файлы production-кода (без тестов), где нельзя sys.path.insert
PRODUCTION_DIRS = [
    BASE / "multiprocess_framework" / "refactored" / "modules",
    BASE / "multiprocess_prototype",
]

errors = []
warnings = []


def check_header(text: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {text}")
    print('='*60)


def check_imports() -> None:
    check_header("1. Проверка импортов модулей")
    prefix = "multiprocess_framework.refactored.modules"
    for module_name in MODULES:
        full_name = f"{prefix}.{module_name}"
        try:
            importlib.import_module(full_name)
            print(f"  [OK] {module_name}")
        except Exception as e:
            msg = f"  [FAIL] {module_name}: {e}"
            print(msg)
            errors.append(msg)


def check_no_syspath() -> None:
    check_header("2. Проверка отсутствия sys.path.insert в production-коде")
    for prod_dir in PRODUCTION_DIRS:
        if not prod_dir.exists():
            continue
        for py_file in prod_dir.rglob("*.py"):
            # Пропускаем тесты и этот скрипт
            parts_lower = [p.lower() for p in py_file.parts]
            if any(t in parts_lower for t in ("tests", "test")) or py_file == Path(__file__):
                continue
            if py_file.name.startswith("test_") or py_file.name == "conftest.py":
                continue
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            if "sys.path.insert" in text or "sys.path.append" in text:
                rel = py_file.relative_to(BASE)
                msg = f"  [WARN] sys.path hack найден: {rel}"
                print(msg)
                warnings.append(msg)
    if not warnings:
        print("  [OK] sys.path хаков не найдено")


def check_init_files() -> None:
    check_header("3. Проверка __init__.py в каждом модуле")
    for module_name in MODULES:
        module_dir = MODULES_ROOT / module_name
        init_file = module_dir / "__init__.py"
        if init_file.exists():
            print(f"  [OK] {module_name}/__init__.py")
        else:
            msg = f"  [FAIL] Отсутствует: {module_name}/__init__.py"
            print(msg)
            errors.append(msg)


def check_interfaces() -> None:
    check_header("4. Проверка interfaces.py в обязательных модулях")
    for module_name in REQUIRED_INTERFACES:
        iface_file = MODULES_ROOT / module_name / "interfaces.py"
        if iface_file.exists():
            print(f"  [OK] {module_name}/interfaces.py")
        else:
            msg = f"  [MISS] Нет interfaces.py: {module_name}"
            print(msg)
            warnings.append(msg)


def check_status_files() -> None:
    check_header("5. Проверка STATUS.md в каждом модуле")
    for module_name in MODULES:
        status_file = MODULES_ROOT / module_name / "STATUS.md"
        if status_file.exists():
            print(f"  [OK] {module_name}/STATUS.md")
        else:
            msg = f"  [MISS] Нет STATUS.md: {module_name}"
            print(msg)
            warnings.append(msg)


def main() -> int:
    print(f"\nMULTIPROCESS FRAMEWORK — Валидация")
    print(f"Base: {BASE}")

    check_imports()
    check_no_syspath()
    check_init_files()
    check_interfaces()
    check_status_files()

    print(f"\n{'='*60}")
    print(f"  ИТОГ")
    print('='*60)

    if errors:
        print(f"\n  ОШИБОК: {len(errors)}")
        for e in errors:
            print(f"    {e.strip()}")
    else:
        print(f"\n  Ошибок нет!")

    if warnings:
        print(f"\n  ПРЕДУПРЕЖДЕНИЙ: {len(warnings)}")
        for w in warnings:
            print(f"    {w.strip()}")
    else:
        print(f"  Предупреждений нет!")

    print()
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
