"""remote_state_proxy.py — :class:`GuiStateProxy` поверх сокета (Task 1.2, gui-service).

Контракт-в-коде (module-contract, уровень lite).

Назначение
----------
Внешний GUI читает и пишет дерево состояния хоста тем же объектом, что встроенный:
``RemoteStateProxy`` — подкласс :class:`GuiStateProxy` (контракт ``IStateProxy``), поэтому
кэш, revision/resync, ``ensure_subscription``/``release_subscription`` наследуются.
Под ним — не ``RouterManager`` процесса, а адаптер ``IRouter`` над :class:`SocketClient`:
    ``send`` / ``send_async``  → ``client.send_nowait``;
    ``request``                → ``client.request``;
    ``request_async``          → ``client.request_async`` (ресинк не блокирует reader-поток);
push ``state.changed`` приходит через ``client.add_push_listener`` → ``on_state_changed``.
Хост не правится: обработчики ``state.*`` уже есть, push адресуется по ``subscriber``.
Qt-free.

Инварианты
----------
S1. Имя процесса прокси (``process_name``: ``sender``/``source``/``subscriber`` всех
    ``state.*``) == ``client.subscriber_address`` ТЕКУЩЕГО соединения — иначе хост не
    доставит push этому сокету. После реконнекта имя сменится (I5 ``socket_client``) и
    станет верным только после :meth:`on_reconnected`.
S2. Колбэки подписчиков (``callback(list[Delta])``) НИКОГДА не исполняются на reader-потоке
    клиента: кэш обновляется на reader-потоке, а вызов колбэков уходит в ``dispatch(fn)``.
    Сколько раз и в каком потоке ``dispatch`` выполнит ``fn`` — его контракт (Qt: очередь
    main thread; тесты: синхронно или своя очередь).
S3. Push других команд (не ``state.changed``) прокси игнорирует — один клиент делят
    несколько потребителей.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

from multiprocess_framework.modules.router_module.channels.socket_client import (
    ResponseCallback,
    SocketClient,
)
from multiprocess_framework.modules.state_store_module import GuiStateProxy

Dispatch = Callable[[Callable[[], None]], None]


class _ClientRouter:
    """``IRouter`` (+ ``request``/``request_async``) для ``StateProxy`` поверх клиента."""

    def __init__(self, client: SocketClient) -> None:
        self._client = client

    def register_message_handler(self, key: str, handler: Callable, expects_full_message: bool = True) -> None:
        # Push приходит через add_push_listener клиента, не через роутер.
        return None

    def send_async(self, message: dict, priority: str = "normal") -> None:
        self._client.send_nowait(message)

    def send(self, message: dict) -> dict | None:
        self._client.send_nowait(message)
        return None

    def request(self, message: dict, timeout: float = 5.0) -> Dict[str, Any]:
        return self._client.request(message, timeout=timeout)

    def request_async(
        self,
        message: dict,
        on_response: ResponseCallback,
        timeout: float = 5.0,
        correlation_id: Optional[str] = None,
    ) -> str:
        return self._client.request_async(message, on_response, timeout=timeout, correlation_id=correlation_id)


class RemoteStateProxy(GuiStateProxy):
    """``GuiStateProxy``, чей транспорт — :class:`SocketClient`.

    ``get``/``get_subtree``/``set``/``merge``/``delete``/``subscribe``/``unsubscribe``/
    ``ensure_subscription``/``release_subscription``/``shutdown`` — унаследованы, семантика
    ``StateProxy`` без изменений (``set`` — fire-and-forget, как на очередях; ``subscribe``
    с ``sync=True`` блокирует — не с Qt main thread и не с reader-потока).
    """

    def __init__(
        self,
        client: SocketClient,
        *,
        dispatch: Dispatch,
        logger: Any = None,
    ) -> None:
        """Pre:  ``client`` подключён (``client.subscriber_address is not None``);
              ``dispatch`` — callable, принимающий нуль-арную функцию.
        Post: ``process_name == client.subscriber_address`` (S1); ``server_target`` —
              дефолт ``GuiStateProxy`` (``"ProcessManager"``); push-слушатель
              ``state.changed`` зарегистрирован в клиенте (ровно один на экземпляр);
              ``delta_sink`` маршалит вызов колбэков через ``dispatch`` (S2);
              ни одного сетевого вызова в конструкторе.
        """
        name = client.subscriber_address
        if name is None:
            raise ValueError("RemoteStateProxy: клиент не подключён (subscriber_address is None)")
        self._client = client
        self._dispatch = dispatch
        super().__init__(
            name,
            router=_ClientRouter(client),
            delta_sink=self._marshal_deltas,
            manager_name=f"RemoteStateProxy:{client._sender}",
            logger=logger,
        )
        # exclude_self каждой подписки: при переподписке после реконнекта он обязан
        # сохраниться (база хранит только pattern).
        self._sub_exclude_self: Dict[str, bool] = {}
        # После реконнекта: (pattern, exclude_self) → серверный sub_id НОВОГО соединения
        # (None — хост не вернул id). Пусто до первого on_reconnected: тогда sub_id
        # подписки и есть серверный (база), перевод не нужен.
        self._resubscribed: Dict[Tuple[str, bool], Optional[str]] = {}
        # sub_id → что слать хосту в state.unsubscribe вместо него (None — не слать);
        # заполняется на время вызова unsubscribe (см. _send).
        self._unsub_translate: Dict[str, Optional[str]] = {}
        client.add_push_listener(self._on_push)

    def _marshal_deltas(self, deltas: list) -> None:
        # S2: кэш уже обновлён на reader-потоке; колбэки подписчиков — через dispatch.
        self._dispatch(lambda: self._invoke_callbacks(deltas))

    def _on_push(self, msg: Dict[str, Any]) -> None:
        # S3: один клиент делят несколько потребителей — берём только state.changed.
        if msg.get("command") == "state.changed":
            self.on_state_changed(msg)

    def subscribe(self, pattern: str, callback: Callable, exclude_self: bool = True, sync: bool = True) -> str:
        sub_id = super().subscribe(pattern, callback, exclude_self=exclude_self, sync=sync)
        self._sub_exclude_self[sub_id] = exclude_self
        return sub_id

    def unsubscribe(self, sub_id: str) -> None:
        """После реконнекта серверная подписка — одна на (pattern, exclude_self), со
        своим sub_id нового соединения: отписка шлёт ЕГО и только когда снимается
        последняя локальная подписка этой пары. До реконнекта — поведение базы."""
        exclude_self = self._sub_exclude_self.pop(sub_id, True)
        pattern = self._sub_patterns.get(sub_id)
        key = (pattern, exclude_self)
        if pattern is None or key not in self._resubscribed or sub_id in self._covered_sub_ids:
            super().unsubscribe(sub_id)
            return
        siblings = [
            other
            for other, other_pattern in self._sub_patterns.items()
            if other != sub_id
            and other_pattern == pattern
            and other not in self._covered_sub_ids
            and self._sub_exclude_self.get(other, True) == exclude_self
        ]
        self._unsub_translate[sub_id] = None if siblings else self._resubscribed[key]
        if not siblings:
            del self._resubscribed[key]
        try:
            super().unsubscribe(sub_id)
        finally:
            self._unsub_translate.pop(sub_id, None)

    def _send(self, msg: dict) -> None:
        if msg.get("command") == "state.unsubscribe":
            data = msg.get("data") or {}
            sub_id = data.get("sub_id")
            if sub_id in self._unsub_translate:
                server_id = self._unsub_translate[sub_id]
                if server_id is None:
                    return  # серверная подписка ещё нужна другим (или id неизвестен)
                msg = {**msg, "data": {**data, "sub_id": server_id}}
        super()._send(msg)

    def on_reconnected(self) -> None:
        """Восстановить подписки после ``client.connect()`` с новым ``session``.

        Шаг 4 протокола реконнекта (докстринг ``socket_client``); вызывает владелец
        соединения, не reader-поток.

        Pre:  клиент подключён заново (``client.subscriber_address`` — новый адрес);
              вызов не с reader-потока клиента.
        Post: ``process_name == client.subscriber_address`` (S1);
              для КАЖДОЙ уникальной пары (паттерн, ``exclude_self``) непокрытых подписок
              хосту отправлен ``state.subscribe`` под новым адресом — локальные ``sub_id``
              и колбэки НЕ меняются (подписчики ничего не перерегистрируют); серверный
              ``sub_id`` ответа запоминается — ``unsubscribe`` шлёт хосту его, и только
              когда снимается последняя локальная подписка этой пары;
              база revision сброшена и запущен ресинк по этим паттернам (хост мог
              перезапуститься — старая revision у него не валидна; изменения, случившиеся
              за время разрыва, приходят снимком);
              событие, которое хост опубликует ПОСЛЕ возврата, доставляется колбэку.
              Без активных подписок — только смена имени, ни одного сетевого вызова.
        Ошибки: отказ хоста на отдельном паттерне логируется и не прерывает остальные;
              ``SocketConnectionLost``/``_lost_exc`` клиента пробрасывается (соединение
              снова мёртво — решает владелец).
        """
        name = self._client.subscriber_address
        if name is None:
            raise ValueError("RemoteStateProxy.on_reconnected: клиент не подключён")
        self._process_name = name
        patterns = list(dict.fromkeys(self._sub_patterns.values()))
        if not patterns:
            return
        # Серверные подписки — на каждую уникальную пару (pattern, exclude_self) среди
        # НЕпокрытых sub_id: покрытые (coverage-check) серверной подписки не имели и не
        # получают, их дельты едут потоком покрывающей.
        keys = list(
            dict.fromkeys(
                (pattern, self._sub_exclude_self.get(sub_id, True))
                for sub_id, pattern in self._sub_patterns.items()
                if sub_id not in self._covered_sub_ids
            )
        )
        self._resubscribed = {}
        for pattern, exclude_self in keys:
            msg = {
                "type": "command",
                "sender": name,
                "targets": [self._server_target],
                "command": "state.subscribe",
                "data": {
                    "pattern": pattern,
                    "subscriber": name,
                    "exclude_sources": [name] if exclude_self else [],
                },
            }
            self._resubscribed[(pattern, exclude_self)] = None
            try:
                envelope = self._client.request(msg, timeout=self._SYNC_REQUEST_TIMEOUT)
            except self._client._lost_exc:
                raise
            except Exception as exc:  # noqa: BLE001 — отказ одного паттерна не рвёт остальные
                self._log_error(f"RemoteStateProxy.on_reconnected: '{pattern}' не переподписан: {exc}")
                continue
            response = self._unwrap_envelope(envelope)
            if response is None or response.get("status") != "ok":
                self._log_error(f"RemoteStateProxy.on_reconnected: хост отказал '{pattern}': {envelope}")
                continue
            self._resubscribed[(pattern, exclude_self)] = response.get("sub_id") or None
        # Хост мог перезапуститься: старая база revision у него не валидна, а изменения
        # за время разрыва приходят снимком.
        self._last_revision = None
        self._resync(patterns)


__all__ = ["RemoteStateProxy", "Dispatch"]
