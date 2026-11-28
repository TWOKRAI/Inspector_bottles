"""Слепая приёмка задачи 2.14 (C-130): таймаут заставки считается от последнего роста шкалы.

Написано до реализации по ``tasks/2.14.md`` (Goal, Факты, DESIGN, REDS). Настоящие ``SplashWindow``
(offscreen) и ``SplashController`` со своим UDP-сокетом ``127.0.0.1:0``. Время подменяется атрибутом
``time`` модуля ``splash.window`` (DESIGN п.5), реальных ожиданий нет. Секунды в тестах считаются от
создания контроллера; моментом роста считается тот ``poll()``, который вычитал посылку.
"""

from __future__ import annotations

import select
import socket

import pytest

from multiprocess_prototype.splash import protocol

_APP: list = []  # ссылка на QApplication на всё время модуля

_START = 1000.0  # показание подменных часов в момент создания контроллера
_DELIVERY_WAIT_S = 5.0  # предел ожидания доставки датаграммы по loopback (настоящее время)
_GARBAGE = b"x"


class _Clock:
    """Подменные часы вместо модуля ``time`` в ``splash.window``."""

    def __init__(self) -> None:
        self.now = _START

    def monotonic(self) -> float:
        return self.now


class _Stand:
    """Окно, контроллер, сокеты и часы одного теста."""

    def __init__(self, clock: _Clock, window, controller, sock: socket.socket, sender: socket.socket) -> None:
        self.clock = clock
        self.window = window
        self.controller = controller
        self.sock = sock
        self.sender = sender

    def send(self, payload: bytes) -> None:
        """Отправить датаграмму и дождаться, пока она ляжет в сокет контроллера."""
        self.sender.sendto(payload, self.sock.getsockname())
        readable, _, _ = select.select([self.sock], [], [], _DELIVERY_WAIT_S)
        assert readable, "датаграмма не доставлена"

    def poll_at(self, second: float) -> str | None:
        """``poll()`` на указанной секунде от создания контроллера."""
        self.clock.now = _START + second
        return self.controller.poll()

    def poll_consumed_at(self, second: float) -> str | None:
        """``poll()`` и проверка, что он вычитал всё лежавшее в сокете (иначе ``None`` ничего не значит)."""
        reason = self.poll_at(second)
        readable, _, _ = select.select([self.sock], [], [], 0)
        assert not readable, "poll() не вычитал посылку из сокета"
        return reason


def _leaf(progress_id: str, percent: int, done: bool = False) -> bytes:
    return protocol.encode(progress_id, {"percent": percent, "done": done})


@pytest.fixture
def make_stand(monkeypatch):
    """Фабрика стенда; ``timeout_s=None`` — контроллер строится без аргумента ``timeout_s``."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from multiprocess_prototype.splash import window as window_module

    app = QApplication.instance() or QApplication([])
    _APP.append(app)
    assert app.platformName() == "offscreen"

    opened: list = []

    def _make(timeout_s: float | None = 10.0) -> _Stand:
        # Часы подменяются раньше создания окна и контроллера.
        clock = _Clock()
        monkeypatch.setattr(window_module, "time", clock)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        opened.extend([sock, sender])
        sock.bind(("127.0.0.1", 0))
        window = window_module.SplashWindow()
        opened.append(window)
        if timeout_s is None:
            controller = window_module.SplashController(window, sock)
        else:
            controller = window_module.SplashController(window, sock, timeout_s=timeout_s)
        # Блокирующий сокет повесил бы прогон на первом poll(), а не уронил тест.
        assert sock.getblocking() is False
        return _Stand(clock, window, controller, sock, sender)

    yield _make

    for item in opened:
        item.close()
        if not isinstance(item, socket.socket):
            item.deleteLater()


def test_r1_growth_restarts_the_timeout_count(make_stand):
    stand = make_stand()

    stand.send(_leaf("boot", 20))
    assert stand.poll_consumed_at(8) is None
    assert stand.window.percent() == 10

    assert stand.poll_at(17) is None
    assert stand.poll_at(18.5) == "timeout"


def test_r2_postings_without_growth_do_not_move_the_count(make_stand):
    stand = make_stand()

    stand.send(_leaf("boot", 20))
    assert stand.poll_consumed_at(1) is None
    assert stand.window.percent() == 10

    for second in (4, 7, 10):
        # тот же процент, меньший процент, неизвестный id
        for payload in (_leaf("boot", 20), _leaf("boot", 10), _leaf("recipe_load", 90)):
            stand.send(payload)
            assert stand.poll_consumed_at(second) is None, f"секунда {second}, посылка {payload!r}"
            assert stand.window.percent() == 10

    assert stand.poll_at(11.5) == "timeout"


def test_r3_garbage_datagrams_do_not_move_the_count(make_stand):
    stand = make_stand()

    for second in (3, 6, 9):
        stand.send(_GARBAGE)
        assert stand.poll_consumed_at(second) is None, f"секунда {second}"

    assert stand.poll_at(10.5) == "timeout"


def test_r4_gui_done_after_long_silence_wins_over_timeout(make_stand):
    stand = make_stand()

    stand.send(_leaf("gui", 100, done=False))
    assert stand.poll_consumed_at(1) is None
    assert stand.window.percent() == 40

    # Тишина без единого poll() до 30-й секунды; посылка done не растит шкалу.
    stand.send(_leaf("gui", 100, done=True))
    assert stand.poll_at(30) == "gui_done"


def test_r5_pending_growth_is_counted_before_the_timeout_verdict(make_stand):
    stand = make_stand()

    stand.send(_leaf("boot", 20))
    assert stand.poll_consumed_at(12) is None
    assert stand.window.percent() == 10

    # Отсчёт идёт от poll(), вычитавшего посылку (12-я секунда): на 21,5-й прошло только 9,5 с.
    assert stand.poll_at(21.5) is None
    assert stand.poll_at(22.5) == "timeout"


def test_r6_splash_timeout_constant_is_180_seconds():
    assert protocol.SPLASH_TIMEOUT_S == 180.0


def test_r6_default_controller_times_out_after_180_seconds(make_stand):
    stand = make_stand(timeout_s=None)

    assert stand.poll_at(179) is None
    assert stand.poll_at(181) == "timeout"


def test_r7_without_any_posting_the_count_starts_at_creation(make_stand):
    stand = make_stand()

    assert stand.poll_at(9) is None
    assert stand.poll_at(10.5) == "timeout"


def test_r8_chain_of_growth_longer_than_timeout_keeps_splash_open(make_stand):
    stand = make_stand()

    steps = (
        (8, "launch", 100, 10),
        (16, "boot", 40, 30),
        (24, "boot", 100, 60),
        (32, "gui", 50, 80),
    )
    for second, progress_id, percent, total in steps:
        stand.send(_leaf(progress_id, percent))
        assert stand.poll_consumed_at(second) is None, f"секунда {second}"
        assert stand.window.percent() == total
