#!/usr/bin/env python3
"""
Запуск unit-тестов всех модулей фреймворка.

Зависимости: pydantic, numpy (для shared_resources_module).
Установка: pip install -e . из Inspector_prototype/

Использование:
    python run_unit_tests.py                    # Все unit-тесты
    python run_unit_tests.py --module config    # Конкретный модуль
    python run_unit_tests.py -v                 # Подробный вывод
    python run_unit_tests.py -q                 # Краткий вывод

Запуск из корня Inspector_prototype:
    python multiprocess_framework/tests/run_unit_tests.py

Или из refactored/tests/:
    python run_unit_tests.py
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import List, Optional

# Пути: tests/run_unit_tests.py -> refactored/tests/ -> refactored/
TESTS_DIR = Path(__file__).resolve().parent
REFACTORED_ROOT = TESTS_DIR.parent
MODULES_PATH = REFACTORED_ROOT / "modules"
# Inspector_prototype/ (корень проекта с pyproject.toml)
PROJECT_ROOT = REFACTORED_ROOT.parent.parent

# Модули с тестами (исключаем tests_backup)
MODULES_WITH_TESTS = [
    "base_manager",
    "channel_routing_module",
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
    "router_module",
    "shared_resources_module",
    "statistics_module",
    "worker_module",
]


def get_test_paths(module: Optional[str] = None) -> List[Path]:
    """Получить пути к тестам для запуска."""
    if module:
        if module not in MODULES_WITH_TESTS:
            return []
        tests_dir = MODULES_PATH / module / "tests"
        if tests_dir.exists():
            return [tests_dir]
        return []

    paths = []
    for mod in MODULES_WITH_TESTS:
        tests_dir = MODULES_PATH / mod / "tests"
        if tests_dir.exists():
            paths.append(tests_dir)
    return paths


def run_unit_tests(
    module: Optional[str] = None,
    verbose: bool = True,
    extra_args: Optional[List[str]] = None,
) -> bool:
    """
    Запустить unit-тесты модулей через pytest.

    PYTHONPATH устанавливается так, чтобы модули импортировались как
    data_schema_module, config_module и т.д.
    """
    paths = get_test_paths(module)
    if not paths:
        mod_str = f"модуля {module}" if module else "модулей"
        print(f"⚠️  Тесты для {mod_str} не найдены")
        return False

    env = dict(os.environ)
    # Корень проекта + modules — для patch("multiprocess_framework...") и импортов data_schema_module
    pythonpath = f"{PROJECT_ROOT}:{MODULES_PATH}"
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"{pythonpath}:{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = pythonpath

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *[str(p) for p in paths],
        "--ignore=*/tests_backup/*",
        "--ignore=*tests_backup*",
        "-v" if verbose else "-q",
        "--tb=short",
    ]
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    return result.returncode == 0


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Запуск unit-тестов модулей Multiprocess Framework"
    )
    parser.add_argument(
        "--module",
        "-m",
        type=str,
        help="Запустить тесты только для указанного модуля",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=True,
        help="Подробный вывод (по умолчанию)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Краткий вывод",
    )
    parser.add_argument(
        "pytest_args",
        nargs="*",
        help="Дополнительные аргументы для pytest (например, -x, -k test_name)",
    )
    args = parser.parse_args()

    print("🧪 Unit-тесты модулей Multiprocess Framework")
    print("=" * 60)
    if args.module:
        print(f"Модуль: {args.module}")
    else:
        print(f"Модули: {len(MODULES_WITH_TESTS)}")
    print("=" * 60)

    success = run_unit_tests(
        module=args.module,
        verbose=not args.quiet,
        extra_args=args.pytest_args if args.pytest_args else None,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
