"""Hazard-тесты по ревью 2.6 (итерация 1): задержка без порта, осиротевшая заставка, закрытое окно.

Настоящие дети — только свои; гасятся в ``finally``.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from multiprocess_prototype.splash import launcher

_ROOT = Path(__file__).resolve().parents[3]


def _call(fn, timeout: float = 20.0):
    box: dict = {}

    def _run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), f"вызов не вернулся за {timeout} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _env() -> dict:
    env = dict(os.environ, PYTHONPATH=str(_ROOT), QT_QPA_PLATFORM="offscreen")
    env.pop("INSPECTOR_SPLASH", None)
    env.pop("INSPECTOR_SPLASH_PORT", None)
    return env


def _timed_publish(link, env: dict) -> tuple[bool, float]:
    started = time.monotonic()
    result = link.publish_port(env)
    return result, time.monotonic() - started


@pytest.fixture(autouse=True)
def _clean_holder():
    launcher.stop_splash()
    yield
    launcher.stop_splash()


def test_publish_port_without_line_does_not_hold_main_thread() -> None:
    """Настоящий живой процесс без строки порта: потолок — 0,9 с (0,3 ожидания порта + добить без паузы)."""
    spawned: list = []

    def _popen(argv, **kwargs):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"], **kwargs)
        spawned.append(child)
        return child

    env = _env()
    try:
        link = _call(lambda: launcher.start_splash(True, environ=env, title="t", popen=_popen))
        result, elapsed = _call(lambda: _timed_publish(link, env))
        print(f"publish_port без порта: {elapsed:.3f} с")
        assert result is False
        assert elapsed < 0.9
        link._reader.join(5.0)
        assert not link._reader.is_alive()  # пишущих концов трубы не осталось: ребёнок погашен
        assert spawned[0].wait(timeout=5.0) is not None
    finally:
        for child in spawned:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5.0)


def test_publish_port_ceiling_when_child_does_not_die_even_after_kill() -> None:
    """Худший случай: ``wait`` не дожидается и после ``kill``, конец трубы жив. Потолок — 1,5 с."""
    events: list[str] = []
    read_fd, write_fd = os.pipe()

    class _Pipe:
        def __init__(self, name: str) -> None:
            self._name = name

        def fileno(self) -> int:
            return read_fd

        def close(self) -> None:
            events.append(f"{self._name}.close")

    class _Immortal:
        stdin = _Pipe("stdin")
        stdout = _Pipe("stdout")

        def wait(self, timeout: float | None = None) -> int:
            events.append("wait")
            time.sleep(30.0 if timeout is None else timeout)
            raise subprocess.TimeoutExpired("splash", timeout)

        def kill(self) -> None:
            events.append("kill")

    env: dict = {}
    try:
        link = launcher.start_splash(True, environ=env, title="t", popen=lambda *a, **k: _Immortal())
        result, elapsed = _call(lambda: _timed_publish(link, env))
        assert result is False
        assert elapsed < 1.5
        assert events == ["stdin.close", "kill", "wait"]  # stdout не закрыт: читатель ещё в os.read
    finally:
        os.close(write_fd)
        link._reader.join(5.0)
        os.close(read_fd)


def _spawn_main(patch: str) -> subprocess.Popen:
    """Настоящий ``window.main`` в отдельном процессе; ``patch`` ломает одно место до запуска."""
    code = (
        "import sys, time\n"
        "from PySide6.QtCore import QTimer\n"
        "from multiprocess_prototype.splash import window\n"
        f"{patch}\n"
        "sys.exit(window.main([]))\n"
    )
    return subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=str(_ROOT),
        env=_env(),
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _finish(child: subprocess.Popen) -> None:
    if child.poll() is None:
        child.kill()
        child.wait(timeout=5.0)
    for pipe in (child.stdin, child.stderr):
        if pipe is not None:
            pipe.close()


def _wait_shown(child: subprocess.Popen) -> None:
    def _read() -> None:
        while True:
            line = child.stderr.readline()
            assert line, "заставка вышла, не сказав shown"
            if line.strip() == b"[splash] shown":
                return

    _call(_read, timeout=30.0)


def test_orphan_with_blocked_qt_thread_exits_by_itself() -> None:
    """Qt-поток завис, лончер умер (EOF stdin) -> процесс выходит сам, кодом 0, через ~3 с."""
    child = _spawn_main("window.SplashController.poll = lambda self: time.sleep(60)")
    try:
        _wait_shown(child)
        time.sleep(0.5)  # такт таймера прошёл: Qt-поток уже висит в poll
        assert child.poll() is None
        started = time.monotonic()
        child.stdin.close()
        assert child.wait(timeout=10.0) == 0
        assert 2.0 < time.monotonic() - started < 8.0
        assert b"closed reason" not in child.stderr.read()  # вышел не штатной дорогой
    finally:
        _finish(child)


def test_closed_window_ends_the_process() -> None:
    """``window.close()`` (Alt+F4): окно скрыто -> процесс не остаётся жить до ``timeout``."""
    child = _spawn_main("window.SplashWindow.showEvent = lambda self, event: QTimer.singleShot(200, self.close)")
    try:
        assert child.wait(timeout=20.0) == 0
        assert b"[splash] closed reason=window_closed" in child.stderr.read()
    finally:
        _finish(child)


def test_close_event_reaches_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from multiprocess_prototype.splash.window import SplashController, SplashWindow

    app = QApplication.instance() or QApplication([])
    assert app.platformName() == "offscreen"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    window = None
    try:
        sock.bind(("127.0.0.1", 0))
        window = SplashWindow()
        controller = SplashController(window, sock)
        window.show()
        assert controller.poll() is None
        window.close()
        assert controller.poll() == "window_closed"
    finally:
        if window is not None:
            window.deleteLater()
        sock.close()
