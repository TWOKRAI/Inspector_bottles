# -*- coding: utf-8 -*-
"""T1 / A3: страж — кто в репозитории трогает автосборку ``gc`` (AST).

Источник — plans/2026-10-03_lifecycle-owner-scope/task-T1.md («Страж», A3).

Сканируются файлы ``git ls-files`` под корнями ``multiprocess_framework/ multiprocess_prototype/
Services/ Plugins/ apps/ backend_ctl/ examples/``. Считаются только вызовы ``gc.<attr>(...)``
(``ast.Call``): строки-скрипты, которые тест гоняет в подпроцессе, не в счёт.

Классы файлов:

* GUI-файл — импортирует ``PySide6`` / ``shiboken6`` или модуль на ``qt_imports`` (в том числе
  относительным ``ImportFrom``, любой ``level``).
* тест-файл — ``/tests/`` в пути, либо ``test_*.py`` / ``conftest.py``.

Правила:

* R1 — не-тестовый GUI-файл не зовёт ``gc.collect/enable/disable/set_threshold/freeze/unfreeze``.
* R2 — тест-файл не зовёт ``gc.enable()``: автосборку включает только механизм (``paused_gc``,
  выход ``suspend_collection_owner``); исключения — allowlist ниже, с причиной.
* R3 — GUI тест-файл не зовёт ``gc.collect()``: сборка — ``gui_memory_policy().collect_now()``.

Ключ нарушения — ``путь::внутренний def`` (вызов вне функции — ``путь::``). Пути — от корня репо.
"""

from __future__ import annotations

import ast
import functools
import subprocess
from dataclasses import dataclass
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
_ROOTS = (
    "multiprocess_framework/",
    "multiprocess_prototype/",
    "Services/",
    "Plugins/",
    "apps/",
    "backend_ctl/",
    "examples/",
)
_R1_ATTRS = frozenset({"collect", "enable", "disable", "set_threshold", "freeze", "unfreeze"})
_QT_TOP_MODULES = frozenset({"PySide6", "shiboken6"})
_QT_IMPORTS = "qt_imports"

_A1 = "multiprocess_framework/modules/process_module/tests/test_gc_collection_owner.py"

#: ``{"путь::функция": причина}``. Запись без причины не считается; запись без живого
#: ``gc.enable()`` под этим ключом — мёртвая, красный (``test_allowlist_has_no_dead_entries``).
_ALLOWLIST: dict[str, str] = {
    "multiprocess_framework/modules/base_manager/tests/test_lifetime_scope.py::worker": (
        "намеренная автосборка на рабочем потоке; Qt-мусор снят границей"
    ),
    f"{_A1}::test_collect_on_disables_and_release_restores_prior": (
        "тест механизма: включает автосборку намеренно, enforce/paused_gc восстанавливают"
    ),
    f"{_A1}::test_enforce_heals_and_counts_once": (
        "тест механизма: включает автосборку намеренно, enforce/paused_gc восстанавливают"
    ),
    f"{_A1}::test_paused_gc_restores_exact_state": (
        "тест механизма: включает автосборку намеренно, enforce/paused_gc восстанавливают"
    ),
}


@dataclass(frozen=True)
class GcCall:
    path: str
    attr: str
    key: str
    lineno: int
    is_gui: bool
    is_test: bool


def _is_test_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return "/tests/" in f"/{path}" or name == "conftest.py" or (name.startswith("test_") and name.endswith(".py"))


def _is_qt_imports(module: str | None) -> bool:
    return bool(module) and module.rsplit(".", 1)[-1] == _QT_IMPORTS


class _Scanner(ast.NodeVisitor):
    def __init__(self) -> None:
        self.gui = False
        self.calls: list[tuple[str, str, int]] = []  # (attr, innermost def, lineno)
        self._defs: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.split(".")[0] in _QT_TOP_MODULES or _is_qt_imports(alias.name):
                self.gui = True

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module and node.module.split(".")[0] in _QT_TOP_MODULES:
            self.gui = True
        if _is_qt_imports(node.module) or any(a.name == _QT_IMPORTS for a in node.names):
            self.gui = True

    def _visit_def(self, node: ast.AST) -> None:
        self._defs.append(node.name)  # type: ignore[attr-defined]
        self.generic_visit(node)
        self._defs.pop()

    visit_FunctionDef = _visit_def
    visit_AsyncFunctionDef = _visit_def

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "gc":
            self.calls.append((func.attr, self._defs[-1] if self._defs else "", node.lineno))
        self.generic_visit(node)


def _scan_file(path: str, source: str) -> tuple[bool, list[GcCall]]:
    """(GUI-файл?, вызовы ``gc.<attr>(...)``); ``SyntaxError`` — наверх."""
    scanner = _Scanner()
    scanner.visit(ast.parse(source, filename=path))
    is_test = _is_test_path(path)
    calls = [
        GcCall(path, attr, f"{path}::{func}", lineno, scanner.gui, is_test) for attr, func, lineno in scanner.calls
    ]
    return scanner.gui, calls


def scan_source(path: str, source: str) -> list[GcCall]:
    return _scan_file(path, source)[1]


def r1_violations(calls: list[GcCall]) -> list[GcCall]:
    return [c for c in calls if c.is_gui and not c.is_test and c.attr in _R1_ATTRS]


def r2_violations(calls: list[GcCall], allowlist: dict[str, str]) -> list[GcCall]:
    allowed = {key for key, reason in allowlist.items() if reason.strip()}
    return [c for c in calls if c.is_test and c.attr == "enable" and c.key not in allowed]


def r3_violations(calls: list[GcCall]) -> list[GcCall]:
    return [c for c in calls if c.is_test and c.is_gui and c.attr == "collect"]


@dataclass(frozen=True)
class Scan:
    calls: list[GcCall]
    files: int
    gui_non_test: frozenset[str]
    test_files: frozenset[str]
    unparsable: list[str]


@functools.cache
def _scan_repo() -> Scan:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", *_ROOTS],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    paths = sorted(p for p in out.split("\0") if p.endswith(".py"))
    calls: list[GcCall] = []
    gui_non_test: set[str] = set()
    test_files: set[str] = set()
    unparsable: list[str] = []
    files = 0
    for path in paths:
        file = _REPO_ROOT / path
        if not file.is_file():  # удалён в рабочем дереве, но ещё в индексе
            continue
        files += 1
        try:
            gui, file_calls = _scan_file(path, file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            unparsable.append(path)
            continue
        if _is_test_path(path):
            test_files.add(path)
        elif gui:
            gui_non_test.add(path)
        calls.extend(file_calls)
    return Scan(calls, files, frozenset(gui_non_test), frozenset(test_files), unparsable)


def _assert_scan_is_not_vacuous(scan: Scan) -> None:
    """Страж, который ничего не просканировал, зелёный вакуумно — это красный."""
    assert scan.files > 1000, f"git ls-files дал {scan.files} .py-файлов под {_ROOTS}"
    assert not scan.unparsable, f"не разобраны AST (нарушения в них не видны): {scan.unparsable}"
    # якоря классификации: GUI-файл фреймворка и тест-файл существуют и распознаны
    assert "multiprocess_framework/modules/frontend_module/core/qt_lifetime.py" in scan.gui_non_test
    assert "multiprocess_framework/modules/base_manager/tests/test_lifetime_scope.py" in scan.test_files


def _describe(violations: list[GcCall]) -> str:
    files = {v.path for v in violations}
    lines = "\n".join(f"  {v.path}:{v.lineno} gc.{v.attr}()  [{v.key}]" for v in violations)
    return f"{len(violations)} вызовов в {len(files)} файлах:\n{lines}"


# ---------------------------------------------------------------------------------------------


def test_gui_code_has_no_gc_calls():
    """R1: не-тестовый GUI-файл не трогает автосборку напрямую."""
    scan = _scan_repo()
    _assert_scan_is_not_vacuous(scan)
    violations = r1_violations(scan.calls)
    assert not violations, "R1: " + _describe(violations)


def test_tests_do_not_reenable_gc():
    """R2: тест-файл не включает автосборку; исключения — allowlist (путь::функция + причина)."""
    scan = _scan_repo()
    _assert_scan_is_not_vacuous(scan)
    violations = r2_violations(scan.calls, _ALLOWLIST)
    assert not violations, "R2: " + _describe(violations)


def test_qt_tests_collect_through_policy():
    """R3: GUI тест-файл собирает через ``gui_memory_policy().collect_now()``, не ``gc.collect()``."""
    scan = _scan_repo()
    _assert_scan_is_not_vacuous(scan)
    violations = r3_violations(scan.calls)
    assert not violations, "R3: " + _describe(violations)


def test_scanner_sees_synthetic_violation():
    """Сканер различает: найденное нарушение — красное, исключения правил — зелёные."""
    test_path = "multiprocess_framework/modules/synthetic/tests/test_synthetic.py"
    code_path = "multiprocess_framework/modules/synthetic/widget.py"

    # R2: gc.enable() в тест-файле — ровно одно нарушение, ключ — путь::
    calls = scan_source(test_path, "import gc\ngc.enable()\n")
    assert len(r2_violations(calls, {})) == 1
    assert calls[0].key == f"{test_path}::"
    # allowlist гасит нарушение только с причиной
    assert r2_violations(calls, {f"{test_path}::": "причина"}) == []
    assert len(r2_violations(calls, {f"{test_path}::": ""})) == 1

    # R1: относительный импорт на qt_imports делает файл GUI
    qt_source = "from ..core.qt_imports import X\nimport gc\ngc.collect()\n"
    assert len(r1_violations(scan_source(code_path, qt_source))) == 1
    # прямой PySide6 и абсолютный qt_imports — тоже GUI
    assert (
        len(r1_violations(scan_source(code_path, "from PySide6.QtCore import QTimer\nimport gc\ngc.freeze()\n"))) == 1
    )
    abs_qt = "from multiprocess_framework.modules.frontend_module.core.qt_imports import X\nimport gc\ngc.disable()\n"
    assert len(r1_violations(scan_source(code_path, abs_qt))) == 1

    # контроли: тот же код не нарушает там, где правило не действует
    assert r1_violations(scan_source(code_path, "import gc\ngc.collect()\n")) == []  # не GUI
    assert r1_violations(scan_source(test_path, qt_source)) == []  # тест-файл R1 не касается
    assert r2_violations(scan_source(code_path, "import gc\ngc.enable()\n"), {}) == []  # не тест-файл
    # R3: GUI тест-файл — gc.collect() нарушение; не-GUI тест-файл — нет
    assert len(r3_violations(scan_source(test_path, qt_source))) == 1
    assert r3_violations(scan_source(test_path, "import gc\ngc.collect()\n")) == []

    # строка-скрипт не вызов; ключ — внутренний def
    assert scan_source(test_path, 's = "import gc\\ngc.enable()"\n') == []
    nested = "import gc\ndef outer():\n    def inner():\n        gc.enable()\n"
    assert [c.key for c in scan_source(test_path, nested)] == [f"{test_path}::inner"]


def test_allowlist_has_no_dead_entries():
    """Каждая запись allowlist — с причиной и с живым ``gc.enable()`` под своим ключом."""
    scan = _scan_repo()
    _assert_scan_is_not_vacuous(scan)
    live = {c.key for c in scan.calls if c.is_test and c.attr == "enable"}
    no_reason = sorted(key for key, reason in _ALLOWLIST.items() if not reason.strip())
    dead = sorted(key for key in _ALLOWLIST if key not in live)
    assert not no_reason, f"записи без причины не считаются: {no_reason}"
    assert not dead, f"мёртвые записи allowlist (под ключом нет gc.enable()): {dead}"
    assert len(_ALLOWLIST) == 4
