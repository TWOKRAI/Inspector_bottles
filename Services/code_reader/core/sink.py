# -*- coding: utf-8 -*-
"""Приём результатов чтения по TCP.

Считыватель настроен как `TCP Client` — подключается к нам сам и держит
соединение открытым, отправляя по пакету на каждое срабатывание триггера.
Значит принимающая сторона (мы) — сервер.

Почему именно так, а не наоборот: при недоступности сервера прибор умеет
копить результаты (`Output Result Buffer`) и досылать их после восстановления
связи. В обратной схеме этот буфер не работает.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable

from Services.code_reader.core.result import ReadResult, parse_packet, split_stream


def _set_exclusive_bind(server: socket.socket) -> None:
    """Запретить чужому слушателю делить наш порт.

    На Windows `SO_REUSEADDR` разрешает ДВА живых слушателя на одном порту, и
    ядро отдаёт соединение одному из них — bind проходит молча, а кодов нет.
    Ровно это и случилось на стенде 2026-09-28: забытый `tools/id3000_tcp_sink.py`
    держал 5000, рецепт «успешно» занял тот же порт и не получил ни одного пакета.
    Правильный флаг Windows — `SO_EXCLUSIVEADDRUSE`: занятый порт даёт `OSError`,
    и вызывающий видит причину.

    На POSIX `SO_REUSEADDR` двойного слушателя не даёт (только переиспользование
    адреса в TIME_WAIT) и нужен для быстрого перезапуска — там он и остаётся.
    """
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if exclusive is not None:
        server.setsockopt(socket.SOL_SOCKET, exclusive, 1)
    else:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)


ResultHandler = Callable[[ReadResult], None]
ClientHandler = Callable[[int], None]
"""Уведомление о смене числа подключённых приборов (0 = связи нет)."""


class ResultSink:
    """TCP-сервер, разбирающий поток считывателя в `ReadResult`.

    Обработчик вызывается в потоке соединения, не в вызывающем — если он
    трогает общее состояние, синхронизация на стороне вызывающего.
    """

    def __init__(
        self,
        handler: ResultHandler,
        host: str = "0.0.0.0",  # nosec B104 — прибор подключается из сети линии, слушаем все интерфейсы намеренно
        port: int = 5000,
        *,
        terminator: str = ";",
        prefix: str = "",
        no_code_text: str = "NoRead",
        bad_code_text: str | None = None,
        backlog: int = 4,
        on_client: ClientHandler | None = None,
    ) -> None:
        self._handler = handler
        self._on_client = on_client
        self._host = host
        self._port = port
        self._parse_kwargs = {
            "terminator": terminator,
            "prefix": prefix,
            "no_code_text": no_code_text,
            "bad_code_text": bad_code_text,
        }
        self._backlog = backlog
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._clients = 0
        self._clients_lock = threading.Lock()

    @property
    def port(self) -> int:
        """Фактический порт — осмыслен после start(), если запрошен порт 0."""
        if self._server is None:
            return self._port
        return self._server.getsockname()[1]

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def client_count(self) -> int:
        """Сколько приборов держат соединение прямо сейчас.

        Прибор в режиме `TCP Client` подключается сам и соединение не рвёт,
        поэтому ноль при запущенном приёме означает «связи с прибором нет» —
        единственный честный признак обрыва на нашей стороне.
        """
        return self._clients

    def start(self) -> None:
        """Поднять сервер и слушать в фоновом потоке."""
        if self.is_running:
            raise RuntimeError("ResultSink уже запущен")
        self._stop.clear()
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _set_exclusive_bind(server)
        server.bind((self._host, self._port))
        server.listen(self._backlog)
        server.settimeout(0.2)  # чтобы stop() не ждал следующего клиента
        self._server = server
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Остановить приём и закрыть слушающий сокет."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        if self._server is not None:
            self._server.close()
            self._server = None

    def __enter__(self) -> ResultSink:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    def _accept_loop(self) -> None:
        assert self._server is not None
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _count_client(self, delta: int) -> None:
        """Изменить счётчик соединений и уведомить подписчика."""
        with self._clients_lock:
            self._clients = max(0, self._clients + delta)
            count = self._clients
        if self._on_client is not None:
            self._on_client(count)

    def _serve(self, conn: socket.socket) -> None:
        self._count_client(+1)
        try:
            self._read_loop(conn)
        finally:
            self._count_client(-1)

    def _read_loop(self, conn: socket.socket) -> None:
        buffer = b""
        with conn:
            conn.settimeout(0.2)
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buffer += chunk
                packets, buffer = split_stream(buffer, self._parse_kwargs["terminator"])
                for packet in packets:
                    self._handler(parse_packet(packet, **self._parse_kwargs))
