"""Throwaway pytest plugin: thread-leak census + Qt garbage census / off-main GC trigger.

Копия docs/reviews/2026-10-03_task-5.5c-gate3/crashprobe.py.txt; два отличия:
журнал сбрасывается на диск сразу после записи строки (до возможного падения процесса);
если PySide6 в процессе не загружен, проба молчит (сама его не импортирует; в реальном наборе
PySide6 загружен всегда).
В остальном копия сознательно не причёсана под стиль репозитория.
"""

# ruff: noqa
import gc, os, sys, threading, time

MODE = os.environ.get("CRASHPROBE_MODE", "census")
LOG = os.environ.get("CRASHPROBE_LOG", "crashprobe.log")
_done_first_logger = False
_before = set()


def _w(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
        f.flush()
        os.fsync(f.fileno())


def _drain_threads():
    return {t.ident: t.name for t in threading.enumerate() if t.name.startswith("batch-drain")}


def pytest_runtest_setup(item):
    global _before, _done_first_logger
    _before = _drain_threads()
    if not _done_first_logger and "logger_module" in item.nodeid:
        _done_first_logger = True
        if "PySide6" not in sys.modules:
            return  # отличие от .txt: сам PySide6 не импортируем - нет загруженного Qt, нечего измерять
        try:
            from PySide6 import QtWidgets, QtGui
        except Exception:
            return
        live = [o for o in gc.get_objects() if isinstance(o, (QtWidgets.QWidget, QtGui.QWindow))]
        _w(f"[{MODE}] at first logger test: gc-tracked QWidget/QWindow wrappers alive-or-garbage = {len(live)}")
        del live
        if MODE == "census":
            gc.set_debug(gc.DEBUG_SAVEALL)
            n = gc.collect()
            qs = [o for o in gc.garbage if isinstance(o, (QtWidgets.QWidget, QtGui.QWindow))]
            names = {}
            for o in qs:
                k = type(o).__module__ + "." + type(o).__qualname__
                names[k] = names.get(k, 0) + 1
            _w(
                f"[census] unreachable objects={n}, of them QWidget/QWindow={len(qs)}: {sorted(names.items(), key=lambda kv: -kv[1])[:15]}"
            )
            gc.set_debug(0)
        elif MODE == "main_gc":
            n = gc.collect()
            x = sum(range(10))
            _w(f"[main_gc] collected {n} on main, survived")
        elif MODE == "main_then_offmain":
            n1 = gc.collect()
            res = {}
            t = threading.Thread(target=lambda: res.setdefault("n", gc.collect()), name="probe-offmain-gc")
            t.start()
            t.join()
            x = sum(range(10))
            _w(f"[main_then_offmain] main collected {n1}, then off-main collected {res.get('n')}, survived")
        elif MODE == "offmain_gc":
            main_id = threading.get_ident()
            res = {}

            def worker():
                res["n"] = gc.collect()
                res["tid"] = threading.get_ident()

            t = threading.Thread(target=worker, name="probe-offmain-gc")
            t.start()
            t.join()
            _w(
                f"[offmain_gc] collected {res.get('n')} objects on thread {res.get('tid')} (main {main_id}); main returning to bytecode now"
            )
            x = sum(range(10))  # eval breaker -> pending calls on main
            _w(f"[offmain_gc] survived pending-call deletions on main")


def pytest_runtest_logfinish(nodeid, location):
    after = _drain_threads()
    new = {k: v for k, v in after.items() if k not in _before}
    if new:
        _w(f"[leak] {nodeid} +{len(new)} batch-drain: {sorted(set(new.values()))} (alive total {len(after)})")
