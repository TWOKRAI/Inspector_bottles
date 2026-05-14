"""
Скрипт для запуска всех интеграционных тестов.

Использование:
    python run_integration_tests.py                    # Все тесты
    python run_integration_tests.py --file test_template_application.py  # Конкретный файл
    python run_integration_tests.py --class TestApplicationLifecycle     # Конкретный класс
    python run_integration_tests.py --test test_app_initialization       # Конкретный тест
    python run_integration_tests.py --verbose                           # Подробный вывод
    python run_integration_tests.py --stop-on-failure                   # Остановка на первой ошибке
"""

import sys
import subprocess
from pathlib import Path
from typing import Optional, Dict
import argparse

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Путь к интеграционным тестам
INTEGRATION_TESTS_DIR = Path(__file__).parent

# Все тестовые файлы
TEST_FILES = [
    "test_comprehensive_integration.py",
    "test_module_interactions.py",
    "test_performance.py",
    "test_template_application.py",
    "test_template_application_comprehensive.py",
    "test_usage_scenarios.py",
]


def run_pytest(
    test_path: str, verbose: bool = False, stop_on_failure: bool = False, capture_output: bool = False
) -> tuple[bool, str]:
    """
    Запустить pytest тесты.

    Args:
        test_path: Путь к тесту (файл, класс или метод)
        verbose: Подробный вывод
        stop_on_failure: Остановка на первой ошибке
        capture_output: Захватывать вывод (для анализа)

    Returns:
        tuple: (успех, вывод)
    """
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(INTEGRATION_TESTS_DIR / test_path),
        "-v" if verbose else "",
        "-x" if stop_on_failure else "",
        "--tb=short",
        "--color=yes",
    ]

    # Убираем пустые строки из команды
    cmd = [c for c in cmd if c]

    try:
        if capture_output:
            result = subprocess.run(cmd, cwd=str(project_root), capture_output=True, text=True)
            output = result.stdout + result.stderr
            return result.returncode == 0, output
        else:
            result = subprocess.run(cmd, cwd=str(project_root), capture_output=False)
            return result.returncode == 0, ""
    except Exception as e:
        error_msg = f"Ошибка при запуске тестов: {e}"
        print(f"❌ {error_msg}")
        return False, error_msg


def run_all_integration_tests(
    test_file: Optional[str] = None,
    test_class: Optional[str] = None,
    test_method: Optional[str] = None,
    verbose: bool = False,
    stop_on_failure: bool = False,
) -> Dict[str, tuple[bool, str]]:
    """
    Запустить все интеграционные тесты.

    Args:
        test_file: Конкретный файл теста
        test_class: Конкретный класс теста
        test_method: Конкретный метод теста
        verbose: Подробный вывод
        stop_on_failure: Остановка на первой ошибке

    Returns:
        dict: Результаты тестов {имя: (успех, вывод)}
    """
    results = {}

    if test_method and test_class:
        # Запустить конкретный тест
        test_path = f"{test_file}::{test_class}::{test_method}"
        print(f"\n{'=' * 70}")
        print(f"[TEST] Запуск теста: {test_path}")
        print(f"{'=' * 70}")
        success, output = run_pytest(test_path, verbose, stop_on_failure, capture_output=True)
        results[test_path] = (success, output)
    elif test_class:
        # Запустить конкретный класс
        test_path = f"{test_file}::{test_class}"
        print(f"\n{'=' * 70}")
        print(f"[CLASS] Запуск класса: {test_path}")
        print(f"{'=' * 70}")
        success, output = run_pytest(test_path, verbose, stop_on_failure, capture_output=True)
        results[test_path] = (success, output)
    elif test_file:
        # Запустить конкретный файл
        print(f"\n{'=' * 70}")
        print(f"[FILE] Запуск файла: {test_file}")
        print(f"{'=' * 70}")
        success, output = run_pytest(test_file, verbose, stop_on_failure, capture_output=True)
        results[test_file] = (success, output)
    else:
        # Запустить все тесты
        print(f"\n{'=' * 70}")
        print("[ALL] Запуск всех интеграционных тестов")
        print(f"{'=' * 70}")

        for test_file_name in TEST_FILES:
            test_path = test_file_name
            print(f"\n{'=' * 70}")
            print(f"[FILE] Тестовый файл: {test_file_name}")
            print(f"{'=' * 70}")

            success, output = run_pytest(test_path, verbose, stop_on_failure, capture_output=True)
            results[test_file_name] = (success, output)

            if stop_on_failure and not success:
                print(f"\n⚠️  Остановка на первой ошибке в {test_file_name}")
                break

    return results


def analyze_results(results: Dict[str, tuple[bool, str]]) -> Dict:
    """
    Анализировать результаты тестов и найти проблемы.

    Args:
        results: Результаты тестов

    Returns:
        dict: Анализ результатов
    """
    analysis = {"total": len(results), "passed": 0, "failed": 0, "errors": [], "warnings": [], "failed_tests": []}

    for test_name, (success, output) in results.items():
        if success:
            analysis["passed"] += 1
        else:
            analysis["failed"] += 1
            analysis["failed_tests"].append(test_name)

            # Анализ вывода для поиска ошибок
            if output:
                lines = output.split("\n")
                for i, line in enumerate(lines):
                    # Поиск ошибок
                    if "ERROR" in line or "Error" in line or "FAILED" in line:
                        # Берем контекст вокруг ошибки
                        context_start = max(0, i - 2)
                        context_end = min(len(lines), i + 5)
                        context = "\n".join(lines[context_start:context_end])
                        analysis["errors"].append({"test": test_name, "error": line, "context": context})

                    # Поиск предупреждений
                    if "WARNING" in line or "Warning" in line:
                        analysis["warnings"].append({"test": test_name, "warning": line})

    return analysis


def print_summary(results: Dict[str, tuple[bool, str]], analysis: Dict):
    """
    Вывести итоговую статистику и анализ.

    Args:
        results: Результаты тестов
        analysis: Анализ результатов
    """
    print("\n" + "=" * 70)
    print("📊 ИТОГОВАЯ СТАТИСТИКА")
    print("=" * 70)

    print(f"\nВсего тестовых файлов: {analysis['total']}")
    print(f"✅ Прошли: {analysis['passed']}")
    print(f"❌ Провалились: {analysis['failed']}")

    if analysis["passed"] > 0:
        print("\n[PASS] Успешные тесты:")
        for test_name, (success, _) in results.items():
            if success:
                print(f"  [OK] {test_name}")

    if analysis["failed"] > 0:
        print("\n[FAIL] Провалившиеся тесты:")
        for test_name in analysis["failed_tests"]:
            print(f"  [X] {test_name}")

    if analysis["errors"]:
        print("\n" + "=" * 70)
        print("[ERRORS] НАЙДЕННЫЕ ОШИБКИ")
        print("=" * 70)
        for i, error in enumerate(analysis["errors"][:10], 1):  # Показываем первые 10
            print(f"\n{i}. Тест: {error['test']}")
            print(f"   Ошибка: {error['error']}")
            if error.get("context"):
                print(f"   Контекст:\n{error['context']}")

        if len(analysis["errors"]) > 10:
            print(f"\n... и еще {len(analysis['errors']) - 10} ошибок")

    if analysis["warnings"]:
        print("\n" + "=" * 70)
        print("[WARN] ПРЕДУПРЕЖДЕНИЯ")
        print("=" * 70)
        for i, warning in enumerate(analysis["warnings"][:5], 1):  # Показываем первые 5
            print(f"{i}. {warning['test']}: {warning['warning']}")

        if len(analysis["warnings"]) > 5:
            print(f"\n... и еще {len(analysis['warnings']) - 5} предупреждений")

    print("\n" + "=" * 70)

    # Рекомендации
    if analysis["failed"] > 0:
        print("\n[TIPS] РЕКОМЕНДАЦИИ:")
        print("   1. Проверьте вывод ошибок выше")
        print("   2. Запустите конкретный тест для детального анализа:")
        print("      python run_integration_tests.py --file <имя_файла> --verbose")
        print("   3. Проверьте зависимости и импорты")
        print("   4. Убедитесь что все модули инициализированы корректно")

    print("\n" + "=" * 70)


def main():
    """Главная функция."""
    # Настройка кодировки для Windows
    import io
    import sys

    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Запуск интеграционных тестов Multiprocess Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python run_integration_tests.py
  python run_integration_tests.py --file test_template_application.py
  python run_integration_tests.py --file test_comprehensive_integration.py --class TestApplicationLifecycle
  python run_integration_tests.py --verbose --stop-on-failure
        """,
    )

    parser.add_argument("--file", "-f", type=str, help="Запустить тесты из конкретного файла")
    parser.add_argument("--class", "-c", dest="test_class", type=str, help="Запустить тесты конкретного класса")
    parser.add_argument("--test", "-t", dest="test_method", type=str, help="Запустить конкретный тест")
    parser.add_argument("--verbose", "-v", action="store_true", help="Подробный вывод")
    parser.add_argument("--stop-on-failure", "-x", action="store_true", help="Остановка на первой ошибке")

    args = parser.parse_args()

    print("[RUN] Запуск интеграционных тестов Multiprocess Framework")
    print("=" * 70)
    print(f"[DIR] Директория тестов: {INTEGRATION_TESTS_DIR}")
    print(f"[INFO] Тестовых файлов: {len(TEST_FILES)}")

    # Запуск тестов
    results = run_all_integration_tests(
        test_file=args.file,
        test_class=args.test_class,
        test_method=args.test_method,
        verbose=args.verbose,
        stop_on_failure=args.stop_on_failure,
    )

    # Анализ результатов
    analysis = analyze_results(results)

    # Вывод статистики
    print_summary(results, analysis)

    # Код выхода: 0 если все прошли, 1 если есть провалы
    exit_code = 0 if analysis["failed"] == 0 else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
