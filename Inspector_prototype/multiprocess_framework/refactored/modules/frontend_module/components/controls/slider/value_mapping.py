# -*- coding: utf-8 -*-
"""
Пересчёт позиции слайдера и «реального» значения поля регистра.

Не зависит от Qt. Использует ``ResolvedMeta`` (transfer_k, round_k, min/max).
Ответственность виджета — вызвать эти функции с актуальным ``meta``.
"""
from __future__ import annotations

from typing import Any, Optional, Union

from frontend_module.schemas.register_binding import ResolvedMeta


def slider_position_to_value(raw: Union[int, float], meta: Optional[ResolvedMeta]) -> Any:
    """
    Позиция трека слайдера (целое) → значение для регистра.

    Умножение на ``transfer_k``; при ``round_k == 0`` результат целый.
    """
    k = meta.transfer_k if meta else 1.0
    rk = meta.round_k if meta else 0
    v = float(raw) * k
    return int(round(v)) if rk == 0 else round(v, rk)


def real_value_to_slider_position(real: Any, meta: Optional[ResolvedMeta]) -> int:
    """
    Значение из регистра → позиция слайдера (целое деление на ``transfer_k``).
    """
    k = meta.transfer_k if meta else 1.0
    v = float(real) / k if k else float(real)
    return int(round(v))


def clamp_to_meta_range(
    val: Union[int, float],
    meta: Optional[ResolvedMeta],
) -> Union[int, float]:
    """Ограничить число диапазоном ``min_val``..``max_val`` из метаданных."""
    if not meta or not isinstance(val, (int, float)):
        return val
    return max(meta.min_val, min(float(val), meta.max_val))
