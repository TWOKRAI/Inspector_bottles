"""Слепой контракт-тест пакета заставки (задача 2.6, «Публичные имена»).

Написано до реализации по ``tasks/2.6.md``. Только ``offscreen``, свои сокеты ``127.0.0.1:0``.
"""

from __future__ import annotations

import os
import socket
import subprocess
import threading

import pytest

_APP: list = []  # ссылка на QApplication на всё время модуля


def _call(fn, timeout: float = 20.0):
    """Вызов в daemon-потоке: зависание — падение с именем, а не стоящий прогон."""
    box: dict = {}

    def _run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # перебрасываем в тестовый поток
            box["error"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), f"вызов не вернулся за {timeout} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _reap(process) -> None:
    """Погасить порождённый тестом процесс (только его)."""
    if process is None or process.poll() is not None:
        return
    if process.stdin is not None:
        try:
            process.stdin.close()
        except OSError:
            pass
    try:
        process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5.0)


@pytest.fixture
def offscreen_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    _APP.append(app)
    assert app.platformName() == "offscreen"
    return app


def test_public_classes_satisfy_protocols(offscreen_app):
    from multiprocess_prototype.splash.interface import (
        LeafSender,
        SplashControllerProtocol,
        SplashLinkProtocol,
    )
    from multiprocess_prototype.splash.launcher import start_splash, stop_splash
    from multiprocess_prototype.splash.protocol import send_leaf
    from multiprocess_prototype.splash.window import SplashController, SplashWindow

    # Якорь: пустой Protocol принял бы что угодно и сделал бы проверки ниже вакуумными.
    assert not isinstance(object(), SplashLinkProtocol)
    assert not isinstance(object(), SplashControllerProtocol)
    assert not isinstance(object(), LeafSender)

    env = dict(os.environ)
    env.pop("INSPECTOR_SPLASH", None)
    env.pop("INSPECTOR_SPLASH_PORT", None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    process = None
    _call(stop_splash)
    try:
        link = _call(lambda: start_splash(True, environ=env, title="Inspector Bottles"))
        assert link is not None
        process = link.process
        assert isinstance(link, SplashLinkProtocol)
    finally:
        try:
            _call(stop_splash)
        finally:
            _reap(process)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    window = None
    try:
        sock.bind(("127.0.0.1", 0))
        window = SplashWindow()
        assert isinstance(SplashController(window, sock), SplashControllerProtocol)
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
        sock.close()

    assert isinstance(send_leaf, LeafSender)


def test_public_names_literals():
    import multiprocess_prototype.splash as splash
    from multiprocess_prototype.splash import interface, protocol

    assert protocol.SPLASH_ENV == "INSPECTOR_SPLASH"
    assert protocol.SPLASH_PORT_ENV == "INSPECTOR_SPLASH_PORT"
    assert protocol.SPLASH_WEIGHTS == {"launch": 10, "boot": 50, "gui": 40}
    assert protocol.SPLASH_TIMEOUT_S == 60.0
    assert protocol.SPLASH_PORT_WAIT_S == 0.3

    for name in ("SplashLinkProtocol", "SplashControllerProtocol", "LeafSender"):
        assert name in splash.__all__
        assert getattr(splash, name) is getattr(interface, name)
