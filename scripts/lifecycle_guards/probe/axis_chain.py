"""Minimal chain (копия docs/reviews/2026-10-11_task-0.5-axis/chain.py.txt без изменений поведения). argv: <mode>  mode in: main | thread | auto | policy | nogc_thread_alloc
main   : Qt garbage in cycle, event loop ran, gc.collect() on MAIN      -> expect survive
thread : same, explicit gc.collect() on a worker thread, thread exits   -> expect abort
auto   : gc ENABLED, worker only allocates (no gc call) -> automatic GC on worker -> expect abort
policy : gc DISABLED, worker allocates, QTimer on main collects + flushes DeferredDelete -> expect survive
"""

# ruff: noqa
import gc, sys, threading, faulthandler, os

faulthandler.enable(all_threads=True)
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QTreeWidget, QStackedWidget, QPushButton, QLabel
from PySide6.QtCore import QTimer, QEventLoop, QCoreApplication, QEvent

app = QApplication([])
mode = sys.argv[1]
print("platform", app.platformName(), "mode", mode, flush=True)


class Holder:
    pass


def make_garbage(n=6):
    for _ in range(n):
        h = Holder()
        h.me = h  # Python cycle holding a Python-owned top-level QWidget
        top = QWidget()
        lay = QVBoxLayout(top)
        tree = QTreeWidget()
        lay.addWidget(tree)
        stack = QStackedWidget()
        lay.addWidget(stack)
        for i in range(3):
            p = QWidget()
            QVBoxLayout(p).addWidget(QPushButton(f"b{i}"))
            stack.addWidget(p)
        lab = QLabel("x", top)
        h.top = top
        h.tree = tree
        h.view = lab
        top.show()
        h.timer = QTimer()  # parentless QTimer, Python-owned
        # (no lambda connect: a C++-held callable would make the cycle immortal, not garbage)
        h.timer.start(10)


gc.collect()
gc.disable()
make_garbage()
# event loop runs (like qtbot.wait)
loop = QEventLoop()
QTimer.singleShot(60, loop.quit)
loop.exec()
print("loop done; garbage in cycles; gc.collect would find", gc.collect(0) if False else "?", flush=True)


def alloc():
    junk = []
    for i in range(400_000):
        junk.append(([i], {i: i}))
        if len(junk) > 2000:
            junk.clear()


if mode == "main":
    n = gc.collect()
    print("main collected", n, flush=True)
elif mode == "thread":
    t = threading.Thread(target=lambda: print("thread collected", gc.collect(), flush=True))
    t.start()
    t.join()
    print("thread exited", flush=True)
elif mode == "auto":
    gc.enable()
    gc.set_threshold(700, 10, 10)
    t = threading.Thread(target=alloc)
    t.start()
    t.join()
    print(
        "alloc thread exited; gc.get_count()",
        gc.get_count(),
        "collections",
        gc.get_stats()[0]["collections"],
        flush=True,
    )
elif mode == "policy":
    assert not gc.isenabled()
    collected = []

    def tick():
        collected.append(gc.collect())
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    tm = QTimer()
    tm.timeout.connect(tick)
    tm.start(20)
    t = threading.Thread(target=alloc)
    t.start()
    loop2 = QEventLoop()
    QTimer.singleShot(300, loop2.quit)
    loop2.exec()
    t.join()
    print("policy: main collected", collected, "gc enabled", gc.isenabled(), flush=True)
else:
    raise SystemExit("bad mode")
loop = QEventLoop()
QTimer.singleShot(60, loop.quit)
loop.exec()
print("SURVIVED", mode, flush=True)
