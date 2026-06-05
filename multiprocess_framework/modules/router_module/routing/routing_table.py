# -*- coding: utf-8 -*-
"""
Таблица маршрутизации «kind → канал» (контракт P0.2 transport-router-hub).

Замысел: ``RouterManager.send`` выбирает ОДИН канал по типу груза. Канонический
ключ выбора — **channel-kind** (system/data/event/state/log), а имя канала в
``ChannelRegistry`` склеивается с адресом получателя: ``f"{process}_{kind}"``
(совпадает с уже существующими очередями ``{proc}_system`` / ``{proc}_data``).

Почему НЕ просто ``MessageType → channel`` (находка recon #1):
  На живых билетах поле ``type`` НЕ всегда соответствует целевому каналу —
  диспатч исторически идёт по ``command``, а ``type`` вторичен. Примеры:
    - state-телеметрия (``DeltaDispatcher``): ``type="event"``, но семантика STATE
      (``command="state.changed"``);
    - ``state.set``/``state.merge``: ``type="command"``, семантика STATE;
    - heartbeat: ``type="system"`` + ``command="heartbeat"``.
  Поэтому канал резолвится **с нормализацией**: сперва override по префиксу
  ``command``, затем таблица по ``MessageType``. STATE — это channel-kind,
  выводимый из ``command="state.*"``, а НЕ член enum ``MessageType``
  (его не вводим — план запрещает новые ``kind``).

Этот модуль — только ДЕКЛАРАЦИЯ контракта (таблица + чистый резолвер). Проводка
в рантайм (``register_route`` при init процесса, использование в
``_resolve_channels``) — P1, вне scope P0.2.
"""

from typing import Mapping

from ...message_module import MessageType

# --- channel-kind: строковые константы (НЕ новый enum — переиспользуем суффиксы
#     очередей, уже принятые в receive(channel_types=[...]) и {proc}_system/{proc}_data) ---
SYSTEM = "system"
DATA = "data"
EVENT = "event"
STATE = "state"
LOG = "log"

#: Полный набор канонических channel-kind.
CHANNEL_KINDS = frozenset({SYSTEM, DATA, EVENT, STATE, LOG})


class UnknownMessageTypeError(ValueError):
    """Канал не выводится: ``type`` вне ``MessageType`` и ``command`` не покрыт префиксами.

    Бросается вместо тихого drop'а (реализует требование P1.2 «неизвестный type
    не теряется молча»).
    """

    pass


#: База: MessageType → channel-kind. Объявляется как набор маршрутов, которые в P1
#: будут заведены через ``RouterManager.register_route(MessageType.value, channel)``.
MESSAGE_TYPE_TO_CHANNEL: "dict[MessageType, str]" = {
    MessageType.COMMAND: SYSTEM,
    MessageType.SYSTEM: SYSTEM,
    MessageType.REQUEST: SYSTEM,
    MessageType.RESPONSE: SYSTEM,
    MessageType.GENERAL: SYSTEM,
    MessageType.BROADCAST: SYSTEM,  # fan-out резолвится по адресу, не по kind
    MessageType.DATA: DATA,
    MessageType.EVENT: EVENT,
    MessageType.LOG: LOG,
}

#: Override по префиксу ``command`` — нормализация ДО таблицы (recon #1).
#: Порядок важен: первый совпавший префикс выигрывает.
COMMAND_PREFIX_TO_CHANNEL: "tuple[tuple[str, str], ...]" = (("state.", STATE),)


def resolve_channel_kind(msg: Mapping) -> str:
    """Определить channel-kind билета (нормализация ``command``/``type`` → kind).

    Порядок резолва:
      1. ``command`` совпал с префиксом из ``COMMAND_PREFIX_TO_CHANNEL`` → его kind
         (так STATE-трафик ловится независимо от литерала ``type``);
      2. иначе ``type`` → ``MessageType`` → ``MESSAGE_TYPE_TO_CHANNEL``.

    Raises:
        UnknownMessageTypeError: если ``type`` не входит в ``MessageType`` и
            ``command`` не покрыт префиксами. Напр. ``type="system_event"`` (B10)
            — будет нормализован при миграции EventChannel (P3.3); здесь намеренно
            громко падаем, а не мимо-роутим.
    """
    command = msg.get("command")
    if command:
        for prefix, kind in COMMAND_PREFIX_TO_CHANNEL:
            if command.startswith(prefix):
                return kind

    raw_type = msg.get("type")
    try:
        mt = MessageType(raw_type)
    except ValueError as exc:
        raise UnknownMessageTypeError(
            f"Не удаётся определить канал: type={raw_type!r} не входит в MessageType, "
            f"command={command!r} не покрыт COMMAND_PREFIX_TO_CHANNEL"
        ) from exc
    return MESSAGE_TYPE_TO_CHANNEL[mt]


def channel_name(process: str, kind: str) -> str:
    """Имя канала в ``ChannelRegistry`` для пары (процесс, channel-kind).

    Конвенция совпадает с существующими очередями: ``"{proc}_system"``, ``"{proc}_data"``.
    Это «склейка» оси адреса (куда) и оси kind (что за груз) в один ключ канала.
    """
    return f"{process}_{kind}"
