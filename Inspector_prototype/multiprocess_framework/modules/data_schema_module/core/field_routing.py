# -*- coding: utf-8 -*-
"""
FieldRouting — типизированный дескриптор маршрутизации поля.

Альтернатива словарю routing={"channel": "control_draw"} — даёт
автодополнение IDE, строгую типизацию и читаемый код.

Пример:

    # Старый стиль (работает, но многословно)
    dp: Annotated[float, FieldMeta("Разрешение", routing={"channel": "control_draw"})]

    # Новый стиль (с FieldRouting)
    DRAW = FieldRouting(channel="control_draw")

    dp: Annotated[float, FieldMeta("Разрешение", routing=DRAW)] = 1.4
    minDist: Annotated[float, FieldMeta("Расстояние", routing=DRAW)] = 50.0

    # Один объект для нескольких полей — DRY без копипасты.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FieldRouting:
    """
    Типизированная маршрутизация поля к Router-каналу.

    Атрибуты:
        channel          — имя канала в Router (обязательный)
        priority         — приоритет обработки (по умолч. 0)
        transform        — имя функции трансформации значения перед отправкой
        process_targets  — опционально: имена процессов для register_update с GUI
                          (перекрывает register_dispatch класса для этого поля)
    """

    channel: str
    priority: int = 0
    transform: str | None = None
    process_targets: tuple[str, ...] | None = None

    def to_dict(self) -> dict:
        """Конвертировать в dict для хранения в FieldMeta.routing."""
        d: dict = {"channel": self.channel}
        if self.priority:
            d["priority"] = self.priority
        if self.transform:
            d["transform"] = self.transform
        if self.process_targets:
            d["process_targets"] = list(self.process_targets)
        return d

    def __repr__(self) -> str:
        parts = [repr(self.channel)]
        if self.priority:
            parts.append(f"priority={self.priority}")
        if self.transform:
            parts.append(f"transform={self.transform!r}")
        if self.process_targets:
            parts.append(f"process_targets={self.process_targets!r}")
        return f"FieldRouting({', '.join(parts)})"
