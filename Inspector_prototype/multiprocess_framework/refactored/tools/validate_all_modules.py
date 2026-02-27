"""
Скрипт для автоматической валидации всех модулей.

Запуск:
    python -m multiprocess_framework.refactored.tools.validate_all_modules
    
Или для конкретного модуля:
    python -m multiprocess_framework.refactored.tools.validate_all_modules base_manager
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

# Добавляем путь к модулям
# Находим корень проекта (где находится src/)
current_file = Path(__file__).resolve()
# От tools/ до корня проекта: tools -> refactored -> multiprocess_framework -> src -> корень
project_root = current_file.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from multiprocess_framework.refactored.tools.module_validator import ModuleValidator, ValidationResult


def generate_report(results: dict[str, ValidationResult], output_file: Optional[Path] = None):
    """
    Генерация отчета о валидации.
    
    Args:
        results: Словарь результатов валидации
        output_file: Файл для сохранения отчета (опционально)
    """
    report_lines = []
    report_lines.append("# Отчет о валидации модулей\n")
    report_lines.append(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    
    # Статистика
    total = len(results)
    passed = sum(1 for r in results.values() if r.passed)
    failed = total - passed
    
    report_lines.append("## Статистика\n\n")
    report_lines.append(f"- Всего модулей: {total}\n")
    report_lines.append(f"- Прошли валидацию: {passed} ✅\n")
    report_lines.append(f"- Не прошли: {failed} ❌\n\n")
    
    # Детали по модулям
    report_lines.append("## Детали по модулям\n\n")
    
    for module_name, result in sorted(results.items()):
        status = "✅ ПРОШЕЛ" if result.passed else "❌ НЕ ПРОШЕЛ"
        report_lines.append(f"### {module_name} - {status}\n\n")
        
        if result.errors:
            report_lines.append("**Ошибки:**\n")
            for error in result.errors:
                report_lines.append(f"- ❌ {error}\n")
            report_lines.append("\n")
        
        if result.warnings:
            report_lines.append("**Предупреждения:**\n")
            for warning in result.warnings[:10]:  # Первые 10 предупреждений
                report_lines.append(f"- ⚠️  {warning}\n")
            if len(result.warnings) > 10:
                report_lines.append(f"- ... и еще {len(result.warnings) - 10} предупреждений\n")
            report_lines.append("\n")
        
        if result.checks:
            report_lines.append("**Проверки:**\n")
            for check, passed in result.checks.items():
                status_icon = "✅" if passed else "❌"
                report_lines.append(f"- {status_icon} {check}\n")
            report_lines.append("\n")
        
        report_lines.append("---\n\n")
    
    report_text = "".join(report_lines)
    
    if output_file:
        output_file.write_text(report_text, encoding="utf-8")
        print(f"Отчет сохранен в {output_file}")
    else:
        print(report_text)


def main():
    """Главная функция."""
    validator = ModuleValidator()
    
    if len(sys.argv) > 1:
        # Валидация конкретного модуля
        module_name = sys.argv[1]
        result = validator.validate_module(module_name)
        
        print(f"\n{'='*60}")
        print(f"Валидация модуля: {module_name}")
        print(f"{'='*60}")
        print(f"Статус: {'✅ ПРОШЕЛ' if result.passed else '❌ НЕ ПРОШЕЛ'}\n")
        
        if result.errors:
            print(f"Ошибки ({len(result.errors)}):")
            for error in result.errors:
                print(f"  ❌ {error}")
            print()
        
        if result.warnings:
            print(f"Предупреждения ({len(result.warnings)}):")
            for warning in result.warnings:
                print(f"  ⚠️  {warning}")
            print()
        
        if result.checks:
            print("Проверки:")
            for check, passed in result.checks.items():
                status = "✅" if passed else "❌"
                print(f"  {status} {check}")
    else:
        # Валидация всех модулей
        print("Запуск валидации всех модулей...\n")
        results = validator.validate_all_modules()
        
        # Вывод в консоль
        passed = sum(1 for r in results.values() if r.passed)
        total = len(results)
        
        print(f"{'='*60}")
        print(f"Результаты валидации")
        print(f"{'='*60}\n")
        print(f"Всего модулей: {total}")
        print(f"Прошли валидацию: {passed} ✅")
        print(f"Не прошли: {total - passed} ❌\n")
        
        # Детали
        for module_name, result in sorted(results.items()):
            status = "✅" if result.passed else "❌"
            error_count = len(result.errors)
            warning_count = len(result.warnings)
            
            print(f"{status} {module_name}", end="")
            if error_count > 0:
                print(f" ({error_count} ошибок)", end="")
            if warning_count > 0:
                print(f" ({warning_count} предупреждений)", end="")
            print()
        
        # Генерация отчета
        report_path = validator.refactored_path / "MODULES_VALIDATION_REPORT.md"
        generate_report(results, report_path)
        
        # Возвращаем код выхода
        sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()

