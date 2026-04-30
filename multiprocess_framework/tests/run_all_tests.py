#!/usr/bin/env python3
"""
Запуск всех проверок фреймворка: unit-тесты модулей + валидация документации.

Использование:
    python run_all_tests.py                    # Всё: unit-тесты + документация
    python run_all_tests.py --unit-only        # Только unit-тесты
    python run_all_tests.py --docs-only        # Только валидация документации
    python run_all_tests.py --module config    # Только unit-тесты для модуля

Запуск из корня проекта:
    python multiprocess_framework/tests/run_all_tests.py
"""

import sys
from pathlib import Path

# Пути
TESTS_DIR = Path(__file__).resolve().parent
REFACTORED_ROOT = TESTS_DIR.parent
PROJECT_ROOT = REFACTORED_ROOT.parent


def run_unit_tests(module: str | None = None) -> bool:
    """Запустить unit-тесты через run_unit_tests.py."""
    run_unit = TESTS_DIR / "run_unit_tests.py"
    if not run_unit.exists():
        print("❌ run_unit_tests.py не найден")
        return False

    import subprocess

    cmd = [sys.executable, str(run_unit)]
    if module:
        cmd.extend(["--module", module])
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return result.returncode == 0


def run_documentation_validation() -> bool:
    """Запустить валидацию документации (ModuleValidator)."""
    tools_dir = REFACTORED_ROOT / "tools"
    if not tools_dir.exists():
        print("⚠️  Папка tools/ не найдена, пропускаем валидацию документации")
        return True

    module_validator = tools_dir / "module_validator.py"
    if not module_validator.exists():
        print("⚠️  module_validator.py не найден, пропускаем валидацию документации")
        return True

    import subprocess

    # Добавляем refactored в PYTHONPATH для импорта ModuleValidator
    import os

    env = dict(os.environ)
    pythonpath = str(REFACTORED_ROOT)
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"{pythonpath}:{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = pythonpath

    result = subprocess.run(
        [sys.executable, str(module_validator)],
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    return result.returncode == 0


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Запуск всех проверок: unit-тесты + валидация документации"
    )
    parser.add_argument(
        "--unit-only",
        action="store_true",
        help="Запустить только unit-тесты",
    )
    parser.add_argument(
        "--docs-only",
        action="store_true",
        help="Запустить только валидацию документации",
    )
    parser.add_argument(
        "--module",
        "-m",
        type=str,
        help="Запустить unit-тесты только для указанного модуля (игнорируется с --docs-only)",
    )
    args = parser.parse_args()

    print("🚀 Multiprocess Framework — полная проверка")
    print("=" * 60)

    unit_ok = True
    docs_ok = True

    if not args.docs_only:
        print("\n📋 1. Unit-тесты модулей")
        print("-" * 60)
        unit_ok = run_unit_tests(module=args.module)

    if not args.unit_only and not args.module:
        print("\n📋 2. Валидация документации (модули)")
        print("-" * 60)
        docs_ok = run_documentation_validation()

    print("\n" + "=" * 60)
    print("📊 Итог")
    print("=" * 60)
    print(f"Unit-тесты:     {'✅ OK' if unit_ok else '❌ FAILED'}")
    if not args.unit_only and not args.module:
        print(f"Документация:  {'✅ OK' if docs_ok else '❌ FAILED'}")
    print("=" * 60)

    all_ok = unit_ok and docs_ok
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
