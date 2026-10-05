"""Независимые приёмочные тесты Task 0.3: канал ``IScope.note_emits_after_close``, строки N1-N5.

Написаны вслепую, ДО реализации, по plans/2026-10-03_lifecycle-owner-scope/task-0.3.md
(раздел «Контракт реализации», подраздел «Канал», и таблица «Acceptance criteria и инъекции»).
Ожидаемые значения — литералы из спека.

Правила набора:
- вход только через дверь пакета (``open_scope``); метод ``note_emits_after_close`` до реализации
  отсутствует, поэтому каждый тест падает сам (``AttributeError``), а не при сборе файла;
- эффект наблюдаем через отчёты (``close()``, reporter) и ``live()``, не через внутренние имена;
- каждый вызов, который может зависнуть, идёт в daemon-потоке с join(timeout);
  зависание = assert с текстом, а не таймаут прогона.
"""

from __future__ import annotations

import importlib
import logging
import threading
import time

import pytest

PKG = "multiprocess_framework.modules.base_manager"


# ======================================================================== дверь и инфраструктура


def _open(path, **kw):
    return importlib.import_module(PKG).open_scope(path, **kw)


def _run(fn, *args, _timeout=10.0, _what="вызов", **kwargs):
    """Выполнить fn в daemon-потоке с join(timeout); исключение — в поток теста."""
    box = {}

    def runner():
        try:
            box["r"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - пробрасываем в поток теста
            box["e"] = exc

    th = threading.Thread(target=runner, daemon=True, name="t03n-helper")
    th.start()
    th.join(_timeout)
    assert not th.is_alive(), f"{_what} завис дольше {_timeout} с"
    if "e" in box:
        raise box["e"]
    return box.get("r")


def _wait_until(pred, timeout=5.0, text="условие не наступило"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.005)
    assert pred(), text


@pytest.fixture
def got():
    return []


@pytest.fixture
def root(got):
    """Фикстура спека: ``root = open_scope("root", budget_s=1.0, reporter=got.append)``."""
    scope = _open("root", budget_s=1.0, reporter=got.append)
    yield scope
    _run(scope.close, _what="close() в teardown")


def _reports_of(got, path):
    """Счётчики всех отчётов reporter'а с данным путём — в порядке прихода."""
    return [r.emits_after_close for r in got if r.path == path]


# ======================================================================== N1-N2: канал до родителя


def test_n1_note_into_open_child_lands_in_root_report(root):
    c = root.child("c")

    _run(c.note_emits_after_close, 2, _what="note(2)")

    assert _run(root.close, _what="root.close()").emits_after_close == 2


def test_n2_note_into_closed_child_goes_to_parent_report_not_own(root, got):
    c = root.child("c")
    _run(c.close, _what="c.close()")

    _run(c.note_emits_after_close, 3, _what="note(3) в закрытого ребёнка")

    assert _reports_of(got, "root/c") == [0]  # отчёт c — один, со счётчиком 0
    assert _run(root.close, _what="root.close()").emits_after_close == 3


# ======================================================================== N3: вся цепочка закрыта


def test_n3_note_after_whole_chain_closed_reports_third_kind_call(root, got):
    _run(root.close, _what="root.close()")
    assert len(got) == 1

    _run(root.note_emits_after_close, 1, _what="note(1) после закрытия корня")

    assert len(got) == 2  # ровно один новый вызов reporter'а
    r = got[-1]
    assert r.path == "root"
    assert r.emits_after_close == 1
    assert r.elapsed_s == 0.0
    assert r.survivors == ()
    assert r.killed == ()
    assert r.errors == ()
    assert r.ok is True


def test_n3_note_after_whole_chain_closed_without_reporter_logs_warning(caplog):
    scope = _open("root", budget_s=1.0)
    try:
        _run(scope.close, _what="close()")
        caplog.clear()

        with caplog.at_level(logging.WARNING):
            _run(scope.note_emits_after_close, 1, _what="note(1) без reporter'а")

        lines = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("root" in line for line in lines), f"нет строки logging.warning с путём 'root'; есть: {lines}"
    finally:
        _run(scope.close, _what="close() в teardown")


# ======================================================================== N4: проверка аргумента


def test_n4_note_zero_raises_value_error_and_counts_nothing(root):
    with pytest.raises(ValueError):
        root.note_emits_after_close(0)

    assert _run(root.close, _what="root.close()").emits_after_close == 0


def test_n4_note_bool_raises_type_error_and_counts_nothing(root):
    with pytest.raises(TypeError):
        root.note_emits_after_close(True)

    assert _run(root.close, _what="root.close()").emits_after_close == 0


def test_n4_note_float_raises_type_error_and_counts_nothing(root):
    with pytest.raises(TypeError):
        root.note_emits_after_close(1.0)

    assert _run(root.close, _what="root.close()").emits_after_close == 0


# ======================================================================== N5: полный счётчик при любом порядке закрытия


def test_n5_child_first(root, got):
    c = root.child("c")
    c.note_emits_after_close(3)

    _run(c.close, _what="c.close()")
    report = _run(root.close, _what="root.close()")

    assert report.emits_after_close == 3
    assert all(n == 0 for n in _reports_of(got, "root/c")), _reports_of(got, "root/c")


def test_n5_root_first(root, got):
    c = root.child("c")
    c.note_emits_after_close(3)

    report = _run(root.close, _what="root.close()")

    assert report.emits_after_close == 3
    assert all(n == 0 for n in _reports_of(got, "root/c")), _reports_of(got, "root/c")


def test_n5_overlap(root, got):
    c = root.child("c")
    c.note_emits_after_close(3)

    inside = threading.Event()
    go = threading.Event()

    def hold():
        inside.set()
        go.wait(10.0)  # потолок: зависший тест не держит процесс

    c.own(hold, name="hold")

    box = {}

    def t2_body():
        box["c"] = c.close()

    def t1_body():
        box["root"] = root.close()

    t2 = threading.Thread(target=t2_body, daemon=True, name="t03n-T2-c.close")
    t1 = threading.Thread(target=t1_body, daemon=True, name="t03n-T1-root.close")
    try:
        t2.start()
        assert inside.wait(5.0), "освобождающее вызываемое ребёнка не вызвано за 5 с"
        t1.start()

        def c_is_stopping():
            return any(d["path"] == "root/c" and d["state"] == "stopping" for d in _run(root.live, _what="live()"))

        _wait_until(c_is_stopping, 5.0, 'root.live() не показал {"path": "root/c", "state": "stopping"} за 5 с')
    finally:
        go.set()

    t2.join(5.0)
    t1.join(5.0)
    assert not t2.is_alive(), "c.close() не вернулся за 5 с после go"
    assert not t1.is_alive(), "root.close() не вернулся за 5 с после go"

    assert box["root"].emits_after_close == 3
    assert all(n == 0 for n in _reports_of(got, "root/c")), _reports_of(got, "root/c")
