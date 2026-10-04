"""Тесты автора ``core/lifetime.py`` (Task 0.2, Step 4): внутренние опасности механизма.

Приёмка по критериям — ``test_lifetime_scope_acceptance.py`` (слепой тестер). Здесь —
то, что видно только из устройства реализации:

- гонки «освобождение ровно один раз»: ``own`` против ``close``, ``Handle.close`` против
  ``close`` области, пара исключения упавшего потока — ровно в одном отчёте;
- ни один вызов ресурса не идёт под локом области (ресурс в фазе 2 зовёт ``own`` из
  другого потока — без дедлока);
- самоотцепление потока — по тождеству записи: старая ручка не трогает новую запись
  с тем же именем; выживший, вышедший после ``close``, отцепляется без исключения;
- потолок копилки исключений потоков: 21 → 20 пар + одна пара-счётчик;
- ``lifetime.py`` импортирует только stdlib из литерального списка.

Каждый вызов, который может зависнуть, идёт в daemon-потоке с ``join(timeout)``.
"""

from __future__ import annotations

import ast
import threading
import time
import uuid
from pathlib import Path

import pytest

from multiprocess_framework.modules.base_manager import open_scope
from multiprocess_framework.modules.base_manager.interfaces import ScopeClosedError

_LIFETIME_PY = Path(__file__).resolve().parent.parent / "core" / "lifetime.py"

# Литеральный список из task-0.2.md, раздел «Ограничения файла».
_ALLOWED_IMPORTS = {
    "__future__",
    "collections",
    "collections.abc",
    "dataclasses",
    "itertools",
    "logging",
    "math",
    "threading",
    "time",
    "typing",
    "weakref",
    "..interfaces",
}


def _path() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


def _bounded(fn, timeout: float = 5.0):
    """Выполнить ``fn`` в daemon-потоке; зависание — провал с текстом, не таймаут прогона."""
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — переносим в поток теста
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), f"вызов завис дольше {timeout} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _wait_thread_gone(name: str, timeout: float = 3.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not any(t.name == name for t in threading.enumerate()):
            return
        time.sleep(0.005)
    raise AssertionError(f"поток {name} не вышел за {timeout} с")


class _Counter:
    def __init__(self) -> None:
        self.n = 0
        self._lock = threading.Lock()

    def __call__(self) -> None:
        with self._lock:
            self.n += 1


# ---------------------------------------------------------------------------
# Гонки: освобождение ровно один раз
# ---------------------------------------------------------------------------


def test_race_own_against_close_releases_exactly_once():
    for _ in range(100):
        root = open_scope(_path(), budget_s=1.0)
        cb = _Counter()
        gate = threading.Barrier(2)
        refused: list[bool] = []

        def closer() -> None:
            gate.wait()
            root.close()

        def owner() -> None:
            gate.wait()
            try:
                root.own(cb, name="x")
            except ScopeClosedError:
                refused.append(True)

        threads = [threading.Thread(target=closer, daemon=True), threading.Thread(target=owner, daemon=True)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5.0)
            assert not t.is_alive()
        assert cb.n == 1, f"освобождений {cb.n}, отказ own={bool(refused)}"
        assert root.live() == []


def test_race_handle_close_against_scope_close_releases_exactly_once():
    for _ in range(100):
        root = open_scope(_path(), budget_s=1.0)
        cb = _Counter()
        handle = root.own(cb, name="x")
        gate = threading.Barrier(2)
        threads = [
            threading.Thread(target=lambda: (gate.wait(), handle.close()), daemon=True),
            threading.Thread(target=lambda: (gate.wait(), root.close()), daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5.0)
            assert not t.is_alive()
        assert cb.n == 1


def test_race_failed_thread_pair_lands_in_exactly_one_report():
    for i in range(100):
        root = open_scope(_path(), budget_s=1.0)

        def boom(_event: threading.Event) -> None:
            raise ValueError("x")

        handle = root.spawn(boom, name="w")
        _wait_thread_gone(f"{root.path}/w")
        reports: list = []
        gate = threading.Barrier(2)
        threads = [
            threading.Thread(target=lambda: (gate.wait(), reports.append(handle.close())), daemon=True),
            threading.Thread(target=lambda: (gate.wait(), reports.append(root.close())), daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5.0)
            assert not t.is_alive()
        pair = (f"{root.path}/w", "ValueError: x")
        hits = sum(report.errors.count(pair) for report in reports)
        assert hits == 1, f"итерация {i}: пара в {hits} отчётах"


# ---------------------------------------------------------------------------
# Ни один вызов ресурса не под локом
# ---------------------------------------------------------------------------


class _OwnsFromAnotherThread:
    """Stoppable: в фазе 2 зовёт ``own`` той же области из другого потока и ждёт его."""

    def __init__(self, scope) -> None:
        self.scope = scope
        self.outcome: list[str] = []
        self.late = _Counter()

    def request_stop(self) -> None:
        pass

    def join_until(self, deadline: float) -> bool:
        def other() -> None:
            try:
                self.scope.own(self.late, name="late")
                self.outcome.append("accepted")
            except ScopeClosedError:
                self.outcome.append("refused")

        thread = threading.Thread(target=other, daemon=True)
        thread.start()
        thread.join(2.0)
        if thread.is_alive():
            self.outcome.append("deadlock")
        return True


def test_resource_calling_own_from_another_thread_in_phase2_does_not_deadlock():
    root = open_scope(_path(), budget_s=1.0)
    res = _OwnsFromAnotherThread(root)
    root.own(res, name="r")
    report = _bounded(root.close)
    assert res.outcome == ["refused"]
    assert res.late.n == 1  # отказанный ресурс освобождён
    assert report.complete is True


# ---------------------------------------------------------------------------
# Самоотцепление потока
# ---------------------------------------------------------------------------


def test_old_handle_does_not_touch_new_entry_with_same_name():
    root = open_scope(_path(), budget_s=1.0)
    old = root.spawn(lambda ev: None, name="w")
    _wait_thread_gone(f"{root.path}/w")
    new = root.spawn(lambda ev: ev.wait(5.0), name="w")
    report_old = _bounded(old.close)
    assert report_old.ok
    assert root.live() == [{"path": f"{root.path}/w", "kind": "thread", "state": "open"}]
    assert any(t.name == f"{root.path}/w" for t in threading.enumerate())
    report_new = _bounded(new.close)
    assert report_new.ok
    assert root.live() == []
    _bounded(root.close)


def test_survivor_thread_exiting_after_close_detaches_without_exception(monkeypatch):
    seen: list = []
    monkeypatch.setattr(threading, "excepthook", lambda args: seen.append(args.exc_type))
    release = threading.Event()
    root = open_scope(_path(), budget_s=0.1)
    root.spawn(lambda ev: release.wait(5.0), name="w")
    report = _bounded(root.close)
    assert f"{root.path}/w" in report.survivors
    assert root.live() == [{"path": f"{root.path}/w", "kind": "thread", "state": "survivor"}]
    release.set()
    _wait_thread_gone(f"{root.path}/w")
    assert root.live() == []
    assert seen == []


# ---------------------------------------------------------------------------
# Потолок копилки исключений потоков
# ---------------------------------------------------------------------------


def test_thread_error_pot_caps_at_20_pairs_plus_counter():
    root = open_scope(_path(), budget_s=1.0)

    def boom(_event: threading.Event) -> None:
        raise ValueError("x")

    for i in range(21):
        root.spawn(boom, name=f"w{i}")
    for i in range(21):
        _wait_thread_gone(f"{root.path}/w{i}")
    report = _bounded(root.close)
    thread_pairs = [p for p in report.errors if p[1] == "ValueError: x"]
    assert len(thread_pairs) == 20
    assert (root.path, "ещё 1 исключений потоков не показано") in report.errors
    assert len(report.errors) == 21


# ---------------------------------------------------------------------------
# Импорты lifetime.py
# ---------------------------------------------------------------------------


def _imported_modules(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add("." * node.level + (node.module or ""))
    return names


def test_lifetime_imports_only_allowed_modules():
    imported = _imported_modules(ast.parse(_LIFETIME_PY.read_text(encoding="utf-8")))
    assert "..interfaces" in imported, "сторож пуст: относительный импорт не найден"
    assert imported - _ALLOWED_IMPORTS == set()


def test_import_guard_is_not_vacuous():
    tree = ast.parse("import threading\nimport os\nfrom ..core import base_manager\n")
    assert _imported_modules(tree) - _ALLOWED_IMPORTS == {"os", "..core"}


@pytest.mark.parametrize("name", ["Scope", "Handle"])
def test_package_does_not_export_classes(name):
    from multiprocess_framework.modules import base_manager

    assert hasattr(base_manager, name) is False
    assert name not in base_manager.__all__
