# -*- coding: utf-8 -*-
"""
Трансформация значений UI ↔ хранилище на основе transfer_k, round_k из метаданных.

Универсальный «кубик» для любых числовых контролов (слайдер, спинбокс и т.д.).
"""
from __future__ import annotations

from typing import Any, Optional

from multiprocess_framework.modules.frontend_module.schemas.register_binding import ResolvedMeta


class ValueTransformer:
    """
    Трансформация значений на основе transfer_k, round_k из ResolvedMeta.
    """

    def __init__(self, meta: Optional[ResolvedMeta]) -> None:
        self._transfer_k = meta.transfer_k if meta else 1.0
        self._round_k = meta.round_k if meta else 0
        self._min = getattr(meta, "min_val", None) if meta else None
        self._max = getattr(meta, "max_val", None) if meta else None

    def to_storage(self, ui_value: float) -> int | float:
        """UI → Регистр (с учётом transfer_k)."""
        v = float(ui_value) * self._transfer_k
        if self._round_k == 0:
            return int(round(v))
        return round(v, self._round_k)

    def to_ui(self, storage_value: int | float) -> float:
        """Регистр → UI."""
        if not self._transfer_k:
            return float(storage_value)
        return float(storage_value) / self._transfer_k

    def clamp_to_range(self, ui_value: float) -> float:
        """Ограничение диапазоном (в UI-координатах)."""
        if self._min is None or self._max is None:
            return ui_value
        ui_min = self.to_ui(self._min)
        ui_max = self.to_ui(self._max)
        return max(ui_min, min(ui_value, ui_max))

    def get_step(self) -> float:
        """Шаг для QSlider (в UI-координатах)."""
        return 1.0 / self._transfer_k if self._transfer_k else 1.0
