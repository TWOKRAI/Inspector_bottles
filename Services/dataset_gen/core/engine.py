"""DatasetEngine — единый движок генерации кадров для обоих режимов вывода.

Один и тот же generate_sample питает и экспорт на диск (export.py),
и on-the-fly torch-Dataset (torch_adapter.py), и QC-сетку (preview.py).

Пайплайн одного кадра (порядок фиксирован — см. docstring generate_sample).
"""

from __future__ import annotations

import cv2
import numpy as np

from Services.dataset_gen.core.catalog import SpriteCatalog
from Services.dataset_gen.core.compose import (
    composite,
    crop_to_alpha,
    fit_longest_side,
    rotate_expand,
)
from Services.dataset_gen.core.config import GeneratorConfig, SymmetryType
from Services.dataset_gen.core.labels import SampleLabel
from Services.dataset_gen.core.augment import apply_photometric
from Services.dataset_gen.core.symmetry import combine_symmetries, detect_symmetry, encode_angle


class DatasetEngine:
    """Движок: каталог + симметрии классов + генерация кадра с меткой.

    Симметрия каждого класса резолвится один раз при создании:
    приоритет у ручного override из конфига, иначе авто-детектор по всем
    эталонам класса (несколько эталонов сводятся к худшей симметрии),
    при выключенном auto_detect — "none".
    """

    def __init__(self, config: GeneratorConfig) -> None:
        self.config = config
        self._catalog = SpriteCatalog(config.catalog)
        self._catalog.load()
        self._rng = np.random.default_rng(config.seed)
        self._symmetry: dict[int, SymmetryType] = self._resolve_symmetries()

    @classmethod
    def from_yaml(cls, preset_path: str) -> DatasetEngine:
        """Создать движок из YAML-пресета."""
        return cls(GeneratorConfig.from_yaml(preset_path))

    # -- свойства -------------------------------------------------------------

    @property
    def num_classes(self) -> int:
        return self._catalog.num_classes

    @property
    def class_names(self) -> list[str]:
        return self._catalog.class_names

    @property
    def symmetry_map(self) -> dict[str, SymmetryType]:
        """Имя класса → тип симметрии (вычисленный или переопределённый)."""
        names = self._catalog.class_names
        return {names[i]: s for i, s in self._symmetry.items()}

    # -- генерация ------------------------------------------------------------

    def generate_sample(
        self,
        class_index: int | None = None,
        rng: np.random.Generator | None = None,
    ) -> tuple[np.ndarray, SampleLabel]:
        """Сгенерировать один кадр с меткой.

        Порядок (важен):
          1. класс и случайный его эталон (RGBA);
          2. поворот на θ с expand-холстом, альфа сохранена — θ = ground truth;
          3. обрезка по альфе (прозрачные уголки не попадают в кадр);
          4. случайный фон, кроп/ресайз под рабочий размер;
          5. композиция по альфе со сдвигом X/Y и лёгким масштабом;
          6. фотометрия единым проходом на ВЕСЬ кадр (после композиции —
             иначе модель учит шов вклейки);
          7. ресайз до выходного разрешения.

        Pre:
          - class_index ∈ [0, num_classes) или None (случайный класс)
        Post:
          - кадр: (H, W, 3) uint8 RGB, H/W из config.output.size
          - метка согласована: sin²+cos²≈1 при angle_valid, иначе (0,0,False)
        """
        rng = rng if rng is not None else self._rng
        cfg = self.config

        if class_index is None:
            class_index = int(rng.integers(self.num_classes))

        # 1. эталон
        sprite = self._catalog.get_sprite(class_index, rng)

        # 2-3. поворот (GT-угол) + обрезка по альфе
        rot_cfg = cfg.augment.rotation
        angle = float(rng.uniform(*rot_cfg.range)) % 360.0 if rot_cfg.enabled else 0.0
        rotated = crop_to_alpha(rotate_expand(sprite, angle))

        # 4. фон под рабочий размер (с учётом supersample)
        out_h, out_w = cfg.output.size
        ss = cfg.output.supersample
        work_h, work_w = int(round(out_h * ss)), int(round(out_w * ss))
        frame = self._catalog.get_background(rng, (work_h, work_w))

        # 5. размер объекта + сдвиг + композиция
        base_frac = float(rng.uniform(*cfg.placement.object_size_frac))
        scale_cfg = cfg.augment.scale
        jitter = float(rng.uniform(*scale_cfg.range)) if scale_cfg.enabled else 1.0
        target_px = max(1, int(round(base_frac * jitter * min(work_h, work_w))))
        if cfg.placement.keep_inside:
            target_px = min(target_px, min(work_h, work_w))
        sized = fit_longest_side(rotated, target_px)

        shift_cfg = cfg.augment.shift
        max_dx = shift_cfg.frac * work_w if shift_cfg.enabled else 0.0
        max_dy = shift_cfg.frac * work_h if shift_cfg.enabled else 0.0
        cx = work_w / 2.0 + float(rng.uniform(-max_dx, max_dx))
        cy = work_h / 2.0 + float(rng.uniform(-max_dy, max_dy))
        if cfg.placement.keep_inside:
            sh, sw = sized.shape[:2]
            cx = float(np.clip(cx, sw / 2.0, work_w - sw / 2.0))
            cy = float(np.clip(cy, sh / 2.0, work_h - sh / 2.0))
        frame = composite(frame, sized, (cx, cy))

        # 6. фотометрия полным кадром
        frame = apply_photometric(frame, cfg.augment, rng)

        # 7. финальный ресайз
        if (work_h, work_w) != (out_h, out_w):
            frame = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)

        symmetry = self._symmetry[class_index]
        sin_v, cos_v, valid = encode_angle(angle, symmetry)
        label = SampleLabel(
            class_index=class_index,
            class_name=self._catalog.class_names[class_index],
            angle_deg=angle,
            angle_sin=sin_v,
            angle_cos=cos_v,
            symmetry=symmetry,
            angle_valid=valid,
        )
        return frame, label

    # -- внутреннее -----------------------------------------------------------

    def _resolve_symmetries(self) -> dict[int, SymmetryType]:
        sym_cfg = self.config.symmetry
        result: dict[int, SymmetryType] = {}
        for entry in self._catalog.classes:
            override = sym_cfg.overrides.get(entry.name)
            if override is not None:
                result[entry.index] = override
                continue
            if not sym_cfg.auto_detect:
                result[entry.index] = "none"
                continue
            kinds = {
                detect_symmetry(s, sym_cfg.threshold, sym_cfg.full_angles, sym_cfg.rel_threshold)
                for s in self._catalog.sprites(entry.index)
            }
            result[entry.index] = combine_symmetries(kinds)
        return result
