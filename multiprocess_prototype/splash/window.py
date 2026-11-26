"""Процесс заставки: окно со шкалой. Запуск — ``python -m multiprocess_prototype.splash.window``.

Импортирует только stdlib, PySide6 и ``splash.protocol``: любой ``multiprocess_framework.*`` добавляет
около секунды до появления окна.

Протокол с лончером: первой строкой в stdout — номер UDP-порта (до импорта PySide6); stdin — «верёвка
жизни» (EOF = лончера больше нет); дальше в stdout ничего, свои строки — в stderr.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import threading
import time
from collections.abc import Callable

_BOOT_SOCK: socket.socket | None = None
if __name__ == "__main__":
    # Порт уходит лончеру ДО тяжёлого импорта PySide6 (иначе он ждал бы на ~150 мс дольше).
    _BOOT_SOCK = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _BOOT_SOCK.bind(("127.0.0.1", 0))
    os.write(1, f"{_BOOT_SOCK.getsockname()[1]}\n".encode("ascii"))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QVBoxLayout, QWidget  # noqa: E402

from multiprocess_prototype.splash.protocol import (  # noqa: E402
    SPLASH_ORPHAN_EXIT_S,
    SPLASH_TIMEOUT_S,
    SplashScale,
    decode,
    is_close_signal,
)

_STAGE_TITLES = {"launch": "Подготовка рецепта", "boot": "Запуск процессов", "gui": "Загрузка интерфейса"}
_POLL_MS = 50
#: Потолок датаграмм за один такт: поток чужих посылок не должен вешать цикл событий.
_DRAIN_LIMIT = 256


class SplashWindow(QWidget):
    """Окно заставки. Не поверх всех окон (иначе накрыло бы диалог входа) и не отбирает фокус."""

    def __init__(self, title: str = "Inspector Bottles") -> None:
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle(title)
        self._scale = SplashScale()
        self._stage = ""
        self._detail = ""
        self._created = time.monotonic()
        #: Окно закрыли (Alt+F4, ``close()``). Qt у SplashScreen сам цикл событий не завершает.
        self.on_close: Callable[[], None] | None = None

        heading = QLabel(title, self)
        heading.setStyleSheet("font-size: 18px; font-weight: bold;")
        self._stage_label = QLabel("", self)
        self._bar = QProgressBar(self)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._detail_label = QLabel("", self)
        self._elapsed_label = QLabel("0 с", self)
        self._elapsed_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        for label in (heading, self._stage_label, self._detail_label, self._elapsed_label):
            label.setTextFormat(Qt.TextFormat.PlainText)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 12)
        for widget in (heading, self._stage_label, self._bar, self._detail_label, self._elapsed_label):
            layout.addWidget(widget)
        self.setFixedWidth(420)

    def closeEvent(self, event) -> None:  # noqa: N802 — имя Qt
        if self.on_close is not None:
            self.on_close()
        super().closeEvent(event)

    def apply(self, message: dict) -> None:
        """Pre: ``message`` — выход ``decode``. Неизвестный ``id`` меняет только строку подписи."""
        self._bar.setValue(self._scale.feed(message))
        title = _STAGE_TITLES.get(message["id"])
        if title is not None:
            self._stage = title
        self._detail = message["label"]
        self._stage_label.setText(self._stage)
        self._detail_label.setText(self._detail)

    def percent(self) -> int:
        return self._scale.percent

    def label_text(self) -> str:
        """Заголовок этапа и подпись листа (двумя строками, пустые опущены)."""
        return "\n".join(part for part in (self._stage, self._detail) if part)

    def refresh_elapsed(self) -> None:
        self._elapsed_label.setText(f"{int(time.monotonic() - self._created)} с")


class SplashController:
    """Владелец причины закрытия: запрошенная, затем ``gui_done``, затем ``timeout``."""

    def __init__(self, window: SplashWindow, sock: socket.socket, timeout_s: float = SPLASH_TIMEOUT_S) -> None:
        sock.setblocking(False)
        self._window = window
        self._sock = sock
        self._timeout_s = timeout_s
        self._started = time.monotonic()
        # RLock: обработчик SIGINT исполняется в главном потоке и может прийти, пока тот держит замок.
        self._lock = threading.RLock()
        self._requested: str | None = None
        self._gui_done = False
        window.on_close = lambda: self.request_close("window_closed")

    def request_close(self, reason: str) -> None:
        """Любой поток. Только флаг; первая причина выигрывает."""
        with self._lock:
            if self._requested is None:
                self._requested = reason

    def poll(self) -> str | None:
        """Только Qt-поток: дренирует сокет в окно и возвращает причину закрытия или ``None``."""
        with self._lock:
            requested = self._requested
        if requested is not None:
            return requested
        self._drain()
        if self._gui_done:
            return "gui_done"
        if time.monotonic() - self._started >= self._timeout_s:
            return "timeout"
        return None

    def _drain(self) -> None:
        for _ in range(_DRAIN_LIMIT):
            try:
                data = self._sock.recv(65535)
            except OSError:  # BlockingIOError — очередь пуста
                return
            message = decode(data)
            if message is None:
                continue
            self._window.apply(message)
            if is_close_signal(message):
                self._gui_done = True


def _lifeline(controller: SplashController, finished: threading.Event) -> None:
    """EOF на stdin = лончер умер. Только ``os.read``: поток в ``sys.stdin.read`` роняет выход интерпретатора.

    Штатно уходит Qt-поток (по ``request_close``). Не успел за ``SPLASH_ORPHAN_EXIT_S`` — он завис, а
    гасить осиротевший процесс больше некому.
    """
    try:
        while os.read(0, 1):
            pass
    except OSError:
        pass  # нет stdin — то же самое, что «родителя нет»
    controller.request_close("parent_gone")
    if not finished.wait(SPLASH_ORPHAN_EXIT_S):
        os._exit(0)


def _say(text: str) -> None:
    try:
        print(text, file=sys.stderr, flush=True)
    except (OSError, ValueError, AttributeError):
        pass  # консоли уже нет (лончер умер) — писать некуда


def main(argv: list[str] | None = None, *, sock: socket.socket | None = None) -> int:
    """Показать заставку и дождаться причины закрытия. ``sock=None`` — забиндить свой (тесты)."""
    parser = argparse.ArgumentParser(prog="splash")
    parser.add_argument("--title", default="Inspector Bottles")
    args, _unknown = parser.parse_known_args(argv)

    own_sock = sock is None
    if sock is None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))

    app = QApplication.instance() or QApplication([sys.argv[0]])
    window = SplashWindow(args.title)
    controller = SplashController(window, sock)
    started = time.monotonic()
    reasons: list[str] = []

    def _tick() -> None:
        window.refresh_elapsed()
        reason = controller.poll()
        if reason is not None and not reasons:
            reasons.append(reason)
            app.quit()

    finished = threading.Event()  # main() дошёл до конца: принудительный выход не нужен
    previous_sigint = None
    if threading.current_thread() is threading.main_thread():
        previous_sigint = signal.signal(signal.SIGINT, lambda *_: controller.request_close("sigint"))
    lifeline_args = (controller, finished)
    threading.Thread(target=_lifeline, args=lifeline_args, name="splash-lifeline", daemon=True).start()
    timer = QTimer(window)
    timer.timeout.connect(_tick)
    try:
        window.show()
        screen = window.screen()
        if screen is not None:
            window.move(screen.availableGeometry().center() - window.rect().center())
        QTimer.singleShot(0, lambda: _say("[splash] shown"))  # первый оборот цикла: окно уже на экране
        timer.start(_POLL_MS)
        app.exec()
    finally:
        timer.stop()
        window.close()
        if previous_sigint is not None:
            signal.signal(signal.SIGINT, previous_sigint)
        if own_sock:
            sock.close()
        finished.set()
    reason = reasons[0] if reasons else "window_closed"
    _say(f"[splash] closed reason={reason} after {time.monotonic() - started:.1f} s percent={window.percent()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sock=_BOOT_SOCK))
