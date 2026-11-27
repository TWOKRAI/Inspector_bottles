"""PresenceWatchRegisters — параметры индикатора наличия изделия.

Все поля живые: плагин читает регистр на каждом вызове. Пустой текст выключает свою причину.
Опечатка в ключе принимается молча. Python-валидаторы здесь запрещены, только ``FieldMeta``.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("PresenceWatchRegistersV1")
class PresenceWatchRegisters(SchemaBase):
    """Срок, тексты причин и ключи изделия."""

    absent_after_s: Annotated[float, FieldMeta("Нет изделия через, с", min=1.0, max=600.0)] = 10.0
    text_absent: Annotated[str, FieldMeta("Текст: нет изделия")] = "нет изделия"
    text_weak: Annotated[str, FieldMeta("Текст: слабое распознавание")] = "слабое распознавание"
    presence_keys: Annotated[str, FieldMeta("Ключи изделия")] = "predictions,sidecar"
    predictions_key: Annotated[str, FieldMeta("Ключ предсказаний")] = "predictions"
    label_key: Annotated[str, FieldMeta("Ключ метки")] = "label"
    below_threshold_key: Annotated[str, FieldMeta("Ключ «ниже порога»")] = "below_threshold"
    confidence_key: Annotated[str, FieldMeta("Ключ уверенности")] = "confidence"
    min_confidence: Annotated[float, FieldMeta("Порог уверенности", min=0.0, max=1.0)] = 0.0
