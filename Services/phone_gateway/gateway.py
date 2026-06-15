"""PhoneGateway — HTTP-сервер приёма фото и слова с телефона.

Поднимает мини HTTP-сервер (stdlib, фоновый поток-демон). Хранит последний
принятый кадр и последнее слово под блокировкой. Потребитель (плагин-мост)
забирает их методами take_frame() / word_snapshot().

Эндпоинты:
    GET  /         -> HTML-страница для телефона
    GET  /health   -> {"ok": true}
    POST /frame    -> сырые байты картинки -> decode -> latest_frame
    POST /word     -> текст UTF-8 -> latest_word

Сервер и потребитель работают в разных потоках одного процесса — доступ к
состоянию сериализован через self._lock.
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from Services.phone_gateway.imaging import MAX_UPLOAD_BYTES, decode_image
from Services.phone_gateway.web import render_page


class _Handler(BaseHTTPRequestHandler):
    """HTTP-обработчик. Делегирует приём в self.server.gateway."""

    protocol_version = "HTTP/1.1"

    # Глушим стандартный лог BaseHTTPRequestHandler (он пишет в stderr).
    def log_message(self, *args) -> None:  # noqa: D102
        return

    @property
    def _gw(self) -> "PhoneGateway":
        return self.server.gateway  # type: ignore[attr-defined]

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, obj: dict) -> None:
        import json

        self._send(code, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _read_body(self) -> bytes | None:
        """Прочитать тело запроса с лимитом размера. None если слишком большое."""
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return b""
        if length > MAX_UPLOAD_BYTES:
            return None
        return self.rfile.read(length)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", render_page().encode("utf-8"))
        elif self.path == "/health":
            self._send_json(200, {"ok": True})
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")

    def do_POST(self) -> None:  # noqa: N802
        body = self._read_body()
        if body is None:
            self._send_json(413, {"ok": False, "error": "файл слишком большой"})
            return
        if self.path == "/frame":
            self._send_json(200, self._gw.submit_frame(body))
        elif self.path == "/word":
            self._send_json(200, self._gw.submit_word(body.decode("utf-8", "replace")))
        else:
            self._send_json(404, {"ok": False, "error": "неизвестный эндпоинт"})


class PhoneGateway:
    """Сервер приёма фото/слова с телефона + хранилище последних значений."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080) -> None:  # nosec B104 — телефон подключается по LAN, bind на все интерфейсы намеренно
        self._host = host
        self._req_port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_seq = 0
        self._frame_ts = 0.0
        self._consumed_seq = 0  # последний seq, отданный в consume-режиме

        self._word = ""
        self._word_seq = 0
        self._word_ts = 0.0

    # --- Lifecycle ---

    def start(self) -> None:
        """Запустить HTTP-сервер в фоновом потоке-демоне (идемпотентно)."""
        if self._server is not None:
            return
        server = ThreadingHTTPServer((self._host, self._req_port), _Handler)
        server.daemon_threads = True
        server.gateway = self  # type: ignore[attr-defined]
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, name="phone-gateway", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Остановить сервер и освободить порт (идемпотентно)."""
        if self._server is None:
            return
        try:
            self._server.shutdown()
        finally:
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._server = None
        self._thread = None

    @property
    def port(self) -> int:
        """Фактический порт (актуально при port=0 — ОС выбирает свободный)."""
        if self._server is not None:
            return self._server.server_address[1]
        return self._req_port

    @property
    def running(self) -> bool:
        """Поднят ли сейчас HTTP-сервер."""
        return self._server is not None

    # --- Приём (вызывается из потока сервера) ---

    def submit_frame(self, data: bytes) -> dict:
        """Принять и декодировать кадр. {"ok",width,height,seq} или {"ok":False,error}."""
        img = decode_image(data)
        if img is None:
            return {"ok": False, "error": "не удалось декодировать изображение"}
        h, w = img.shape[:2]
        with self._lock:
            self._frame = img
            self._frame_seq += 1
            self._frame_ts = time.time()
            seq = self._frame_seq
        return {"ok": True, "width": int(w), "height": int(h), "seq": seq}

    def submit_word(self, text: str) -> dict:
        """Принять слово или фразу. {"ok",word,seq} или {"ok":False,error}.

        Внутренние пробелы сохраняются (можно передать несколько слов);
        крайние и повторяющиеся пробелы схлопываются (" ".join(split())).
        """
        word = " ".join((text or "").split())
        if not word:
            return {"ok": False, "error": "пустое слово"}
        with self._lock:
            self._word = word
            self._word_seq += 1
            self._word_ts = time.time()
            seq = self._word_seq
        return {"ok": True, "word": word, "seq": seq}

    # --- Потребление (вызывается из потока плагина) ---

    def take_frame(self, consume: bool = False) -> np.ndarray | None:
        """Последний кадр (BGR). При consume=True — один раз на каждую загрузку."""
        with self._lock:
            if self._frame is None:
                return None
            if consume:
                if self._consumed_seq == self._frame_seq:
                    return None
                self._consumed_seq = self._frame_seq
            return self._frame

    def word_snapshot(self) -> dict:
        """Снимок последнего слова: {"word","seq","ts"}."""
        with self._lock:
            return {"word": self._word, "seq": self._word_seq, "ts": self._word_ts}

    def frame_info(self) -> dict:
        """Метаданные последнего кадра: {"seq","ts","has_frame"}."""
        with self._lock:
            return {
                "seq": self._frame_seq,
                "ts": self._frame_ts,
                "has_frame": self._frame is not None,
            }
