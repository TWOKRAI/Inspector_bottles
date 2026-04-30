"""Пресеты layout для display-подписок: одиночный, двойной, квад и др."""

from __future__ import annotations

import enum

from .schemas import DisplaySubscription


class LayoutPreset(enum.Enum):
    """Стандартные варианты раскладки окон отображения."""

    NONE = "none"      # Без подписок
    SINGLE = "single"  # Одно окно — первая камера
    DUAL = "dual"      # Два окна — первые две камеры
    QUAD = "quad"      # Четыре окна — первые четыре камеры
    CUSTOM = "custom"  # Пользовательская раскладка (пользователь добавляет вручную)


def preset_subscriptions(
    preset: LayoutPreset,
    camera_ids: list[int],
) -> list[DisplaySubscription]:
    """Сгенерировать список подписок для выбранного пресета.

    Args:
        preset: Вариант раскладки окон.
        camera_ids: Список идентификаторов камер (целые числа).

    Returns:
        Список DisplaySubscription. Пустой список для NONE и CUSTOM.
    """
    # Определяем количество окон для каждого пресета
    window_count_map: dict[LayoutPreset, int] = {
        LayoutPreset.NONE: 0,
        LayoutPreset.SINGLE: 1,
        LayoutPreset.DUAL: 2,
        LayoutPreset.QUAD: 4,
        LayoutPreset.CUSTOM: 0,
    }

    count = window_count_map[preset]
    if count == 0:
        return []

    subscriptions: list[DisplaySubscription] = []
    for i in range(count):
        # Берём камеру с индексом i, если она существует в списке
        if i >= len(camera_ids):
            break
        subscriptions.append(
            DisplaySubscription(
                source_ref=f"camera_{camera_ids[i]}",
                window_id=f"win_{i}",
            )
        )

    return subscriptions


__all__ = ["LayoutPreset", "preset_subscriptions"]
