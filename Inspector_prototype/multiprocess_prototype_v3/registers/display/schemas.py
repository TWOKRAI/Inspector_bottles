"""Схема подписки display: связь source_ref с window_id и трансформацией."""

from __future__ import annotations

import uuid
from typing import Annotated

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)
from pydantic import Field

from .transform import DisplayTransform


@register_schema("DisplaySubscriptionV3")
class DisplaySubscription(SchemaBase):
    """Подписка display-окна на источник кадров.

    source_ref форматы:
      - ``camera_{id}``                      — сырой поток камеры
      - ``processor_{id}.{region}.{step}``   — промежуточный шаг обработки
      - ``processor_{id}.{region}.final``    — финальный результат обработки
    """

    # Уникальный идентификатор подписки (автогенерация UUID)
    subscription_id: Annotated[
        str,
        FieldMeta("ID подписки", info="UUID подписки, генерируется автоматически."),
    ] = Field(default_factory=lambda: str(uuid.uuid4()))

    # Ссылка на источник кадров (camera_N или processor_N.region.step)
    source_ref: Annotated[
        str,
        FieldMeta("Source ref", info="Идентификатор источника кадров."),
    ]

    # Идентификатор окна-получателя
    window_id: Annotated[
        str,
        FieldMeta("Window ID", info="Идентификатор окна отображения (win_0, win_1, ...)."),
    ]

    # Параметры трансформации кадра перед отображением
    transform: Annotated[
        DisplayTransform,
        FieldMeta("Трансформация", info="Resize, overlay, лимит FPS."),
    ] = Field(default_factory=DisplayTransform)


__all__ = ["DisplaySubscription"]
