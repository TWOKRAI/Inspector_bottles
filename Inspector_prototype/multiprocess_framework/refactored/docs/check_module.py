"""
Скрипт для проверки конкретного модуля.

Использование:
    python check_module.py worker_module
    python check_module.py process_module --tests
    python check_module.py config_module --validate
"""

import sys
import subprocess
from pathlib import Path
from typing import Optional

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


def check_module_structure(module_name: str) -> bool:
    """Проверить структуру модуля."""
    module_dir = project_root / 'src' / 'multiprocess_framework' / 'refactored' / 'modules' / module_name
    
    if not module_dir.exists():
        print(f"❌ Модуль {module_name} не найден: {module_dir}")
        return False
    
    print(f"\n📁 Проверка структуры модуля {module_name}")
    print("="*60)
    
    required_files = [
        '__init__.py',
        'README.md'
    ]
    
    all_ok = True
    for file_name in required_files:
        file_path = module_dir / file_name
        if file_path.exists():
            print(f"  ✅ {file_name}")
        else:
            print(f"  ❌ {file_name} - не найден")
            all_ok = False
    
    # Проверка наличия core/
    core_dir = module_dir / 'core'
    if core_dir.exists():
        print(f"  ✅ core/")
    else:
        print(f"  ⚠️  core/ - не найден (может быть нормально)")
    
    # Проверка наличия tests/
    tests_dir = module_dir / 'tests'
    if tests_dir.exists():
        test_files = list(tests_dir.glob('test_*.py'))
        print(f"  ✅ tests/ ({len(test_files)} тестов)")
    else:
        print(f"  ⚠️  tests/ - не найден")
    
    return all_ok


def check_imports(module_name: str) -> bool:
    """Проверить импорты модуля."""
    print(f"\n📦 Проверка импортов модуля {module_name}")
    print("="*60)
    
    module_dir = project_root / 'src' / 'multiprocess_framework' / 'refactored' / 'modules' / module_name
    
    # Проверяем наличие старых импортов
    old_imports = [
        'from ...modules.',
        'from modules.',
        'import modules.',
        'Config_module',
        'Shared_resources_module',
        'Dispatch_module',
        'Memory_Manager',
    ]
    
    all_ok = True
    for py_file in module_dir.rglob('*.py'):
        if 'test' in str(py_file) or '__pycache__' in str(py_file):
            continue
        
        try:
            content = py_file.read_text(encoding='utf-8')
            for old_import in old_imports:
                if old_import in content:
                    print(f"  ❌ Найден старый импорт в {py_file.relative_to(module_dir)}: {old_import}")
                    all_ok = False
        except Exception as e:
            print(f"  ⚠️  Не удалось прочитать {py_file}: {e}")
    
    if all_ok:
        print("  ✅ Старых импортов не найдено")
    
    return all_ok


def run_tests(module_name: str) -> bool:
    """Запустить тесты модуля."""
    print(f"\n🧪 Запуск тестов модуля {module_name}")
    print("="*60)
    
    tests_dir = project_root / 'src' / 'multiprocess_framework' / 'refactored' / 'modules' / module_name / 'tests'
    
    if not tests_dir.exists():
        print(f"  ⚠️  Тесты не найдены: {tests_dir}")
        return False
    
    # Определяем тип тестов
    test_files = list(tests_dir.glob('test_*.py'))
    if not test_files:
        print(f"  ⚠️  Файлы тестов не найдены")
        return False
    
    # Проверяем первый файл на использование unittest или pytest
    first_test = test_files[0]
    content = first_test.read_text(encoding='utf-8')
    
    if 'unittest' in content or 'TestCase' in content:
        # unittest
        result = subprocess.run(
            [
                sys.executable, '-m', 'unittest', 'discover',
                '-s', str(tests_dir),
                '-p', 'test_*.py',
                '-v'
            ],
            cwd=str(project_root)
        )
    else:
        # pytest
        result = subprocess.run(
            [
                sys.executable, '-m', 'pytest',
                str(tests_dir),
                '-v',
                '--tb=short'
            ],
            cwd=str(project_root)
        )
    
    return result.returncode == 0


def run_validator(module_name: str) -> bool:
    """Запустить валидатор модуля."""
    print(f"\n✅ Запуск валидатора модуля {module_name}")
    print("="*60)
    
    try:
        result = subprocess.run(
            [
                sys.executable, '-m',
                'multiprocess_framework.refactored.tools.validate_all_modules',
                module_name
            ],
            cwd=str(project_root)
        )
        return result.returncode == 0
    except Exception as e:
        print(f"  ❌ Ошибка при запуске валидатора: {e}")
        return False


def main():
    """Главная функция."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Проверка модуля')
    parser.add_argument('module', type=str, help='Имя модуля для проверки')
    parser.add_argument('--tests', action='store_true', help='Запустить тесты')
    parser.add_argument('--validate', action='store_true', help='Запустить валидатор')
    parser.add_argument('--all', action='store_true', help='Выполнить все проверки')
    
    args = parser.parse_args()
    
    print("🔍 Проверка модуля")
    print("="*60)
    
    all_ok = True
    
    # Структура
    if args.all or not (args.tests or args.validate):
        all_ok = check_module_structure(args.module) and all_ok
    
    # Импорты
    if args.all or not (args.tests or args.validate):
        all_ok = check_imports(args.module) and all_ok
    
    # Тесты
    if args.tests or args.all:
        all_ok = run_tests(args.module) and all_ok
    
    # Валидатор
    if args.validate or args.all:
        all_ok = run_validator(args.module) and all_ok
    
    print("\n" + "="*60)
    if all_ok:
        print("✅ Все проверки пройдены")
    else:
        print("❌ Некоторые проверки провалились")
    print("="*60)
    
    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()

