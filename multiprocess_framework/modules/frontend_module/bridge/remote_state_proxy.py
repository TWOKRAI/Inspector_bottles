"""remote_state_proxy.py — :class:`GuiStateProxy` поверх сокета (Task 1.2, gui-service).

Контракт-в-коде (module-contract, уровень lite). Стадия INTERFACE: тела методов
``raise NotImplementedError``.

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

from typing import Any, Callable

from multiprocess_framework.modules.router_module.channels.socket_client import SocketClient
from multiprocess_framework.modules.state_store_module import GuiStateProxy

Dispatch = Callable[[Callable[[], None]], None]


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
        raise NotImplementedError

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
        raise NotImplementedError


__all__ = ["RemoteStateProxy", "Dispatch"]
