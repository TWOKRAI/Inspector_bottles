"""Метка сэмпла: всё, что нужно обучающему коду для построения loss.

Контракт с обучающим сервисом: class_index — для классификационной головы;
(angle_sin, angle_cos) — таргет регрессии угла; angle_valid — маска включения
сэмпла в loss по углу (False для полностью симметричных классов).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from Services.dataset_gen.core.config import SymmetryType


class SampleLabel(BaseModel):
    """Метка одного сгенерированного кадра."""

    class_index: int
    class_name: str
    angle_deg: float  # ground truth, CCW, [0, 360)
    angle_sin: float  # кодирование с учётом симметрии (см. symmetry.encode_angle)
    angle_cos: float
    symmetry: SymmetryType
    angle_valid: bool  # False → исключить сэмпл из loss по углу

    def to_dict(self) -> dict[str, Any]:
        """Сериализация на границе (CSV/JSON/parquet)."""
        return self.model_dump()
