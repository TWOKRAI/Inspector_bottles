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
* R4 (T1-iso, plans/2026-10-03_lifecycle-owner-scope/task-T1-gc-isolation.md, DESIGN 4) — файл под
  ``tests/`` (включая ``conftest.py`` и хелперы) не трогает ``gc.freeze``/``gc.unfreeze`` и
  ``suspend_collection_owner``: это глобальное состояние процесса pytest. Исключение — файлы из
  литерала ``collect_ignore`` соседнего ``conftest.py``: их гоняет свой интерпретатор. Без allowlist.

Ключ нарушения R1–R3 — ``путь::внутренний def`` (вызов вне функции — ``путь::``); R4 — ``путь:строка``.
Пути — от корня репо.
"""

from __future__ import annotations

import ast
import functools
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

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


# --------------------------------------------------------------------------------------- R4

_R4_GC_ATTRS = frozenset({"freeze", "unfreeze"})
_R4_SUSPEND = "suspend_collection_owner"
_COLLECT_IGNORE = "collect_ignore"


class CollectIgnoreNotLiteral(ValueError):
    """``collect_ignore`` присвоен не литералом списка (кортежа) строк; ``lineno`` — строка присвоения."""

    def __init__(self, lineno: int, what: str) -> None:
        super().__init__(f"строка {lineno}: collect_ignore — не литерал списка строк ({what})")
        self.lineno = lineno


def isolated_names(conftest_source: str) -> frozenset[str]:
    """Имена из литерала ``collect_ignore`` конфтеста.

    Нет присвоения — ``frozenset()`` (каталог без изоляции). Список или кортеж строк — допустимы.
    Иное (имя, вызов, генератор, нестроковый элемент, ``+=``) — ``CollectIgnoreNotLiteral`` (``ValueError``).
    Присвоений несколько — действует последнее (как при исполнении модуля), каждое обязано быть литералом.
    """
    names: frozenset[str] = frozenset()
    for node in ast.walk(ast.parse(conftest_source)):
        if isinstance(node, ast.AugAssign) and _is_name(node.target, _COLLECT_IGNORE):
            raise CollectIgnoreNotLiteral(node.lineno, "изменение через +=")
        if isinstance(node, ast.Assign) and any(_is_name(t, _COLLECT_IGNORE) for t in node.targets):
            value = node.value
        elif isinstance(node, ast.AnnAssign) and _is_name(node.target, _COLLECT_IGNORE) and node.value is not None:
            value = node.value
        else:
            continue
        if not isinstance(value, ast.List | ast.Tuple):
            raise CollectIgnoreNotLiteral(node.lineno, type(value).__name__)
        if not all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in value.elts):
            raise CollectIgnoreNotLiteral(node.lineno, "нестроковый элемент")
        names = frozenset(e.value for e in value.elts)  # type: ignore[attr-defined]
    return names


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _r4_lines(tree: ast.AST) -> set[int]:
    """Строки, где файл трогает заморозку gc или слот владельца сборки (только код, не строки/комментарии)."""
    gc_modules = {"gc"}  # имена модуля gc: ``import gc`` и ``import gc as g``
    frozen_funcs: set[str] = set()  # ``from gc import freeze/unfreeze [as x]``
    suspend_names = {_R4_SUSPEND}  # ``from ... import suspend_collection_owner [as x]``
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            gc_modules.update(a.asname or a.name for a in node.names if a.name == "gc")
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if node.module == "gc" and node.level == 0 and a.name in _R4_GC_ATTRS:
                    frozen_funcs.add(a.asname or a.name)
                elif a.name == _R4_SUSPEND:
                    suspend_names.add(a.asname or a.name)

    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            # gc.unfreeze() и f = gc.unfreeze; _door().suspend_collection_owner()
            if node.attr in _R4_GC_ATTRS and isinstance(node.value, ast.Name) and node.value.id in gc_modules:
                lines.add(node.lineno)
            elif node.attr == _R4_SUSPEND:
                lines.add(node.lineno)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            # имя из ``from gc import`` — на строке использования, не импорта; suspend как Name
            if node.id in frozen_funcs or node.id in suspend_names:
                lines.add(node.lineno)
        elif isinstance(node, ast.Call) and _is_name(node.func, "getattr") and len(node.args) >= 2:
            obj, attr = node.args[0], node.args[1]
            if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
                if attr.value in _R4_GC_ATTRS and isinstance(obj, ast.Name) and obj.id in gc_modules:
                    lines.add(node.lineno)
                elif attr.value == _R4_SUSPEND:
                    lines.add(node.lineno)
    return lines


def r4_violations(path: str, source: str, isolated: frozenset[str]) -> list[str]:
    """``"<path>:<line>"`` по возрастанию строки, одна запись на строку; ``SyntaxError`` — наверх.

    ``path`` — от корня репо (POSIX); ``isolated`` — имена из ``collect_ignore`` соседнего ``conftest.py``.
    Файл из ``isolated`` чист; ``conftest.py`` не изолируется никогда (он грузится в общий прогон).
    """
    name = path.rsplit("/", 1)[-1]
    if name != "conftest.py" and name in isolated:
        return []
    return [f"{path}:{line}" for line in sorted(_r4_lines(ast.parse(source, filename=path)))]


@dataclass(frozen=True)
class R4Scan:
    violations: list[str]
    scanned: frozenset[str]  # просканированные пути от корня репо
    isolated: dict[str, frozenset[str]]  # каталог -> имена из collect_ignore его conftest.py
    unparsable: list[str]

    @property
    def files(self) -> int:
        return len(self.scanned)


@functools.cache
def _r4_scan_repo() -> R4Scan:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", *_ROOTS],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    # тест-файлы те же, что у R1–R3: в том числе сессионный modules/conftest.py вне tests/
    paths = sorted(p for p in out.split("\0") if p.endswith(".py") and _is_test_path(p))
    isolated_by_dir: dict[str, frozenset[str]] = {}
    violations: list[str] = []
    unparsable: list[str] = []
    scanned: set[str] = set()

    def isolated_for(directory: str) -> frozenset[str]:
        if directory not in isolated_by_dir:
            conftest = _REPO_ROOT / directory / "conftest.py"
            names: frozenset[str] = frozenset()
            if conftest.is_file():
                try:
                    names = isolated_names(conftest.read_text(encoding="utf-8"))
                except CollectIgnoreNotLiteral as exc:
                    violations.append(f"{directory}/conftest.py:{exc.lineno}")
                except SyntaxError:
                    pass  # сам конфтест попадёт в unparsable при своём разборе ниже
            isolated_by_dir[directory] = names
        return isolated_by_dir[directory]

    for path in paths:
        file = _REPO_ROOT / path
        if not file.is_file():  # удалён в рабочем дереве, но ещё в индексе
            continue
        scanned.add(path)
        directory = path.rsplit("/", 1)[0]
        try:
            violations.extend(r4_violations(path, file.read_text(encoding="utf-8"), isolated_for(directory)))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            unparsable.append(path)
    return R4Scan(violations, frozenset(scanned), isolated_by_dir, unparsable)


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


_PM_TESTS = "multiprocess_framework/modules/process_module/tests"


def test_tests_do_not_touch_freeze_outside_own_interpreter():
    """R4: файл под ``tests/`` не трогает заморозку gc и слот владельца, если он не в ``collect_ignore``."""
    _assert_scan_is_not_vacuous(_scan_repo())
    scan = _r4_scan_repo()
    assert scan.files > 500, f"R4 просканировал {scan.files} тест-файлов (ожидалось больше 500)"
    assert not scan.unparsable, f"R4: не разобраны AST: {scan.unparsable}"
    # якорь: изоляция двух файлов механизма прочитана из conftest.py пакета
    # сначала список нарушений: выпавшее из collect_ignore имя видно как путь:строка, не как diff множеств
    assert not scan.violations, f"R4: {len(scan.violations)} нарушений:\n  " + "\n  ".join(scan.violations)
    assert scan.isolated[_PM_TESTS] == frozenset({"test_gc_collection_owner.py", "test_gc_discipline.py"})
    # сессионный conftest вне tests/ тоже в скане (он грузится в каждый процесс сессии)
    assert "multiprocess_framework/modules/conftest.py" in scan.scanned


def test_r4_isolated_files_really_touch_freeze():
    """Якорь против вакуума: без изоляции файлы механизма — нарушения R4 (выпадение имени = красный)."""
    for name, at_least in (("test_gc_collection_owner.py", 8), ("test_gc_discipline.py", 4)):
        path = f"{_PM_TESTS}/{name}"
        source = (_REPO_ROOT / path).read_text(encoding="utf-8")
        assert r4_violations(path, source, frozenset({name})) == []
        assert len(r4_violations(path, source, frozenset())) >= at_least, path


def test_r4_ambiguity_decisions():
    """Решения лида по неоднозначностям спека (DESIGN 4, абзац «Решения по неоднозначностям»)."""
    # нет collect_ignore — каталог без изоляции; пустой список — то же
    assert isolated_names("import sys\n") == frozenset()
    assert isolated_names("collect_ignore = []\n") == frozenset()
    # кортеж строк допустим, аннотированное присвоение — тоже
    assert isolated_names('collect_ignore = ("a.py", "b.py")\n') == frozenset({"a.py", "b.py"})
    assert isolated_names('collect_ignore: list[str] = ["a.py"]\n') == frozenset({"a.py"})
    # += не литерал; строка присвоения — в исключении
    with pytest.raises(ValueError):
        isolated_names('collect_ignore = ["a.py"]\ncollect_ignore += ["b.py"]\n')
    with pytest.raises(CollectIgnoreNotLiteral) as info:
        isolated_names('import os\n\ncollect_ignore = sorted(["a.py"])\n')
    assert info.value.lineno == 3

    p = "multiprocess_framework/modules/synthetic/tests/test_s.py"
    # from gc import — одно нарушение на строке ВЫЗОВА; импорт без вызова — не нарушение
    assert r4_violations(p, "from gc import freeze\n\nfreeze()\n", frozenset()) == [f"{p}:3"]
    assert r4_violations(p, "from gc import unfreeze as thaw\n\nx = 1\nthaw()\n", frozenset()) == [f"{p}:4"]
    assert r4_violations(p, "from gc import freeze, unfreeze\n", frozenset()) == []
    # порядок — по возрастанию строки, одна запись на строку
    src = "import gc\n\ndef f():\n    gc.unfreeze()\ngc.freeze(); gc.unfreeze()\n"
    assert r4_violations(p, src, frozenset()) == [f"{p}:4", f"{p}:5"]


def test_r4_scanner_forms_beyond_contract():
    """Формы сверх контракта: псевдоним suspend, getattr на слот, свой def с именем не из gc."""
    p = "multiprocess_framework/modules/synthetic/tests/helpers.py"
    alias = "from x.gc_discipline import suspend_collection_owner as s\n\nwith s():\n    pass\n"
    assert r4_violations(p, alias, frozenset()) == [f"{p}:3"]
    assert r4_violations(p, 'getattr(door, "suspend_collection_owner")()\n', frozenset()) == [f"{p}:1"]
    # свой freeze — не gc.freeze; gc.collect — не R4; другой объект с .freeze — не gc
    assert r4_violations(p, "def freeze():\n    pass\n\nfreeze()\nobj.freeze()\n", frozenset()) == []
    # имя из isolated гасит только сам файл, не соседний conftest.py
    conf = "multiprocess_framework/modules/synthetic/tests/conftest.py"
    assert r4_violations(conf, "import gc\ngc.freeze()\n", frozenset({"conftest.py"})) == [f"{conf}:2"]


def test_r4_covers_session_conftest_outside_tests_dir():
    """Сессионный conftest.py вне ``tests/`` — тест-файл для R4 (грузится в каждый процесс сессии)."""
    session_conftest = "multiprocess_framework/modules/conftest.py"
    assert _is_test_path(session_conftest)  # отбор файлов скана R4 — тот же, что у R1–R3
    source = "import gc\n\n\ndef _injected():\n    gc.unfreeze()\n"
    assert r4_violations(session_conftest, source, frozenset()) == [f"{session_conftest}:5"]
