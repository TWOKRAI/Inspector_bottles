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

from typing import Any, Callable, Dict, Optional

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
        client.add_push_listener(self._on_push)

    def _marshal_deltas(self, deltas: list) -> None:
        # S2: кэш уже обновлён на reader-потоке; колбэки подписчиков — через dispatch.
        self._dispatch(lambda: self._invoke_callbacks(deltas))

    def _on_push(self, msg: Dict[str, Any]) -> None:
        # S3: один клиент делят несколько потребителей — берём только state.changed.
        if msg.get("command") == "state.changed":
            self.on_state_changed(msg)

    def on_reconnected(self) -> None:
        """Восстановить подписки после ``client.connect()`` с новым ``session``.

        Шаг 4 протокола реконнекта (докстринг ``socket_client``); вызывает владелец
        соединения, не reader-поток.

        Pre:  клиент подключён заново (``client.subscriber_address`` — новый адрес);
              вызов не с reader-потока клиента.
        Post: ``process_name == client.subscriber_address`` (S1);
              для КАЖДОГО уникального активного паттерна (``_sub_patterns``) хосту отправлен
              ``state.subscribe`` под новым адресом — локальные ``sub_id`` и колбэки НЕ
              меняются (подписчики ничего не перерегистрируют);
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
        for pattern in patterns:
            msg = {
                "type": "command",
                "sender": name,
                "targets": [self._server_target],
                "command": "state.subscribe",
                "data": {"pattern": pattern, "subscriber": name, "exclude_sources": [name]},
            }
            try:
                envelope = self._client.request(msg, timeout=self._SYNC_REQUEST_TIMEOUT)
            except self._client._lost_exc:
                raise
            except Exception as exc:  # noqa: BLE001 — отказ одного паттерна не рвёт остальные
                self._log_error(f"RemoteStateProxy.on_reconnected: '{pattern}' не переподписан: {exc}")
                continue
            if self._unwrap_envelope(envelope) is None:
                self._log_error(f"RemoteStateProxy.on_reconnected: хост отказал '{pattern}': {envelope}")
        # Хост мог перезапуститься: старая база revision у него не валидна, а изменения
        # за время разрыва приходят снимком.
        self._last_revision = None
        self._resync(patterns)


__all__ = ["RemoteStateProxy", "Dispatch"]
