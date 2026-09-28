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

#: Потолок буфера сборки одного соединения. Пакет прибора — десятки байт, так что
#: 64 КиБ недостижимы при согласованном терминаторе. Достижимы они при РАСХОЖДЕНИИ
#: (`Output Stop Text` прибора не совпадает с нашим `terminator`): тогда поток не
#: режется вообще и буфер растёт линейно по трафику. Замер ревью Ф2: 11 МБ входа →
#: 10,9 МБ в буфере, ноль пакетов, ноль ошибок. Потолок превращает эту немую утечку
#: в громкую: буфер сбрасывается, потеря считается, причина уходит в `on_error`.
_BUFFER_LIMIT = 64 * 1024

#: Сколько ждать поток соединения в `stop()`, прежде чем перестать ждать. Шаг чтения
#: 0,2 с, поэтому 1 с — пять шагов с запасом.
_JOIN_TIMEOUT = 1.0


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


def _enable_keepalive(conn: socket.socket, idle_sec: int = 10, interval_sec: int = 3) -> None:
    """Включить TCP-keepalive на принятом соединении.

    Прибор молчит между срабатываниями триггера, поэтому тишина в сокете —
    норма, и отличить «ждём следующий код» от «кабель выдернут» на прикладном
    уровне нечем: при физическом обрыве FIN не приходит, и соединение остаётся
    «живым» сколько угодно долго. Keepalive — единственный механизм, который эту
    разницу видит: ядро само шлёт пробы и рвёт мёртвое соединение, после чего
    `recv` даёт ошибку и счётчик подключений падает.

    Тонкости заданы намеренно короткими (штатные системные — десятки минут, на
    линии это вечность). На Windows интервалы задаются только через
    `SIO_KEEPALIVE_VALS`, на Linux — через `TCP_KEEP*`; где ни того, ни другого
    нет, остаётся сам флаг с системными таймингами.
    """
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    vals = getattr(socket, "SIO_KEEPALIVE_VALS", None)
    if vals is not None:  # Windows
        conn.ioctl(vals, (1, idle_sec * 1000, interval_sec * 1000))
        return
    for name, value in (
        ("TCP_KEEPIDLE", idle_sec),
        ("TCP_KEEPINTVL", interval_sec),
        ("TCP_KEEPCNT", 3),
    ):
        opt = getattr(socket, name, None)
        if opt is not None:
            conn.setsockopt(socket.IPPROTO_TCP, opt, value)


ResultHandler = Callable[[ReadResult], None]
ClientHandler = Callable[[int], None]
"""Уведомление о смене числа подключённых приборов (0 = связи нет)."""
ErrorHandler = Callable[[str], None]
"""Сообщение о потере данных или обрыве: текст для телеметрии, не исключение."""


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
        on_error: ErrorHandler | None = None,
        buffer_limit: int = _BUFFER_LIMIT,
    ) -> None:
        self._handler = handler
        self._on_client = on_client
        self._on_error = on_error
        self._host = host
        self._port = port
        self._parse_kwargs = {
            "terminator": terminator,
            "prefix": prefix,
            "no_code_text": no_code_text,
            "bad_code_text": bad_code_text,
        }
        self._backlog = backlog
        self._buffer_limit = buffer_limit
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        # Событие создаётся в start(), а не здесь: объект переиспользуем, и общий
        # на все запуски Event воскрешал бы потоки прошлого запуска (`_stop.clear()`
        # снимал стоп с потока, который уже должен был умереть).
        self._stop = threading.Event()
        self._stop.set()
        self._clients = 0
        self._clients_lock = threading.Lock()
        # Живые соединения: нужны, чтобы stop() закрыл их и дождался потоков, а не
        # возвращал управление, оставив позади поток, который потом перепишет
        # телеметрию (замер ревью Ф2: 15 прогонов из 30 давали «слушаем» при
        # погашенном приёме).
        self._conns: list[tuple[threading.Thread, socket.socket]] = []
        self._conns_lock = threading.Lock()

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
        поэтому ноль при запущенном приёме означает, что связи нет. Видит и
        чистый разрыв со стороны прибора (FIN), и физический обрыв — последний
        только потому, что на соединениях включён keepalive (`_enable_keepalive`);
        без него мёртвое соединение осталось бы в счётчике навсегда.
        """
        return self._clients

    def start(self) -> None:
        """Поднять сервер и слушать в фоновом потоке."""
        if self.is_running:
            raise RuntimeError("ResultSink уже запущен")
        self._stop = threading.Event()
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _set_exclusive_bind(server)
        try:
            server.bind((self._host, self._port))
            server.listen(self._backlog)
        except OSError:
            # Порт занят или нет прав: сокет закрываем сами, иначе при повторных
            # «start» из GUI они копятся до GC.
            server.close()
            raise
        server.settimeout(0.2)  # чтобы stop() не ждал следующего клиента
        self._server = server
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Остановить приём: закрыть слушающий сокет и все живые соединения.

        Возвращает управление, когда потоки соединений уже не могут ничего
        сообщить наружу — иначе доживающий поток перезаписывает телеметрию после
        того, как вызывающий объявил приём погашенным.
        """
        self._stop.set()
        # Порядок остановки: сначала разбудить соединения, потом дождаться потоков.
        # Быстрее не получается: поток приёма сидит в accept() с шагом 0,2 с, и на
        # Windows закрытие слушающего сокета из другого потока заблокированный accept
        # НЕ будит — замер 2026-09-28: 188 мс и с закрытием, и без. Поэтому stop()
        # стоит до одного шага чтения; на освобождение порта это не влияет (порт
        # свободен к возврату, проверено ревью Ф2), только на время команды.
        with self._conns_lock:
            conns = list(self._conns)
        for _thread, conn in conns:
            # shutdown, а не только close: разблокирует recv немедленно, не дожидаясь
            # следующего шага таймаута.
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        if self._server is not None:
            self._server.close()
            self._server = None
        for thread, _conn in conns:
            thread.join(_JOIN_TIMEOUT)

    def __enter__(self) -> ResultSink:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    def _accept_loop(self) -> None:
        server = self._server
        if server is None:
            return
        while not self._stop.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            thread = threading.Thread(target=self._serve, args=(conn,), daemon=True)
            with self._conns_lock:
                self._conns.append((thread, conn))
            thread.start()

    def _count_client(self, delta: int) -> None:
        """Изменить счётчик соединений и уведомить подписчика."""
        with self._clients_lock:
            self._clients = max(0, self._clients + delta)
            count = self._clients
        if self._on_client is not None:
            self._on_client(count)

    def _report(self, message: str) -> None:
        """Сообщить о потере данных или обрыве — в телеметрию, не исключением."""
        if self._on_error is not None:
            self._on_error(message)

    def _serve(self, conn: socket.socket) -> None:
        self._count_client(+1)
        try:
            self._read_loop(conn)
        finally:
            self._count_client(-1)
            with self._conns_lock:
                self._conns = [(thread, sock) for thread, sock in self._conns if sock is not conn]

    def _read_loop(self, conn: socket.socket) -> None:
        buffer = b""
        with conn:
            try:
                _enable_keepalive(conn)
            except OSError as exc:
                # Не критично: без keepalive приём работает, но физический обрыв
                # станет невидимым — об этом надо сказать, а не проглотить.
                self._report(f"keepalive не включён: {exc}")
            conn.settimeout(0.2)
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    continue
                except OSError as exc:
                    self._report(self._loss_message(buffer, f"обрыв соединения: {exc}"))
                    break
                if not chunk:
                    if buffer:
                        self._report(self._loss_message(buffer, "прибор закрыл соединение"))
                    break
                buffer += chunk
                packets, buffer = split_stream(buffer, self._parse_kwargs["terminator"])
                for packet in packets:
                    self._handler(parse_packet(packet, **self._parse_kwargs))
                if len(buffer) > self._buffer_limit:
                    # Терминатор не встретился на протяжении всего потолка — почти
                    # наверняка `Output Stop Text` прибора не тот, что у нас.
                    self._report(
                        f"терминатор {self._parse_kwargs['terminator']!r} не встречен "
                        f"в {len(buffer)} Б потока — буфер сброшен; сверь "
                        f"`Output Stop Text` прибора с настройкой приёма"
                    )
                    buffer = b""

    @staticmethod
    def _loss_message(buffer: bytes, reason: str) -> str:
        """Текст об обрыве с ценой: сколько недособранных байт потеряно."""
        if not buffer:
            return reason
        return f"{reason}; потерян недособранный хвост {len(buffer)} Б"


__all__ = ["ResultSink", "ResultHandler", "ClientHandler", "ErrorHandler"]
