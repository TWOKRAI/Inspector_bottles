# -*- coding: utf-8 -*-
"""Тесты автора Task 0.4: набор «T» спека и опасности (гонки, каскад, ожидание чужого close).

Спек: plans/2026-10-03_lifecycle-owner-scope/task-0.4.md, таблица «Acceptance criteria и инъекции».
Приёмочный набор «R» тестера — ``test_qt_lifetime_acceptance.py`` (не здесь).

Правила: offscreen до импорта PySide6; только ``QObject``/``QThread``; имена двери — внутри
теста; то, что может зависнуть, — в daemon-потоке с ``join(timeout)``; ``app.exec()`` и
самозакрытие ``QThread`` — в подпроцессе; teardown закрывает все корни и делает flush.
"""

from __future__ import annotations

import faulthandler
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
import shiboken6  # noqa: E402
from PySide6.QtCore import QEvent, QObject, QThread, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from multiprocess_framework.modules.base_manager import open_scope  # noqa: E402
from multiprocess_framework.modules.base_manager.interfaces import ScopeClosedError  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[4]
_IFACE = "multiprocess_framework.modules.frontend_module.interfaces"
_HANG_GUARD_S = 90.0


def _door():
    import importlib

    return importlib.import_module(_IFACE)


def _run(fn, *args, _timeout=10.0, _what="вызов", **kwargs):
    """fn в daemon-потоке с join(timeout); вернуть (результат, длительность изнутри потока)."""
    box: dict = {}

    def runner():
        t0 = time.monotonic()
        try:
            box["r"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - пробрасываем в поток теста
            box["e"] = exc
        box["dt"] = time.monotonic() - t0

    th = threading.Thread(target=runner, daemon=True, name="t04-author")
    th.start()
    th.join(_timeout)
    assert not th.is_alive(), f"{_what} завис дольше {_timeout} с"
    if "e" in box:
        raise box["e"]
    return box["r"], box["dt"]


def _flush_for_teardown() -> None:
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
    """Корень ``root`` (budget 1.0) → ``tab`` → ``comp``; журнал отчётов ``got``."""
    got: list = []
    root = open_scope("root", budget_s=1.0, reporter=got.append)
    tab = root.child("tab")
    comp = tab.child("comp")
    ns = SimpleNamespace(got=got, root=root, tab=tab, comp=comp, roots=[root], app=qapp_inst)
    faulthandler.dump_traceback_later(_HANG_GUARD_S, exit=True)
    try:
        yield ns
    finally:
        faulthandler.cancel_dump_traceback_later()
        errors: list = []
        for r in reversed(ns.roots):
            try:
                _run(r.close, _timeout=10.0, _what=f"teardown close({r.path})")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
        _flush_for_teardown()
        if errors:
            raise errors[0]


def _run_script(script: str):
    e = dict(os.environ)
    e["QT_QPA_PLATFORM"] = "offscreen"
    e["PYTHONUTF8"] = "1"
    e["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + e.get("PYTHONPATH", "")
    try:
        return subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            env=e,
            cwd=str(_REPO_ROOT),
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"подпроцесс завис дольше 60 с; stdout={exc.stdout!r} stderr={exc.stderr!r}")


# ======================================================================== Q1 / Q13


def test_attach_returns_qobject_handle(env):
    """Q1: запись вида ``"qobject"``; имя по умолчанию ``<Тип>#n``, явное — как задано."""
    attach_qt = _door().attach_qt
    h = attach_qt(env.root, QObject())
    assert h.kind == "qobject"
    assert re.fullmatch(r"root/QObject#\d+", h.path), h.path
    h2 = attach_qt(env.root, QObject(), name="w")
    assert h2.path == "root/w"
    assert h2.kind == "qobject"


def test_reexport_identity():
    """Q13: интерфейс модуля реэкспортирует те же объекты, не копии."""
    from multiprocess_framework.modules.frontend_module.core import qt_lifetime

    door = _door()
    for name in ("attach_qt", "flush_deferred_deletes", "QThreadHandle", "QtTreeMismatch"):
        assert getattr(door, name) is getattr(qt_lifetime, name), name
        assert name in door.__all__, name


# ======================================================================== правило C: совпадения


def test_parentless_and_owned_parent_no_mismatch(env):
    """Q7: родитель привязан в области-предке; объект без родителя — оба совпадения."""
    attach_qt = _door().attach_qt
    t = QObject()
    attach_qt(env.tab, t)
    c2 = QObject(t)
    attach_qt(env.comp, c2, name="c2")
    c3 = QObject()
    attach_qt(env.comp, c3, name="c3")
    rep = env.comp.close()
    assert rep.errors == ()
    assert rep.ok is True


def test_parentless_timer_attached_first_no_mismatch(env):
    """S1: первым привязан таймер без родителя, затем ``w``; родитель ``w`` — совпадение."""
    attach_qt = _door().attach_qt
    timer = QTimer()
    attach_qt(env.tab, timer)
    w = QObject()
    attach_qt(env.tab, w)
    c = QObject(w)
    attach_qt(env.comp, c, name="c")
    rep = env.comp.close()
    assert rep.errors == ()


def test_child_scope_before_object_no_mismatch(env):
    """S7: дочерняя область создана до объекта; LIFO освобождает ``t`` раньше ``c`` — адрес ``t`` ещё в реестре."""
    attach_qt = _door().attach_qt
    attach_qt(env.root, QObject())  # W: включает проверку для tab2/comp2
    tab2 = env.root.child("tab2")
    comp2 = tab2.child("comp")
    t = QObject()
    attach_qt(tab2, t)
    c = QObject(t)
    attach_qt(comp2, c, name="c")
    rep = tab2.close()
    assert rep.errors == ()
    assert rep.ok is True


def test_second_toplevel_no_mismatch(env):
    """S6: в области два верхних объекта; родитель — второй из них.

    Две части: верхние объекты в области-предке (``tab``) и в своей области (``comp``).
    Вторая часть сторожит ``owned`` со своей областью: верхние ``tab`` уже делают ``above``
    непустым, поэтому первая часть к такой поломке слепа (инъекция Q2 ведущего).
    """
    attach_qt = _door().attach_qt
    t = QObject()
    attach_qt(env.tab, t)
    dock = QObject()
    attach_qt(env.tab, dock)
    c = QObject(dock)
    attach_qt(env.comp, c, name="c")
    t2 = QObject()
    attach_qt(env.comp, t2, name="t2")
    dock2 = QObject()
    attach_qt(env.comp, dock2, name="dock2")
    c2 = QObject(dock2)
    attach_qt(env.comp, c2, name="c2")
    rep = env.comp.close()
    assert rep.errors == ()
    assert rep.ok is True


def test_no_registered_ancestor_skips_tree_check(env):
    """Правило миграции: выше области ничего не привязано — проверки дерева нет, чужой родитель не ошибка."""
    attach_qt = _door().attach_qt
    f = QObject()  # не привязан никуда; в root и tab тоже ничего не привязано
    c = QObject(f)
    attach_qt(env.comp, c, name="c")
    rep = env.comp.close()
    assert rep.errors == ()
    assert rep.ok is True


def test_offthread_close_skips_tree_check(env):
    """S9: ``close`` с чужого потока проверку дерева не делает (best-effort): ``errors == ()``."""
    attach_qt = _door().attach_qt
    t = QObject()
    attach_qt(env.tab, t)
    f = QObject()  # не привязан — на главном потоке это было бы несовпадение (Q6)
    c = QObject(f)
    attach_qt(env.comp, c, name="c")
    rep, _ = _run(env.comp.close, _timeout=5.0, _what="comp.close() из daemon")
    assert rep.errors == ()


def test_own_dialog_helper_no_mismatch(env):
    """S10: родитель привязан в той же области — совпадение."""
    attach_qt = _door().attach_qt
    t = QObject()
    attach_qt(env.tab, t)
    dlg = QObject()
    attach_qt(env.comp, dlg, name="dlg")
    c = QObject(dlg)
    attach_qt(env.comp, c, name="c")
    rep = env.comp.close()
    assert rep.errors == ()


# ======================================================================== attach_qt: отказы


def test_attach_to_closed_scope_deletes_and_raises(env):
    """Q8: закрытая область освобождает объект (``deleteLater``) и бросает ``ScopeClosedError``."""
    attach_qt = _door().attach_qt
    flush = _door().flush_deferred_deletes
    env.root.close()
    obj = QObject()
    with pytest.raises(ScopeClosedError):
        attach_qt(env.root, obj)
    assert shiboken6.isValid(obj) is True, "удалён синхронно, без deleteLater"
    flush()
    assert shiboken6.isValid(obj) is False


def test_bad_args_and_flush_thread(env):
    """Q9: не ``QObject`` → ``TypeError``; flush с чужого потока → ``RuntimeError``."""
    door = _door()
    with pytest.raises(TypeError, match="ожидается QObject, получено object"):
        door.attach_qt(env.root, object())
    with pytest.raises(RuntimeError, match="flush_deferred_deletes"):
        _run(door.flush_deferred_deletes, _timeout=5.0, _what="flush из daemon")
    with pytest.raises(TypeError):
        door.QThreadHandle(QObject())
    with pytest.raises(TypeError):
        door.QThreadHandle(QThread(), stop=42)


def test_name_taken_leaves_no_connection(env):
    """Q16: имя занято → ``ValueError``; объект не попал в реестр — ребёнок даёт ровно 1 несовпадение."""
    attach_qt = _door().attach_qt
    a = QObject()
    attach_qt(env.root, a, name="w")
    b = QObject()
    with pytest.raises(ValueError):
        attach_qt(env.root, b, name="w")
    c = QObject(b)
    attach_qt(env.comp, c, name="c")
    rep = env.comp.close()
    assert len(rep.errors) == 1, f"errors={rep.errors!r}"
    assert rep.errors[0][0] == "root/tab/comp/c"
    assert "qt-tree mismatch" in rep.errors[0][1]


def test_attach_finished_thread_raises(env):
    """Q17: объект завершившегося Python-потока → ``ValueError`` (deleteLater не будет доставлен)."""
    attach_qt = _door().attach_qt
    box: dict = {}

    def make():
        box["o"] = QObject()

    th = threading.Thread(target=make, daemon=True)
    th.start()
    th.join(5.0)
    assert not th.is_alive()
    with pytest.raises(ValueError, match="поток объекта не работает"):
        attach_qt(env.root, box["o"])


def test_attach_not_started_qthread_accepted(env):
    """Q17b: объект, перенесённый в ещё не запущенный ``QThread``, принимается."""
    attach_qt = _door().attach_qt
    r = open_scope("q17b", budget_s=0.3)
    env.roots.append(r)
    qt = QThread()
    o = QObject()
    o.moveToThread(qt)
    h = attach_qt(r, o)
    assert h.kind == "qobject"
    env.keep = (qt, o)  # поток не запускается: удаление объекта не будет доставлено, держим до конца теста


# ======================================================================== flush


def test_flush_drains_cascaded_deletes(env):
    """Q15: удаление ``a`` закрывает ``tab``, её освобождение ставит ``b.deleteLater`` — один flush берёт оба."""
    attach_qt = _door().attach_qt
    flush = _door().flush_deferred_deletes
    a = QObject()
    attach_qt(env.tab, a, name="a")
    b = QObject()
    attach_qt(env.tab, b, name="b")
    a.deleteLater()
    flush()
    assert env.tab.closed is True
    assert shiboken6.isValid(b) is False, "второй проход не выполнен: b жив после одного flush"


def test_flush_during_foreign_close_returns_fast(env):
    """Q14: Qt удалил объект, пока область закрывается чужим потоком — flush не ждёт чужой close."""
    attach_qt = _door().attach_qt
    flush = _door().flush_deferred_deletes

    class Slow:
        def request_stop(self) -> None:
            pass

        def join_until(self, deadline: float) -> bool:
            time.sleep(0.8)
            return True

    rr = open_scope("rr", budget_s=2.0)
    env.roots.append(rr)
    p = QObject()
    o = QObject(p)
    attach_qt(rr, o)
    rr.own(Slow(), name="slow")
    closer = threading.Thread(target=rr.close, daemon=True, name="t04-closer")
    closer.start()
    poll_until = time.monotonic() + 2.0
    while not rr.closed and time.monotonic() < poll_until:
        time.sleep(0.005)
    assert rr.closed is True, "rr.close() не начался за 2 с"
    p.deleteLater()
    t0 = time.monotonic()
    flush()
    dt = time.monotonic() - t0
    closer.join(5.0)
    assert not closer.is_alive(), "rr.close() завис"
    assert dt < 0.1, f"flush ждал чужой close: {dt:.3f} с"


# ======================================================================== QThreadHandle


def test_qthread_cooperative_stop(env):
    """Q10: поток, опрашивающий ``isInterruptionRequested``, останавливается в бюджете."""
    QThreadHandle = _door().QThreadHandle

    class Coop(QThread):
        def run(self):  # noqa: D102
            while not self.isInterruptionRequested():
                time.sleep(0.01)

    t = Coop()
    env.root.own(QThreadHandle(t), name="qt", kind="qthread")
    t.start()
    rep, dt = _run(env.root.close, _timeout=5.0, _what="root.close() с QThread")
    assert dt <= 1.0, f"close() занял {dt:.3f} с"
    assert rep.ok is True, f"{rep}"
    assert t.isFinished() is True


def test_stop_called_once(env):
    """Q12: ``stop`` зовётся один раз за жизнь ручки, сколько бы ни было ``request_stop``."""
    QThreadHandle = _door().QThreadHandle
    calls: list = []
    r = open_scope("r", budget_s=0.3)
    env.roots.append(r)
    t = QThread()
    h = QThreadHandle(t, stop=lambda: calls.append(1))
    r.own(h, name="qt", kind="qthread")
    h.request_stop()
    h.request_stop()
    assert len(calls) == 1
    rep = r.close()
    assert rep.ok is True, f"{rep}"
    assert len(calls) == 1


_Q18_SCRIPT = """
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from multiprocess_framework.modules.base_manager import open_scope
from multiprocess_framework.modules.frontend_module.interfaces import QThreadHandle, flush_deferred_deletes
r = open_scope("r", budget_s=0.3)
reports = []
class Self(QThread):
    def run(self):
        reports.append(r.close())
t = Self()
r.own(QThreadHandle(t), name="qt", kind="qthread")
t.start()
waited = t.wait(5000)
print("waited=%s survivors=%r" % (waited, reports[0].survivors if reports else None))
flush_deferred_deletes()
"""


def test_qthread_self_close_survivor():
    """Q18: ``QThread``, закрывший свою область изнутри ``run``, — выживший ``"r/qt"`` без ``" (self)"``."""
    _ = _door().QThreadHandle
    proc = _run_script(_Q18_SCRIPT)
    assert "waited=True survivors=('r/qt',)" in proc.stdout, (
        f"rc={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )


# ======================================================================== опасности: гонка привязки


def test_concurrent_attach_from_four_threads(env):
    """200 ``attach_qt`` в одну область из 4 потоков (объекты главного потока): все удалены, ``errors == ()``."""
    attach_qt = _door().attach_qt
    flush = _door().flush_deferred_deletes
    objs = [QObject() for _ in range(200)]
    barrier = threading.Barrier(4)
    failures: list = []

    def worker(part):
        try:
            barrier.wait(5.0)
            for o in part:
                attach_qt(env.root, o)
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)

    threads = [threading.Thread(target=worker, args=(objs[i::4],), daemon=True) for i in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(10.0)
    assert not any(th.is_alive() for th in threads), "attach_qt завис"
    assert failures == []
    assert sum(1 for e in env.root.live() if e["kind"] == "qobject") == 200
    rep = env.root.close()
    assert rep.errors == ()
    flush()
    alive = sum(1 for o in objs if shiboken6.isValid(o))
    assert alive == 0, f"после close + flush живы {alive} из 200"


# ======================================================================== ревью р1


_THREAD_SCRIPT_HEAD = """
import os, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from multiprocess_framework.modules.base_manager import open_scope
from multiprocess_framework.modules.frontend_module.interfaces import QThreadHandle, flush_deferred_deletes
class Coop(QThread):
    def run(self):
        t0 = time.monotonic()
        while not self.isInterruptionRequested() and time.monotonic() - t0 < 3.0:
            time.sleep(0.01)
"""

_START_AFTER_CLOSE_SCRIPT = (
    _THREAD_SCRIPT_HEAD
    + """
r = open_scope("r", budget_s=0.3)
t = Coop()
r.own(QThreadHandle(t), name="qt", kind="qthread")
rep = r.close()
t.start()
flush_deferred_deletes()
print("flushed ok=%s" % rep.ok, flush=True)
t.requestInterruption()
print("waited=%s" % t.wait(5000), flush=True)
"""
)

_CLOSE_RUNNING_SCRIPT = (
    _THREAD_SCRIPT_HEAD
    + """
t = Coop()
t.start()
h = QThreadHandle(t)
h.close()
flush_deferred_deletes()
print("flushed running=%s" % t.isRunning(), flush=True)
t.requestInterruption()
print("waited=%s" % t.wait(5000), flush=True)
"""
)


_CLOSE_RUNNING_SOLE_HOLDER_SCRIPT = (
    _THREAD_SCRIPT_HEAD
    + """
import gc, time
t = Coop()
t.start()
h = QThreadHandle(t)
del t  # ручка — единственный держатель работающего потока
h.close()
gc.collect()
flush_deferred_deletes()
print("after close alive", flush=True)
h.request_stop()
print("joined=%s" % h.join_until(time.monotonic() + 5.0), flush=True)
h.close()
flush_deferred_deletes()
print("closed after finish", flush=True)
"""
)


def test_qthread_handle_close_running_keeps_sole_reference():
    """Ревью 0.4 р2 (4c): ``close()`` на работающем потоке не отпускает ссылку ручки —
    иначе последняя ссылка на работающий ``QThread`` умирает и процесс падает (abort)."""
    _ = _door().QThreadHandle
    proc = _run_script(_CLOSE_RUNNING_SOLE_HOLDER_SCRIPT)
    assert proc.returncode == 0, f"rc={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    assert "after close alive" in proc.stdout
    assert "joined=True" in proc.stdout
    assert "closed after finish" in proc.stdout


def test_qthread_started_after_close_not_deleted():
    """Р1-1а: ручка закрыта при незапущенном потоке, поток запущен потом — flush его не удаляет (нет abort)."""
    _ = _door().QThreadHandle
    proc = _run_script(_START_AFTER_CLOSE_SCRIPT)
    assert proc.returncode == 0, f"rc={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    assert "flushed ok=True" in proc.stdout
    assert "waited=True" in proc.stdout
    assert "поток не завершён" in proc.stderr, proc.stderr


def test_qthread_handle_close_running_not_deleted():
    """Р1-1б: публичный ``close()`` ручки на работающем потоке — объект не удаляется, строка warning."""
    _ = _door().QThreadHandle
    proc = _run_script(_CLOSE_RUNNING_SCRIPT)
    assert proc.returncode == 0, f"rc={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    assert "flushed running=True" in proc.stdout
    assert "waited=True" in proc.stdout
    assert "поток не завершён" in proc.stderr, proc.stderr


_GC_REENTRY_SCRIPT = """
import os, gc, threading
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from multiprocess_framework.modules.base_manager import open_scope
from multiprocess_framework.modules.frontend_module.core import qt_lifetime as ql
gc.disable()
gc.collect()
rec = []

def other_thread_gets_lock():
    box = {}
    def grab():
        box["got"] = ql._lock.acquire(timeout=0.2)
        if box["got"]:
            ql._lock.release()
    th = threading.Thread(target=grab)
    th.start()
    th.join()
    return box["got"]

class P(QObject):
    pass

p = P()
p.me = p  # цикл: соберёт только gc
c = QObject(p)
s2 = open_scope("s2", budget_s=1.0)
s2.own(lambda: rec.append((ql._lock._is_owned(), other_thread_gets_lock())), name="rec")
ql.attach_qt(s2, c, name="c")

root = open_scope("root", budget_s=1.0)
ql.attach_qt(root, QObject(), name="W")
tab = root.child("tab")

class HookScope:
    # IScope поверх настоящей области; parent — точка gc, которой управляет тест
    def __init__(self, real, parent):
        self._real, self._parent, self.armed = real, parent, False
    @property
    def path(self):
        return self._real.path
    @property
    def closed(self):
        return self._real.closed
    @property
    def parent(self):
        if self.armed:
            self.armed = False
            gc.collect()
        return self._parent
    def own(self, res, *, name, kind="resource"):
        return self._real.own(res, name=name, kind=kind)
    def close(self, *a, **k):
        return self._real.close(*a, **k)

hs = HookScope(tab, root)
x = QObject()
ql.attach_qt(hs, x, name="x")
del p
hs.armed = True
tab.close()
print("rec=%r s2closed=%s" % (rec, s2.closed), flush=True)
root.close()
ql.flush_deferred_deletes()
"""


def test_gc_finalizer_close_not_under_module_lock():
    """Р1-2: gc на проверке дерева закрывает чужую область — лок модуля в этот момент не занят."""
    _ = _door().attach_qt
    proc = _run_script(_GC_REENTRY_SCRIPT)
    assert "rec=[(False, True)] s2closed=True" in proc.stdout, (
        f"rc={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )


def test_lock_sections_have_no_calls():
    """Р1-2 (белый ящик): под ``_lock`` нет вызовов — ни точки gc, ни кода Python."""
    import ast

    from multiprocess_framework.modules.frontend_module.core import qt_lifetime

    tree = ast.parse(Path(qt_lifetime.__file__).read_text(encoding="utf-8"))
    sections = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.With) and any(
            isinstance(it.context_expr, ast.Name) and it.context_expr.id == "_lock" for it in node.items
        ):
            sections += 1
            calls = [ast.unparse(n) for st in node.body for n in ast.walk(st) if isinstance(n, ast.Call)]
            assert calls == [], f"вызовы под _lock (строка {node.lineno}): {calls}"
    assert sections >= 1


_FLUSH_IN_LOOP_SCRIPT = """
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from multiprocess_framework.modules.base_manager import open_scope
from multiprocess_framework.modules.frontend_module.interfaces import attach_qt, flush_deferred_deletes
class Em(QObject):
    sig = Signal()
    def fire(self):
        self.sig.emit()
        return self.objectName()
r = open_scope("r", budget_s=1.0)
e = Em()
e.setObjectName("em")
attach_qt(r, e, name="em")
out = []
def slot():
    r.close()
    try:
        flush_deferred_deletes()
        out.append("no-raise")
    except RuntimeError as exc:
        out.append("raised:" + str(exc))
e.sig.connect(slot)
def go():
    try:
        out.append("fire=" + e.fire())
    except RuntimeError as exc:
        out.append("fire-raised:" + str(exc))
    app.quit()
QTimer.singleShot(0, go)
QTimer.singleShot(3000, app.quit)
app.exec()
print(repr(out), flush=True)
"""


def test_flush_inside_event_loop_raises():
    """Р1-3: flush из слота работающего цикла — ``RuntimeError``, отправитель сигнала жив."""
    _ = _door().flush_deferred_deletes
    proc = _run_script(_FLUSH_IN_LOOP_SCRIPT)
    out = proc.stdout
    assert "raised:flush_deferred_deletes" in out, f"rc={proc.returncode}\nstdout={out!r}\nstderr={proc.stderr!r}"
    assert "fire=em" in out, out
