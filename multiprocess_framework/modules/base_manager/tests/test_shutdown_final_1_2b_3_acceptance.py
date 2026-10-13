"""Слепые приёмочные тесты Task 1.2b-3: ``shutdown()`` финальный (ADR-BM-009), принуждение Р1 (а).

Источник истины — гарантии брифа G-8a…G-8f и G-9, не код ``BaseManager``.

G-8a…G-8c — отрицательные: подкласс со своим ``shutdown`` не создаётся (``TypeError`` при
выполнении оператора ``class``, точный текст). Отрицательные классы объявлены ВНУТРИ тестов:
на уровне модуля они прервали бы сбор файла до правки.
G-8d…G-8f — стражи (зелёные и до, и после правки): разрешённые формы, кооперативность
``__init_subclass__``, номинальная проверка ``ErrorManager``.
G-9 — статика по шести корням (AST по ``git ls-files``): потомков ``BaseManager`` со своим
``shutdown`` — 0 в производстве и 0 в тестах.

Всё, что может зависнуть (вызов ``shutdown()``), идёт в daemon-потоке со сроком.
"""

from __future__ import annotations

import ast
import functools
import inspect
import subprocess
import threading
import time
from pathlib import Path

import pytest

from multiprocess_framework.modules.base_manager import BaseManager
from multiprocess_framework.modules.channel_routing_module.core.channel_routing_manager import (
    ChannelRoutingManager,
)
from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager
from multiprocess_framework.modules.error_module.interfaces import IErrorManager
from multiprocess_framework.modules.logger_module.core.logger_core import LoggerCore
from multiprocess_framework.modules.process_module import ProcessModule

DEADLINE_S = 15.0

# Корень репозитория: .../multiprocess_framework/modules/base_manager/tests/<файл> -> parents[4]
REPO_ROOT = Path(__file__).resolve().parents[4]
SIX_ROOTS = ["multiprocess_framework", "Services", "Plugins", "multiprocess_prototype", "apps", "backend_ctl"]

# G-9: единственное исключение скана — этот файл (негативные классы G-8a…G-8c). Литерал, других нет.
SCAN_EXCLUDED = ["multiprocess_framework/modules/base_manager/tests/test_shutdown_final_1_2b_3_acceptance.py"]


def call_bounded(fn, timeout_s: float):
    """Вызвать ``fn`` в daemon-потоке; вернуть (завершился, результат, ошибка, длительность)."""
    box: dict = {}

    def run() -> None:
        t0 = time.monotonic()
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - тест сам разбирает ошибку
            box["error"] = exc
        box["elapsed"] = time.monotonic() - t0

    th = threading.Thread(target=run, daemon=True, name="call_bounded")
    th.start()
    th.join(timeout_s)
    return (not th.is_alive()), box.get("result"), box.get("error"), box.get("elapsed")


def _expected_message(test_name: str) -> str:
    """Текст G-8a: ``<модуль>.<qualname>: shutdown() финальный (ADR-BM-009) — определите _on_shutdown()``."""
    return f"{__name__}.{test_name}.<locals>.Bad: shutdown() финальный (ADR-BM-009) — определите _on_shutdown()"


# ---------------------------------------------------------------------------
# G-8a: прямой подкласс BaseManager с def shutdown
# ---------------------------------------------------------------------------


def test_direct_subclass_with_shutdown_raises() -> None:
    """G-8a: ``class Bad(BaseManager)`` с ``def shutdown`` -> ``TypeError`` с точным текстом."""
    with pytest.raises(TypeError) as info:

        class Bad(BaseManager):
            def initialize(self) -> bool:
                return True

            def shutdown(self) -> bool:
                return True

    assert str(info.value) == _expected_message("test_direct_subclass_with_shutdown_raises")


# ---------------------------------------------------------------------------
# G-8b: непрямой подкласс
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("base", [ProcessModule, ChannelRoutingManager, LoggerCore], ids=lambda c: c.__name__)
def test_indirect_subclass_with_shutdown_raises(base: type) -> None:
    """G-8b: подкласс ``ProcessModule``/``ChannelRoutingManager``/``LoggerCore`` со своим ``shutdown`` -> TypeError."""
    with pytest.raises(TypeError) as info:

        class Bad(base):  # type: ignore[valid-type, misc]
            def shutdown(self) -> bool:
                return True

    assert str(info.value) == _expected_message("test_indirect_subclass_with_shutdown_raises")


# ---------------------------------------------------------------------------
# G-8c: shutdown = lambda в теле класса
# ---------------------------------------------------------------------------


def test_shutdown_assignment_in_body_raises() -> None:
    """G-8c: ``shutdown = lambda self: True`` в теле класса -> ``TypeError``."""
    with pytest.raises(TypeError):

        class Bad(BaseManager):
            def initialize(self) -> bool:
                return True

            shutdown = lambda self: True  # noqa: E731 - предмет теста

        assert Bad is not None  # pragma: no cover - класс не должен быть создан


# ---------------------------------------------------------------------------
# G-8d: разрешённые формы (страж, зелёный и до правки)
# ---------------------------------------------------------------------------


def test_on_shutdown_only_subclass_ok() -> None:
    """G-8d: подкласс только с ``_on_shutdown`` создаётся; ``shutdown()`` -> ``True``, тело выполнено 1 раз."""
    body_calls: list[int] = []

    class Good(BaseManager):
        def initialize(self) -> bool:
            return True

        def _on_shutdown(self) -> bool:
            body_calls.append(1)
            return True

    obj = Good("t02good")
    done, result, error, _ = call_bounded(obj.shutdown, DEADLINE_S)
    assert done, "shutdown() завис"
    assert error is None, repr(error)
    assert result is True
    assert body_calls == [1]


def test_instance_attribute_spy_allowed() -> None:
    """G-8d: ``obj.shutdown = spy`` на экземпляре не даёт ``TypeError``; вызов идёт в шпиона."""
    spy_calls: list[int] = []

    class Good(BaseManager):
        def initialize(self) -> bool:
            return True

        def _on_shutdown(self) -> bool:
            return True

    obj = Good("t02spy")

    def spy() -> bool:
        spy_calls.append(1)
        return True

    obj.shutdown = spy  # type: ignore[method-assign]
    assert obj.shutdown() is True
    assert spy_calls == [1]


# ---------------------------------------------------------------------------
# G-8e: кооперативность __init_subclass__ (страж)
# ---------------------------------------------------------------------------


def test_subclass_kwargs_reach_mixin() -> None:
    """G-8e: ``class M(BaseManager, TagMixin, tag="x")`` -> хук миксина получил ``tag``, ровно 1 раз на класс."""
    hook_calls: list[type] = []

    class TagMixin:
        def __init_subclass__(cls, tag=None, **kw):  # noqa: ANN001, ANN003
            super().__init_subclass__(**kw)
            cls.tag = tag
            hook_calls.append(cls)

    class M(BaseManager, TagMixin, tag="x"):
        def initialize(self) -> bool:
            return True

    assert M.tag == "x"
    assert hook_calls == [M]


# ---------------------------------------------------------------------------
# G-8f: номинальная проверка ErrorManager цела (страж)
# ---------------------------------------------------------------------------


def test_error_manager_nominal_isinstance() -> None:
    """G-8f: ``isinstance`` к ``ErrorManager`` номинальный: чужие объекты -> ``False``, наследники -> ``True``."""
    assert isinstance(object(), ErrorManager) is False

    class Plain:
        """Не наследник, но со всеми методами ``IErrorManager``."""

        def initialize(self) -> bool:
            return True

        def shutdown(self) -> bool:
            return True

        def error(self, message, module="errors", *args, **extra) -> None:  # noqa: ANN001, ANN002, ANN003
            return None

        def warning(self, message, module="errors", *args, **extra) -> None:  # noqa: ANN001, ANN002, ANN003
            return None

        def critical(self, message, module="errors", *args, **extra) -> None:  # noqa: ANN001, ANN002, ANN003
            return None

        def info(self, message, module="errors", *args, **extra) -> None:  # noqa: ANN001, ANN002, ANN003
            return None

        def log_exception(self, exc, message="", module="errors", include_stacktrace=None) -> None:  # noqa: ANN001
            return None

        def get_stats(self) -> dict:
            return {}

    assert isinstance(Plain(), ErrorManager) is False

    class Sub(ErrorManager):
        def _on_shutdown(self) -> bool:
            return True

    obj = Sub.__new__(Sub)
    assert isinstance(obj, ErrorManager) is True
    assert isinstance(obj, IErrorManager) is True


def test_error_manager_duck_is_not_instance() -> None:
    """G-8f: утка со всеми атрибутами ``ErrorManager`` (``getattr_static``) всё равно не ``ErrorManager``."""
    skip = {"__class__", "__dict__", "__weakref__", "__init_subclass__", "__subclasshook__", "__init__", "__new__"}
    namespace = {n: inspect.getattr_static(ErrorManager, n) for n in dir(ErrorManager) if n not in skip}
    Duck = type("Duck", (), namespace)  # noqa: N806 - имя класса
    assert isinstance(Duck(), ErrorManager) is False


# ---------------------------------------------------------------------------
# G-9: статика по шести корням
# ---------------------------------------------------------------------------


def _is_test_path(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return "tests" in parts[:-1] or name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def _base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return None


def _has_own_shutdown(node: ast.ClassDef) -> bool:
    """``def shutdown`` или присваивание ``shutdown = …`` в теле класса."""
    for stmt in node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == "shutdown":
            return True
        if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "shutdown" for t in stmt.targets):
            return True
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == "shutdown":
            return True
    return False


@functools.cache
def _scan() -> tuple[dict[str, list[str]], int]:
    """({'prod'|'tests': ['путь:Класс', ...] — потомки ``BaseManager`` со своим ``shutdown``}, число всех потомков)."""
    out = subprocess.run(
        ["git", "ls-files", *SIX_ROOTS],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    files = [line for line in out.splitlines() if line.endswith(".py") and line not in SCAN_EXCLUDED]
    classes: list[tuple[str, str, list[str], bool]] = []  # (путь, имя, базы, есть ли свой shutdown)
    for rel in files:
        try:
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = [b for b in (_base_name(x) for x in node.bases) if b]
                classes.append((rel, node.name, bases, _has_own_shutdown(node)))
    # транзитивное наследование от BaseManager по простым именам (по всем файлам, тесты тоже в цепочке)
    descendants = {"BaseManager"}
    changed = True
    while changed:
        changed = False
        for _rel, name, bases, _own in classes:
            if name not in descendants and any(b in descendants for b in bases):
                descendants.add(name)
                changed = True
    result: dict[str, list[str]] = {"prod": [], "tests": []}
    for rel, name, _bases, own in classes:
        if name == "BaseManager" or name not in descendants or not own:
            continue
        result["tests" if _is_test_path(rel) else "prod"].append(f"{rel}:{name}")
    return result, len(descendants) - 1


def test_static_scan_sees_the_hierarchy() -> None:
    """Страж скана: скан видит иерархию (иначе нули G-9 — пустой зелёный). Порог 40 — ниже инвентаря (47)."""
    _, descendants = _scan()
    assert descendants >= 40, f"скан нашёл всего {descendants} потомков BaseManager"


@pytest.mark.parametrize(("kind", "expected"), [("prod", 0), ("tests", 0)])
def test_static_no_own_shutdown_anywhere(kind: str, expected: int) -> None:
    """G-9: потомков ``BaseManager`` со своим ``shutdown`` — 0 в производстве и 0 в тестах (шесть корней)."""
    found, _ = _scan()
    offenders = found[kind]
    assert len(offenders) == expected, f"{kind}: {len(offenders)} вместо {expected}: {sorted(offenders)}"
