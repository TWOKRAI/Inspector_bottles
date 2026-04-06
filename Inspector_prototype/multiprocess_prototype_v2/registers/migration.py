# -*- coding: utf-8 -*-
"""Нормализация снимков рецептов (legacy → текущие поля processor)."""

from __future__ import annotations

from typing import Any, Dict


def normalize_processor_register_payload(proc: Dict[str, Any]) -> Dict[str, Any]:
    """Пока без преобразований; расширять при смене схемы vision_pipeline."""
    return proc
