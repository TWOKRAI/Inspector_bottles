# -*- coding: utf-8 -*-
"""
CameraData — данные конфигурации камеры, регионов и параметров Hikvision.
"""
from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from .region import RegionData


class CameraData(BaseModel):
    """Конфигурация камеры: параметры подключения, регионы интереса."""

    # Идентификатор / имя камеры
    name: str = "unknown"

    # Параметры SDK Hikvision (ключ → значение)
    hikvision_params: Dict[str, Any] = Field(default_factory=dict)

    # Порядок регионов (список имён для сортировки)
    region_order: List[str] = Field(default_factory=list)

    # Регионы интереса (имя → RegionData)
    regions: Dict[str, RegionData] = Field(default_factory=dict)
