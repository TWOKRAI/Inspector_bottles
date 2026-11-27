"""Слепая приёмка задачи 2.6: окно заставки и причины закрытия (``splash.window``).

Написано до реализации по ``tasks/2.6.md`` (DESIGN п.6, REDS). Только ``offscreen``, свои сокеты
``127.0.0.1:0``. ``poll()`` зовётся из Qt-потока (тестового); цикл событий не крутится, чтобы внутренний
таймер реализации не забрал ответ ``poll()`` у теста.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

_APP: list = []  # ссылка на QApplication на всё время модуля

_BOOT_50 = b'{"id": "boot", "percent": 50, "label": "", "done": false}'
_GUI_DONE = b'{"id": "gui", "percent": 100, "label": "", "done": true}'


@pytest.fixture
def offscreen_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    _APP.append(app)
    assert app.platformName() == "offscreen"
    return app


def test_controller_close_reasons(offscreen_app):
    from PySide6.QtCore import Qt

    from multiprocess_prototype.splash.window import SplashController, SplashWindow

    sockets: list = []
    windows: list = []
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _controller(timeout_s: float):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sockets.append(sock)
        sock.bind(("127.0.0.1", 0))
        window = SplashWindow()
        windows.append(window)
        controller = SplashController(window, sock, timeout_s=timeout_s)
        # Раньше первого poll(): блокирующий сокет повесил бы прогон, а не уронил тест.
        assert sock.getblocking() is False
        return controller, window, sock.getsockname()

    try:
        controller, window, address = _controller(60.0)

        sender.sendto(b"x", address)
        time.sleep(0.2)
        assert controller.poll() is None

        sender.sendto(_BOOT_50, address)
        deadline = time.monotonic() + 5.0
        while window.percent() != 25 and time.monotonic() < deadline:
            assert controller.poll() is None
            time.sleep(0.02)
        assert window.percent() == 25

        sender.sendto(_GUI_DONE, address)
        deadline = time.monotonic() + 5.0
        reason = controller.poll()
        while reason is None and time.monotonic() < deadline:
            time.sleep(0.02)
            reason = controller.poll()
        assert reason == "gui_done"

        controller, window, _address = _controller(60.0)
        assert controller.poll() is None
        thread = threading.Thread(target=controller.request_close, args=("parent_gone",), daemon=True)
        thread.start()
        thread.join(5.0)
        assert not thread.is_alive(), "request_close из другого потока не вернулся за 5 с"
        assert controller.poll() == "parent_gone"

        controller, window, _address = _controller(0.0)
        assert controller.poll() == "timeout"

        assert not (window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) is True
    finally:
        for window in windows:
            window.close()
            window.deleteLater()
        for sock in sockets:
            sock.close()
        sender.close()
