"""socket_client.py — клиентская половина :class:`SocketChannel` (Task 1.2, gui-service).

Контракт-в-коде (module-contract, уровень lite). Стадия INTERFACE: тела методов
``raise NotImplementedError``; реализация — перенос ``_TransportMixin`` на стадии GREEN.

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
    :attr:`subscriber_address` = ``f"{sender}.{session}"`` меняется вместе с ним.
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

from typing import Any, Callable, Dict, Optional

PushHandler = Callable[[Dict[str, Any]], None]
SendMiddleware = Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]
ResponseCallback = Callable[[Dict[str, Any]], None]


class SocketConnectionLost(RuntimeError):
    """Соединение с хостом оборвалось неожиданно (не намеренный :meth:`SocketClient.close`)."""


class SocketClient:
    """Клиент сокетного канала хоста: request/response по ``request_id`` + push.

    Invariants: см. I1–I5 в докстринге модуля.
    """

    _lost_exc: type[BaseException] = SocketConnectionLost
    _reader_thread_name: str = "socket-client-reader"

    def __init__(
        self,
        host: str,
        port: int,
        *,
        sender: str,
        reply_to: str = "ProcessManager",
        default_timeout: float = 5.0,
        on_push: PushHandler | None = None,
    ) -> None:
        """Сконфигурировать клиент; соединения НЕ открывает.

        Pre:  ``port`` в 0..65535; ``default_timeout > 0``; ``sender`` — непустое
              имя канала хоста, к которому подключаемся (префикс адреса push-получателя,
              см. I5 — хост разрешает ``<канал>.<session>`` в сокет только при совпадении).
        Post: ``connection_lost is False``; ``session is None``; ``late_replies == 0``;
              ``on_push`` (если задан) — первый push-обработчик.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------ жизненный цикл

    def connect(self, timeout: float = 5.0) -> None:
        """Открыть соединение и запустить reader-поток.

        Pre:  клиент не подключён (первый вызов либо после :meth:`close`/разрыва);
              повторный ``connect`` на живом соединении не проверяется (паритет с шимом).
        Post: новый ``session`` (12 hex), отличный от предыдущего; ``subscriber_address``
              обновлён; ``connection_lost is False``; reader-поток жив.
        Raises: ``OSError`` — хост недоступен за ``timeout`` (состояние как до вызова).
        """
        raise NotImplementedError

    def close(self) -> None:
        """Закрыть соединение намеренно. Идемпотентен.

        Post: сокет закрыт; reader-поток завершён (join ≤ 1 с); все ожидающие
              :meth:`request` разбужены и вернули ``{"success": False, "error":
              "connection closed", ...}`` (НЕ исключение); ожидающие :meth:`request_async`
              получили колбэк с ошибкой ровно один раз; ``connection_lost`` не меняется;
              вызван ``_on_closed()``.
        """
        raise NotImplementedError

    def __enter__(self) -> "SocketClient":
        """``connect()`` и вернуть себя."""
        raise NotImplementedError

    def __exit__(self, *exc: Any) -> None:
        """``close()``."""
        raise NotImplementedError

    # ------------------------------------------------------------------ исходящие

    def request(self, message: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        """Отправить сообщение и дождаться ответа по ``request_id`` (блокирует).

        Pre:  ``message`` — JSON-сериализуемый dict; вызов НЕ с reader-потока.
        Post: в ``message`` проставлены ``request_id`` (если не было), ``reply_to``
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
        raise NotImplementedError

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
        raise NotImplementedError

    def send_nowait(self, message: Dict[str, Any]) -> None:
        """Fire-and-forget: отправить, ответа не ждать.

        Хост отвечает на КАЖДОЕ входящее; этот ответ уходит в карантин (I3) и не
        всплывает push-событием. Ошибка обработки на хосте поэтому не видна —
        как на очередях.

        Pre:  ``message`` — JSON-сериализуемый dict.
        Post: ``request_id`` проставлен (если не было), ``reply_to`` — ``setdefault``;
              сообщение записано в сокет до возврата.
        Raises: ``_lost_exc`` — соединение мертво; ``ConnectionError`` — не подключён
              или закрыт. Middleware вернул ``None`` → молча не отправлено.
        """
        raise NotImplementedError

    def add_send_middleware(self, fn: SendMiddleware) -> None:
        """Зарегистрировать send-middleware (I1). Переживает реконнект.

        Pre:  ``fn(msg) -> msg | None`` — мутирует/возвращает сообщение; ``None`` =
              не отправлять.
        Post: применяется ко ВСЕМ последующим исходящим (``request``, ``request_async``,
              ``send_nowait``) в порядке регистрации, до сериализации; исключение ``fn``
              не роняет отправку (сообщение уходит как есть).
        """
        raise NotImplementedError

    # ------------------------------------------------------------------ входящие

    def add_push_listener(self, fn: PushHandler) -> None:
        """Добавить получателя push-сообщений (I2). Переживает реконнект.

        Post: каждое push-сообщение доставляется ``on_push`` и затем всем слушателям в
              порядке регистрации, на reader-потоке; исключение одного не мешает
              остальным и не роняет reader-поток.
        """
        raise NotImplementedError

    def dispatch_raw(self, raw: bytes) -> None:
        """Инъекция одной «проводной» строки, как если бы её прочёл reader (для тестов).

        Post: невалидный JSON / не-dict — тихо игнорируется; иначе — разбор по I2/I3
              в текущем потоке.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------ состояние

    @property
    def session(self) -> Optional[str]:
        """Идентификатор текущего соединения; ``None`` до первого ``connect``."""
        raise NotImplementedError

    @property
    def subscriber_address(self) -> Optional[str]:
        """``f"{sender}.{session}"`` — адрес push-получателя этого соединения (I5);
        ``None`` до первого ``connect``."""
        raise NotImplementedError

    @property
    def connection_lost(self) -> bool:
        """``True`` после неожиданного разрыва; сбрасывается следующим ``connect``."""
        raise NotImplementedError

    @property
    def late_replies(self) -> int:
        """Сколько ответов на таймаутнутые :meth:`request` дропнуто (I3)."""
        raise NotImplementedError

    # ------------------------------------------------------------------ хуки шима

    def _handle_push(self, msg: Dict[str, Any]) -> None:
        """Доставка push (дефолт: ``on_push`` + слушатели)."""
        raise NotImplementedError

    def _on_closed(self) -> None:
        """Вызывается в конце :meth:`close` (дефолт no-op)."""

    def _on_conn_lost(self) -> None:
        """Вызывается после фиксации разрыва (дефолт no-op)."""

    def _conn_lost_message(self, *, request_id: Optional[str] = None) -> str:
        """Текст исключения разрыва: хост:порт, причина, ``request_id``."""
        raise NotImplementedError


__all__ = ["SocketClient", "SocketConnectionLost", "PushHandler", "SendMiddleware", "ResponseCallback"]
