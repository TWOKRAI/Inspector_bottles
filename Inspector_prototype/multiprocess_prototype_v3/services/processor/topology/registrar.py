"""Registrar: императивное применение RouterTopology к IRouterManager.

Часть C (Task 9.5): apply_topology() — мост между декларативной топологией и
императивным API RouterManager (register_channel, register_route, register_broadcast_route).

Часть B (Task 9.6): cross-process интеграция — SHM middleware для image-каналов,
динамический запуск/остановка процессов через IProcessRegistry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from multiprocess_framework.modules.router_module.channels import QueueChannel
from multiprocess_framework.modules.router_module.interfaces import IRouterManager

from .builder import ChannelSpec, EdgeSpec, RouterTopology

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
    shm_middlewares_added: int = 0
    processes_created: int = 0
    processes_stopped: int = 0


# ---------------------------------------------------------------------------
# Кеш SHM middleware (глобальный на уровне модуля, привязан к channel_name)
# ---------------------------------------------------------------------------

# channel_name → FrameShmMiddleware — защита от повторного подключения
_shm_middleware_cache: Dict[str, Any] = {}


def _reset_shm_middleware_cache() -> None:
    """Сброс кеша SHM middleware. Используется в тестах."""
    _shm_middleware_cache.clear()


# ---------------------------------------------------------------------------
# Приватные хелперы
# ---------------------------------------------------------------------------


def _create_channel(spec: ChannelSpec) -> QueueChannel:
    """Создать QueueChannel из ChannelSpec.

    Используем готовый QueueChannel из framework — in-process Queue-канал.
    Для cross-process каналов SHM middleware подключается отдельно
    через _attach_shm_middlewares().
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
    """Зарегистрировать broadcast-маршруты (fan-out: один source -> несколько targets)."""
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


def _build_channel_spec_map(topology: RouterTopology) -> Dict[str, ChannelSpec]:
    """channel_name -> ChannelSpec для быстрого lookup."""
    return {ch.channel_name: ch for ch in topology.channels}


def _attach_shm_middlewares(
    router: IRouterManager,
    topology: RouterTopology,
    memory_manager: Optional[Any],
) -> int:
    """Подключить FrameShmMiddleware для cross-process рёбер с payload_kind='image'.

    Для каждого cross-process edge с payload_kind 'image' создаёт middleware
    и подключает on_send / on_receive к router.

    Использует _shm_middleware_cache чтобы не подключать дубли при повторном apply.

    Returns:
        Количество подключённых middleware.
    """
    if memory_manager is None:
        # Без memory_manager SHM невозможен — работаем in-process
        cross_image_count = sum(
            1 for e in topology.edges
            if e.cross_process
        )
        if cross_image_count > 0:
            logger.warning(
                "memory_manager не передан — %d cross-process рёбер будут работать "
                "без SHM (только in-process QueueChannel)",
                cross_image_count,
            )
        return 0

    # Ленивый импорт — framework middleware
    from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
        FrameShmMiddleware,
    )

    channel_map = _build_channel_spec_map(topology)
    count = 0

    for edge in topology.edges:
        if not edge.cross_process:
            continue

        # Определяем payload_kind source-канала
        source_spec = channel_map.get(edge.source_channel)
        if source_spec is None:
            continue

        if source_spec.payload_kind != "image":
            # SHM middleware только для тяжёлых image данных.
            # Лёгкие payload (detections, mask) передаём через обычные каналы.
            continue

        # Проверяем кеш — не подключать дубли
        if edge.source_channel in _shm_middleware_cache:
            continue

        mw = FrameShmMiddleware(
            memory_manager=memory_manager,
            owner=source_spec.process_id,
            slot=edge.source_channel,
        )
        router.add_send_middleware(mw.on_send)
        router.add_receive_middleware(mw.on_receive)

        _shm_middleware_cache[edge.source_channel] = mw
        count += 1

        logger.info(
            "SHM middleware подключён для cross-process канала '%s' "
            "(owner=%s, payload=image)",
            edge.source_channel,
            source_spec.process_id,
        )

    return count


def _manage_dynamic_processes(
    topology: RouterTopology,
    previous: Optional[RouterTopology],
    process_registry: Optional[Any],
    process_class_path: str,
    base_worker_config: Optional[Dict[str, Any]],
) -> tuple[int, int]:
    """Создать новые и остановить устаревшие процессы через ProcessRegistry.

    Returns:
        (processes_created, processes_stopped)
    """
    if process_registry is None:
        return 0, 0

    new_pids = set(topology.process_ids)
    old_pids = set(previous.process_ids) if previous is not None else set()

    # --- Создание новых процессов ---
    to_create = new_pids - old_pids
    created = 0

    for pid in sorted(to_create):
        # Формируем конфиг с process_id для нового воркера
        config = dict(base_worker_config) if base_worker_config else {}
        config["process_id"] = pid

        result = process_registry.create_and_register(
            name=pid,
            class_path=process_class_path,
            config=config,
            priority="normal",
        )
        if result is not None:
            created += 1
            logger.info("Динамический процесс '%s' создан", pid)
        else:
            logger.error("Не удалось создать процесс '%s'", pid)

    # --- Остановка устаревших процессов ---
    to_stop = old_pids - new_pids
    stopped = 0

    for pid in sorted(to_stop):
        try:
            process_registry.stop_one(pid, timeout=5.0)
            process_registry.remove_process(pid)
            stopped += 1
            logger.info("Устаревший процесс '%s' остановлен и удалён", pid)
        except Exception as exc:
            logger.error("Ошибка при остановке процесса '%s': %s", pid, exc)

    return created, stopped


# ---------------------------------------------------------------------------
# Публичное API
# ---------------------------------------------------------------------------


def apply_topology(
    router: IRouterManager,
    topology: RouterTopology,
    *,
    previous: Optional[RouterTopology] = None,
    memory_manager: Optional[Any] = None,
    process_registry: Optional[Any] = None,
    process_class_path: str = (
        "multiprocess_prototype_v3.backend.processes.processor_worker"
        ".process.ProcessorWorkerProcess"
    ),
    base_worker_config: Optional[Dict[str, Any]] = None,
) -> ApplyResult:
    """Императивно применить топологию к Router.

    Если передан previous — выполняется DIFF: удаляются устаревшие каналы/маршруты,
    затем добавляются новые. Это позволяет UI изменять граф без рестарта процессов.

    Без previous — полная регистрация всех каналов и маршрутов.

    Cross-process расширения (Task 9.6):
        - Для cross-process edges с payload_kind='image' — подключить FrameShmMiddleware.
        - Если process_registry передан и в topology.process_ids появился новый id —
          create_and_register нового ProcessorWorker.
        - Если process_id ушёл из topology — stop_one + remove_process.

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

    # Cross-process: SHM middleware для image-каналов
    shm_added = _attach_shm_middlewares(router, topology, memory_manager)

    # Cross-process: динамические процессы
    processes_created, processes_stopped = _manage_dynamic_processes(
        topology=topology,
        previous=previous,
        process_registry=process_registry,
        process_class_path=process_class_path,
        base_worker_config=base_worker_config,
    )

    result = ApplyResult(
        channels_added=channels_added,
        channels_removed=channels_removed,
        routes_added=routes_added,
        routes_removed=0,  # router_module не имеет unregister_route — используем replacement
        broadcast_routes_added=broadcast_added,
        shm_middlewares_added=shm_added,
        processes_created=processes_created,
        processes_stopped=processes_stopped,
    )

    logger.info(
        "apply_topology: channels +%d/-%d, routes +%d, broadcasts +%d, "
        "shm_mw +%d, procs +%d/-%d",
        result.channels_added,
        result.channels_removed,
        result.routes_added,
        result.broadcast_routes_added,
        result.shm_middlewares_added,
        result.processes_created,
        result.processes_stopped,
    )

    return result


__all__ = ["ApplyResult", "apply_topology"]
