"""
Скрипт валидации фреймворка.

Проверяет:
1. Все модули импортируются без ошибок
2. Нет sys.path.insert в production-коде
3. Все __init__.py существуют
4. interfaces.py существует в модулях из REQUIRED_INTERFACES
5. STATUS.md в каждом модуле
5a. README.md в каждом модуле
5b. Структура Services/ (__init__.py, interfaces.py, STATUS.md, README.md)
6. ADR-документация синхронизирована (python -m scripts.sync --check)

Архитектурные границы между слоями (framework → Services → Plugins → app) — sentrux check.

Запуск: python scripts/validate.py
"""

import sys
import subprocess
import importlib
from pathlib import Path

BASE = Path(__file__).parent.parent
MODULES_ROOT = BASE / "multiprocess_framework" / "modules"
SERVICES_ROOT = BASE / "Services"

# Как в pytest conftest модулей: плоские импорты (data_schema_module) + пакет multiprocess_framework
for _p in (MODULES_ROOT, BASE):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

MODULES = [
    "app_module",
    "base_manager",
    "channel_routing_module",
    "command_module",
    "config_module",
    "console_module",
    "data_schema_module",
    "dispatch_module",
    "error_module",
    "frontend_module",
    "logger_module",
    "message_module",
    "process_manager_module",
    "process_module",
    "registers_module",
    "router_module",
    "shared_resources_module",
    "statistics_module",
    "worker_module",
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
    "statistics_module",
]

# Сервисы прикладного слоя (Phase 4 carve-out)
# Каждый сервис ожидаемо имеет __init__.py, interfaces.py, STATUS.md, README.md, tests/.
SERVICES = [
    "sql",
    "hikvision_camera",
]

# Сервисы, для которых требуется interfaces.py (Protocol-контракт)
SERVICES_REQUIRED_INTERFACES = [
    "sql",
    "hikvision_camera",
]

# Файлы production-кода (без тестов), где нельзя sys.path.insert
PRODUCTION_DIRS = [
    BASE / "multiprocess_framework" / "modules",
    BASE / "multiprocess_prototype",
]

errors = []
warnings = []


def check_header(text: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print("=" * 60)


def check_imports() -> None:
    check_header("1. Проверка импортов модулей")
    prefix = "multiprocess_framework.modules"
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
            # Исключения: точки входа (launcher + main). Они обязаны
            # бутстрапить sys.path до того, как пакет станет импортируемым.
            if py_file.name in ("main.py", "run.py") and "multiprocess_prototype" in str(py_file):
                continue
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


def check_readme_files() -> None:
    check_header("5a. Проверка README.md в каждом модуле")
    for module_name in MODULES:
        readme_file = MODULES_ROOT / module_name / "README.md"
        if readme_file.exists():
            print(f"  [OK] {module_name}/README.md")
        else:
            msg = f"  [MISS] Нет README.md: {module_name}"
            print(msg)
            warnings.append(msg)


def check_services() -> None:
    """Проверка структуры Services/ (Phase 4 carve-out)."""
    check_header("5b. Проверка Services/ (прикладной слой)")
    for svc in SERVICES:
        svc_dir = SERVICES_ROOT / svc
        # __init__.py
        if (svc_dir / "__init__.py").exists():
            print(f"  [OK] Services/{svc}/__init__.py")
        else:
            msg = f"  [FAIL] Отсутствует: Services/{svc}/__init__.py"
            print(msg)
            errors.append(msg)
        # interfaces.py
        if svc in SERVICES_REQUIRED_INTERFACES:
            if (svc_dir / "interfaces.py").exists():
                print(f"  [OK] Services/{svc}/interfaces.py")
            else:
                msg = f"  [MISS] Нет interfaces.py: Services/{svc}"
                print(msg)
                warnings.append(msg)
        # STATUS.md
        if (svc_dir / "STATUS.md").exists():
            print(f"  [OK] Services/{svc}/STATUS.md")
        else:
            msg = f"  [MISS] Нет STATUS.md: Services/{svc}"
            print(msg)
            warnings.append(msg)
        # README.md
        if (svc_dir / "README.md").exists():
            print(f"  [OK] Services/{svc}/README.md")
        else:
            msg = f"  [MISS] Нет README.md: Services/{svc}"
            print(msg)
            warnings.append(msg)


def check_adr_sync() -> None:
    check_header("6. Проверка синхронизации ADR-документации (scripts/sync --check)")
    result = subprocess.run(
        [sys.executable, "-m", "scripts.sync", "--check"],
        capture_output=True,
        text=True,
        cwd=str(BASE),
    )
    if result.returncode == 0:
        print("  [OK] ADR-документация синхронизирована")
    else:
        msg = "  [FAIL] ADR дрифт обнаружен — запусти: python -m scripts.sync"
        print(msg)
        if result.stderr:
            # печатаем stderr с отступом, чтобы было видно diff
            for line in result.stderr.splitlines():
                print(f"    {line}")
        errors.append(msg)


def main() -> int:
    print("\nMULTIPROCESS FRAMEWORK — Валидация")
    print(f"Base: {BASE}")

    check_imports()
    check_no_syspath()
    check_init_files()
    check_interfaces()
    check_status_files()
    check_readme_files()
    check_services()
    check_adr_sync()

    print(f"\n{'=' * 60}")
    print("  ИТОГ")
    print("=" * 60)

    if errors:
        print(f"\n  ОШИБОК: {len(errors)}")
        for e in errors:
            print(f"    {e.strip()}")
    else:
        print("\n  Ошибок нет!")

    if warnings:
        print(f"\n  ПРЕДУПРЕЖДЕНИЙ: {len(warnings)}")
        for w in warnings:
            print(f"    {w.strip()}")
    else:
        print("  Предупреждений нет!")

    print()
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
