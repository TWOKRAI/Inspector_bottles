"""
Скрипт для запуска всех тестов модулей.

Использование:
    python run_all_tests.py                    # Все тесты
    python run_all_tests.py --module worker    # Конкретный модуль
    python run_all_tests.py --pytest-only      # Только pytest тесты
    python run_all_tests.py --unittest-only    # Только unittest тесты
"""

import sys
import subprocess
from pathlib import Path
from typing import List, Optional

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Модули с unittest тестами
UNITTEST_MODULES = [
    'console_module',
    'config_module',
]

# Модули с pytest тестами
PYTEST_MODULES = [
    'worker_module',
    'process_module',
    'dispatch_module',
    'base_manager',
    'data_schema_module',
    'message_module',
    'shared_resources_module',
    'router_module',
    'command_module',
    'logger_module',
]

# Все модули
ALL_MODULES = UNITTEST_MODULES + PYTEST_MODULES


def run_unittest(module_name: str) -> bool:
    """Запустить unittest тесты для модуля."""
    tests_dir = project_root / 'src' / 'multiprocess_framework' / 'refactored' / 'modules' / module_name / 'tests'
    
    if not tests_dir.exists():
        print(f"⚠️  Тесты для {module_name} не найдены: {tests_dir}")
        return False
    
    print(f"\n{'='*60}")
    print(f"🧪 Запуск unittest тестов для {module_name}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run(
            [
                sys.executable, '-m', 'unittest', 'discover',
                '-s', str(tests_dir),
                '-p', 'test_*.py',
                '-v'
            ],
            cwd=str(project_root),
            capture_output=False
        )
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Ошибка при запуске тестов для {module_name}: {e}")
        return False


def run_pytest(module_name: str) -> bool:
    """Запустить pytest тесты для модуля."""
    tests_dir = project_root / 'src' / 'multiprocess_framework' / 'refactored' / 'modules' / module_name / 'tests'
    
    if not tests_dir.exists():
        print(f"⚠️  Тесты для {module_name} не найдены: {tests_dir}")
        return False
    
    print(f"\n{'='*60}")
    print(f"🧪 Запуск pytest тестов для {module_name}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run(
            [
                sys.executable, '-m', 'pytest',
                str(tests_dir),
                '-v',
                '--tb=short'
            ],
            cwd=str(project_root),
            capture_output=False
        )
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Ошибка при запуске тестов для {module_name}: {e}")
        return False


def run_all_tests(
    module: Optional[str] = None,
    pytest_only: bool = False,
    unittest_only: bool = False
) -> dict:
    """Запустить все тесты."""
    results = {}
    
    if module:
        # Запустить тесты для конкретного модуля
        if module in UNITTEST_MODULES:
            results[module] = run_unittest(module)
        elif module in PYTEST_MODULES:
            results[module] = run_pytest(module)
        else:
            print(f"❌ Модуль {module} не найден")
            return results
    else:
        # Запустить все тесты
        if not unittest_only:
            print("\n" + "="*60)
            print("📋 Запуск pytest тестов")
            print("="*60)
            for module_name in PYTEST_MODULES:
                results[module_name] = run_pytest(module_name)
        
        if not pytest_only:
            print("\n" + "="*60)
            print("📋 Запуск unittest тестов")
            print("="*60)
            for module_name in UNITTEST_MODULES:
                results[module_name] = run_unittest(module_name)
    
    return results


def print_summary(results: dict):
    """Вывести итоговую статистику."""
    print("\n" + "="*60)
    print("📊 Итоговая статистика")
    print("="*60)
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    failed = total - passed
    
    print(f"\nВсего модулей: {total}")
    print(f"✅ Прошли: {passed}")
    print(f"❌ Провалились: {failed}")
    
    if passed > 0:
        print("\n✅ Успешные модули:")
        for module, result in results.items():
            if result:
                print(f"  - {module}")
    
    if failed > 0:
        print("\n❌ Провалившиеся модули:")
        for module, result in results.items():
            if not result:
                print(f"  - {module}")
    
    print("\n" + "="*60)


def main():
    """Главная функция."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Запуск тестов модулей')
    parser.add_argument('--module', '-m', type=str, help='Запустить тесты для конкретного модуля')
    parser.add_argument('--pytest-only', action='store_true', help='Запустить только pytest тесты')
    parser.add_argument('--unittest-only', action='store_true', help='Запустить только unittest тесты')
    
    args = parser.parse_args()
    
    print("🚀 Запуск тестов модулей Multiprocess Framework (Refactored)")
    print("="*60)
    
    results = run_all_tests(
        module=args.module,
        pytest_only=args.pytest_only,
        unittest_only=args.unittest_only
    )
    
    print_summary(results)
    
    # Код выхода: 0 если все прошли, 1 если есть провалы
    exit_code = 0 if all(results.values()) else 1
    sys.exit(exit_code)


if __name__ == '__main__':
    main()

