"""Страж дедлайнов в тредовых тестах наблюдаемости (план D2, шаг 3).

Смысл: **регрессия обязана падать, а не висеть**. Тест, который вместо красного
блокируется в `join()`/`wait()`, хуже отсутствующего — он прячет поломку за
таймаутом всего прогона, и виноватым выглядит CI, а не правка. Класс уже кусал
проект: в Ф0.3 инъекция «цикл не слышит stop_event» вместо красного дала
подвисший прогон, снимать пришлось руками.

Правило простое: в тестах плоскостей наблюдаемости (логи / ошибки / статистика /
общая база каналов) у каждого ожидания есть дедлайн.

  * `X.join()` без аргумента — нарушение всегда;
  * `X.wait()` без аргумента — нарушение, КРОМЕ случая, когда `X` в этом же файле
    создан как `threading.Barrier(..., timeout=...)`: у барьера дедлайн задаётся
    конструктором и работает на каждом `wait()`.

Проверка статическая (AST), цена — доли секунды. Она сознательно НЕ смотрит на
`Thread(daemon=...)`: демон спасает интерпретатор от вечного зависания на выходе,
но не спасает прогон — тест всё равно стоит до общего таймаута.

Список каталогов ниже — не «весь репозиторий»: правило вводится там, где живёт
наблюдаемость. Расширять осознанно, каталогом за каталогом.
"""

from __future__ import annotations

import ast
from pathlib import Path

_MODULES_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _MODULES_ROOT.parents[1]

# Каталоги целиком: плоскости наблюдаемости и их общая база.
_GUARDED_DIRS = (
    "multiprocess_framework/modules/channel_routing_module/tests",
    "multiprocess_framework/modules/logger_module/tests",
    "multiprocess_framework/modules/error_module/tests",
    "multiprocess_framework/modules/statistics_module/tests",
)

# Отдельные файлы наблюдаемости в чужих каталогах.
_GUARDED_GLOBS = (
    "multiprocess_framework/modules/process_module/tests/test_observability*.py",
    "backend_ctl/tests/test_observability*.py",
    "backend_ctl/tests/test_audit_threading.py",
)


def _guarded_files() -> list[Path]:
    files: set[Path] = set()
    for rel in _GUARDED_DIRS:
        files.update((_REPO_ROOT / rel).rglob("test_*.py"))
    for pattern in _GUARDED_GLOBS:
        files.update(_REPO_ROOT.glob(pattern))
    return sorted(files)


def _is_barrier_call(node: ast.AST) -> bool:
    """`threading.Barrier(...)` или голый `Barrier(...)`."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "Barrier"
    return isinstance(func, ast.Name) and func.id == "Barrier"


def _barriers_with_own_deadline(tree: ast.AST) -> set[str]:
    """Имена, которым присвоен барьер с `timeout=` в конструкторе.

    Возвращаются в текстовом виде (`barrier`, `self._barrier`) — сравнение с
    получателем `wait()` идёт по тому же тексту.
    """
    named: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not _is_barrier_call(node.value):
            continue
        call = node.value
        has_deadline = any(kw.arg == "timeout" for kw in call.keywords) or len(call.args) > 1
        if not has_deadline:
            continue
        for target in node.targets:
            if isinstance(target, (ast.Name, ast.Attribute)):
                named.add(ast.unparse(target))
    return named


def _violations_in_source(source: str, label: str) -> list[str]:
    tree = ast.parse(source)
    exempt = _barriers_with_own_deadline(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.args or node.keywords:
            continue
        method = node.func.attr
        if method not in {"join", "wait"}:
            continue
        receiver = ast.unparse(node.func.value)
        if method == "wait" and receiver in exempt:
            continue
        found.append(f"{label}:{node.lineno}  {receiver}.{method}()")
    return found


def _violations(path: Path) -> list[str]:
    return _violations_in_source(
        path.read_text(encoding="utf-8"),
        path.relative_to(_REPO_ROOT).as_posix(),
    )


def test_guard_sees_the_files_it_claims_to_guard() -> None:
    """Каждая запись списка обязана разрешаться хотя бы в один файл.

    Ровно этим классом («молчащий детектор ничего не доказывает») страж и
    обесценивается: путь разъехался — проверка стала НЕ-операцией и осталась
    зелёной.

    Судим ПОИМЁННО, а не суммой. Первая редакция проверяла «файлов не меньше
    сорока» — и осталась ЗЕЛЁНОЙ под инъекцией, разломавшей один из четырёх
    каталогов: остаток списка перекрывал порог. Порог, взятый там, где кандидаты
    не расходятся, не проверяет ничего.
    """
    blind: list[str] = []
    for rel in _GUARDED_DIRS:
        if not list((_REPO_ROOT / rel).rglob("test_*.py")):
            blind.append(rel)
    for pattern in _GUARDED_GLOBS:
        if not list(_REPO_ROOT.glob(pattern)):
            blind.append(pattern)
    assert not blind, (
        f"страж не видит ни одного файла по записям {blind} — путь разъехался, и проверка ниже стала НЕ-операцией"
    )


def test_no_wait_without_deadline_in_observability_tests() -> None:
    """Ни одного `join()`/`wait()` без дедлайна в тестах наблюдаемости."""
    offenders: list[str] = []
    for path in _guarded_files():
        offenders.extend(_violations(path))
    assert not offenders, "ожидание без дедлайна — регрессия повиснет вместо красного:\n  " + "\n  ".join(offenders)


def test_barrier_with_constructor_deadline_is_not_a_violation() -> None:
    """Дедлайн в конструкторе барьера засчитывается — иначе страж врал бы.

    Проверяем обе стороны на синтетике: барьер С таймаутом освобождает голый
    `wait()`, барьер БЕЗ таймаута — нет.
    """
    src_ok = "import threading\nb = threading.Barrier(2, timeout=5)\ndef w():\n    b.wait()\n"
    src_bad = src_ok.replace(", timeout=5", "")
    assert _violations_in_source(src_ok, "<синтетика>") == []
    assert len(_violations_in_source(src_bad, "<синтетика>")) == 1
