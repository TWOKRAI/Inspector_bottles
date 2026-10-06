# -*- coding: utf-8 -*-
"""Независимые приёмочные тесты Task 0.4: ``qt_lifetime`` (attach_qt / flush_deferred_deletes / QThreadHandle).

Написаны вслепую, ДО реализации, по plans/2026-10-03_lifecycle-owner-scope/task-0.4.md
(раздел «Контракт реализации» и таблица приёмки, набор R). Ожидаемые значения —
литералы из спека. Проверяется наблюдаемый эффект (``shiboken6.isValid``, ``weakref``,
поля ``CloseReport``, поток сигнала ``destroyed``), а не имена внутренних функций.

Правила набора:
- ``QT_QPA_PLATFORM=offscreen`` ставится до импорта PySide6; одно ``QApplication`` на процесс;
  окон и всплывающих меню нет, только ``QObject`` / ``QThread``;
- имена двери (``attach_qt`` и др.) импортируются ВНУТРИ каждого теста: до GREEN
  прогон показывает N failed, а не одну ошибку сбора;
- то, что может зависнуть (``close`` с потоком), идёт в daemon-потоке с ``join(timeout)``;
  зависание = assert с текстом. ``close`` с проверкой Qt-дерева обязан идти на потоке объекта
  (главном), поэтому там вызов прямой, а страховку даёт ``faulthandler`` (трассировка + выход);
- ``app.exec()`` и отложенное удаление «вне цикла» — только в подпроцессе (timeout=60);
- teardown: закрыть ВСЕ корни теста, затем ``flush_deferred_deletes`` в цикле.
"""

from __future__ import annotations

import faulthandler
import os
import subprocess
import sys
import threading
import time
import weakref
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
import shiboken6  # noqa: E402
from PySide6.QtCore import QEvent, QObject, QThread  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from shiboken6 import Shiboken  # noqa: E402

from multiprocess_framework.modules.base_manager import open_scope  # noqa: E402
from multiprocess_framework.modules.process_module.lifecycle.gc_discipline import paused_gc

_REPO_ROOT = Path(__file__).resolve().parents[4]
_IFACE = "multiprocess_framework.modules.frontend_module.interfaces"
_HANG_GUARD_S = 90.0


# ======================================================================== инфраструктура


def _door():
    """Имена двери — внутри теста, чтобы отсутствие реализации было красным тестом, не ошибкой сбора."""
    import importlib

    return importlib.import_module(_IFACE)


def _run(fn, *args, _timeout=10.0, _what="вызов", **kwargs):
    """fn в daemon-потоке с join(timeout); вернуть (результат, длительность изнутри потока)."""
    box = {}

    def runner():
        t0 = time.monotonic()
        try:
            box["r"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - пробрасываем в поток теста
            box["e"] = exc
        box["dt"] = time.monotonic() - t0

    th = threading.Thread(target=runner, daemon=True, name="t04-helper")
    th.start()
    th.join(_timeout)
    assert not th.is_alive(), f"{_what} завис дольше {_timeout} с"
    if "e" in box:
        raise box["e"]
    return box["r"], box["dt"]


def _flush_for_teardown() -> None:
    """Teardown-flush: настоящий, если дверь уже есть; до GREEN — сырой цикл, чтобы красный тест не плодил ошибок."""
    app = QApplication.instance()
    try:
        flush = _door().flush_deferred_deletes
    except (ImportError, AttributeError):
        for _ in range(16):
            app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        return
    for _ in range(3):
        flush()


@pytest.fixture(scope="session")
def qapp_inst():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def env(qapp_inst):
    """Корень ``root`` (budget 1.0) → ``tab`` → ``comp``; журнал отчётов ``got``; потоки сигнала ``dthreads``."""
    got: list = []
    root = open_scope("root", budget_s=1.0, reporter=got.append)
    tab = root.child("tab")
    comp = tab.child("comp")
    dthreads: list = []

    def on_destroyed(*_args):
        dthreads.append(threading.get_ident())

    def watch(obj):
        obj.destroyed.connect(on_destroyed)

    ns = SimpleNamespace(
        got=got,
        root=root,
        tab=tab,
        comp=comp,
        main=threading.get_ident(),
        dthreads=dthreads,
        watch=watch,
        roots=[root],
        app=qapp_inst,
    )
    faulthandler.dump_traceback_later(_HANG_GUARD_S, exit=True)
    try:
        yield ns
    finally:
        faulthandler.cancel_dump_traceback_later()
        errors: list = []
        for r in reversed(ns.roots):
            try:
                _run(r.close, _timeout=10.0, _what=f"teardown close({r.path})")
            except BaseException as exc:  # noqa: BLE001 - соберём, flush всё равно нужен
                errors.append(exc)
        _flush_for_teardown()
        if errors:
            raise errors[0]


def _child_env() -> dict:
    e = dict(os.environ)
    e["QT_QPA_PLATFORM"] = "offscreen"
    e["PYTHONUTF8"] = "1"
    e["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + e.get("PYTHONPATH", "")
    return e


def _run_script(script: str):
    """Подпроцесс с timeout=60; зависание = провал с текстом."""
    try:
        return subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            env=_child_env(),
            cwd=str(_REPO_ROOT),
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"подпроцесс завис дольше 60 с; stdout={exc.stdout!r} stderr={exc.stderr!r}")


# ======================================================================== Q2


def test_close_from_worker_destroys_on_main_after_flush(env):
    """Q2: ``close`` из чужого потока не удаляет объект там; удаление — на главном, после flush."""
    attach_qt = _door().attach_qt
    flush_deferred_deletes = _door().flush_deferred_deletes

    obj = QObject()
    env.watch(obj)
    attach_qt(env.root, obj)
    r = weakref.ref(obj)
    del obj
    with paused_gc():
        rep, _ = _run(env.root.close, _timeout=5.0, _what="root.close() из daemon-потока")
        assert rep.ok, f"close() не ok: {rep}"
        assert env.dthreads == [], "объект уничтожен до flush (на потоке закрывающего?)"
        flush_deferred_deletes()
        assert env.dthreads == [env.main], f"destroyed не на главном потоке: {env.dthreads} (main={env.main})"
        assert r() is None, "обёртка объекта жива после flush"


# ======================================================================== Q2b


_Q2B_SCRIPT = """
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import gc, weakref
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from multiprocess_framework.modules.base_manager import open_scope
from multiprocess_framework.modules.frontend_module.interfaces import attach_qt
rt = open_scope("ab", budget_s=1.0)
o = QObject()
attach_qt(rt, o)
r = weakref.ref(o)
del o, rt
gc.collect()
print("dead=%s" % (r() is None))
"""


def test_abandoned_root_frees_qobject_subprocess():
    """Q2b: брошенный корень освобождает QObject без жизни цикла: обработчик ``destroyed`` его не держит."""
    _ = _door().attach_qt  # дверь обязана существовать и в тест-процессе
    proc = _run_script(_Q2B_SCRIPT)
    assert "dead=True" in proc.stdout, f"rc={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"


# ======================================================================== Q3


def test_close_transfers_ownership_to_cpp(env):
    """Q3: до привязки объект принадлежит Python; после ``close`` — C++ (deleteLater), после flush — мёртв."""
    attach_qt = _door().attach_qt
    flush_deferred_deletes = _door().flush_deferred_deletes

    obj = QObject()
    assert Shiboken.ownedByPython(obj) is True
    attach_qt(env.root, obj)
    env.root.close()
    assert Shiboken.ownedByPython(obj) is False, "после close владение не передано C++"
    assert shiboken6.isValid(obj) is True, "объект удалён синхронно, без deleteLater"
    flush_deferred_deletes()
    assert shiboken6.isValid(obj) is False, "после flush объект жив (deleteLater не вызван)"


# ======================================================================== Q4


_Q4_SCRIPT = """
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import shiboken6
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
QTimer.singleShot(0, app.quit)
QTimer.singleShot(3000, app.quit)
app.exec()
from multiprocess_framework.modules.base_manager import open_scope
from multiprocess_framework.modules.frontend_module.interfaces import attach_qt, flush_deferred_deletes
root = open_scope("q4", budget_s=1.0)
o = QObject()
attach_qt(root, o)
root.close()
before = shiboken6.isValid(o)
flush_deferred_deletes()
after = shiboken6.isValid(o)
print("before=%s after=%s" % (before, after))
"""


def test_flush_after_exec_in_subprocess():
    """Q4: после выхода из ``app.exec()`` цикла событий нет, а flush всё равно удаляет объект."""
    _ = _door().flush_deferred_deletes  # дверь обязана существовать и в тест-процессе
    proc = _run_script(_Q4_SCRIPT)
    assert "before=True after=False" in proc.stdout, (
        f"rc={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert proc.returncode == 0, f"rc={proc.returncode}\nstderr={proc.stderr!r}"


# ======================================================================== Q5


def test_qt_deletes_first_closes_scope(env):
    """Q5: Qt удалил объект первым — область без него закрывается синхронно, отчёт ``ok``."""
    attach_qt = _door().attach_qt
    flush_deferred_deletes = _door().flush_deferred_deletes

    p = QObject()
    c = QObject(p)
    attach_qt(env.tab, c)
    p.deleteLater()
    flush_deferred_deletes()
    assert env.tab.closed is True, "область не закрылась после удаления привязанного объекта Qt-ом"
    assert [(r.path, r.ok) for r in env.got] == [("root/tab", True)]


# ======================================================================== Q6 / S3 / S8: несовпадение дерева


def test_qt_tree_mismatch_unowned_parent(env):
    """Q6 (S4): Qt-родитель привязанного объекта не принадлежит ни области, ни предкам → пара в ``errors``."""
    attach_qt = _door().attach_qt
    flush_deferred_deletes = _door().flush_deferred_deletes

    t = QObject()
    attach_qt(env.tab, t)
    f = QObject()  # НЕ привязан
    c = QObject(f)
    attach_qt(env.comp, c, name="c")
    rep = env.comp.close()
    assert rep.ok is False
    assert len(rep.errors) == 1, f"errors={rep.errors!r}"
    assert rep.errors[0][0] == "root/tab/comp/c"
    assert "qt-tree mismatch" in rep.errors[0][1], rep.errors[0][1]
    flush_deferred_deletes()
    assert shiboken6.isValid(c) is False, "объект с несовпадением всё равно обязан быть удалён"


def test_qt_deleted_cascade_no_errors(env):
    """S2: каскад удаления Qt-ом (родитель уходит вместе с детьми) не даёт ложных ``qt-tree mismatch``."""
    attach_qt = _door().attach_qt
    flush_deferred_deletes = _door().flush_deferred_deletes

    attach_qt(env.root, QObject())  # W: выше comp что-то привязано, проверка дерева включена
    t = QObject()
    attach_qt(env.tab, t)
    c = QObject(t)
    attach_qt(env.comp, c)
    del c
    t.deleteLater()
    del t
    flush_deferred_deletes()
    assert [(r.path, r.ok) for r in env.got] == [("root/tab", True)]
    assert env.got[0].errors == ()


def test_qt_tree_mismatch_sibling_scope(env):
    """S3: родитель объекта привязан к ЧУЖОЙ (соседней) области — для этой области это несовпадение."""
    attach_qt = _door().attach_qt
    flush_deferred_deletes = _door().flush_deferred_deletes

    t = QObject()
    attach_qt(env.tab, t)
    other = env.root.child("other")
    f = QObject()
    attach_qt(other, f)
    c = QObject(f)
    attach_qt(env.comp, c, name="c")
    rep = env.comp.close()
    assert rep.ok is False
    assert len(rep.errors) == 1, f"errors={rep.errors!r}"
    assert rep.errors[0][0] == "root/tab/comp/c"
    assert "qt-tree mismatch" in rep.errors[0][1], rep.errors[0][1]
    assert shiboken6.isValid(c) is True, "до flush объект обязан быть ещё жив"
    flush_deferred_deletes()
    assert shiboken6.isValid(c) is False


def test_qt_tree_mismatch_descendant_inversion(env):
    """S8: Qt-родитель — объект ПОТОМКА области (инверсия): потомки не входят в ``owned``."""
    attach_qt = _door().attach_qt

    attach_qt(env.root, QObject())  # W
    w = QObject()
    attach_qt(env.comp, w)
    c = QObject(w)
    attach_qt(env.tab, c, name="c")
    rep = env.tab.close()
    assert rep.ok is False
    assert len(rep.errors) == 1, f"errors={rep.errors!r}"
    assert rep.errors[0][0] == "root/tab/c"
    assert "qt-tree mismatch" in rep.errors[0][1], rep.errors[0][1]


# ======================================================================== Q11


def test_qthread_stuck_is_survivor_within_budget(env):
    """Q11: не остановившийся ``QThread`` — выживший в срок бюджета; ни kill, ни ошибок, ни ожидания «до 5 с»."""
    QThreadHandle = _door().QThreadHandle

    release = threading.Event()

    class Stuck(QThread):
        def run(self):  # noqa: D102
            release.wait(10.0)

    r = open_scope("r", budget_s=0.3)
    env.roots.append(r)
    t = Stuck()
    try:
        r.own(QThreadHandle(t), name="qt", kind="qthread")
        t.start()
        rep, dt = _run(r.close, _timeout=5.0, _what="r.close() со зависшим QThread")
        assert dt <= 0.6, f"close() занял {dt:.3f} с (> 0.6 при budget_s=0.3)"
        assert rep.survivors == ("r/qt",), f"survivors={rep.survivors!r}"
        assert rep.killed == (), f"killed={rep.killed!r} (terminate запрещён)"
        assert rep.errors == (), f"errors={rep.errors!r}"
    finally:
        release.set()
        assert t.wait(5000), "QThread не завершился после снятия блокировки"
