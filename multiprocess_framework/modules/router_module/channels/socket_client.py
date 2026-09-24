"""socket_client.py — клиентская половина :class:`SocketChannel` (Task 1.2, gui-service).

Контракт-в-коде (module-contract, уровень lite). Реализация — перенос wire-клиента
dev-драйвера (GREEN Task 1.2); драйвер наследует класс через тонкий шим.

Назначение
----------
Wire-клиент сокетного канала хоста: одно TCP-соединение, JSON + ``\\n`` (UTF-8,
``ensure_ascii=False``), мультиплексирование запросов по ``request_id``, приём push-
сообщений хоста. Qt-free, без импортов из dev-пакетов верхнего уровня (фреймворк —
нижний слой). Потребители: ``frontend_module.bridge.RemoteCommandSender`` /
``RemoteStateProxy`` (внешний GUI) и dev-драйвер (наследует класс через тонкий шим,
переопределяя хуки ниже).

Потоки
------
* ``connect()`` запускает ОДИН daemon reader-поток; он разбирает входящие строки,
  будит ожидающих :meth:`request`, зовёт колбэки :meth:`request_async` и push-обработчики.
  Всё, что клиент вызывает сам (``on_push``, push-слушатели, ``on_response``), исполняется
  НА reader-потоке — колбэк обязан быть коротким и не звать блокирующий :meth:`request`.
* Остальные методы потокобезопасны: запись в сокет — под одним write-lock, реестр
  ожидающих — под pending-lock.

Инварианты класса
-----------------
I1. Каждое исходящее сообщение проходит ОДНУ точку записи (``_send_raw``): там
    проставляется ``session`` (``setdefault``) и применяются send-middleware в порядке
    регистрации. Обходного пути записи нет.
I2. Сообщение с ``request_id``, который ждёт pending-слот, — ответ, и только ответ:
    в push оно не попадает. Сообщение без ``request_id`` либо с ``request_id``, который
    никто не ждёт и которого нет в карантине, — push.
I3. Ответ на таймаутнутый :meth:`request` и любой ответ на :meth:`send_nowait` —
    в карантине (TTL 60 с): дропается, в push не попадает. Таймаутнутые считает
    :attr:`late_replies`; ответы ``send_nowait`` не считаются.
I4. Разрыв соединения (EOF/OSError в reader) → :attr:`connection_lost` ``True``,
    все ожидающие :meth:`request` будятся и поднимают ``_lost_exc``; все ожидающие
    :meth:`request_async` получают колбэк ``{"success": False, "error": "connection lost"}``
    РОВНО ОДИН РАЗ. Намеренный :meth:`close` — не разрыв: ``connection_lost`` ``False``.
I5. ``session`` — новый на каждый :meth:`connect`; адрес push-получателя
    :attr:`subscriber_address` = ``f"{door}.{session}"`` меняется вместе с ним.
    Префикс — имя канала-ДВЕРИ хаба (``SocketChannel``), а не ``sender``: хаб доставляет
    push по ``_address`` только если его голова равна имени канала
    (``socket_channel.py`` ``_resolve_session``: ``addr[0] == self._name``), иначе push
    уходит мимо молча. Живой стенд 1.3: клиент с ``sender="pult"`` подписался, мост
    отправил 492 дескриптора, клиент получил 0.
    Всё, что зарегистрировано на хосте под старым адресом (state-подписки), после
    реконнекта этому клиенту больше не доставляется — перерегистрация на стороне
    потребителя (``RemoteStateProxy.on_reconnected``).

Реконнект
---------
Сам клиент НЕ переподключается: политика (когда, сколько раз, с какой паузой) — у
владельца соединения (точка входа Пульта, Task 1.4). Протокол реконнекта, который
обязан выполнить владелец, в этом порядке:
    1. ``client.close()`` (если ещё не закрыт);
    2. ``client.connect()``   — новый ``session`` (I5);
    3. ``RemoteCommandSender.refresh_fence()`` — свежие inc/epoch до первой команды;
    4. ``RemoteStateProxy.on_reconnected()``  — перерегистрация подписок под новым адресом.
Push-слушатели и send-middleware переживают ``close()``/``connect()`` — повторно их
регистрировать не нужно.

Хуки для наследника-шима (переопределяются, публичной поверхностью не являются)
------------------------------------------------------------------------------
* ``_lost_exc`` (атрибут класса) — тип исключения разрыва; дефолт :class:`SocketConnectionLost`.
* ``_reader_thread_name`` (атрибут класса) — имя reader-потока.
* ``_handle_push(msg)`` — доставка push; дефолт: ``on_push`` + слушатели по порядку.
  Имя НЕ ``_emit_event``: наследник стоит в MRO раньше своего событийного миксина.
* ``_on_closed()`` — после :meth:`close` (дефолт no-op).
* ``_on_conn_lost()`` — после фиксации разрыва (дефолт no-op).
* ``_conn_lost_message(request_id=None)`` — текст исключения разрыва.

Публичных ``send``/``subscribe`` нет намеренно: они затенили бы одноимённые методы
событийного миксина у наследника (MRO).
"""

from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

from multiprocess_framework.modules.logger_module import get_std_logger

_log = get_std_logger(__name__)

PushHandler = Callable[[Dict[str, Any]], None]
SendMiddleware = Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]
ResponseCallback = Callable[[Dict[str, Any]], None]

# TTL карантина (I3): дольше этого поздний ответ уже не ждём — запись протухает и
# вычищается лениво. Запас над самым долгим таймаутом.
_TIMED_OUT_TTL_SEC: float = 60.0

# На столько сервер ждёт МЕНЬШЕ клиента (запас на дорогу ответа). Клиент, сдавшийся
# первым, теряет честный ответ сервера и подменяет диагноз своим «таймаутом».
_SERVER_MARGIN_SEC: float = 0.5

# Период опроса reader-потока (socket timeout): с этой точностью срабатывают таймауты
# request_async и протухает карантин send_nowait.
_READ_POLL_SEC: float = 0.5

_READER_THREAD_GUARD_ERROR: str = (
    "request() позван из reader-потока — дедлок: этот же поток должен доставить ответ, "
    "а вызов блокируется в ожидании его самого. Колбэки push-слушателей и request_async "
    "исполняются на reader-потоке: из них — request_async() либо передача намерения "
    "другому потоку (queue.Queue), но не блокирующий request()."
)


class SocketConnectionLost(RuntimeError):
    """Соединение с хостом оборвалось неожиданно (не намеренный :meth:`SocketClient.close`)."""


class _Pending:
    """Слот ожидания ответа по request_id.

    Три вида слотов в одном реестре (``_pending``):
      * синхронный :meth:`SocketClient.request` — ``callback is None``, ``nowait is False``:
        ответ кладётся в ``response``, ожидающий будится ``event``;
      * :meth:`SocketClient.request_async` — ``callback`` задан, ``deadline`` — момент
        таймаута;
      * :meth:`SocketClient.send_nowait` — ``nowait is True``: карантин ответа (I3),
        ``deadline`` — конец TTL.
    Один реестр, а не три: шим драйвера заводит поля транспорта сам, в своём
    ``__init__`` (``_pending`` в их числе), и новых словарей не знает.
    """

    __slots__ = ("event", "response", "callback", "deadline", "nowait")

    def __init__(
        self,
        callback: Optional[ResponseCallback] = None,
        deadline: Optional[float] = None,
        nowait: bool = False,
    ) -> None:
        self.event = threading.Event()
        self.response: Optional[Dict[str, Any]] = None
        self.callback = callback
        self.deadline = deadline
        self.nowait = nowait


def _fire(callback: ResponseCallback, envelope: Dict[str, Any]) -> None:
    """Позвать колбэк request_async; исключение колбэка не роняет вызывающий поток."""
    try:
        callback(envelope)
    except Exception:  # noqa: BLE001 — чужой колбэк не должен ронять reader
        _log.exception("socket_client: исключение в колбэке request_async")


class SocketClient:
    """Клиент сокетного канала хоста: request/response по ``request_id`` + push.

    Invariants: см. I1–I5 в докстринге модуля.
    """

    _lost_exc: type[BaseException] = SocketConnectionLost
    _reader_thread_name: str = "socket-client-reader"
    # Текст guard'а дедлока (вызов request() с reader-потока); шим подменяет своим.
    _reader_guard_error: str = _READER_THREAD_GUARD_ERROR

    # Значения по умолчанию на уровне класса — неизменяемые (кортежи/None): шим драйвера
    # не зовёт ``SocketClient.__init__`` и этих полей не заводит. Добавление —
    # copy-on-write (новый кортеж на экземпляре), общий объект класса не мутируется.
    _on_push: Optional[PushHandler] = None
    _push_listeners: tuple = ()
    _send_middleware: tuple = ()

    def __init__(
        self,
        host: str,
        port: int,
        *,
        sender: str,
        door: str = "backend_ctl",
        reply_to: str | None = None,
        default_timeout: float = 5.0,
        on_push: PushHandler | None = None,
    ) -> None:
        """Сконфигурировать клиент; соединения НЕ открывает.

        Pre:  ``port`` в 0..65535; ``default_timeout > 0``; ``sender`` — непустая
              идентичность клиента в сообщениях и логах (на адрес push'ей НЕ влияет).
              ``door`` — имя канала-двери хаба (``SocketChannel``), к которому подключаемся;
              префикс :attr:`subscriber_address` (I5 — хост разрешает ``<канал>.<session>``
              в сокет только при совпадении). Дефолт — дверь ``backend_ctl`` хаба
              ``ProcessManager``.
              ``reply_to`` — адресат ответа НА ХОСТЕ; ``None`` (дефолт) = поле не
              ставится, его подставляет мост хоста своим именем (``SocketBridgeAdapter``
              ``setdefault``). Явное имя, не совпадающее с именем хоста, уводит ответ
              мимо ожидающего на хосте ``request()`` — тот досиживает до таймаута.
        Post: ``connection_lost is False``; ``session is None``; ``late_replies == 0``;
              ``on_push`` (если задан) — первый push-обработчик.
        """
        self._host = host
        self._port = port
        self._sender = sender
        self._door = door
        self._reply_to = reply_to
        self._default_timeout = default_timeout
        self._on_push = on_push
        self._push_listeners = ()
        self._send_middleware = ()
        self._session: Optional[str] = None
        self._subscriber: str = sender
        self._sock: Optional[socket.socket] = None
        self._reader: Optional[threading.Thread] = None
        self._running = False
        self._pending: Dict[str, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._conn_lost = False
        self._conn_lost_reason = ""
        # Карантин таймаутнутых request_id: cid → момент протухания (I3).
        self._timed_out: Dict[str, float] = {}
        self._late_replies = 0

    # ------------------------------------------------------------------ жизненный цикл

    def connect(self, timeout: float = 5.0) -> None:
        """Открыть соединение и запустить reader-поток.

        Pre:  клиент не подключён (первый вызов либо после :meth:`close`/разрыва);
              повторный ``connect`` на живом соединении не проверяется (паритет с шимом).
        Post: новый ``session`` (12 hex), отличный от предыдущего; ``subscriber_address``
              обновлён; ``connection_lost is False``; reader-поток жив.
        Raises: ``OSError`` — хост недоступен за ``timeout`` (состояние как до вызова).
        """
        sock = socket.create_connection((self._host, self._port), timeout=timeout)
        sock.settimeout(_READ_POLL_SEC)
        self._session = uuid.uuid4().hex[:12]
        # Наследник-шим (``backend_ctl.BackendDriver``) заводит поля сам, без __init__ базы:
        # у него дверь = sender (``backend_ctl``), поэтому без ``_door`` берём ``_sender``.
        door = getattr(self, "_door", self._sender)
        self._subscriber = f"{door}.{self._session}"
        # Свежее соединение — прошлая смерть больше не актуальна.
        self._conn_lost = False
        self._sock = sock
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, name=self._reader_thread_name, daemon=True)
        self._reader.start()

    def close(self) -> None:
        """Закрыть соединение намеренно. Идемпотентен.

        Post: сокет закрыт; reader-поток завершён (join ≤ 1 с); все ожидающие
              :meth:`request` разбужены и вернули ``{"success": False, "error":
              "connection closed", ...}`` (НЕ исключение); ожидающие :meth:`request_async`
              получили колбэк с ошибкой ровно один раз; ``connection_lost`` не меняется;
              вызван ``_on_closed()``.
        """
        self._running = False
        # Обнуление сокета под _write_lock (симметрия с _send_raw/_read_loop) и ДО
        # пробуждения ожидающих: request(), ещё не вставивший слот, увидит _sock is None
        # в _send_raw и упадёт сразу, а уже вставленные будятся снапшотом ниже.
        with self._write_lock:
            sock = self._sock
            self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        with self._pending_lock:
            slots = list(self._pending.items())
            self._pending.clear()
        self._wake_slots(slots, "connection closed")
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=1.0)
        self._reader = None
        self._on_closed()

    def __enter__(self) -> "SocketClient":
        """``connect()`` и вернуть себя."""
        self.connect()
        return self

    def __exit__(self, *exc: Any) -> None:
        """``close()``."""
        self.close()

    # ------------------------------------------------------------------ исходящие

    def request(self, message: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        """Отправить сообщение и дождаться ответа по ``request_id`` (блокирует).

        Pre:  ``message`` — JSON-сериализуемый dict; вызов НЕ с reader-потока.
        Post: в ``message`` проставлены ``request_id`` (если не было), ``reply_to`` (если задан)
              (``setdefault``), ``timeout`` для сервера (``setdefault``, на 0.5 с меньше
              клиентского ожидания, не меньше 0.5 с). Возвращает поле ``result`` ответа
              хоста (конверт ``RouterManager.request``: ``{"success", "result"|"error"}``),
              либо весь ответ, если ``result`` нет.
        Ошибки — два класса, две реакции:
          * соединение мертво (до или во время ожидания) → поднимает ``_lost_exc``
            за ≤ ``timeout``;
          * таймаут при живом сокете / не подключён / намеренный close →
            error-dict ``{"success": False, "error": "timeout"|"not connected"|
            "connection closed", ...}``, без исключения;
          * вызов с reader-потока → немедленный error-dict (guard дедлока), без отправки;
          * send-middleware вернул ``None`` → ``{"success": False, "error": "dropped"}``,
            без отправки.
        """
        if threading.current_thread() is self._reader:
            # Проверка ДО conn_lost/sock: поток-дедлок не доедет до приёма в любом случае.
            return {"success": False, "error": self._reader_guard_error}
        if self._conn_lost:
            raise self._lost_exc(self._conn_lost_message())
        if self._sock is None:
            return {"success": False, "error": "not connected"}

        cid = message.get("request_id") or str(uuid.uuid4())
        message["request_id"] = cid
        if self._reply_to:
            message.setdefault("reply_to", self._reply_to)

        pending = _Pending()
        # Проверка разрыва и вставка слота — под ОДНИМ локом с _mark_conn_lost: иначе
        # reader, отметивший обрыв между проверкой выше и вставкой, уже не разбудит слот.
        with self._pending_lock:
            lost = self._conn_lost
            if not lost:
                self._pending[cid] = pending
        if lost:
            raise self._lost_exc(self._conn_lost_message(request_id=cid))
        try:
            wait = timeout if timeout is not None else self._default_timeout
            # Бюджет ожидания — СЕРВЕРУ, чуть меньше своего: иначе сервер отвечает
            # «timeout» по своему дефолту на команде, которая успешно отрабатывает, а
            # клиент, сдавшийся первым, теряет честный ответ. Явный timeout сильнее.
            message.setdefault("timeout", max(0.5, wait - _SERVER_MARGIN_SEC))
            if not self._send_raw(message):
                return {"success": False, "error": "dropped", "request_id": cid}
            if not pending.event.wait(wait):
                # Таймаут: cid в карантин — поздний ответ dispatcher дропнет (I3).
                self._quarantine_timed_out(cid)
                return {"success": False, "error": "timeout", "request_id": cid}
            if pending.response is None:
                # Разбужены без ответа: смерть соединения (исключение, реконнект у
                # владельца) либо намеренный close() (error-dict, реконнектить нечего).
                if self._conn_lost:
                    raise self._lost_exc(self._conn_lost_message(request_id=cid))
                return {"success": False, "error": "connection closed", "request_id": cid}
            return pending.response.get("result", pending.response)
        except (ConnectionError, OSError) as exc:
            # Гонка close()/request(): сокет обнулён/закрыт из другого потока во время отправки.
            if self._conn_lost:
                raise self._lost_exc(self._conn_lost_message(request_id=cid)) from exc
            return {"success": False, "error": "connection closed", "detail": str(exc), "request_id": cid}
        finally:
            with self._pending_lock:
                self._pending.pop(cid, None)

    def request_async(
        self,
        message: Dict[str, Any],
        on_response: ResponseCallback,
        timeout: float = 5.0,
        correlation_id: Optional[str] = None,
    ) -> str:
        """Отправить запрос, ответ получить колбэком; не блокирует. Паритет с
        ``RouterManager.request_async``.

        Pre:  ``timeout > 0``; допустим вызов с reader-потока (в этом смысл метода).
        Post: возвращает ``request_id`` (= ``correlation_id``, если задан).
              ``on_response`` вызывается РОВНО ОДИН РАЗ, в одном из случаев:
                * пришёл ответ → конверт как у :meth:`request`, на reader-потоке;
                * истёк ``timeout`` → ``{"success": False, "error": "timeout", ...}``
                  не позже ``timeout`` + период опроса reader-потока (0.5 с);
                * разрыв/close → ``{"success": False, "error": "connection lost"|
                  "connection closed", ...}``;
                * отправка не удалась → error-dict СИНХРОННО, внутри этого вызова.
              Поздний ответ после таймаута — в карантин (I3), колбэк повторно не зовётся.
              Исключение колбэка не роняет reader-поток.
        """
        cid = correlation_id or message.get("request_id") or str(uuid.uuid4())
        message["request_id"] = cid
        if self._reply_to:
            message.setdefault("reply_to", self._reply_to)
        message.setdefault("timeout", max(0.5, timeout - _SERVER_MARGIN_SEC))

        pending = _Pending(callback=on_response, deadline=time.monotonic() + timeout)
        # Проверка разрыва и вставка — под одним локом с _mark_conn_lost (см. request):
        # слот, вставленный после ухода reader'а, не вынул бы уже никто.
        with self._pending_lock:
            lost = self._conn_lost
            if not lost:
                self._pending[cid] = pending
        if lost:
            _fire(on_response, {"success": False, "error": "connection lost", "request_id": cid})
            return cid
        try:
            sent = self._send_raw(message)
            error = None if sent else "dropped"
        except (ConnectionError, OSError) as exc:
            error = "connection lost" if self._conn_lost else f"connection closed: {exc}"
        if error is not None:
            # Слот снимает тот, кто его вынул: если close()/разрыв/ответ успели раньше,
            # колбэк уже позван — второго не будет (ровно один раз).
            with self._pending_lock:
                mine = self._pending.pop(cid, None)
            if mine is not None:
                _fire(on_response, {"success": False, "error": error, "request_id": cid})
        return cid

    def send_nowait(self, message: Dict[str, Any]) -> None:
        """Fire-and-forget: отправить, ответа не ждать.

        Хост отвечает на КАЖДОЕ входящее; этот ответ уходит в карантин (I3) и не
        всплывает push-событием. Ошибка обработки на хосте поэтому не видна —
        как на очередях.

        Pre:  ``message`` — JSON-сериализуемый dict.
        Post: ``request_id`` проставлен (если не было), ``reply_to`` (если задан) — ``setdefault``;
              сообщение записано в сокет до возврата.
        Raises: ``_lost_exc`` — соединение мертво; ``ConnectionError`` — не подключён
              или закрыт. Middleware вернул ``None`` → молча не отправлено.
        """
        if self._conn_lost:
            raise self._lost_exc(self._conn_lost_message())
        cid = message.get("request_id") or str(uuid.uuid4())
        message["request_id"] = cid
        if self._reply_to:
            message.setdefault("reply_to", self._reply_to)
        # Карантин ДО записи: ответ хоста может прийти раньше, чем вернётся sendall.
        # Проверка разрыва — под тем же локом, что вставка (см. request).
        with self._pending_lock:
            lost = self._conn_lost
            if not lost:
                self._pending[cid] = _Pending(deadline=time.monotonic() + _TIMED_OUT_TTL_SEC, nowait=True)
        if lost:
            raise self._lost_exc(self._conn_lost_message(request_id=cid))
        try:
            sent = self._send_raw(message)
        except BaseException:
            with self._pending_lock:
                self._pending.pop(cid, None)
            if self._conn_lost:
                raise self._lost_exc(self._conn_lost_message(request_id=cid)) from None
            raise
        if not sent:
            with self._pending_lock:
                self._pending.pop(cid, None)

    def add_send_middleware(self, fn: SendMiddleware) -> None:
        """Зарегистрировать send-middleware (I1). Переживает реконнект.

        Pre:  ``fn(msg) -> msg | None`` — мутирует/возвращает сообщение; ``None`` =
              не отправлять.
        Post: применяется ко ВСЕМ последующим исходящим (``request``, ``request_async``,
              ``send_nowait``) в порядке регистрации, до сериализации; исключение ``fn``
              не роняет отправку (сообщение уходит как есть).
        """
        self._send_middleware = (*self._send_middleware, fn)

    # ------------------------------------------------------------------ входящие

    def add_push_listener(self, fn: PushHandler) -> None:
        """Добавить получателя push-сообщений (I2). Переживает реконнект.

        Post: каждое push-сообщение доставляется ``on_push`` и затем всем слушателям в
              порядке регистрации, на reader-потоке; исключение одного не мешает
              остальным и не роняет reader-поток.
        """
        self._push_listeners = (*self._push_listeners, fn)

    def dispatch_raw(self, raw: bytes) -> None:
        """Инъекция одной «проводной» строки, как если бы её прочёл reader (для тестов).

        Post: невалидный JSON / не-dict — тихо игнорируется; иначе — разбор по I2/I3
              в текущем потоке.
        """
        self._dispatch(raw)

    # ------------------------------------------------------------------ состояние

    @property
    def session(self) -> Optional[str]:
        """Идентификатор текущего соединения; ``None`` до первого ``connect``."""
        return self._session

    @property
    def subscriber_address(self) -> Optional[str]:
        """``f"{door}.{session}"`` — адрес push-получателя этого соединения (I5);
        ``None`` до первого ``connect``."""
        return None if self._session is None else self._subscriber

    @property
    def connection_lost(self) -> bool:
        """``True`` после неожиданного разрыва; сбрасывается следующим ``connect``."""
        return bool(self._conn_lost)

    @property
    def late_replies(self) -> int:
        """Сколько ответов на таймаутнутые :meth:`request` дропнуто (I3)."""
        return self._late_replies

    # ------------------------------------------------------------------ хуки шима

    def _handle_push(self, msg: Dict[str, Any]) -> None:
        """Доставка push (дефолт: ``on_push`` + слушатели)."""
        handlers = (self._on_push, *self._push_listeners) if self._on_push is not None else self._push_listeners
        for fn in handlers:
            try:
                fn(msg)
            except Exception:  # noqa: BLE001 — слушатель не должен ронять reader
                _log.exception("socket_client: исключение в push-слушателе")

    def _on_closed(self) -> None:
        """Вызывается в конце :meth:`close` (дефолт no-op)."""

    def _on_conn_lost(self) -> None:
        """Вызывается после фиксации разрыва (дефолт no-op)."""

    def _conn_lost_message(self, *, request_id: Optional[str] = None) -> str:
        """Текст исключения разрыва: хост:порт, причина, ``request_id``."""
        reason = self._conn_lost_reason or "соединение оборвано"
        tail = f" (request_id={request_id})" if request_id else ""
        return f"соединение с {self._host}:{self._port} оборвано: {reason}{tail}"

    # ------------------------------------------------------------------ внутреннее

    def _send_raw(self, message: Dict[str, Any]) -> bool:
        """Единственная точка записи (I1). ``False`` — middleware отказал, не отправлено."""
        if self._session is not None:
            message.setdefault("session", self._session)
        msg: Dict[str, Any] = message
        for fn in self._send_middleware:
            try:
                out = fn(msg)
            except Exception:  # noqa: BLE001 — сбой middleware не роняет отправку
                _log.exception("socket_client: исключение в send-middleware")
                continue
            if out is None:
                return False
            msg = out
        line = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        with self._write_lock:
            sock = self._sock
            if sock is None:
                # close() из другого потока обнулил сокет — штатная ConnectionError.
                raise ConnectionError("socket closed")
            sock.sendall(line)
        return True

    def _quarantine_timed_out(self, cid: str) -> None:
        """Пометить request_id как таймаутнутый + лениво вычистить протухшие (I3)."""
        now = time.monotonic()
        with self._pending_lock:
            if self._timed_out:
                for stale in [k for k, exp in self._timed_out.items() if exp <= now]:
                    del self._timed_out[stale]
            self._timed_out[cid] = now + _TIMED_OUT_TTL_SEC

    def _wake_slots(self, slots: list, error: str) -> None:
        """Разбудить вынутые из реестра слоты: sync — event, async — колбэк с ошибкой.

        Слоты уже СНЯТЫ из ``_pending`` вызывающим — поэтому колбэк каждого async-слота
        зовётся ровно один раз (второй вынуть нечего).
        """
        for cid, p in slots:
            if p.callback is not None:
                _fire(p.callback, {"success": False, "error": error, "request_id": cid})
            elif not p.nowait:
                p.event.set()

    def _expire_slots(self) -> None:
        """Таймауты request_async и протухание карантина send_nowait (зовёт reader)."""
        now = time.monotonic()
        with self._pending_lock:
            expired = [(cid, p) for cid, p in self._pending.items() if p.deadline is not None and p.deadline <= now]
            for cid, p in expired:
                del self._pending[cid]
                if p.callback is not None:
                    # Поздний ответ на таймаутнутый async — в карантин, не в push (I3).
                    self._timed_out[cid] = now + _TIMED_OUT_TTL_SEC
        for cid, p in expired:
            if p.callback is not None:
                _fire(p.callback, {"success": False, "error": "timeout", "request_id": cid})

    def _read_loop(self) -> None:
        buf = b""
        while self._running:
            # Локальная ссылка под _write_lock: close() из другого потока обнуляет _sock.
            with self._write_lock:
                sock = self._sock
            if sock is None:
                break
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                self._expire_slots()
                continue
            except (OSError, AttributeError) as exc:
                # Штатное закрытие (_running=False) — молча; неожиданный обрыв — в лог.
                if self._running:
                    _log.warning("%s: обрыв соединения при recv (%s)", self._reader_thread_name, exc)
                    self._mark_conn_lost(f"обрыв при recv ({exc})")
                break
            if not chunk:
                if self._running:
                    _log.warning("%s: сервер закрыл соединение", self._reader_thread_name)
                    self._mark_conn_lost("сервер закрыл соединение")
                break
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                if raw.strip():
                    self._dispatch(raw)
            self._expire_slots()

    def _mark_conn_lost(self, reason: str) -> None:
        """Объявить соединение мёртвым и разбудить всех ожидающих (I4).

        Зовётся ТОЛЬКО reader-потоком и ТОЛЬКО при неожиданной смерти (``_running`` ещё
        True) — намеренный :meth:`close` сюда не попадает. Синхронные слоты НЕ вынимаются:
        их снимает ``finally`` в :meth:`request` (владелец). Async- и nowait-слоты
        вынимаются здесь — у них нет владельца, который снял бы их сам.
        """
        self._conn_lost_reason = reason
        with self._pending_lock:
            # Флаг — под локом реестра: вставка слота (request/request_async/send_nowait)
            # проверяет его под тем же локом, так что слот либо попадает в этот снимок,
            # либо видит флаг и не вставляется.
            self._conn_lost = True
            sync_slots = [p for p in self._pending.values() if p.callback is None and not p.nowait]
            orphan = [(cid, p) for cid, p in self._pending.items() if p.callback is not None or p.nowait]
            for cid, _ in orphan:
                del self._pending[cid]
        for p in sync_slots:
            p.event.set()
        self._wake_slots(orphan, "connection lost")
        self._on_conn_lost()

    def _dispatch(self, raw: bytes) -> None:
        """Разобрать входящую строку: ответ ожидающему (I2), карантин (I3) или push."""
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
                if pending is not None and (pending.callback is not None or pending.nowait):
                    # async/nowait-слот снимается тем, кто его нашёл (ровно один раз).
                    del self._pending[cid]
                is_late = pending is None and cid in self._timed_out
                if is_late:
                    del self._timed_out[cid]
                    # Под тем же локом: dispatch_raw публичный, «только reader» не опора.
                    self._late_replies += 1
            if pending is not None:
                if pending.callback is not None:
                    _fire(pending.callback, msg.get("result", msg))
                elif not pending.nowait:
                    pending.response = msg
                    pending.event.set()
                return
            if is_late:
                return
        # Нет request_id либо ответ никто не ждёт (и это не карантин) → push.
        self._handle_push(msg)


__all__ = ["SocketClient", "SocketConnectionLost", "PushHandler", "SendMiddleware", "ResponseCallback"]
