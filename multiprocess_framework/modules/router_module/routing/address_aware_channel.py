# -*- coding: utf-8 -*-
"""
Контракт address-aware канала (спека P0.2 transport-router-hub).

Что это (концепция владельца «телефонная станция»):
  Один канал на пару (процесс-получатель, channel-kind), а НЕ один канал на
  получателя. То есть 2–4 канала на процесс: ``{proc}_system`` / ``{proc}_data``
  (+ event/state). Канал — тупая труба: читает адрес из ``msg["targets"]``,
  кладёт билет в очередь процесса ``address[0]`` через нижний транспорт
  (``queue_registry``), спрятанный ЗА каналом.

Контракт реализации (P1.1, НЕ здесь):
  ``AddressAwareQueueChannel(MessageChannel)`` — подкласс существующего
  ``MessageChannel`` (НЕ новый Protocol, переиспользуем ``IMessageChannel``):
    - ``send(msg)``: для каждого получателя — :func:`resolve_route` → положить
      в очередь ``decision.process`` нужного ``decision.kind`` через
      ``queue_registry.send_to_queue``; ``decision.subpath`` (воркер+) едет в
      билете и резолвится внутри процесса-получателя (P2);
    - ``poll(timeout)``: над существующей ``queue.get`` (как сегодня в ``receive``).

Решения по находкам recon, зафиксированные этим контрактом:
  - **recon #2** (скаляр ``target`` vs список ``targets``): канал нормализует оба
    через :func:`message_module.normalize_targets`; целевой контракт — ``targets``.
  - **recon #3** (vestigial ``channel:"data"`` блокирует резолв): при оживлении
    ``send`` явный ``msg["channel"]`` у data-билетов УДАЛЯЕТСЯ из билета —
    маршрутизация идёт по kind (``DataChannel`` регистрируется под именем
    ``{proc}_data``), а не по строковому ``channel``. Решение реализуется в P1/P3.
  - **recon #4** (Claim Check SHM): payload DATA-билета сохраняет ОБА ключа
    ``shm_name`` (slot) и ``shm_actual_name`` (вкл. PID на Windows) — GUI-fallback
    открывает SHM по ``shm_actual_name`` из другого OS-процесса. Слияние двух
    middleware (P3.1) обязано сохранить оба.
  - **recon #6** (broadcast): спец-адреса ``all``/``broadcast`` НЕ являются
    иерархическими — :func:`resolve_routes` их пропускает; fan-out выражается
    отдельным путём (решение P1/P3).

Здесь — только чистый резолвер маршрута (ядро логики ``send`` будущего канала),
тестируемый без рантайма и переиспользуемый в P1.
"""

from dataclasses import dataclass, field
from typing import List, Mapping

from ...message_module import is_broadcast, normalize_targets, split_address
from .routing_table import channel_name, resolve_channel_kind


@dataclass(frozen=True)
class RouteDecision:
    """Решение о доставке одного билета одному получателю (per-target).

    Attributes:
        process: ``address[0]`` — процесс-получатель, уровень cross-process очереди.
        kind:    channel-kind груза (system/data/event/state/log).
        channel: имя канала в ``ChannelRegistry`` == ``f"{process}_{kind}"``.
        subpath: ``address[1:]`` — воркер и глубже; резолвится ВНУТРИ процесса (P2),
                 не плодит IPC-очереди.
    """

    process: str
    kind: str
    channel: str
    subpath: List[str] = field(default_factory=list)


def resolve_route(target: str, msg: Mapping) -> RouteDecision:
    """Резолв маршрута для одного получателя ``target`` и билета ``msg``.

    Combines две ортогональные оси: адрес (куда, иерархия) и kind (что за груз).

    Raises:
        AddressValidationError: невалидный dotted-адрес (см. ``split_address``).
        UnknownMessageTypeError: kind не выводится (см. ``resolve_channel_kind``).
    """
    kind = resolve_channel_kind(msg)
    parts = split_address(target)  # валидирует prefix-правило
    process = parts[0]
    return RouteDecision(
        process=process,
        kind=kind,
        channel=channel_name(process, kind),
        subpath=parts[1:],
    )


def resolve_routes(msg: Mapping) -> List[RouteDecision]:
    """Резолв маршрутов для всех получателей билета (мультикаст).

    Читает оба способа адресации (``target`` скаляр + ``targets`` список, recon #2),
    пропускает спец-адреса широковещания (recon #6 — отдельный fan-out путь).
    """
    targets = normalize_targets(target=msg.get("target"), targets=msg.get("targets"))
    return [resolve_route(t, msg) for t in targets if not is_broadcast(t)]
