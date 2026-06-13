# -*- coding: utf-8 -*-
"""Группа «Нейронные сети» во вкладке Services — секции ML-конвейера.

Три секции поверх Services-слоя (dataset_gen → ml_train → ml_inference):
    «Генерация датасета» — пресет + объёмы сплитов, превью, фоновая генерация;
    «Обучение»           — конфиг, запуск обучения subprocess'ом, лог, прогоны;
    «Модели (инференс)»  — каталог data/models глазами ModelRegistry.

Сборка — build_neural_sections(); generic-узлы этих сервисов скрываются
из группы «Сервисы» (см. _sections.py), как у камер/робота/ПЧ.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec


def build_neural_sections(services: Any, runtime: Any, *, parent_key: str) -> list[SectionSpec]:
    """SectionSpec'и трёх ML-секций (lazy) под родительским узлом parent_key."""
    from .dataset_gen_section import build_dataset_gen_section
    from .ml_inference_section import build_ml_inference_section
    from .ml_train_section import build_ml_train_section

    return [
        build_dataset_gen_section(services, runtime, parent_key=parent_key),
        build_ml_train_section(services, runtime, parent_key=parent_key),
        build_ml_inference_section(services, runtime, parent_key=parent_key),
    ]


__all__ = ["build_neural_sections"]
