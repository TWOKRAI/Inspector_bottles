# -*- coding: utf-8 -*-
"""T1 / A2: приёмка Qt-адаптера политики памяти GUI (``qt_gc_policy``).

Источник — plans/2026-10-03_lifecycle-owner-scope/task-T1.md («Qt-адаптер», «A2», Q1–Q5).
Тест слепой: написан до реализации, ожидаемые значения — литералы спека.

Политика берётся через публичные ``gui_memory_policy()`` / ``install_gui_memory_policy()``:
под сессионной фикстурой корня (Brief B) это уже установленная политика сессии, без неё —
политика, которую ставит и снимает фикстура ``policy`` ниже. Двери импортируются лениво:
до реализации каждый тест падает ``ImportError``, а не весь файл на сборе.

Прямых ``gc.collect()`` в файле нет (страж R3): сборка — через ``policy.collect_now()``.
"""

from __future__ import annotations

import functools
import importlib
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest
import shiboken6

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QObject,
    Qt,
    QTimer,
    QWidget,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_POLICY_MODULE = "multiprocess_framework.modules.frontend_module.core.qt_gc_policy"


@functools.cache
def _door():
    """Модуль адаптера; ``ImportError`` — красный до реализации."""
    return importlib.import_module(_POLICY_MODULE)


@pytest.fixture
def policy(qapp):
    door = _door()
    pre = door.gui_memory_policy()
    installed = pre or door.install_gui_memory_policy(qapp)
    try:
        yield installed
    finally:
        if pre is None:
            installed.uninstall()


class _Holder:
    """Пустой объект под цикл ``h.me = h`` (освободить его может только сборщик)."""


# Q1 ---------------------------------------------------------------------------------------------


def test_install_off_app_thread_raises(policy):
    door = _door()
    box: dict = {}

    def body() -> None:
        try:
            box["r"] = door.install_gui_memory_policy()  # app=None -> QCoreApplication.instance()
        except BaseException as exc:  # noqa: BLE001 — исключение и есть предмет проверки
            box["e"] = exc

    th = threading.Thread(target=body, daemon=True)
    th.start()
    th.join(5)
    assert not th.is_alive(), "install_gui_memory_policy с чужого потока завис дольше 5 с"
    exc = box.get("e")
    # политика уже установлена (повтор) — проверка потока всё равно первая
    assert isinstance(exc, RuntimeError), box
    assert "только поток QCoreApplication" in str(exc)


# Q2 ---------------------------------------------------------------------------------------------


def test_timer_collects_qwidget_cycle_on_main(policy, qtbot):
    policy.collect_now()
    assert policy.stats()["timer_attached"] is True

    seen: list[int] = []

    def on_destroyed(*_args) -> None:
        seen.append(threading.get_ident())

    h = _Holder()
    h.me = h
    h.w = QWidget()
    h.w.destroyed.connect(on_destroyed, Qt.ConnectionType.DirectConnection)
    del h
    # живые контейнеры: счётчик gen0 >= 700, первый тик соберёт gen0
    keep = [[] for _ in range(1000)]
    qtbot.waitUntil(lambda: bool(seen), timeout=2500)
    assert seen == [threading.get_ident()]
    del keep


# Q3 ---------------------------------------------------------------------------------------------


def test_collect_now_flushes_outside_loop(policy):
    from multiprocess_framework.modules.base_manager import open_scope
    from multiprocess_framework.modules.frontend_module.interfaces import attach_qt

    root = open_scope("t1-q3", budget_s=1.0)
    o = QObject()
    attach_qt(root, o)
    box: dict = {}

    def closer() -> None:
        try:
            root.close()
        except BaseException as exc:  # noqa: BLE001
            box["e"] = exc

    th = threading.Thread(target=closer, daemon=True)
    th.start()
    th.join(5)
    assert not th.is_alive(), "root.close() на daemon-потоке завис дольше 5 с"
    assert "e" not in box, box
    assert shiboken6.isValid(o) is True  # deleteLater отдан, но цикла событий не было
    policy.collect_now()
    assert shiboken6.isValid(o) is False


# Q4 ---------------------------------------------------------------------------------------------


def test_collect_now_inside_loop_no_flush_no_error(policy, qtbot):
    calls: list[int] = []
    errors: list[BaseException] = []

    def slot() -> None:
        calls.append(1)
        try:
            policy.collect_now()
        except BaseException as exc:  # noqa: BLE001 — исключения собираем в список
            errors.append(exc)

    QTimer.singleShot(0, slot)
    qtbot.wait(200)
    assert len(calls) == 1
    assert errors == []


# Q5 ---------------------------------------------------------------------------------------------

_Q5_SCRIPT = textwrap.dedent(
    """
    import sys
    import threading

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QWidget

    from multiprocess_framework.modules.frontend_module.core.qt_gc_policy import (
        install_gui_memory_policy,
    )
    from multiprocess_framework.modules.process_module.lifecycle.gc_discipline import collection_owner

    app = QApplication([])
    policy = install_gui_memory_policy(app)


    class Holder:
        pass


    def build_tree():
        h = Holder()
        h.me = h  # цикл: освободит только сборщик
        h.root = QWidget()
        h.kids = [QWidget(h.root) for _ in range(3)]
        h.timer = QTimer(h.root)
        h.timer.timeout.connect(lambda: h.me)


    for _ in range(6):
        build_tree()

    box = {}


    def alloc():
        junk = [[i] for i in range(400000)]
        box["n"] = len(junk)


    worker = threading.Thread(target=alloc)
    worker.start()
    worker.join(30)
    if worker.is_alive():
        print("worker hung")
        sys.exit(3)

    owner = collection_owner()
    owner.tick()
    owner.tick()
    app.processEvents()
    policy.collect_now()
    print("Q5-DONE", box["n"])
    """
)


def test_worker_alloc_with_policy_survives_subprocess():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-c", _Q5_SCRIPT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            env=env,
            cwd=str(_REPO_ROOT),
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"подпроцесс завис дольше 60 с; stdout={exc.stdout!r} stderr={exc.stderr!r}")
    assert proc.returncode == 0, f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    assert "Q5-DONE" in proc.stdout, proc.stdout
