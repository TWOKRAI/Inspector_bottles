"""Сторона лончера: запустить процесс заставки, получить его порт, закрыть. Только stdlib.

Ни одна функция здесь не имеет права уронить или заметно задержать запуск приложения.

Держатель ``_holder`` — модульная ссылка на живой ``SplashLink``: собранный GC объект закрыл бы stdin
заставки, и она погасла бы посреди загрузки.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 — один запуск своей заставки: sys.executable и argv списком, без shell
import sys
import threading
import time
from collections.abc import Callable, Mapping, MutableMapping
from pathlib import Path

from multiprocess_prototype.splash.protocol import (
    SPLASH_PORT_ENV,
    SPLASH_PORT_WAIT_S,
    parse_port,
    send_leaf,
    splash_enabled,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WINDOW_MODULE = "multiprocess_prototype.splash.window"
_EXIT_WAIT_S = 1.0
_KILL_WAIT_S = 5.0
#: Ожидания в ветке «заставки не будет»: она на главном потоке лончера, запуск ждать не должен.
_URGENT_WAIT_S = 0.2
#: Переменные инструментов разработки, которые заставке не передаются. ``QT_MCP_PROBE`` через ``.pth`` ставит пробу
#: в любой Python-процесс с Qt: заставка заняла бы порт, и проба не досталась бы GUI.
_DEV_ONLY_ENV = ("QT_MCP_PROBE",)

_holder: SplashLink | None = None
_holder_lock = threading.Lock()


def _say(text: str) -> None:
    print(f"[run] заставка: {text}", file=sys.stderr)


def _exited(process: subprocess.Popen, timeout_s: float) -> bool:
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return False
    return True


def _shutdown(process: subprocess.Popen, reader: threading.Thread | None, *, urgent: bool = False) -> None:
    """Закрыть stdin -> ждать -> ``kill`` -> ``wait`` -> и только потом stdout.

    ``urgent`` — заставка не заработала: ``kill`` сразу, без паузы на добровольный выход, и каждое
    ожидание не дольше ``_URGENT_WAIT_S``.

    Порядок обязателен: закрытие трубы, на которой поток заблокирован в ``os.read``, на Windows виснет.
    Поэтому stdout закрывается, лишь когда поток чтения вышел; иначе труба остаётся открытой.
    """
    try:
        if process.stdin is not None:
            process.stdin.close()
    except OSError:
        pass  # ребёнок уже умер
    try:
        if urgent or not _exited(process, _EXIT_WAIT_S):
            process.kill()
            process.wait(timeout=_URGENT_WAIT_S if urgent else _KILL_WAIT_S)
    except Exception as exc:  # noqa: BLE001
        _say(f"процесс не погашен: {exc}")
    if reader is not None and reader.ident is not None:
        reader.join(timeout=_URGENT_WAIT_S if urgent else _EXIT_WAIT_S)
        if reader.is_alive():
            return
    try:
        if process.stdout is not None:
            process.stdout.close()
    except OSError:
        pass


class SplashLink:
    """Связь с одним процессом заставки; реализует ``SplashLinkProtocol``."""

    def __init__(self, process: subprocess.Popen, started: float) -> None:
        """``started`` — ``time.monotonic()`` перед запуском процесса (от него считается ожидание порта)."""
        self.process = process
        self._started = started
        self._lock = threading.Lock()  # порт, отложенный лист, closed
        self._port: int | None = None
        self._pending: dict | None = None
        self._closed = False
        self._read_over = threading.Event()  # поток чтения получил порт либо понял, что его не будет
        self._reader = threading.Thread(target=self._read_port, name="splash-port", daemon=True)

    def start_reader(self) -> None:
        self._reader.start()

    def _read_port(self) -> None:
        try:
            fd = self.process.stdout.fileno()
            data = b""
            while b"\n" not in data and len(data) <= 64:
                chunk = os.read(fd, 64)  # только по дескриптору: см. TRAPS задачи 2.6
                if not chunk:
                    return
                data += chunk
            line, newline, _rest = data.partition(b"\n")
            port = parse_port(line.decode("ascii", "replace")) if newline else None
            if port is None:
                return
            with self._lock:
                self._port = port
                if self._pending is not None and not self._closed:
                    self._send(self._pending)
                    self._pending = None
        except (OSError, ValueError, AttributeError):
            return  # трубы нет — порта нет
        finally:
            self._read_over.set()

    def _send(self, leaf: dict) -> None:
        send_leaf("launch", leaf, environ={SPLASH_PORT_ENV: str(self._port)})

    def report(self, leaf: Mapping) -> None:
        """Лист этапа ``launch``. Порта ещё нет — хранится только последний лист. Не бросает."""
        try:
            with self._lock:
                if self._closed:
                    return
                if self._port is None:
                    self._pending = dict(leaf)
                else:
                    self._send(dict(leaf))
        except Exception as exc:  # noqa: BLE001
            _say(f"лист этапа не отправлен: {exc}")

    def publish_port(self, environ: MutableMapping[str, str], wait_s: float = SPLASH_PORT_WAIT_S) -> bool:
        """Записать порт в ``environ`` (звать из главного потока до spawn системы). Не бросает.

        Порт уже получен -> ``True`` сразу; иначе ждать до ``wait_s`` от запуска процесса. Порта нет —
        заставка закрывается, ``environ`` не трогается.
        """
        try:
            if self._port is None:
                self._read_over.wait(max(0.0, self._started + wait_s - time.monotonic()))
            with self._lock:
                port, closed = self._port, self._closed
            if closed:
                return False
            if port is None:
                self._close(urgent=True)
                _say("порт не пришёл — без заставки")
                return False
            environ[SPLASH_PORT_ENV] = str(port)
        except Exception as exc:  # noqa: BLE001
            _say(f"порт не опубликован: {exc}")
            return False
        return True

    def close(self) -> None:
        """Погасить заставку и освободить держатель. Идемпотентно."""
        self._close(urgent=False)

    def _close(self, *, urgent: bool) -> None:
        global _holder
        with self._lock:
            if self._closed:
                return
            self._closed = True
        with _holder_lock:
            if _holder is self:
                _holder = None
        _shutdown(self.process, self._reader, urgent=urgent)


def start_splash(
    expected: bool,
    *,
    environ: MutableMapping[str, str],
    title: str,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> SplashLink | None:
    """Запустить процесс заставки; ``None`` — заставки не будет (не нужна, выключена или не запустилась).

    Живой держатель (ещё не закрытый) + заставка нужна -> тот же объект, ``environ`` не трогается.
    Во всех остальных случаях первым делом из ``environ`` снимается чужой порт.
    """
    global _holder
    process = None
    try:
        wanted = bool(expected) and splash_enabled(environ)
        with _holder_lock:
            if wanted and _holder is not None:
                return _holder
            environ.pop(SPLASH_PORT_ENV, None)
            if not wanted:
                return None
            started = time.monotonic()
            process = popen(
                [sys.executable, "-m", _WINDOW_MODULE, "--title", title],
                cwd=str(_PROJECT_ROOT),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                env={name: value for name, value in environ.items() if name not in _DEV_ONLY_ENV},
            )
            link = SplashLink(process, started)
            link.start_reader()
            _holder = link
            return link
    except Exception as exc:  # noqa: BLE001 — заставка не имеет права уронить запуск
        _say(f"не запущена ({type(exc).__name__}: {exc}) — без заставки")
        if process is not None:
            _shutdown(process, None, urgent=True)
        return None


def stop_splash() -> None:
    """Закрыть заставку из держателя, если она есть."""
    with _holder_lock:
        link = _holder
    if link is not None:
        link.close()
