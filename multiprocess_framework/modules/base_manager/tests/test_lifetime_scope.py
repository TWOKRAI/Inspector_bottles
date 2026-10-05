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
import gc
import threading
import time
import uuid
from pathlib import Path

import pytest

from multiprocess_framework.modules.base_manager import open_scope, unclosed_roots
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
        reports: list = []
        threads = [
            threading.Thread(target=lambda: (gate.wait(), reports.append(handle.close())), daemon=True),
            threading.Thread(target=lambda: (gate.wait(), reports.append(root.close())), daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5.0)
            assert not t.is_alive()
        assert cb.n == 1
        # Второй освобождающий без захвата записи не зовёт ресурс повторно (res уже None),
        # но оставил бы ошибку «NoneType is not callable» — её быть не должно.
        assert [report.errors for report in reports] == [(), ()]


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


# ---------------------------------------------------------------------------
# Итерация 2 (матрица инъекций ведущего): реентрантная ручка, ссылки, захват записи
# ---------------------------------------------------------------------------


class _ClosesOwnHandle:
    """Вызываемое: при освобождении зовёт ``close()`` своей же ручки и запоминает ответ."""

    def __init__(self) -> None:
        self.handle = None
        self.inner: list = []
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1
        start = time.monotonic()
        report = self.handle.close()
        self.inner.append((report, time.monotonic() - start))


def test_reentrant_handle_close_from_its_own_release_returns_incomplete_at_once():
    """Дефект 1: Handle.close держал лок ручки на вызовах ресурса — вечный дедлок."""
    root = open_scope(_path(), budget_s=1.0)
    res = _ClosesOwnHandle()
    res.handle = root.own(res, name="x")
    outer = _bounded(res.handle.close, timeout=3.0)
    assert res.calls == 1
    ((inner, inner_s),) = res.inner
    assert inner.complete is False
    assert inner_s <= 0.1
    assert outer.complete is True
    assert outer.errors == ()
    _bounded(root.close)


def test_handle_close_from_phase2_of_scope_close_returns_incomplete_at_once():
    """Дефект 2: поток закрывающего ждал сам себя до срока (0.31 с при бюджете 0.3)."""
    root = open_scope(_path(), budget_s=1.0)
    res = _ClosesOwnHandle()
    res.handle = root.own(res, name="x")
    report = _bounded(root.close, timeout=3.0)
    assert res.calls == 1
    ((inner, inner_s),) = res.inner
    assert inner.complete is False
    assert inner_s <= 0.1
    assert report.elapsed_s <= 0.1
    assert report.complete is True


class _Res:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


def test_released_entry_does_not_hold_resource_while_handle_lives():
    """J12b: после close области живая ручка не держит ресурс (refcount, без gc)."""
    import gc
    import weakref

    root = open_scope(_path(), budget_s=1.0)
    res = _Res()
    handle = root.own(res, name="x")
    ref = weakref.ref(res)
    gc.disable()
    try:
        _bounded(root.close)
        assert res.calls == 1
        del res
        assert ref() is None, "освобождённая запись держит ресурс"
        assert handle.path.endswith("/x")  # ручка жива до конца проверки
    finally:
        gc.enable()


def test_scope_close_does_not_touch_entry_taken_by_handle_close():
    """J13+J31: вызываемое блокируется внутри handle.close(); close области не зовёт его второй раз."""
    root = open_scope(_path(), budget_s=1.0)
    gate = threading.Event()
    entered = threading.Event()
    calls = _Counter()

    def release() -> None:
        calls()
        entered.set()
        gate.wait(5.0)

    handle = root.own(release, name="x")
    reports: list = []
    a = threading.Thread(target=lambda: reports.append(handle.close()), daemon=True)
    a.start()
    assert entered.wait(3.0)
    b = threading.Thread(target=lambda: reports.append(root.close()), daemon=True)
    b.start()
    time.sleep(0.1)  # B успевает войти в close области, пока A держит вызываемое
    gate.set()
    for t in (a, b):
        t.join(5.0)
        assert not t.is_alive()
    assert calls.n == 1
    assert [report.errors for report in reports] == [(), ()]


# ============================================================ ревью Task 0.2, итерация 1


def test_unclosed_roots_survives_gc_finalizer_under_lock():
    """F1: сборщик мусора срабатывает внутри ``unclosed_roots()`` и зовёт финализатор
    брошенного корня в том же потоке. Финализатор берёт лок сторожа — повторный вход
    не должен зависнуть. 800 живых корней — столько аллокаций, чтобы gen0 сработал
    внутри списка (порог по умолчанию — 700).
    """
    keep = [open_scope(f"{_path()}/live{i}", budget_s=0.1) for i in range(800)]
    abandoned = _path()
    box: dict = {}

    def worker() -> None:
        root = open_scope(abandoned, budget_s=0.1)
        root.own(lambda: None, name="x")  # цикл Scope <-> запись: соберёт только gc
        del root
        box["n"] = len(unclosed_roots())

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(3.0)
    assert not thread.is_alive(), "unclosed_roots() завис под финализатором корня"
    gc.collect()
    assert {"path": abandoned, "state": "abandoned"} in unclosed_roots()
    _bounded(lambda: [root.close() for root in keep], timeout=10.0)


class _Dev:
    """Ресурс со стопом: ``request_stop`` / ``join_until``."""

    def __init__(self) -> None:
        self.stopped = threading.Event()

    def request_stop(self) -> None:
        self.stopped.set()

    def join_until(self, deadline: float) -> bool:
        return self.stopped.wait(max(0.0, deadline - time.monotonic()))


def _close_with_handle_closing_worker(budget_s):
    root = open_scope(_path(), budget_s=1.0)
    dev = _Dev()
    h_dev = root.own(dev, name="dev")
    inner: dict = {}

    def loop(ev: threading.Event) -> None:
        try:
            ev.wait()
        finally:
            t0 = time.monotonic()
            report = h_dev.close()
            inner["dt"] = time.monotonic() - t0
            inner["complete"] = report.complete

    root.spawn(loop, name="w")
    if budget_s is None:
        report = _bounded(root.close, timeout=3.0)
    else:
        report = _bounded(lambda: root.close(budget_s=budget_s), timeout=3.0)
    return report, inner


def test_handle_close_from_subtree_thread_does_not_wait_for_scope_close():
    """F2: spawn-поток в ``finally`` закрывает ручку ресурса, запись которого уже взял
    идущий ``close`` области. Поток не ждёт close, close не ждёт поток: ответ ручки —
    ``complete=False`` сразу, выживших нет. Срок области по умолчанию и короткий срок.
    """
    report, inner = _close_with_handle_closing_worker(None)
    assert report.survivors == ()
    assert report.elapsed_s <= 0.1
    assert inner["complete"] is False
    assert inner["dt"] <= 0.1

    report, inner = _close_with_handle_closing_worker(0.5)
    assert report.survivors == ()
    assert inner["complete"] is False
    assert inner["dt"] <= 0.1


def test_resource_finalizer_does_not_run_under_scope_lock():
    """F3: последняя ссылка на ресурс рвётся при освобождении записи. Финализатор
    ресурса не идёт под локом области: чужой поток в это время читает ``live()``.
    """
    root = open_scope(_path(), budget_s=1.0)
    seen: dict = {}

    class _Res:
        def __call__(self) -> None:
            pass

        def __del__(self) -> None:
            reader = threading.Thread(target=root.live, daemon=True)
            reader.start()
            reader.join(0.5)
            seen["reader_blocked"] = reader.is_alive()

    root.own(_Res(), name="r")  # вызывающий ссылку не держит: владелец — область
    _bounded(root.close, timeout=3.0)
    assert seen == {"reader_blocked": False}
