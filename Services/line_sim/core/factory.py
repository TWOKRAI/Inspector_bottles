"""ObjectFactory — собирает объекты ленты поверх каталога `dataset_gen` (Task 3.2).

Единственное место, которое знает про `SpriteCatalog`: `ScenePreset` остаётся чистым
конфигом (LS-007). Дефект `"damaged"` — occlusion-пятно (`dataset_gen.core.augment.
apply_occlusion`) поверх базового спрайта, отдельный `LayerSpec(mode="defect", ...)`,
рисуется ПОСЛЕДНИМ после слоёв пресета — тот же принцип, что LS-006 (порядок слоёв —
часть контракта seed; дефект в конце и только в конце даёт "defect=None побитово
равен объекту без defect-слоя").
"""

from __future__ import annotations

import numpy as np

from Services.dataset_gen.core.augment import apply_occlusion
from Services.line_sim.core.catalog_bridge import load_catalog, load_image_rgba
from Services.line_sim.core.layered_object import LayeredObject
from Services.line_sim.core.preset import ScenePreset
from Services.line_sim.interfaces import LayerSpec, ObjectPassport

_DEFECT_LAYER_NAME = "damaged"
_DEFECT_COLOR_RGB = (60.0, 60.0, 60.0)  # тёмно-серый — грязь/скол
_DEFECT_SIDE_FRAC = 0.35  # ~35% меньшей стороны базового спрайта
_DEFECT_OFFSET_FRAC = 0.15  # смещение пятна к верхнему левому углу (не по центру)


class ObjectFactory:
    """Строит `LayeredObject` ленты: класс/угол — из rng, дефект `"damaged"` —
    с вероятностью пресета или форсированно через `force_defect_next()`.

    Pre: `preset.catalog_dir` задан ИЛИ `preset.layers` непуст (проверено `ScenePreset`).
    Post: `num_classes` >= 1, если каталог загружен, иначе 0 и `make()` поднимает
    `ValueError` (пресет без каталога не может выбрать класс).
    """

    def __init__(self, preset: ScenePreset) -> None:
        self._preset = preset
        self._catalog = load_catalog(preset.catalog_dir) if preset.catalog_dir is not None else None
        # Доп. слои пресета резолвятся один раз здесь (id -> RGBA); каждый make() их
        # переиспользует как есть — LayeredObject их только читает, не мутирует.
        self._extra_layers: list[LayerSpec] = [
            layer.model_copy(update={"sprite_source": load_image_rgba(layer.sprite_source)}) for layer in preset.layers
        ]
        self._force_defect_pending = False

    @property
    def num_classes(self) -> int:
        return self._catalog.num_classes if self._catalog is not None else 0

    @property
    def class_names(self) -> list[str]:
        return self._catalog.class_names if self._catalog is not None else []

    def force_defect_next(self) -> None:
        """Ровно следующий `make()` получит `passport.defect == "damaged"`,
        независимо от `defect_probability`. Флаг одноразовый (см. `make()`)."""
        self._force_defect_pending = True

    def make(self, object_id: str, spawn_encoder: float, rng: np.random.Generator) -> LayeredObject:
        """Собрать объект: класс и угол — из `rng`, слои — база + пресет + дефект (последним).

        `force_defect_next()` ТОЛЬКО читается здесь (`forced`), а гасится лишь ПОСЛЕ того,
        как `LayeredObject` успешно построен — транзитная ошибка (например каталог на сетевом
        диске моргнул на одном вызове) не должна съедать нажатие оператора: следующий успешный
        `make()` обязан получить дефект, а не "он как будто сработал и пропал" (пин ревью,
        см. test_hazards_3_2.py — репродукция флаки-каталога).
        """
        forced = self._force_defect_pending

        if self._catalog is None:
            raise ValueError(
                "ObjectFactory.make(): пресет без catalog_dir (только layers) не может "
                "выбрать класс — нужен каталог спрайтов (задайте catalog_dir в пресете)"
            )

        class_index = int(rng.integers(self.num_classes))
        class_name = self._catalog.entry(class_index).name
        angle_deg = float(rng.uniform(*self._preset.angle_range_deg))
        base_sprite = self._catalog.get_sprite(class_index, rng)

        base_layer = LayerSpec(name="base", mode="static", sprite_source=base_sprite)
        damaged_layer = LayerSpec(
            name=_DEFECT_LAYER_NAME,
            mode="defect",
            sprite_source=self._build_defect_blob(base_sprite),
            defect_probability=self._preset.defect_probability,
        )
        layers = [base_layer, *self._extra_layers, damaged_layer]

        passport = ObjectPassport(
            object_id=object_id,
            class_name=class_name,
            angle_deg=angle_deg,
            defect=_DEFECT_LAYER_NAME if forced else None,
            spawn_encoder=spawn_encoder,
        )
        obj = LayeredObject(passport=passport, layers=layers, rng=rng)
        self._force_defect_pending = False  # гасим ТОЛЬКО после успеха — см. докстринг выше
        return obj

    @staticmethod
    def _build_defect_blob(base_rgba: np.ndarray) -> np.ndarray:
        """RGBA-заплатка размера базового спрайта — непрозрачный тёмно-серый прямоугольник
        (~35% меньшей стороны, смещён к верхнему левому углу), альфа=255 внутри, иначе 0 —
        И дополнительно замаскированная альфой базового спрайта (`np.minimum`), так что пятно
        никогда не красит область ЗА пределами объекта (круглый диск, а не квадратный спрайт
        с прозрачными углами — без маски occlusion рисовал бы "грязь в воздухе").

        Строит НОВЫЙ массив (`np.zeros`) — `base_rgba` (спрайт каталога) не мутируется,
        только читается ради `.shape` и альфы.
        """
        h, w = base_rgba.shape[:2]
        side = min(h, w)
        size = max(1, round(side * _DEFECT_SIDE_FRAC))
        x = round(w * _DEFECT_OFFSET_FRAC)
        y = round(h * _DEFECT_OFFSET_FRAC)
        rect = (x, y, size, size)

        canvas_rgb = np.zeros((h, w, 3), dtype=np.float32)
        rgb = apply_occlusion(canvas_rgb, rect, _DEFECT_COLOR_RGB)

        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(w, x + size), min(h, y + size)
        alpha = np.zeros((h, w), dtype=np.uint8)
        alpha[y0:y1, x0:x1] = 255
        alpha = np.minimum(alpha, base_rgba[:, :, 3])  # не красить мимо непрозрачной части базы

        return np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), alpha])
