# -*- coding: utf-8 -*-
"""``MjpegSinkPlugin`` — раздаёт последний принятый кадр как HTTP MJPEG-поток.

Обычный sink-плагин ``ProcessModulePlugin`` (форма — как у
``Plugins/sim/robot_host/plugin.py``, Task 1.1): ``configure(ctx)`` разбирает
конфиг и заводит состояние БЕЗ сети, ``start(ctx)`` поднимает HTTP-сервер,
``shutdown(ctx)`` глушит симметрично. Лист цепочки процесса ``camera``
(после ``camera_service`` — Task 1.2a): вход ``frame`` (``image/bgr``),
выходов нет.

**Отказ старта — состояние, а не падение процесса**, тот же приём, что у
``SimRobotHostPlugin._fail``: занятый порт ловится, уходит в
``ctx.health.report_error(...)``, ``_state = "error"``, ``start()`` наружу
не бросает.

**Порт занят — обнаруживается СИНХРОННО самим конструктором сервера, БЕЗ
пробного bind'а.** В отличие от ``SimRobotServer``/``pymodbus`` (см.
докстринг ``robot_host/plugin.py`` — тот бросает фоновым потоком), stdlib
``http.server`` иначе устроен: ``socketserver.TCPServer.__init__`` с
``bind_and_activate=True`` (дефолт) зовёт ``self.server_bind()`` и
``self.server_activate()`` СИНХРОННО в вызывающем потоке и уже там кидает
``OSError`` при занятом порту (плюс сам закрывает открытый сокет в
``except`` до ре-рейза) — проверено чтением ``cpython/Lib/socketserver.py``
(``TCPServer.__init__``), не предположено. Поэтому ``_start_server`` просто
оборачивает конструктор ``ThreadingHTTPServer(...)`` в ``try/except OSError``
— отдельного пробного сокета, в отличие от ``robot_host``, здесь не нужно.

**Поток сервера — чужой поток.** ``process()`` зовётся со штатного потока
плагина, а HTTP-обработчик (``do_GET``) — с потока, который для каждого
соединения создаёт ``ThreadingHTTPServer`` (``socketserver.ThreadingMixIn``,
``daemon_threads = True`` по умолчанию у ``ThreadingHTTPServer`` — сам класс
это выставляет). Последний закодированный кадр и его порядковый номер живут
ОДНИМ полем — кортежем ``_latest = (jpeg, seq)``: писатель собирает новый
кортеж и перепривязывает одну ссылку, читатель берёт ссылку один раз. Пара
согласована по построению — рассогласовать нечего, лок не нужен. (Раньше тут
были два поля под ``threading.Lock``; заявленное локом свойство — атомарность
пары — воспроизвести не удалось ни с ним, ни без, см. OPEN_QUESTIONS.md; одно
поле снимает и лок, и вопрос.) Писатель один — штатный поток ``process()``,
поэтому чтение-приращение ``seq`` гонок не имеет. ``ctx.record_metric``/``ctx.log_*`` с потока
сервера НЕ зовутся (нет гарантии межпотокового вызова у фасада — тот же
довод, что в докстринге ``robot_host``); обработчик доступа к ``ctx`` не
имеет вовсе, только к ``self`` (плагину) через замыкание фабрики
``_build_handler``.

**Кадра ещё нет — соединение закрывается штатно, без границы.** ``do_GET``
шлёт заголовки (200 + ``Content-Type: multipart/x-mixed-replace;
boundary=...``), затем проверяет текущий кадр; если кадра ещё нет —
обработчик просто возвращается (``return``), что при дефолтном
``protocol_version = "HTTP/1.0"`` у ``BaseHTTPRequestHandler`` закрывает
TCP-соединение штатно (EOF клиенту), без multipart-части и без исключения.
Никакого поллинга/ожидания первого кадра внутри обработчика нет — иначе
клиент с коротким socket-таймаутом получил бы ``socket.timeout``, а не
пустой, но валидный ответ.

**``shutdown()`` не обрывает уже открытые потоковые соединения.**
``server.shutdown()`` останавливает только цикл ``serve_forever()`` (accept
новых соединений), ``server_close()`` закрывает только слушающий сокет — оба
возвращаются за ограниченное время (``poll_interval`` у ``serve_forever``,
дефолт 0.5с). Поток УЖЕ принятого соединения, который крутится в
``do_GET``, них не трогают: он продолжает поллить ``_get_frame()`` и писать
кадры, пока клиент не отключится сам (или запись не упадёт с
``BrokenPipeError``/``ConnectionResetError``). Это daemon-поток
(``daemon_threads = True``), так что он не держит процесс — но ресурс
(поток) переживает ``shutdown()`` до дисконнекта клиента. Известное
ограничение, не исправлено в рамках Task 1.2b (потребовало бы отслеживать и
принудительно закрывать сокеты каждого соединения — вне минимального объёма
задачи); см. ``STATUS.md``.
"""

from __future__ import annotations

import http.server
import threading
import time
from typing import Any

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)

#: Дефолты конфига (Task 1.2 плана line-sim; порт 8091 — стенд apps/line_sim).
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8091
_DEFAULT_JPEG_QUALITY = 80
#: 0 — без троттлинга, раздаём каждый принятый кадр.
_DEFAULT_FPS_CAP = 0.0
_BOUNDARY = "mjpegsinkboundary"
#: Пауза цикла обработчика между проверками нового кадра (сек).
_POLL_INTERVAL_SEC = 0.01


def _build_handler(sink: "MjpegSinkPlugin") -> type[http.server.BaseHTTPRequestHandler]:
    """Фабрика класса-обработчика, замкнутого на конкретный экземпляр плагина.

    ``socketserver`` создаёт обработчик на КАЖДОЕ соединение сам
    (``RequestHandlerClass(request, client_address, server)``) — доступа к
    ``self`` плагина у него нет, кроме как через замыкание.
    """

    class _MjpegHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - сигнатура stdlib
            """Подавить дефолтный access-лог в stderr (не наш log-разъём)."""

        def do_GET(self) -> None:  # noqa: N802 - имя метода задано stdlib
            try:
                self.send_response(200)
                self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={_BOUNDARY}")
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

            last_seq = -1
            while True:
                frame, seq = sink._get_frame()
                if frame is None:
                    # Кадра ещё нет: закрыть соединение штатно, границ не слать
                    # (см. докстринг модуля).
                    return
                if seq == last_seq:
                    time.sleep(_POLL_INTERVAL_SEC)
                    continue
                last_seq = seq
                try:
                    self.wfile.write(f"--{_BOUNDARY}\r\n".encode("ascii"))
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return

    return _MjpegHandler


@register_plugin("mjpeg_sink", category="sink", description="HTTP MJPEG-раздача последнего кадра (сим-камера)")
class MjpegSinkPlugin(ProcessModulePlugin):
    """Sink-плагин: кодирует принятые кадры в JPEG и раздаёт multipart по HTTP."""

    name = "mjpeg_sink"
    category = "sink"

    inputs: list = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Кадр для MJPEG-раздачи"),
    ]
    outputs: list = []

    commands: dict = {}

    def configure(self, ctx: PluginContext) -> None:
        """READY: разобрать конфиг, завести состояние. Сеть здесь не трогаем."""
        self._ctx = ctx
        cfg = ctx.config
        self._host: str = cfg.get("host", _DEFAULT_HOST)
        self._port: int = cfg.get("port", _DEFAULT_PORT)
        self._jpeg_quality: int = int(cfg.get("jpeg_quality", _DEFAULT_JPEG_QUALITY))
        self._fps_cap: float = float(cfg.get("fps_cap", _DEFAULT_FPS_CAP))
        self._min_interval: float = 1.0 / self._fps_cap if self._fps_cap > 0 else 0.0

        self._server: http.server.ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        #: (последний JPEG, его номер) — одно поле, см. докстринг модуля.
        self._latest: tuple[bytes | None, int] = (None, 0)
        self._last_encode_ts = 0.0
        self._state = "configured"
        self._reason = ""

        ctx.log_info(f"mjpeg_sink: конфиг принят, {self._host}:{self._port}, jpeg_quality={self._jpeg_quality}")

    def start(self, ctx: PluginContext) -> None:
        """RUNNING: поднять HTTP-сервер. Отказ (порт занят) не роняет процесс."""
        self._start_server(ctx)

    def shutdown(self, ctx: PluginContext) -> None:
        """STOPPED: остановить сервер симметрично ``start()``."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._server_thread is not None:
            self._server_thread.join(timeout=5.0)
            self._server_thread = None
        self._state = "stopped"
        ctx.log_info("mjpeg_sink: остановлен")

    # ------------------------------------------------------------------ #
    # Приём кадров
    # ------------------------------------------------------------------ #

    def process(self, items: list[dict]) -> list[dict]:
        """Закодировать кадр каждого item в JPEG и опубликовать как последний.

        Pass-through: items уходят дальше без мутации (сток последний в
        цепочке процесса ``camera``, но контракт ``process()`` не меняем).
        """
        for item in items:
            frame = item.get("frame")
            if frame is None:
                continue
            self._encode_and_store(frame)
        return items

    def _encode_and_store(self, frame: np.ndarray) -> None:
        """Закодировать кадр в JPEG (с троттлингом по ``fps_cap``) и опубликовать парой.

        ``cv2.imencode`` на ПУСТОМ массиве (например, ``shape=(0, 0, 3)``) не
        возвращает ``ok=False`` — бросает ``cv2.error`` (проверено: ``OpenCV
        4.13.0 ... Assertion failed) !_img.empty()``). На большинстве прочих
        «странных» форм (2D grayscale, 4 канала, float32) кодирует молча —
        ``ok=False`` тоже возможен, но не единственный отказ. Оба случая
        ловятся здесь: битый кадр не публикуется, прошлый валидный (если был)
        остаётся раздаваемым, исключение наружу не уходит.
        """
        now = time.monotonic()
        if self._min_interval and (now - self._last_encode_ts) < self._min_interval:
            return
        try:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality])
        except cv2.error:
            return
        if not ok:
            return
        self._last_encode_ts = now
        jpeg_bytes = buf.tobytes()
        self._latest = (jpeg_bytes, self._latest[1] + 1)

    def _get_frame(self) -> tuple[bytes | None, int]:
        """Последний кадр + его номер одной парой (зовётся с потока сервера)."""
        return self._latest

    # ------------------------------------------------------------------ #
    # Старт сервера
    # ------------------------------------------------------------------ #

    def _start_server(self, ctx: PluginContext) -> None:
        """Поднять ``ThreadingHTTPServer``. Живой сервер — no-op (повторный ``start``)."""
        if self._server is not None:
            return

        try:
            handler_cls = _build_handler(self)
            server = http.server.ThreadingHTTPServer((self._host, self._port), handler_cls)
        except OSError as exc:  # noqa: BLE001 - деградация, не отказ (см. докстринг модуля)
            self._fail(ctx, exc)
            return

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        self._server = server
        self._server_thread = thread
        self._state = "running"
        self._reason = ""
        ctx.log_info(f"mjpeg_sink: сервер поднят на {self._host}:{self._port}")

    def _fail(self, ctx: PluginContext, exc: Exception) -> None:
        """Перевести плагин в ``error``: факт в плоскость ошибок + голос, процесс живёт."""
        self._state = "error"
        self._reason = str(exc)
        ctx.health.report_error(exc, context="mjpeg_sink.start", host=self._host, port=self._port)
