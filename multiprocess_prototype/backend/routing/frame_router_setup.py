"""Frame Router fan-out setup (AD-2).

Настройка broadcast-маршрутов для кадров каждой камеры.
Каждый camera_id получает канал `frame.camera_{id}` с fan-out
на подписчиков (processor, display, history, recorder).

Подписчики добавляются/убираются динамически.

Примечание: этот модуль намеренно размещён в prototype, а не в framework,
т.к. содержит Inspector-специфику (camera_id, семантику subscribe/unsubscribe
для camera-топологии). См. ADR-128.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_framework.modules.router_module import RouterManager


# Дефолтные подписчики для каждой камеры
_DEFAULT_SUBSCRIBERS = ["processor"]


def frame_route_key(camera_id: int) -> str:
    """Ключ маршрута для кадров камеры: frame.camera_{id}."""
    return f"frame.camera_{camera_id}"


def setup_frame_routes(
    router_manager: RouterManager,
    camera_ids: list[int],
    extra_subscribers: dict[int, list[str]] | None = None,
) -> None:
    """Настроить broadcast fan-out для N камер.

    Args:
        router_manager: RouterManager из ProcessManagerProcess или SharedResources.
        camera_ids: Список camera_id (из AppConfig.cameras).
        extra_subscribers: Дополнительные подписчики per-camera:
            {0: ["display", "recorder"], 1: ["display"]}
    """
    extra = extra_subscribers or {}
    for cam_id in camera_ids:
        route_key = frame_route_key(cam_id)
        # Базовые подписчики + дополнительные для конкретной камеры
        subscribers = list(_DEFAULT_SUBSCRIBERS) + extra.get(cam_id, [])
        router_manager.register_broadcast_route(route_key, subscribers)


def subscribe_to_camera(
    router_manager: RouterManager,
    camera_id: int,
    subscriber_channel: str,
) -> bool:
    """Динамически подписать consumer на кадры камеры.

    Используется для подключения Display, History, Recorder в runtime.
    """
    route_key = frame_route_key(camera_id)
    # Получить текущих подписчиков и добавить нового
    current = _get_route_channels(router_manager, route_key)
    if subscriber_channel in current:
        return True  # Уже подписан
    current.append(subscriber_channel)
    return router_manager.register_broadcast_route(route_key, current)


def unsubscribe_from_camera(
    router_manager: RouterManager,
    camera_id: int,
    subscriber_channel: str,
) -> bool:
    """Динамически отписать consumer от кадров камеры."""
    route_key = frame_route_key(camera_id)
    current = _get_route_channels(router_manager, route_key)
    if subscriber_channel not in current:
        return True  # Уже отписан
    current.remove(subscriber_channel)
    return router_manager.register_broadcast_route(route_key, current)


def _get_route_channels(router_manager: RouterManager, route_key: str) -> list[str]:
    """Получить текущий список channel names для route_key."""
    # channel_dispatcher хранит handler'ы — для broadcast это список channel names
    dispatcher = getattr(router_manager, "channel_dispatcher", None)
    if dispatcher is None:
        return []
    info = dispatcher.get_handler(route_key)
    if info is None:
        return []
    # handler в broadcast = список channel names
    handler = info.get("handler") if isinstance(info, dict) else info
    if isinstance(handler, list):
        return list(handler)
    return []
