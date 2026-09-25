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

Гейт/безопасность — на стороне хоста (BACKEND_CTL=1 + bind 127.0.0.1). Канал сам по себе
аутентификацию не делает (localhost dev-tool).
"""

from __future__ import annotations

import json
import socket
import threading
from typing import Any, Callable, Dict, List, Optional, Set

from .base_channel import MessageChannel

# ponytail: потолок 8 одновременных on_inbound на одно соединение; сверх него read-loop
# ждёт свободный слот (backpressure на сокет, TCP-окно отдаёт её клиенту). Поднять,
# если единственное мультиплексное соединение Пульта упрётся в него под нагрузкой.
_MAX_INFLIGHT_PER_CONNECTION = 8

# Сколько ждать слот за одну попытку: между попытками read-loop проверяет _running,
# чтобы close() не упирался в поток, застрявший на полном семафоре.
_INFLIGHT_ACQUIRE_POLL_SEC = 0.1


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
    ) -> None:
        super().__init__(log_warning=log_warning, log_error=log_error)
        self._on_session_closed = on_session_closed
        self._max_line_bytes = max_line_bytes
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

        # Счётчики для get_info (наблюдаемость). Пишутся из нескольких потоков
        # (read-потоки соединений, обработчики) — под своим локом.
        self._stats_lock = threading.Lock()
        self._rx = 0
        self._tx = 0

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
        for c in clients:
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
        sendall), ловится как OSError → один WARNING, сокет помечен мёртвым и
        ``shutdown`` (под ``_write_lock``). Следующие отправители его пропускают,
        поэтому запись стоит не дольше одного таймаута сокета на медленного клиента.
        С учёта соединение снимает только выход его read-loop (``shutdown`` будит
        recv), после обработчиков сессии. Посокетные локи не заведены (YAGNI).

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
        with self._write_lock:
            for c in clients:
                if self._write_locked(c, line, "client"):
                    sent += 1
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
        with self._write_lock:
            ok = self._write_locked(sock, line, f"session {sid}")
        if not ok:
            return {"status": "error", "reason": "session dead", "channel": self._name, "session": sid}
        with self._stats_lock:
            self._tx += 1
        return {"status": "success", "channel": self._name, "clients": 1, "session": sid}

    def _write_locked(self, sock: socket.socket, line: bytes, target: str) -> bool:
        """Записать строку в сокет. Только под ``_write_lock``. Returns: записано ли.

        Мёртвый (помечен) или уже закрытый сокет пропускается молча — ни второго
        ожидания таймаута, ни EBADF. Сбой записи: один WARNING, пометка, ``shutdown``
        (read-loop этого соединения получит EOF и снимет его с учёта сам). Больше
        ничего — ни снятия сессии, ни оповещения отсюда (ревью 1.3a, ADR-RTR-012).
        """
        if sock in self._dead or sock.fileno() == -1:
            return False
        try:
            sock.sendall(line)
            return True
        except OSError as exc:
            self._log_warning(f"[SocketChannel:{self._name}] send to {target} failed: {exc} — сокет помечен мёртвым")
            self._dead.add(sock)
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return False

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
            client.settimeout(0.5)
            with self._clients_lock:
                self._clients.append(client)
            threading.Thread(
                target=self._read_loop,
                args=(client,),
                name=f"socket-ch-read-{self._name}",
                daemon=True,
            ).start()

    def _read_loop(self, client: socket.socket) -> None:
        """Читать newline-JSON из соединения, парсить и передавать в on_inbound.

        Битая строка → лог+skip, не падаем. Закрытие соединения → выход.

        Разбор и привязка сессии — синхронно здесь, вызов on_inbound — в отдельном
        daemon-потоке (ADR-RTR-012): медленный обработчик одной строки не держит
        следующие строки того же соединения (head-of-line). Одновременно в работе
        не больше ``_MAX_INFLIGHT_PER_CONNECTION`` обработчиков на соединение.

        Строка длиннее ``max_line_bytes`` отбрасывается: если перевода строки в
        буфере нет, а он уже больше потолка — режим сброса до ближайшего ``\n``
        (байты не копим). WARNING — один раз на строку.
        """
        buf = b""
        discarding = False
        inflight = threading.BoundedSemaphore(_MAX_INFLIGHT_PER_CONNECTION)
        while self._running:
            try:
                chunk = client.recv(4096)
            except socket.timeout:
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
                if not self._handle_line(raw, client, inflight):
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

    def _handle_line(
        self,
        raw: bytes,
        client: socket.socket,
        inflight: Optional[threading.BoundedSemaphore] = None,
    ) -> bool:
        """Распарсить одну строку wire и передать её в on_inbound (изоляция ошибок).

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
            rx, tx = self._rx, self._tx
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
        }
