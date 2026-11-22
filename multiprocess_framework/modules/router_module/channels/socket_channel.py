# -*- coding: utf-8 -*-
"""
SocketChannel — серверный TCP-канал (сиблинг QueueChannel).

Обычный IMessageChannel: делает ТОЛЬКО байтовый I/O на границе системы.
Регистрируется в RouterManager хоста через register_channel (by-design extension).
Без бизнес-логики — связь с router'ом делает on_inbound-колбэк (см. P2 дизайн §4).

Назначение: внешний тонкий driver (backend_ctl, dev-инструмент) подключается по TCP и
шлёт те же router-сообщения, что GUI по локальной очереди. Граница — ровно Claude↔driver.

Wire-формат: UTF-8, newline-delimited JSON, только dict. Кадры/SHM через сокет НЕ гоняем.

Направления:
  - INBOUND (driver → система): read-loop читает строки, json.loads → on_inbound(msg).
    Это push, не pull → poll() намеренно no-op (receive-цикл router'а канал не опрашивает).
  - OUTBOUND (система → driver): router зовёт send() через _resolve_channels(channel=name);
    JSON+"\n" пишется в клиентские сокеты под Lock.

Гейт/безопасность — на стороне хоста (BACKEND_CTL=1 + bind 127.0.0.1). С ``authenticator``
канал требует первой строкой ``hello`` с токеном (Task 0.12, ADR-RTR-017): до успеха
сокет не в ``_clients`` (рассылки не видит), строки до роутера не доходят. Без
``authenticator`` — как раньше: сокет зарегистрирован на accept; первая строка
``hello`` получает ответ и в ``on_inbound`` не идёт.
"""

from __future__ import annotations

import json
import select
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set

from multiprocess_framework.modules.logger_module import get_std_logger

from .base_channel import MessageChannel

_log = get_std_logger(__name__)

# ponytail: потолок 8 одновременных on_inbound на одно соединение; сверх него read-loop
# ждёт свободный слот (backpressure на сокет, TCP-окно отдаёт её клиенту). Поднять,
# если единственное мультиплексное соединение Пульта упрётся в него под нагрузкой.
_MAX_INFLIGHT_PER_CONNECTION = 8

# Сколько ждать слот за одну попытку: между попытками read-loop проверяет _running,
# чтобы close() не упирался в поток, застрявший на полном семафоре.
_INFLIGHT_ACQUIRE_POLL_SEC = 0.1

# Рукопожатие (Task 0.12): потолок первой строки до аутентификации; дочитывание после
# отказа (иначе непрочитанные байты дают RST и клиент теряет ответ) — не дольше и не больше.
_HELLO_MAX_BYTES = 4096
_DRAIN_AFTER_REJECT_SEC = 0.5
_DRAIN_AFTER_REJECT_BYTES = 65536
_REQUEST_ID_ECHO_MAX = 128
_HELLO_ACK = (json.dumps({"type": "hello", "success": True}) + "\n").encode("utf-8")


class SocketChannel(MessageChannel):
    """Серверный TCP-эндпоинт как IMessageChannel.

    Args:
        name: имя канала (= адрес для channel=-маршрутизации ответа, напр. "backend_ctl").
        host: bind-адрес (по умолчанию 127.0.0.1 — localhost-only).
        port: TCP-порт.
        on_inbound: колбэк(msg: dict) для каждого прочитанного сообщения. None → сообщения
            читаются и отбрасываются (канал работает, но никуда не передаёт).
        log_warning/log_error: инъекция логирования (или от RouterManager при регистрации).
        session_isolation: True → адресная доставка по session (D.1, Вариант A);
            False (default) → broadcast всем подключённым (back-compat).
        on_session_closed: колбэк(session_id) при РАЗРЫВЕ соединения этой сессии.
            Сигнал по факту, а не по догадке: подписчик, чей адрес построен из
            session, умирает вместе с сокетом, и держатель подписок должен узнать
            об этом от того, кто видел разрыв. Без такого сигнала мёртвые намерения
            копятся линейно по реконнектам (5.11-R1).
        max_line_bytes: потолок одной входящей строки (без ``\n``). Длиннее —
            строка отбрасывается целиком (WARNING один раз на строку), соединение
            живо, буфер не растёт выше потолка + одного recv-чанка (ADR-RTR-012).
        authenticator: ``Callable[[dict], bool]`` для первой строки соединения
            (``{"type": "hello", "token": ...}``, см. ``socket_auth.token_authenticator``).
            ``None`` → без рукопожатия (прежнее поведение). Сигнатура сменится в 2.2.
        hello_timeout_s: абсолютный дедлайн ``hello`` от accept; точность — таймаут recv
            (0.5 с). Pre: ``> 0``, иначе ``ValueError``.
    """

    def __init__(
        self,
        name: str,
        host: str = "127.0.0.1",
        port: int = 8765,
        on_inbound: Optional[Callable[[Dict[str, Any]], None]] = None,
        log_warning: Optional[Callable[[str], None]] = None,
        log_error: Optional[Callable[[str], None]] = None,
        session_isolation: bool = False,
        on_session_closed: Optional[Callable[[str], None]] = None,
        max_line_bytes: int = 1_048_576,
        authenticator: Callable[[Dict[str, Any]], bool] | None = None,
        hello_timeout_s: float = 5.0,
    ) -> None:
        if not hello_timeout_s > 0:
            raise ValueError(f"SocketChannel: hello_timeout_s должен быть > 0, получено {hello_timeout_s!r}")
        super().__init__(log_warning=log_warning, log_error=log_error)
        self._on_session_closed = on_session_closed
        self._max_line_bytes = max_line_bytes
        self._authenticator = authenticator
        self._hello_timeout_s = hello_timeout_s
        self._name = name
        self._host = host
        self._port = port
        self._on_inbound = on_inbound
        # D.1 (Вариант A): при True send() адресует одному соединению по session,
        # а _handle_line ведёт маппинг session→сокет. При False — прежний broadcast
        # (default, back-compat). Гейт задаёт endpoint по config/env.
        self._session_isolation = session_isolation

        self._server_sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._running = False
        self._bound = False

        # Клиентские соединения + лок на запись (fan-out ответов всем подключённым).
        self._clients: List[socket.socket] = []
        # Маппинг session→сокет для адресной доставки (D.1). Живёт под _clients_lock
        # (согласованность со списком клиентов). Пуст при session_isolation=False.
        self._sessions: Dict[str, socket.socket] = {}
        self._clients_lock = threading.Lock()
        self._write_lock = threading.Lock()
        # Сокеты, на которых запись упала (ревью 1.3a): помечены и shutdown'нуты под
        # _write_lock, но С УЧЁТА НЕ СНЯТЫ — снятие только на выходе read-loop, после
        # обработчиков сессии. Отправители их пропускают: второго sendall нет.
        self._dead: Set[socket.socket] = set()
        # Сокеты до успешного hello (только с authenticator): не в _clients, рассылки не
        # видят; живут под _clients_lock, close() закрывает их сам.
        self._unauthenticated: Set[socket.socket] = set()

        # Счётчики для get_info (наблюдаемость). Пишутся из нескольких потоков
        # (read-потоки соединений, обработчики) — под своим локом.
        self._stats_lock = threading.Lock()
        self._rx = 0
        self._tx = 0
        self._auth_rejected = 0

    # ---- IMessageChannel: свойства ----

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "socket"

    @property
    def port(self) -> int:
        """Фактический порт после bind (актуально при port=0 — авто-выбор ОС)."""
        return self._port

    @property
    def host(self) -> str:
        return self._host

    # ---- Жизненный цикл ----

    def start(self) -> bool:
        """Поднять сервер: socket/bind/listen + accept-loop в daemon-потоке.

        Returns:
            True если поднят; False если уже запущен или bind не удался.
        """
        if self._running:
            return False
        try:
            self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_sock.bind((self._host, self._port))
            # При port=0 ОС выбирает свободный порт — фиксируем фактический.
            self._port = self._server_sock.getsockname()[1]
            self._server_sock.listen(5)
            # Таймаут на accept, чтобы поток мог завершиться по флагу _running. close() ждёт
            # поток до этого таймаута (закрытие сокета accept() не будит): при 0.5 с стоило
            # 0.05–0.45 с на каждом стопе PM (Task 1.1 lifecycle-stop-ownership).
            self._server_sock.settimeout(0.05)
            self._bound = True
        except OSError as exc:
            self._log_error(f"[SocketChannel:{self._name}] bind/listen failed: {exc}")
            self._bound = False
            if self._server_sock is not None:
                self._server_sock.close()
                self._server_sock = None
            return False

        self._running = True
        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name=f"socket-ch-accept-{self._name}",
            daemon=True,
        )
        self._accept_thread.start()
        return True

    def close(self) -> None:
        """Остановить accept-loop, закрыть клиентские и серверный сокеты."""
        self._running = False
        # Закрыть клиентов — их read-loop'ы выйдут.
        with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()
            pre_hello = list(self._unauthenticated)
            self._unauthenticated.clear()
        for c in clients:
            try:
                c.close()
            except OSError:
                pass
        # До hello: shutdown будит recv их read-потоков сразу (POSIX), не через таймаут.
        for c in pre_hello:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                c.close()
            except OSError:
                pass
        # Закрыть серверный сокет.
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except OSError:
                pass
            self._server_sock = None
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=1.0)
            self._accept_thread = None
        self._bound = False

    # ---- IMessageChannel: отправка (OUTBOUND система → driver) ----

    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Сериализовать dict в newline-JSON и отправить всем клиентам (под Lock).

        Зовётся ТОЛЬКО router'ом через _resolve_channels(channel=name) — и, после
        ADR-RTR-012, из нескольких потоков-обработчиков одновременно; запись
        сериализует общий ``_write_lock``.

        Медленный клиент (не читает, буфер ядра полон): ``sendall`` упирается в
        таймаут сокета 0.5 с (``settimeout`` в accept-loop — это ТОТАЛЬНЫЙ таймаут
        sendall), ловится как OSError → сокет помечен мёртвым и ``shutdown`` (под
        ``_write_lock``), один WARNING на сокет — уже ПОСЛЕ выхода из-под лока
        (Task 0.5c, см. ``_write_locked``). Следующие отправители его пропускают,
        поэтому запись стоит не дольше одного таймаута сокета на медленного клиента.
        С учёта соединение снимает только выход его read-loop, после обработчиков
        сессии. На POSIX ``shutdown`` будит recv (EOF); на Windows не будит — read-loop
        выходит по пометке ``_dead`` на следующем таймауте recv (≤ 0.5 с), а пир, который
        продолжает слать, получает RST, и recv бросает OSError (Task 5.5, ревью). Посокетные локи не заведены (YAGNI).

        Returns:
            {"status": "success"|"error", "channel": name, ...}.
        """
        try:
            line = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        except (TypeError, ValueError) as exc:
            self._log_error(f"[SocketChannel:{self._name}] json encode failed: {exc}")
            return {"status": "error", "reason": str(exc), "channel": self._name}

        # Session-isolation (D.1, Вариант A): адресуем ОДНОМУ соединению, если
        # сообщение несёт session — поле `session` (reply, эхнутое адаптером) ИЛИ
        # dotted-суффикс subscriber (push: `_address=[name, sid]`, положен мостом
        # Ф1.1b router'а). Без session-адреса — broadcast (back-compat). Гейт:
        # при OFF ветка мертва, поведение бит-в-бит прежним broadcast'ом.
        if self._session_isolation:
            sid = self._resolve_session(message)
            if sid is not None:
                return self._send_to_session(sid, line)

        with self._clients_lock:
            clients = list(self._clients)
        if not clients:
            return {"status": "error", "reason": "no clients connected", "channel": self._name}

        sent = 0
        failures: list[str] = []
        with self._write_lock:
            for c in clients:
                if self._write_locked(c, line, "client", failures):
                    sent += 1
        # Лог — ПОСЛЕ выхода из-под _write_lock (Task 0.5c): WARNING идёт в tap
        # форвардера, а тот синхронным router.send может прийти в этот же канал.
        self._log_write_failures(failures)
        if sent == 0:
            return {"status": "error", "reason": "all clients dead", "channel": self._name}
        with self._stats_lock:
            self._tx += sent
        return {"status": "success", "channel": self._name, "clients": sent}

    def _resolve_session(self, message: Dict[str, Any]) -> Optional[str]:
        """Извлечь session-адрес из сообщения. Порядок: явное поле ``session``
        (reply, эхнутое адаптером) → хвост ``_address=[name, sid, …]`` (push через
        мост Ф1.1b). ``None`` → адреса нет, вызывающий уходит в broadcast."""
        sid = message.get("session")
        if sid:
            return str(sid)
        addr = message.get("_address")
        if isinstance(addr, list) and len(addr) > 1 and addr[0] == self._name:
            return str(addr[1])
        return None

    def _send_to_session(self, sid: str, line: bytes) -> Dict[str, Any]:
        """Адресная отправка одному соединению по ``sid``.

        Неизвестный sid → error, **НЕ** fallback в broadcast (иначе изоляция
        дырявая на гонке disconnect: пуш мёртвой сессии протёк бы всем). Мёртвый
        сокет → пометка + error (тот же путь, что broadcast при сбое sendall).
        """
        with self._clients_lock:
            sock = self._sessions.get(sid)
        if sock is None:
            return {"status": "error", "reason": "session not connected", "channel": self._name, "session": sid}
        failures: list[str] = []
        with self._write_lock:
            ok = self._write_locked(sock, line, f"session {sid}", failures)
        self._log_write_failures(failures)
        if not ok:
            return {"status": "error", "reason": "session dead", "channel": self._name, "session": sid}
        with self._stats_lock:
            self._tx += 1
        return {"status": "success", "channel": self._name, "clients": 1, "session": sid}

    def _write_locked(self, sock: socket.socket, line: bytes, target: str, failures: list[str]) -> bool:
        """Записать строку в сокет. Только под ``_write_lock``. Returns: записано ли.

        Мёртвый (помечен) или уже закрытый сокет пропускается молча — ни второго
        ожидания таймаута, ни EBADF. Сбой записи: текст отказа в ``failures``, пометка,
        ``shutdown`` (read-loop снимет соединение сам: на POSIX — по EOF, на Windows —
        по ``_dead`` на таймауте recv, см. ``_read_loop``). Больше
        ничего — ни снятия сессии, ни оповещения отсюда (ревью 1.3a, ADR-RTR-012).

        Здесь НЕ логируем (Task 0.5c): лог под ``_write_lock`` замыкается на этот же
        лок — WARNING идёт в tap ``RecordForwardChannel``, тот зовёт синхронный
        ``router.send``, и пуш адресату-каналу приходит сюда же в том же потоке
        (``threading.Lock`` не реентерабелен). Тексты пишет вызывающий через
        :meth:`_log_write_failures` после выхода из-под лока.
        """
        if sock in self._dead or sock.fileno() == -1:
            return False
        try:
            sock.sendall(line)
            return True
        except OSError as exc:
            failures.append(f"[SocketChannel:{self._name}] send to {target} failed: {exc} — сокет помечен мёртвым")
            self._dead.add(sock)
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return False

    def _log_write_failures(self, failures: list[str]) -> None:
        """По WARNING на каждый отказавший сокет. Зовётся только ВНЕ ``_write_lock``."""
        for text in failures:
            self._log_warning(text)

    # ---- IMessageChannel: получение ----

    def poll(self, timeout: float = 0.0, max_items: int = 0) -> List[Dict[str, Any]]:
        """No-op: inbound доставляется push'ем через read-loop → on_inbound, не pull'ом.

        ``max_items`` принимается ради единой подписи и не используется: дренажа
        как цикла здесь нет.

        Router опрашивает только каналы процесса (input_channels_only); этот канал
        с именем без префикса процесса не попадает в receive-цикл, и это верно.
        """
        return []

    # ---- Внутреннее: accept + read ----

    def _accept_loop(self) -> None:
        """Принимать соединения; на каждое — отдельный read-поток."""
        while self._running and self._server_sock is not None:
            try:
                client, _addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break  # сокет закрыт в close()
            accepted_at = time.monotonic()
            client.settimeout(0.5)
            # С authenticator сокет входит в _clients только после hello (из read-потока):
            # иначе broadcast send() дошёл бы до неаутентифицированного соединения.
            with self._clients_lock:
                if self._authenticator is None:
                    self._clients.append(client)
                else:
                    self._unauthenticated.add(client)
            threading.Thread(
                target=self._read_loop,
                args=(client, accepted_at),
                name=f"socket-ch-read-{self._name}",
                daemon=True,
            ).start()

    def _read_loop(self, client: socket.socket, accepted_at: Optional[float] = None) -> None:
        """Читать newline-JSON из соединения, парсить и передавать в on_inbound.

        Битая строка → лог+skip, не падаем. Закрытие соединения → выход.

        С ``authenticator`` первая строка разбирается :meth:`_handshake` ДО
        ``_handle_line``: иначе ``_bind_session`` внёс бы неаутентифицированный сокет в
        ``_sessions``. Отказ → соединение закрыто, остаток буфера отброшен; успех →
        остаток буфера идёт обычным путём.

        Разбор и привязка сессии — синхронно здесь, вызов on_inbound — в отдельном
        daemon-потоке (ADR-RTR-012): медленный обработчик одной строки не держит
        следующие строки того же соединения (head-of-line). Одновременно в работе
        не больше ``_MAX_INFLIGHT_PER_CONNECTION`` обработчиков на соединение.

        Строка длиннее ``max_line_bytes`` отбрасывается: если перевода строки в
        буфере нет, а он уже больше потолка — режим сброса до ближайшего ``\n``
        (байты не копим). WARNING — один раз на строку.
        """
        carry = b""
        first_line = self._authenticator is None
        if not first_line:
            rest = self._handshake(client, time.monotonic() if accepted_at is None else accepted_at)
            if rest is None:
                self._drop_unauthenticated(client)
                return
            carry = rest
        buf = b""
        discarding = False
        inflight = threading.BoundedSemaphore(_MAX_INFLIGHT_PER_CONNECTION)
        while self._running:
            if carry:
                chunk, carry = carry, b""
            else:
                try:
                    chunk = client.recv(4096)
                except socket.timeout:
                    # Windows: ``shutdown(SHUT_RDWR)`` из ``_write_locked`` не будит
                    # блокирующий ``recv`` — EOF не приходит, и без этой проверки сессия
                    # висит вечно. Сокет помечен в ``_dead`` → выходим, дальше обычная
                    # уборка после цикла. Чтение множества БЕЗ ``_write_lock``: добавляют
                    # под локом, а здесь достаточно атомарного ``in`` — худший случай
                    # один лишний тик таймаута (0.5 с), лок в read-loop не берём.
                    if client in self._dead:
                        break
                    continue
                except OSError:
                    break
                if not chunk:
                    break  # peer закрыл соединение
            if discarding:
                nl = chunk.find(b"\n")
                if nl < 0:
                    continue  # хвост oversize-строки — мимо буфера
                chunk = chunk[nl + 1 :]
                discarding = False
            buf += chunk
            while True:
                nl = buf.find(b"\n")
                if nl < 0:
                    break
                raw, buf = buf[:nl], buf[nl + 1 :]
                if len(raw) > self._max_line_bytes:
                    self._warn_oversize(len(raw))
                    continue
                if not raw.strip():
                    continue
                ack_hello, first_line = first_line, False
                if not self._handle_line(raw, client, inflight, ack_hello=ack_hello):
                    break  # канал закрыт, пока ждали слот
            if len(buf) > self._max_line_bytes:
                self._warn_oversize(len(buf))
                buf = b""
                discarding = True
        # Порядок закрытия (ADR-RTR-012, дополнение): соединение снимается с учёта
        # СРАЗУ (новые ответы ему — «session not connected», без записи), а
        # on_session_closed звучит только ПОСЛЕ последнего обработчика этой сессии —
        # как было, пока обработчики шли в read-потоке. Иначе наблюдатель обработчика
        # (note_point) отработал бы после forget_session: призрачное намерение (Н3-1).
        closed_sessions = self._unregister_clients([client])
        self._await_handlers(inflight)
        self._finish_drop([client], closed_sessions)

    def _await_handlers(self, inflight: threading.BoundedSemaphore) -> None:
        """Дождаться всех обработчиков соединения: забрать все слоты семафора.

        Абсолютного дедлайна нет: обработчик ограничен таймаутом своего запроса —
        ровно так же, как ограничен был read-поток, пока звал их инлайн. Ждёт только
        daemon-поток мёртвого соединения. Сдаётся лишь при close() канала
        (``_running`` = False), чтобы остановка не висела.
        """
        taken = 0
        while taken < _MAX_INFLIGHT_PER_CONNECTION:
            if inflight.acquire(timeout=_INFLIGHT_ACQUIRE_POLL_SEC):
                taken += 1
            elif not self._running:
                return

    def _warn_oversize(self, seen: int) -> None:
        self._log_warning(
            f"[SocketChannel:{self._name}] строка длиннее max_line_bytes={self._max_line_bytes} "
            f"(видно {seen} байт) — отброшена, соединение живо"
        )

    # ---- Рукопожатие (Task 0.12, ADR-RTR-017) ----

    def _handshake(self, client: socket.socket, accepted_at: float) -> Optional[bytes]:
        """Дождаться первой непустой строки и проверить её ``authenticator``.

        Дедлайн абсолютный (``accepted_at + hello_timeout_s``), проверяется после
        каждого recv и на recv-таймауте: клиент, шлющий по байту, соединение не держит.
        Returns: остаток буфера после строки при успехе (сокет уже в ``_clients``);
        ``None`` — отказ или разрыв (сокет закрывает вызывающий).
        """
        deadline = accepted_at + self._hello_timeout_s
        buf = b""
        while self._running:
            if time.monotonic() >= deadline:
                self._reject(client, None, "deadline")
                return None
            while True:  # пустые строки пропускаются
                nl = buf.find(b"\n")
                if nl < 0 or buf[:nl].strip():
                    break
                buf = buf[nl + 1 :]
            if 0 <= nl <= _HELLO_MAX_BYTES:
                return self._check_hello(client, buf[:nl], buf[nl + 1 :])
            if len(buf) > _HELLO_MAX_BYTES:
                self._reject(client, None, "oversize")
                return None
            try:
                chunk = client.recv(4096)
            except socket.timeout:
                if client in self._dead:
                    return None
                continue
            except OSError:
                return None
            if not chunk:
                return None
            buf += chunk
        return None

    def _check_hello(self, client: socket.socket, raw: bytes, rest: bytes) -> Optional[bytes]:
        """Проверить первую строку; при успехе ответить и зарегистрировать сокет."""
        try:
            msg = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            msg = None
        if not isinstance(msg, dict):
            self._reject(client, None, "not a dict")
            return None
        if msg.get("type") != "hello":
            self._reject(client, msg.get("request_id"), "no hello")
            return None
        try:
            ok = self._authenticator(msg) is True  # type: ignore[misc]  # не None: вызывающий проверил
        except Exception as exc:  # noqa: BLE001 — сбой проверки = отказ, канал жив
            # Только имя класса: текст исключения может нести содержимое строки.
            self._log_error(f"[SocketChannel:{self._name}] authenticator упал: {type(exc).__name__} — отказ")
            ok = False
        if not ok:
            self._reject(client, msg.get("request_id"), "bad token")
            return None
        if not self._write_hello_ack(client):
            return None  # ответ не записан — сокет не регистрируем
        # Ответ записан ДО регистрации: иначе broadcast обогнал бы ответ на hello.
        with self._clients_lock:
            if not self._running:
                return None
            self._unauthenticated.discard(client)
            self._clients.append(client)
        return rest

    def _write_hello_ack(self, client: socket.socket) -> bool:
        failures: list[str] = []
        with self._write_lock:
            ok = self._write_locked(client, _HELLO_ACK, "hello", failures)
        for text in failures:  # лог вне _write_lock (ADR-RTR-016)
            _log.debug(text)
        return ok

    def _reject(self, client: socket.socket, request_id: Any, why: str) -> None:
        """Ответить ``auth_required``, закрыть запись и дочитать остаток (ограниченно).

        Без WARNING на соединение (поток неаутентифицированных): счётчик ``auth_rejected``
        и DEBUG без токена и без содержимого строки.
        """
        reply: Dict[str, Any] = {"success": False, "error": "auth_required"}
        if isinstance(request_id, str) and len(request_id) <= _REQUEST_ID_ECHO_MAX:
            reply["request_id"] = request_id
        failures: list[str] = []
        with self._write_lock:
            self._write_locked(client, (json.dumps(reply) + "\n").encode("utf-8"), "pre-hello", failures)
        with self._stats_lock:
            self._auth_rejected += 1
        _log.debug("[SocketChannel:%s] hello отклонён: %s", self._name, why)
        for text in failures:
            _log.debug(text)
        try:
            client.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        self._drain(client)

    def _drain(self, client: socket.socket) -> None:
        """Дочитать входящее до EOF, но не дольше 0.5 с и не больше 64 КиБ.

        Вне ``_write_lock`` и ``_clients_lock``. Без дочитывания ``close()`` при
        непрочитанных байтах шлёт RST, и клиент теряет строку отказа.
        """
        end = time.monotonic() + _DRAIN_AFTER_REJECT_SEC
        budget = _DRAIN_AFTER_REJECT_BYTES
        while budget > 0:
            left = end - time.monotonic()
            if left <= 0:
                return
            try:
                ready, _w, _x = select.select([client], [], [], left)
                if not ready:
                    return
                chunk = client.recv(min(4096, budget))
            except (OSError, ValueError):  # сокет закрыт close() канала
                return
            if not chunk:
                return
            budget -= len(chunk)

    def _drop_unauthenticated(self, client: socket.socket) -> None:
        """Снять сокет без успешного hello с учёта и закрыть (под ``_write_lock``)."""
        with self._clients_lock:
            self._unauthenticated.discard(client)
        with self._write_lock:
            try:
                client.close()
            except OSError:
                pass
            self._dead.discard(client)

    def _handle_line(
        self,
        raw: bytes,
        client: socket.socket,
        inflight: Optional[threading.BoundedSemaphore] = None,
        *,
        ack_hello: bool = False,
    ) -> bool:
        """Распарсить одну строку wire и передать её в on_inbound (изоляция ошибок).

        ``ack_hello`` (первая строка открытого сервера): ``{"type": "hello"}`` получает
        ответ и в on_inbound не идёт. Любой ``hello``, дошедший до on_inbound (повторный
        после рукопожатия), идёт без поля ``token``: токен не доходит до роутера.

        При session-isolation ПЕРЕД on_inbound привязывает session→сокет: peek поля
        ``session`` (адаптер снимет его позже своим pop). Bind — единственная точка;
        self-heal на реконнекте (первое же сообщение переустановит маппинг). Bind
        делается ЗДЕСЬ, в read-потоке, до передачи сообщения обработчику: ответ
        обработчика адресуется по уже установленной привязке.

        ``inflight`` задан (read-loop) → on_inbound уходит в daemon-поток под этим
        семафором; ``None`` → вызов инлайн. Returns: False, если канал закрылся,
        пока ждали свободный слот (сообщение не передано), иначе True.
        """
        try:
            msg = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            self._log_warning(f"[SocketChannel:{self._name}] bad line skipped: {exc}")
            return True  # строка потеряна, соединение живо
        if not isinstance(msg, dict):
            self._log_warning(f"[SocketChannel:{self._name}] non-dict message skipped")
            return True  # строка потеряна, соединение живо
        if msg.get("type") == "hello":
            if ack_hello:
                self._write_hello_ack(client)
                return True
            msg.pop("token", None)
        with self._stats_lock:
            self._rx += 1
        # Привязка session→сокет ведётся ВСЕГДА, а не только при session_isolation.
        # У неё две роли, и это разные вопросы: «кому адресовать» (изоляция, гейт
        # остаётся в send()) и «жив ли ещё этот адрес» (время жизни подписчика).
        # Живой прогон 5.11-R1 поймал ровно это: при выключенной изоляции маппинг
        # был пуст, разрыв соединения не порождал сигнала, и мёртвые намерения
        # копились именно в ШТАТНОЙ конфигурации — то есть фикс существовал только
        # в режиме, который по умолчанию не включён.
        sid = msg.get("session")
        if sid:
            self._bind_session(str(sid), client)
        if self._on_inbound is None:
            return True
        if inflight is None:
            self._deliver(msg, None)
            return True
        # Backpressure: слот ждём порциями, между ними — проверка _running, чтобы
        # close() не оставлял read-поток висеть на полном семафоре.
        while not inflight.acquire(timeout=_INFLIGHT_ACQUIRE_POLL_SEC):
            if not self._running:
                return False
        # Daemon-потоки, НЕ ThreadPoolExecutor: воркеры executor'а не-daemon, и выход
        # интерпретатора ждал бы обработчик, застрявший в router.request(timeout=60).
        try:
            threading.Thread(
                target=self._deliver,
                args=(msg, inflight),
                name=f"socket-ch-inbound-{self._name}",
                daemon=True,
            ).start()
        except RuntimeError as exc:  # нет ресурса на поток — слот вернуть, строку потерять громко
            inflight.release()
            self._log_error(f"[SocketChannel:{self._name}] on_inbound thread start failed: {exc}")
        return True

    def _deliver(self, msg: Dict[str, Any], inflight: Optional[threading.BoundedSemaphore]) -> None:
        """Вызвать on_inbound с изоляцией ошибок; слот семафора вернуть всегда."""
        try:
            self._on_inbound(msg)  # type: ignore[misc]  # None отсечён в _handle_line
        except Exception as exc:  # noqa: BLE001 — граница: ошибка обработки не должна ронять канал
            self._log_error(f"[SocketChannel:{self._name}] on_inbound error: {exc}")
        finally:
            if inflight is not None:
                inflight.release()

    def _bind_session(self, sid: str, client: socket.socket) -> None:
        """Привязать session→сокет (D.1). Идемпотентно для того же сокета (ревью #7:
        не переписываем маппинг на каждом сообщении). sid, уже занятый ДРУГИМ
        соединением, НЕ угоняем (ревью #5): реконнект берёт НОВЫЙ sid (uuid per-connect),
        поэтому чужой sid на нашем сокете = баг/спуфинг — логируем и игнорируем."""
        rejected = False
        with self._clients_lock:
            existing = self._sessions.get(sid)
            if existing is client:
                return  # уже привязан к этому же сокету — no-op (ревью #7)
            if existing is None:
                self._sessions[sid] = client
            else:
                rejected = True  # занят другим соединением (ревью #5)
        if rejected:
            self._log_warning(
                f"[SocketChannel:{self._name}] session {sid} уже за другим соединением — привязка отклонена"
            )

    def _unregister_clients(self, clients: List[socket.socket]) -> List[str]:
        """Первая половина drop: снять сокеты и их session-маппинг с учёта (под локом).

        **Единственная точка unbind** — зовёт её только выход read-loop соединения
        (сбой записи лишь помечает сокет, см. ``_write_locked``).

        Returns: сессии, снятые ЭТИМ вызовом — каждая попадает ровно в один вызов,
        поэтому on_session_closed звучит ровно один раз при любых гонках drop'ов.
        """
        drop_ids = {id(c) for c in clients}
        closed_sessions: List[str] = []
        with self._clients_lock:
            for c in clients:
                if c in self._clients:
                    self._clients.remove(c)
            if self._sessions:
                for sid in [s for s, sock in self._sessions.items() if id(sock) in drop_ids]:
                    del self._sessions[sid]
                    closed_sessions.append(sid)
        return closed_sessions

    def _finish_drop(self, clients: List[socket.socket], closed_sessions: List[str]) -> None:
        """Вторая половина drop: оповестить о закрытых сессиях и закрыть сокеты."""
        # Оповещение — ВНЕ лока: обработчик может пойти в чужие структуры (реестр
        # подписок), и держать на этом лок соединений значило бы связать две
        # блокировки в порядке, о котором вторая сторона не знает.
        for sid in closed_sessions:
            if self._on_session_closed is None:
                continue
            try:
                self._on_session_closed(sid)
            except Exception as exc:  # noqa: BLE001 — обработчик не роняет канал
                self._log_error(f"[SocketChannel:{self._name}] on_session_closed({sid}) упал: {exc}")
        # Закрытие — под _write_lock: отправитель со старым снимком списка увидит
        # закрытый сокет (fileno == -1) уже под тем же локом и пропустит его.
        with self._write_lock:
            for c in clients:
                try:
                    c.close()
                except OSError:
                    pass
                self._dead.discard(c)

    # ---- Мониторинг ----

    def get_info(self) -> Dict[str, Any]:
        with self._clients_lock:
            clients = len(self._clients)
            sessions = len(self._sessions)
        with self._stats_lock:
            rx, tx, auth_rejected = self._rx, self._tx, self._auth_rejected
        return {
            "name": self._name,
            "type": self.channel_type,
            "active": self._running,
            "bound": self._bound,
            "host": self._host,
            "port": self._port,
            "clients": clients,
            "sessions": sessions,
            "session_isolation": self._session_isolation,
            "rx": rx,
            "tx": tx,
            "auth_rejected": auth_rejected,
        }
