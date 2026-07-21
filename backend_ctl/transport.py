# -*- coding: utf-8 -*-
"""transport.py — TCP-транспорт driver'а: сокет + reader-поток + request-response.

Mixin `_TransportMixin`: подключение, читающий daemon-поток, матчинг ответов по
request_id (`_Pending`-слоты), карантин поздних ответов, thread-safe закрытие.
push-сообщения (без reply / поздний ответ никто не ждёт) уходят в событийный канал
через `self._emit_event` (`_EventChannelMixin`).

Выделено из ``driver.py`` (Phase C, C.1) как mixin — код переезжает дословно на тот
же ``self`` (поведение бит-в-бит), включая concurrency-фиксы Phase A (thread-safe
close()/_read_loop, гашение applier-потока watch). Хост (`BackendDriver`) заводит поля
в ``__init__``: ``_sock``/``_reader``/``_running``/``_pending``/``_pending_lock``/
``_write_lock``/``_timed_out``/``_late_replies`` + endpoint (``_host``/``_port``/
``_reply_to``/``_default_timeout``). close() дополнительно гасит watch-контур
(``self._watch``) и будит ожидающих событийного hub'а (``self._hub``) — оркестрация
несущих подсистем.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
import uuid
from typing import Any, Dict, Optional

from backend_ctl.mcp_errors import BackendUnavailable

_log = logging.getLogger(__name__)

# TTL карантина таймаутнутых request_id (Task 0.2): дольше этого поздний ответ уже
# не ждём — запись протухает и вычищается лениво. Запас над самым долгим таймаутом.
_TIMED_OUT_TTL_SEC: float = 60.0

# На столько сервер ждёт МЕНЬШЕ клиента (запас на дорогу ответа). Клиент, сдавшийся
# первым, теряет честный ответ сервера и подменяет диагноз своим «таймаутом».
_SERVER_MARGIN_SEC: float = 0.5


class _Pending:
    """Слот ожидания ответа по request_id."""

    __slots__ = ("event", "response")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.response: Optional[Dict[str, Any]] = None


class _TransportMixin:
    """TCP-клиент: соединение + reader-поток + request-response + thread-safe close()."""

    def dispatch_raw(self, raw: bytes) -> None:
        """Публичная точка инъекции входящей строки (для тестов; Task 0.4).

        Тонкая обёртка над внутренним разбором: тесты событийного канала подают
        «проводные» строки, не трогая приватный ``_dispatch``.
        """
        self._dispatch(raw)

    def connect(self, timeout: float = 5.0) -> None:
        """Подключиться к хосту и запустить читающий поток.

        Генерит session (D.1): per-connection адрес этого driver'а — сервер по нему
        адресует reply/push именно нашему сокету (при session_isolation ON). Из него
        же строится dotted-``_subscriber`` (``<sender>.<session>``) — дефолт получателя
        push'ей: разные driver'ы = разные подписчики, изоляция и на push-плоскости.
        """
        self._session = uuid.uuid4().hex[:12]
        self._subscriber = f"{self._sender}.{self._session}"
        # Свежее соединение — прошлая смерть больше не актуальна (Task 1.1).
        self._conn_lost = False
        self._sock = socket.create_connection((self._host, self._port), timeout=timeout)
        self._sock.settimeout(0.5)
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, name="backend-ctl-reader", daemon=True)
        self._reader.start()

    def close(self) -> None:
        """Остановить читающий поток и закрыть сокет.

        Гасит и applier-поток watch (``backend-ctl-resub``): его иначе снимает только
        :meth:`unwatch`, а реконнект зовёт ``close()`` (``DriverSession.reset``) — без
        этого на каждый реконнект-с-активным-watch daemon-поток навсегда висел бы в
        ``q.get()``, удерживая ссылкой на ``self._resub_loop`` весь старый driver.
        """
        self._running = False
        # Закрыть и обнулить сокет под _write_lock (симметрия с _send_raw/_read_loop):
        # иначе гонка обнуления с чтением _sock в другом потоке (A.3). Обнуление ДО
        # очистки/пробуждения _pending ниже — намеренно: применитель, чей request()
        # ещё не вставил pending, увидит _sock is None в _send_raw и упадёт ConnectionError
        # мгновенно (не повиснет), а уже вставленные pending будятся снапшотом ниже.
        with self._write_lock:
            sock = self._sock
            self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        # Разбудить всех ожидающих ответа (соединение закрыто) — в т.ч. applier,
        # если он застрял в in-flight request(): иначе его join ниже висел бы до таймаута.
        with self._pending_lock:
            pendings = list(self._pending.values())
            self._pending.clear()
        for p in pendings:
            p.event.set()
        # Погасить applier-поток watch — ПОСЛЕ пробуждения pending'ов (in-flight
        # applier-request уже разбужен, join не виснет). Деактивация + sentinel + join
        # инкапсулированы в WatchController.stop() (владелец watch-состояния, C.1).
        self._watch.stop()
        if self._reader is not None:
            self._reader.join(timeout=1.0)
            self._reader = None
        # Разбудить тех, кто блокирует в events(timeout): новых событий не будет.
        self._hub.wake()

    def __enter__(self) -> Any:
        self.connect()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def request(self, message: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        """Отправить router-сообщение и дождаться ответа по request_id.

        Если в message нет request_id — назначается; в reply_to ставится self.reply_to,
        если не задан. Возвращает result из ответа.

        Контракт ошибок (Task 1.1) — две РАЗНЫЕ ситуации, две разные реакции:

        * **соединение мертво** (сервер закрыл сокет / OSError в reader'е) →
          :class:`BackendUnavailable`. Исключение обязано лететь наружу: только по нему
          ``call_tool`` зовёт ``session.reset()``, а следующий ``ensure()`` реконнектится
          с replay'ем durable-подписок. Раньше здесь возвращался error-dict — и весь
          reconnect-аппарат D.1 был недостижим, сессия оставалась мёртвой навсегда.
        * **таймаут при живом сокете** / вызов без соединения → error-dict как прежде
          (бэкенд жив, просто не ответил вовремя — сбрасывать соединение незачем).
        """
        if self._conn_lost:
            raise BackendUnavailable(self._conn_lost_message())
        if self._sock is None:
            return {"success": False, "error": "not connected"}

        cid = message.get("request_id") or str(uuid.uuid4())
        message["request_id"] = cid
        message.setdefault("reply_to", self._reply_to)

        pending = _Pending()
        with self._pending_lock:
            self._pending[cid] = pending
        try:
            wait = timeout if timeout is not None else self._default_timeout
            # Пробросить бюджет ожидания СЕРВЕРУ. socket_bridge_adapter берёт его из
            # msg["timeout"], а без поля — свой дефолт (5с) и отвечает
            # {"success": False, "error": "timeout"} на команде, которая на самом деле
            # успешно отрабатывает. Наблюдалось живьём: topology.apply с timeout=180
            # возвращал «таймаут» ровно через 5.00с, при этом переключение проходило
            # (новая топология в state, ghost-процессов нет).
            # Серверу даём чуть меньше, чем ждём сами: иначе клиент сдастся первым и
            # потеряет ЧЕСТНЫЙ ответ сервера — диагноз «сервер не успел» ценнее, чем
            # «я не дождался». setdefault — явный timeout в сообщении сильнее.
            message.setdefault("timeout", max(0.5, wait - _SERVER_MARGIN_SEC))
            self._send_raw(message)
            if not pending.event.wait(wait):
                # Таймаут: пометить cid в карантин — поздний ответ dispatcher дропнет,
                # а не выдаст псевдо-событием (Task 0.2).
                self._quarantine_timed_out(cid)
                return {"success": False, "error": "timeout", "request_id": cid}
            if pending.response is None:
                # Разбужены без ответа: либо смерть соединения (reader разбудил pending'и),
                # либо штатный close() из другого потока. Первое — исключение (реконнект),
                # второе — error-dict (закрытие намеренное, реконнектить нечего).
                if self._conn_lost:
                    raise BackendUnavailable(self._conn_lost_message(request_id=cid))
                return {"success": False, "error": "connection closed", "request_id": cid}
            return pending.response.get("result", pending.response)
        except (ConnectionError, OSError) as exc:
            # Гонка close()/request(): сокет обнулён/закрыт из другого потока во время
            # отправки. Смерть соединения → исключение (Task 1.1); намеренное закрытие →
            # чистый error-dict, не AssertionError/утечка исключения (Task 0.2).
            if self._conn_lost:
                raise BackendUnavailable(self._conn_lost_message(request_id=cid)) from exc
            return {"success": False, "error": "connection closed", "detail": str(exc), "request_id": cid}
        finally:
            with self._pending_lock:
                self._pending.pop(cid, None)

    def _quarantine_timed_out(self, cid: str) -> None:
        """Пометить request_id как таймаутнутый + лениво вычистить протухшие (Task 0.2)."""
        now = time.monotonic()
        with self._pending_lock:
            if self._timed_out:
                for stale in [k for k, exp in self._timed_out.items() if exp <= now]:
                    del self._timed_out[stale]
            self._timed_out[cid] = now + _TIMED_OUT_TTL_SEC

    def _send_raw(self, message: Dict[str, Any]) -> None:
        # session (D.1): обратный адрес соединения в КАЖДОМ исходящем сообщении —
        # сервер (при session_isolation ON) адресует reply/push именно этому сокету.
        # setdefault — не затираем явно заданный session. Единственный choke-point
        # исходящих (все sends идут через request()→_send_raw).
        if self._session is not None:
            message.setdefault("session", self._session)
        line = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        with self._write_lock:
            sock = self._sock
            if sock is None:
                # close() из другого потока обнулил сокет — не assert'им, а поднимаем
                # штатную ConnectionError (request() превращает её в error-dict).
                raise ConnectionError("socket closed")
            sock.sendall(line)

    def _read_loop(self) -> None:
        buf = b""
        while self._running:
            # Захватить локальную ссылку под _write_lock: close() из другого потока
            # обнуляет _sock, и без этого self._sock.recv() в окне между проверкой
            # условия и вызовом дал бы AttributeError, тихо роняющий reader (daemon,
            # только stderr). Локальная копия делает recv() устойчивым к гонке.
            with self._write_lock:
                sock = self._sock
            if sock is None:
                break
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            except (OSError, AttributeError) as exc:
                # Обрыв в момент чтения. Штатное закрытие (_running=False) — молча;
                # неожиданный обрыв при живом клиенте — залогировать (не только stderr).
                if self._running:
                    _log.warning("backend_ctl reader: обрыв соединения при recv (%s)", exc)
                    self._mark_conn_lost(f"обрыв при recv ({exc})")
                break
            if not chunk:
                if self._running:
                    _log.warning("backend_ctl reader: сервер закрыл соединение")
                    self._mark_conn_lost("сервер закрыл соединение")
                break
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                if raw.strip():
                    self._dispatch(raw)

    def _mark_conn_lost(self, reason: str) -> None:
        """Объявить соединение мёртвым и разбудить всех, кто ждёт ответа (Task 1.1).

        Зовётся ТОЛЬКО reader-потоком и ТОЛЬКО при неожиданной смерти (``_running`` ещё
        True) — намеренный :meth:`close` сюда не попадает. Пробуждённые ``request()``
        увидят ``response is None`` + флаг и поднимут :class:`BackendUnavailable` вместо
        того, чтобы досиживать полный таймаут ради error-dict'а.

        Слоты pending НЕ вычищаются: их снимает ``finally`` в :meth:`request` (владелец),
        иначе гонка «pop уже снятого cid» и потеря карантина поздних ответов.
        """
        self._conn_lost = True
        self._conn_lost_reason = reason
        with self._pending_lock:
            pendings = list(self._pending.values())
        for p in pendings:
            p.event.set()
        # Разбудить и тех, кто блокирует в events(timeout): поток событий оборван.
        self._hub.wake()

    def _conn_lost_message(self, *, request_id: Optional[str] = None) -> str:
        """Actionable-текст смерти соединения (единый для всех точек подъёма)."""
        reason = getattr(self, "_conn_lost_reason", "") or "соединение оборвано"
        tail = f" (request_id={request_id})" if request_id else ""
        return (
            f"соединение с бэкендом на {self._host}:{self._port} оборвано: {reason}{tail}. "
            "Драйвер будет пересоздан на следующем вызове (durable-подписки и watch-профиль "
            "восстанавливаются автоматически); если бэкенд упал — подними его с BACKEND_CTL=1."
        )

    @property
    def connection_lost(self) -> bool:
        """Умерло ли соединение неожиданно (в отличие от намеренного :meth:`close`)."""
        return bool(self._conn_lost)

    def _dispatch(self, raw: bytes) -> None:
        """Распарсить входящую строку и развести по reply-пути или событийному каналу.

        Reply-путь: если у сообщения есть request_id и его ждёт pending-слот — будим
        ожидающего request(). Иначе (нет request_id ИЛИ никто уже не ждёт — поздний
        ответ после таймаута / push вроде state.changed) сообщение становится
        событием и уходит в очередь + подписчикам (раньше здесь молча дропалось).
        """
        try:
            msg = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(msg, dict):
            return
        cid = msg.get("request_id")
        if cid:
            with self._pending_lock:
                pending = self._pending.get(cid)
                # Поздний ответ после таймаута: pending уже снят, но cid в карантине —
                # опознаём и дропаем (не псевдо-событие). Иначе — обычная логика.
                is_late = pending is None and cid in self._timed_out
                if is_late:
                    del self._timed_out[cid]
                    # Инкремент под тем же локом: dispatch_raw (Task 0.4) сделал _dispatch
                    # публичным → нельзя опираться на «только reader-поток» (ревью MINOR #3).
                    self._late_replies += 1
            if pending is not None:
                pending.response = msg
                pending.event.set()
                return
            if is_late:
                return
        # Нет request_id либо reply уже никто не ждёт (и это не карантин) → это событие.
        self._emit_event(msg)

    @property
    def late_replies(self) -> int:
        """Сколько поздних ответов (пришли после таймаута request) дропнуто (Task 0.2)."""
        return self._late_replies


__all__ = ["_TransportMixin", "_Pending"]
