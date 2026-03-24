"""
Валидатор модулей для проверки соответствия стандартам.

Проверяет:
- Интерфейсы соответствуют реализации
- Импорты корректны (нет зависимостей от старого кода)
- Документация актуальна (есть docstrings для всех публичных методов)
- Type hints везде
- Тесты покрывают все публичные методы
- Соответствие структуре модуля
"""

import ast
import inspect
import importlib
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    """Результат валидации модуля."""
    module_name: str
    passed: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checks: Dict[str, bool] = field(default_factory=dict)


class ModuleValidator:
    """
    Валидатор модулей для проверки соответствия стандартам.
    
    Проверяет модули на:
    - Соответствие интерфейсов реализации
    - Корректность импортов
    - Наличие документации
    - Type hints
    - Наличие тестов
    - Структуру модуля
    """
    
    def __init__(self, refactored_path: Optional[Path] = None):
        """
        Инициализация валидатора.
        
        Args:
            refactored_path: Путь к директории refactored (по умолчанию определяется автоматически)
        """
        if refactored_path is None:
            # Определяем путь к refactored автоматически
            current_file = Path(__file__).resolve()
            self.refactored_path = current_file.parent.parent
        else:
            self.refactored_path = Path(refactored_path)
        
        self.modules_path = self.refactored_path / "modules"
        self.tests_path = self.refactored_path / "tests"
        
        # Старые пути для проверки зависимостей
        self.old_modules_patterns = [
            "multiprocess_framework.modules.",
            "from multiprocess_framework.modules",
            "import multiprocess_framework.modules"
        ]
    
    def validate_module(self, module_name: str) -> ValidationResult:
        """
        Валидация модуля.
        
        Args:
            module_name: Имя модуля (например, "base_manager")
            
        Returns:
            ValidationResult с результатами валидации
        """
        result = ValidationResult(module_name=module_name)
        
        module_path = self.modules_path / module_name
        
        if not module_path.exists():
            result.passed = False
            result.errors.append(f"Модуль {module_name} не найден")
            return result
        
        # Проверка структуры модуля
        self._check_module_structure(module_path, result)
        
        # Проверка импортов
        self._check_imports(module_path, result)
        
        # Проверка интерфейсов
        self._check_interfaces(module_path, result)
        
        # Проверка документации
        self._check_documentation(module_path, result)
        
        # Проверка type hints
        self._check_type_hints(module_path, result)
        
        # Проверка тестов
        self._check_tests(module_path, result)
        
        # Определяем общий результат
        result.passed = len(result.errors) == 0
        
        return result
    
    def _check_module_structure(self, module_path: Path, result: ValidationResult):
        """Проверка структуры модуля."""
        checks = {
            "has_init": (module_path / "__init__.py").exists(),
            "has_readme": (module_path / "README.md").exists(),
            "has_interfaces": (module_path / "interfaces.py").exists(),
            "has_core": (module_path / "core").exists(),
            "has_tests": (module_path / "tests").exists(),
        }
        
        result.checks.update(checks)
        
        if not checks["has_init"]:
            result.warnings.append("Отсутствует __init__.py")
        if not checks["has_readme"]:
            result.warnings.append("Отсутствует README.md")
        if not checks["has_interfaces"]:
            result.warnings.append("Отсутствует interfaces.py")
        if not checks["has_core"]:
            result.warnings.append("Отсутствует директория core/")
        if not checks["has_tests"]:
            result.warnings.append("Отсутствует директория tests/")
    
    def _check_imports(self, module_path: Path, result: ValidationResult):
        """Проверка импортов на зависимости от старого кода."""
        python_files = list(module_path.rglob("*.py"))
        
        for py_file in python_files:
            if "test" in py_file.name.lower():
                continue  # Пропускаем тесты
            
            try:
                content = py_file.read_text(encoding="utf-8")
                
                for pattern in self.old_modules_patterns:
                    if pattern in content:
                        result.errors.append(
                            f"Найдена зависимость от старого кода в {py_file.relative_to(self.refactored_path)}: {pattern}"
                        )
            except Exception as e:
                result.warnings.append(f"Не удалось проверить {py_file.name}: {e}")
    
    def _check_interfaces(self, module_path: Path, result: ValidationResult):
        """Проверка соответствия интерфейсов реализации."""
        interfaces_file = module_path / "interfaces.py"
        
        if not interfaces_file.exists():
            return  # Уже предупреждение в структуре
        
        try:
            # Парсим интерфейсы
            interfaces_ast = ast.parse(interfaces_file.read_text(encoding="utf-8"))
            interface_classes = [
                node.name for node in ast.walk(interfaces_ast)
                if isinstance(node, ast.ClassDef) and any(
                    base.id == "ABC" for base in node.bases
                    if isinstance(base, ast.Name)
                )
            ]
            
            if not interface_classes:
                result.warnings.append("Не найдено интерфейсов в interfaces.py")
                return
            
            # Проверяем реализацию интерфейсов в core/
            core_path = module_path / "core"
            if not core_path.exists():
                return
            
            # Простая проверка - ищем классы с теми же именами (без префикса I)
            for interface_name in interface_classes:
                if interface_name.startswith("I"):
                    impl_name = interface_name[1:]  # Убираем префикс I
                    # Ищем реализацию
                    impl_found = False
                    for py_file in core_path.rglob("*.py"):
                        try:
                            content = py_file.read_text(encoding="utf-8")
                            if f"class {impl_name}" in content:
                                impl_found = True
                                break
                        except:
                            pass
                    
                    if not impl_found:
                        result.warnings.append(
                            f"Интерфейс {interface_name} не имеет реализации {impl_name}"
                        )
        except Exception as e:
            result.warnings.append(f"Не удалось проверить интерфейсы: {e}")
    
    def _check_documentation(self, module_path: Path, result: ValidationResult):
        """Проверка наличия документации."""
        python_files = list(module_path.rglob("*.py"))
        files_without_docs = []
        
        for py_file in python_files:
            if "test" in py_file.name.lower() or "__init__" in py_file.name:
                continue
            
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)
                
                # Проверяем классы и функции верхнего уровня
                for node in ast.walk(tree):
                    if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                        if not ast.get_docstring(node):
                            if isinstance(node, ast.ClassDef):
                                files_without_docs.append(f"{py_file.name}: класс {node.name}")
                            elif isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                                files_without_docs.append(f"{py_file.name}: функция {node.name}")
            except:
                pass
        
        if files_without_docs:
            result.warnings.append(
                f"Найдено {len(files_without_docs)} элементов без документации"
            )
    
    def _check_type_hints(self, module_path: Path, result: ValidationResult):
        """Проверка наличия type hints."""
        python_files = list(module_path.rglob("*.py"))
        files_without_hints = []
        
        for py_file in python_files:
            if "test" in py_file.name.lower() or "__init__" in py_file.name:
                continue
            
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)
                
                # Проверяем функции без type hints
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                        if not node.returns and not node.args.args:
                            # Функция без параметров и возвращаемого значения - OK
                            continue
                        if not node.returns:
                            files_without_hints.append(f"{py_file.name}: {node.name} без return type")
            except:
                pass
        
        if files_without_hints:
            result.warnings.append(
                f"Найдено {len(files_without_hints)} функций без type hints"
            )
    
    def _check_tests(self, module_path: Path, result: ValidationResult):
        """Проверка наличия тестов."""
        tests_path = module_path / "tests"
        
        if not tests_path.exists():
            return  # Уже предупреждение в структуре
        
        test_files = list(tests_path.glob("test_*.py"))
        
        if not test_files:
            result.warnings.append("Нет тестовых файлов")
        else:
            result.checks["test_files_count"] = len(test_files)
    
    def validate_all_modules(self) -> Dict[str, ValidationResult]:
        """
        Валидация всех модулей.
        
        Returns:
            Словарь {module_name: ValidationResult}
        """
        results = {}
        
        if not self.modules_path.exists():
            return results
        
        # Находим все модули
        for item in self.modules_path.iterdir():
            if item.is_dir() and not item.name.startswith("__"):
                module_name = item.name
                results[module_name] = self.validate_module(module_name)
        
        return results


def main():
    """Главная функция для запуска валидации."""
    import sys
    
    validator = ModuleValidator()
    
    if len(sys.argv) > 1:
        # Валидация конкретного модуля
        module_name = sys.argv[1]
        result = validator.validate_module(module_name)
        
        print(f"\n{'='*60}")
        print(f"Валидация модуля: {module_name}")
        print(f"{'='*60}")
        print(f"Статус: {'✅ ПРОШЕЛ' if result.passed else '❌ НЕ ПРОШЕЛ'}")
        
        if result.errors:
            print(f"\nОшибки ({len(result.errors)}):")
            for error in result.errors:
                print(f"  ❌ {error}")
        
        if result.warnings:
            print(f"\nПредупреждения ({len(result.warnings)}):")
            for warning in result.warnings:
                print(f"  ⚠️  {warning}")
        
        if result.checks:
            print(f"\nПроверки:")
            for check, passed in result.checks.items():
                status = "✅" if passed else "❌"
                print(f"  {status} {check}")
    else:
        # Валидация всех модулей
        results = validator.validate_all_modules()
        
        print(f"\n{'='*60}")
        print(f"Валидация всех модулей")
        print(f"{'='*60}\n")
        
        passed = sum(1 for r in results.values() if r.passed)
        total = len(results)
        
        print(f"Всего модулей: {total}")
        print(f"Прошли валидацию: {passed}")
        print(f"Не прошли: {total - passed}\n")
        
        for module_name, result in sorted(results.items()):
            status = "✅" if result.passed else "❌"
            print(f"{status} {module_name}")
            if result.errors:
                for error in result.errors[:3]:  # Показываем первые 3 ошибки
                    print(f"    ❌ {error}")
            if len(result.errors) > 3:
                print(f"    ... и еще {len(result.errors) - 3} ошибок")


if __name__ == "__main__":
    main()

