"""Фотометрические аугментации полным кадром — ПОСЛЕ композиции.

КРИТИЧНО: размытие, motion blur, шум, яркость/контраст, цветовая температура,
JPEG-артефакты применяются единым проходом на весь скомпозиченный кадр.
Если применять их к объекту до вклейки — модель выучит шов вклейки, а не объект.

Порядок прохода (от «сцены» к «сенсору» и кодеку):
сцена: блик → тень → окклюзия; оптика: расфокус → смаз движения → виньетка;
сенсор: яркость/контраст → gamma → температура → сдвиг каналов → шум;
кодек: JPEG — последним.

Контактная тень под объектом (cast_contact_shadow) применяется отдельно —
на фон ДО композиции объекта (см. engine.generate_sample), не здесь.

Каждая операция — отдельная детерминированная функция с явными параметрами
(тестируемость); apply_photometric сэмплирует параметры из конфига.

Функции и реестр эффектов живут в `Services.layer_render.effects` (Task 2.2); здесь — реэкспорт
(тот же объект), мост `AugmentConfig` → список `EffectSpec` и однострочный `apply_photometric`.
Порядок прохода задаёт порядок вставки `EFFECTS` в effects.py.
"""

from __future__ import annotations

import numpy as np

from Services.dataset_gen.core.config import AugmentConfig
from Services.layer_render.effects import (
    EFFECTS,
    EffectSpec,
    apply_channel_shift,
    apply_brightness_contrast,
    apply_color_temperature,
    apply_effects,
    apply_gamma,
    apply_glare,
    apply_jpeg,
    apply_motion_blur,
    apply_occlusion,
    apply_shadow,
    apply_vignette,
    make_motion_kernel,
)

__all__ = [
    "apply_brightness_contrast",
    "apply_channel_shift",
    "apply_color_temperature",
    "apply_gamma",
    "apply_glare",
    "apply_jpeg",
    "apply_motion_blur",
    "apply_occlusion",
    "apply_photometric",
    "apply_shadow",
    "apply_vignette",
    "augment_config_to_effects",
    "make_motion_kernel",
]


def augment_config_to_effects(cfg: AugmentConfig) -> list[EffectSpec]:
    """Включённые фотометрические эффекты конфига в каноническом порядке (порядок `EFFECTS`)."""
    return [
        EffectSpec(name, sub.prob, sub.model_dump(exclude={"enabled", "prob"}))
        for name in EFFECTS
        if (sub := getattr(cfg, name)).enabled
    ]


def apply_photometric(frame_rgb_u8: np.ndarray, cfg: AugmentConfig, rng: np.random.Generator) -> np.ndarray:
    """Полный фотометрический проход по скомпозиченному кадру.

    Pre:
      - frame_rgb_u8: HxWx3 uint8 (после композиции объекта на фон)
    Post:
      - выход той же формы, uint8; при всех выключенных аугментациях — копия входа
    """
    return apply_effects(frame_rgb_u8, augment_config_to_effects(cfg), rng)
