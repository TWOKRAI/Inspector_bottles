"""Registrar: императивное применение RouterTopology к IRouterManager.

Часть C (Task 9.5): apply_topology() — мост между декларативной топологией и
императивным API RouterManager (register_channel, register_route, register_broadcast_route).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from multiprocess_framework.modules.router_module.channels import QueueChannel
from multiprocess_framework.modules.router_module.interfaces import IRouterManager

from .builder import ChannelSpec, RouterTopology

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ApplyResult — infrastructure-meta (dataclass, не SchemaBase)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """Статистика применения топологии.

    Это внутренний infrastructure-meta объект (не пересекает границ модуля,
    не показывается UI), поэтому допустим @dataclass вместо SchemaBase.
    """

    channels_added: int = 0
    channels_removed: int = 0
    routes_added: int = 0
    routes_removed: int = 0
    broadcast_routes_added: int = 0


# ---------------------------------------------------------------------------
# Приватные хелперы
# ---------------------------------------------------------------------------


def _create_channel(spec: ChannelSpec) -> QueueChannel:
    """Создать QueueChannel из ChannelSpec.

    Используем готовый QueueChannel из framework — in-process Queue-канал.
    Task 9.6 заменит на SHM для cross-process (по ChannelSpec.cross_process).
    """
    return QueueChannel(name=spec.channel_name)


def _channel_set(topology: RouterTopology) -> set[str]:
    """Множество имён каналов из топологии (для diff-сравнения)."""
    return {ch.channel_name for ch in topology.channels}


def _route_set(topology: RouterTopology) -> set[tuple[str, str]]:
    """Множество (source_channel, target_channel) пар из edges.

    Используется для diff рёбер. target_channel вычисляется как
    '{target_node_id}.{target_input_port}' (упрощение — совпадает с
    тем как to_router_topology формирует broadcast_routes).
    """
    pairs: set[tuple[str, str]] = set()
    for edge in topology.edges:
        # В topology.broadcast_routes уже сгруппированы fan-out.
        # Одиночные маршруты — те source_channel, которых НЕТ в broadcast_routes.
        pairs.add((edge.source_channel, f"{edge.target_node_id}.{edge.target_input_port}"))
    return pairs


def _register_channels(router: IRouterManager, topology: RouterTopology) -> int:
    """Зарегистрировать все каналы из топологии. Возвращает кол-во добавленных."""
    count = 0
    for spec in topology.channels:
        ch = _create_channel(spec)
        if router.register_channel(ch):
            count += 1
    return count


def _register_routes(router: IRouterManager, topology: RouterTopology) -> int:
    """Зарегистрировать одиночные маршруты (1:1 edges).

    Broadcast-маршруты (fan-out) регистрируются отдельно через _register_broadcast_routes.
    Одиночный edge — тот, чей source_channel НЕ входит в broadcast_routes.
    """
    count = 0
    broadcast_sources = set(topology.broadcast_routes.keys())

    for edge in topology.edges:
        if edge.source_channel in broadcast_sources:
            # Будет зарегистрирован как broadcast
            continue
        # target_channel_name: '{target_node_id}.{target_input_port}'
        target_ch = f"{edge.target_node_id}.{edge.target_input_port}"
        if router.register_route(key=edge.source_channel, channel_name=target_ch):
            count += 1

    return count


def _register_broadcast_routes(router: IRouterManager, topology: RouterTopology) -> int:
    """Зарегистрировать broadcast-маршруты (fan-out: один source → несколько targets)."""
    count = 0
    for source_ch, target_channels in topology.broadcast_routes.items():
        if router.register_broadcast_route(key=source_ch, channel_names=target_channels):
            count += 1
    return count


def _remove_obsolete_channels(
    router: IRouterManager,
    old_channels: set[str],
    new_channels: set[str],
) -> int:
    """Удалить каналы, которые были в previous, но отсутствуют в current."""
    to_remove = old_channels - new_channels
    count = 0
    for ch_name in to_remove:
        if router.unregister_channel(ch_name):
            count += 1
        else:
            logger.warning("Не удалось unregister канал '%s'", ch_name)
    return count


# ---------------------------------------------------------------------------
# Публичное API
# ---------------------------------------------------------------------------


def apply_topology(
    router: IRouterManager,
    topology: RouterTopology,
    *,
    previous: Optional[RouterTopology] = None,
) -> ApplyResult:
    """Императивно применить топологию к Router.

    Если передан previous — выполняется DIFF: удаляются устаревшие каналы/маршруты,
    затем добавляются новые. Это позволяет UI изменять граф без рестарта процессов.

    Без previous — полная регистрация всех каналов и маршрутов.

    Note: RouterManager не предоставляет unregister_route() напрямую.
    Для обновления маршрутов используем replacement-подход: register_route()
    при повторном вызове перезаписывает handler в dispatcher'е (register_handler
    заменяет существующий handler для того же key). Для broadcast аналогично —
    register_broadcast_route() заменяет handler.
    Для удалённых каналов — unregister_channel() убирает канал, и маршруты
    к нему становятся «мёртвыми» (router вернёт ошибку при отправке).

    Returns:
        ApplyResult — статистика операции.
    """
    channels_removed = 0

    if previous is not None:
        # Diff: удалить устаревшие каналы
        old_ch = _channel_set(previous)
        new_ch = _channel_set(topology)
        channels_removed = _remove_obsolete_channels(router, old_ch, new_ch)

        logger.info(
            "apply_topology DIFF: удалено %d каналов, %d осталось",
            channels_removed,
            len(new_ch),
        )

    # Регистрация каналов (для новых — добавление, для существующих — замена с warning)
    channels_added = _register_channels(router, topology)

    # Маршруты: одиночные + broadcast
    routes_added = _register_routes(router, topology)
    broadcast_added = _register_broadcast_routes(router, topology)

    result = ApplyResult(
        channels_added=channels_added,
        channels_removed=channels_removed,
        routes_added=routes_added,
        routes_removed=0,  # router_module не имеет unregister_route — используем replacement
        broadcast_routes_added=broadcast_added,
    )

    logger.info(
        "apply_topology: channels +%d/-%d, routes +%d, broadcasts +%d",
        result.channels_added,
        result.channels_removed,
        result.routes_added,
        result.broadcast_routes_added,
    )

    return result


__all__ = ["ApplyResult", "apply_topology"]
