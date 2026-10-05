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
import sys
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
    не должен зависнуть.

    gc выключен от создания корня до вызова: цикл корня гарантированно в gen0, и
    порог 1 собирает его на первой аллокации внутри списка — под локом сторожа.
    Без этого цикл уходит в gen1 при сборке во время ``open_scope``/``own``, и тест
    вакуумен в полном прогоне (инъекция лида J1).
    """
    keep = [open_scope(f"{_path()}/live{i}", budget_s=0.1) for i in range(800)]
    abandoned = _path()
    box: dict = {}

    def worker() -> None:
        old = gc.get_threshold()
        gc.collect()
        gc.disable()
        try:
            root = open_scope(abandoned, budget_s=0.1)
            root.own(lambda: None, name="x")  # цикл Scope <-> запись: соберёт только gc
            del root
            gc.set_threshold(1)
            gc.enable()
            box["n"] = len(unclosed_roots())
        finally:
            gc.set_threshold(*old)
            gc.enable()

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


def _close_with_handle_closing_worker(path, budget_s):
    calls: list = []
    root = open_scope(path, budget_s=1.0, reporter=lambda r: calls.append((r.path, r.ok)))
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
    inner["calls"] = list(calls)  # снимок до позднего close ручки: тот зовёт reporter сам
    inner["after_close_complete"] = _bounded(h_dev.close, timeout=3.0).complete
    return report, inner


def test_handle_close_from_subtree_thread_does_not_wait_for_scope_close():
    """F2: spawn-поток в ``finally`` закрывает ручку ресурса, запись которого уже взял
    идущий ``close`` области. Поток не ждёт close, close не ждёт поток: ответ ручки —
    ``complete=False`` сразу, выживших нет. Срок области по умолчанию и короткий срок.

    Неполный ответ ручки — как реентрантный ``close`` области: без reporter'а и без
    кэша. Reporter зовётся один раз — отчётом корня; ``close`` ручки после закрытия
    области отвечает ``complete=True`` (ревью 0.2 р2).
    """
    report, inner = _close_with_handle_closing_worker("t02r2/handle-default", None)
    assert report.survivors == ()
    assert report.elapsed_s <= 0.1
    assert inner["complete"] is False
    assert inner["dt"] <= 0.1
    assert inner["calls"] == [("t02r2/handle-default", True)]
    assert inner["after_close_complete"] is True

    report, inner = _close_with_handle_closing_worker("t02r2/handle-budget", 0.5)
    assert report.survivors == ()
    assert inner["complete"] is False
    assert inner["dt"] <= 0.1
    assert inner["calls"] == [("t02r2/handle-budget", True)]
    assert inner["after_close_complete"] is True


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


def test_subtree_thread_waits_for_entry_taken_by_foreign_handle_close():
    """F2, граница правила: запись взял не close области, а ``IHandle.close`` чужого
    потока A (вне поддерева). Поток поддерева во время ``close`` области ждёт A и
    получает полный отчёт, а не ``complete=False`` сразу.

    Белый ящик: ``_close_entry_early`` зовётся напрямую — через ту же ручку поток
    ждёт на уровне ``Handle`` и до проверки ``releaser == _closer`` не доходит.
    """
    root = open_scope(_path(), budget_s=3.0)
    entered = threading.Event()
    gate = threading.Event()

    def slow() -> None:
        entered.set()
        gate.wait(5.0)

    handle = root.own(slow, name="slow")
    entry = handle._entry
    inner: dict = {}

    def loop(ev: threading.Event) -> None:
        try:
            ev.wait()
        finally:
            t0 = time.monotonic()
            report = root._close_entry_early(entry, 3.0)
            inner["dt"] = time.monotonic() - t0
            inner["complete"] = report.complete

    root.spawn(loop, name="w")
    a_reports: list = []
    a = threading.Thread(target=lambda: a_reports.append(handle.close()), daemon=True)
    a.start()
    assert entered.wait(3.0)
    root_reports: list = []
    c = threading.Thread(target=lambda: root_reports.append(root.close()), daemon=True)
    c.start()
    time.sleep(0.3)  # close области идёт, поток w уже ждёт запись, взятую A
    gate.set()
    for t in (a, c):
        t.join(5.0)
        assert not t.is_alive()
    assert inner["complete"] is True
    assert inner["dt"] >= 0.2
    assert [r.complete for r in a_reports] == [True]
    assert [r.survivors for r in root_reports] == [()]


# ---- Task 0.3: канал note_emits_after_close ---------------------------------


def test_note_storm_into_child_during_root_close_sums_to_8000() -> None:
    """8 потоков × 1000 ``note`` в ребёнка при ``root.close()``: отчёт корня + отчёты третьего вида = 8000."""
    got: list = []
    root = open_scope(_path(), budget_s=2.0, reporter=got.append)
    c = root.child("c")
    start = threading.Barrier(9)
    errors: list = []

    def noter() -> None:
        try:
            start.wait(5.0)
            for _ in range(1000):
                c.note_emits_after_close(1)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=noter, daemon=True) for _ in range(8)]
    for th in threads:
        th.start()
    start.wait(5.0)
    report = _bounded(root.close)
    for th in threads:
        th.join(10.0)
        assert not th.is_alive()
    assert errors == []
    third = [r for r in got if r is not report]
    assert all(r.elapsed_s == 0.0 and r.survivors == () and r.emits_after_close >= 1 for r in third)
    assert report.emits_after_close + sum(r.emits_after_close for r in third) == 8000


def test_child_close_races_root_close_root_always_counts_3() -> None:
    """Гонка ``c.close()`` / ``root.close()`` × 100: возврат ``root.close()`` всегда 3, отчёт ``c`` — 0.

    ``root.close()`` стартует, когда ``c`` уже закрывается: корень ждёт ``c._done`` —
    передача счётчика обязана успеть до ``_done.set()``.
    """
    bad: list = []
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # больше переключений GIL; чистую перестановку «после _done.set()» ловит редко
    try:
        _race_child_root(bad)
    finally:
        sys.setswitchinterval(old_interval)
    assert bad == []


def _race_child_root(bad: list) -> None:
    for i in range(100):
        got: list = []
        root = open_scope(_path(), budget_s=2.0, reporter=got.append)
        c = root.child("c")
        c.own(lambda: time.sleep(0.002), name="slow")
        c.note_emits_after_close(3)
        barrier = threading.Barrier(2)
        out: dict = {}

        def close_child(c=c, barrier=barrier, out=out) -> None:
            barrier.wait(5.0)
            out["c"] = c.close()

        def close_root(root=root, c=c, barrier=barrier, out=out) -> None:
            barrier.wait(5.0)
            end = time.monotonic() + 5.0
            while not c.closed and time.monotonic() < end:  # c.close() идёт первым — перекрытие
                time.sleep(0)
            out["root"] = root.close()

        threads = [threading.Thread(target=close_child, daemon=True), threading.Thread(target=close_root, daemon=True)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(5.0)
            assert not th.is_alive(), f"итерация {i}: завис"
        child_reports = [r.emits_after_close for r in got if r.path.endswith("/c")]
        if out["root"].emits_after_close != 3 or any(child_reports):
            bad.append((i, out["root"].emits_after_close, child_reports))


def test_note_into_open_scope_lands_in_next_close() -> None:
    got: list = []
    root = open_scope(_path(), budget_s=1.0, reporter=got.append)
    root.note_emits_after_close(2)
    root.note_emits_after_close(5)
    assert root.close().emits_after_close == 7
    assert [r.emits_after_close for r in got] == [7]


def test_note_after_whole_chain_closed_reporter_raising_does_not_escape() -> None:
    def boom(report) -> None:
        raise RuntimeError("reporter")

    root = open_scope(_path(), budget_s=1.0, reporter=boom)
    c = root.child("c")
    root.close()
    c.note_emits_after_close(1)  # третий вид: исключение reporter'а ловится


def test_third_kind_report_on_hand_off_does_not_delay_waiters_of_child_close() -> None:
    """Ревью 0.3 р1 п.3: reporter третьего вида из передачи родителю — после ``_done.set()``.

    Корень закрыт изнутри ``c.close()``: к передаче цепочка закрыта, счётчик 7 уходит
    reporter'у третьим видом. Reporter спит 1 с; T3 ждёт ``c.close()`` с бюджетом 0.3 с —
    обязан получить готовый отчёт, а не ``complete=False`` по сроку.
    """

    def reporter(report) -> None:
        if report.elapsed_s == 0.0 and report.emits_after_close == 7:
            time.sleep(1.0)

    root = open_scope(_path(), budget_s=1.0, reporter=reporter)
    c = root.child("c", budget_s=0.3)
    c.note_emits_after_close(7)
    inside, go = threading.Event(), threading.Event()

    def res() -> None:
        inside.set()
        go.wait(5.0)
        root.close()

    c.own(res, name="res")
    out: dict = {}
    t2 = threading.Thread(target=lambda: out.__setitem__("t2", c.close()), daemon=True)
    t2.start()
    assert inside.wait(5.0)
    t3 = threading.Thread(target=lambda: out.__setitem__("t3", c.close()), daemon=True)
    t3.start()
    time.sleep(0.05)  # T3 уже ждёт c._done
    go.set()
    t3.join(5.0)
    t2.join(5.0)
    assert not t2.is_alive() and not t3.is_alive()
    assert out["t3"].complete is True
