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
from Services.line_sim.core.layered_object import LayeredObject, _load_sprite
from Services.line_sim.core.preset import CLASS_SPRITE_SOURCE, ScenePreset
from Services.line_sim.interfaces import LayerSpec, ObjectPassport

_DEFECT_LAYER_NAME = "damaged"
_DEFECT_COLOR_RGB = (60.0, 60.0, 60.0)  # тёмно-серый — грязь/скол
_DEFECT_SIDE_FRAC = 0.35  # ~35% меньшей стороны базового спрайта
_DEFECT_OFFSET_FRAC = 0.15  # смещение пятна к верхнему левому углу (не по центру)


def _read_only_view(arr: np.ndarray) -> np.ndarray:
    """Read-only вид без копии: `_transform` без трансформа возвращает сам кэш фабрики,
    запись через ответ испортила бы все следующие `make()`."""
    view = arr.view()
    view.flags.writeable = False
    return view


class ObjectFactory:
    """Строит `LayeredObject` ленты: класс/угол — из rng, дефект `"damaged"` —
    с вероятностью пресета или форсированно через `force_defect_next()`.

    Pre: `preset.catalog_dir` задан ИЛИ `preset.layers` непуст (проверено `ScenePreset`).
    Post: `num_classes` >= 1, если каталог загружен, иначе 0. Пресет без `catalog_dir`
    (только `layers`, Task 1.1b) — `make()` строит объект из одних слоёв пресета,
    без класса (`passport.class_name == ""`); слой `class://` в таком пресете запрещён
    отдельно (`ScenePreset`), так что выбирать в `make()` нечего.
    """

    def __init__(self, preset: ScenePreset) -> None:
        self._preset = preset
        self._catalog = (
            load_catalog(preset.resolve_path(preset.catalog_dir)) if preset.catalog_dir is not None else None
        )
        # Доп. слои пресета резолвятся один раз здесь (id -> RGBA); каждый make() их
        # переиспользует как есть — LayeredObject их только читает, не мутирует.
        # preset.resolve_path() — относительные строки от preset.base_dir (Task 1.0, LS-013),
        # абсолютные и id-схемы (fixture://...) пропускает без изменений.
        # Слой class:// (Task 1.1b, блок A) — не картинка, а маркер: спрайт неизвестен до
        # make() (нужен разыгранный класс), поэтому картинка НЕ грузится — сам LayerSpec
        # остаётся как есть, make() подставляет base_sprite на каждый вызов.
        # preset.layers — sprite_source всегда строка-id (ScenePreset._sprite_ids_only), флаг
        # считаем ДО замены на RGBA ниже: после неё sprite_source — ndarray, и "==" с
        # CLASS_SPRITE_SOURCE (строкой) на ndarray даёт поэлементный массив, не bool.
        self._has_class_layer = any(layer.sprite_source == CLASS_SPRITE_SOURCE for layer in preset.layers)
        self._extra_layers: list[LayerSpec] = [
            layer
            if layer.sprite_source == CLASS_SPRITE_SOURCE
            else layer.model_copy(update={"sprite_source": load_image_rgba(preset.resolve_path(layer.sprite_source))})
            for layer in preset.layers
        ]
        self._force_defect_pending = False

    @property
    def num_classes(self) -> int:
        return self._catalog.num_classes if self._catalog is not None else 0

    @property
    def class_names(self) -> list[str]:
        return self._catalog.class_names if self._catalog is not None else []

    @property
    def defect_probability(self) -> float:
        """Доля брака, реально ЗАШИТАЯ в эту фабрику (Task 6.1, ревью итерация 2, Ф2) --
        `self._preset.defect_probability` уже несёт `apply_defect_override`, если фабрика
        собрана через него (`cmd_preset_commit`/`cmd_defect_rate`). Источник для
        `scene.status`, чтобы отдавать ПРИМЕНЁННОЕ значение, а не заявку клиента."""
        return self._preset.defect_probability

    @property
    def force_defect_pending(self) -> bool:
        """Взведён ли одноразовый флаг `force_defect_next()` (ещё не погашен успешным `make()`).
        Только чтение — нужен `ObjectSpawner.set_factory()`, чтобы перенести нажатие на новую фабрику."""
        return self._force_defect_pending

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

        class_name, angle_deg, bottom_layers = self._resolve_bottom_layers(rng)

        # ponytail: блоб дефекта строится из спрайта НИЖНЕГО слоя (bottom_layers[0]) как есть —
        # его собственные offset/scale/angle игнорируются (как и раньше для "base"); апгрейд —
        # компоновать блоб в объектных координатах, если нижний слой получит трансформ.
        bottom_sprite = bottom_layers[0].sprite_source
        damaged_layer = LayerSpec(
            name=_DEFECT_LAYER_NAME,
            mode="defect",
            sprite_source=self._build_defect_blob(bottom_sprite),
            defect_probability=self._preset.defect_probability,
        )
        layers = [*bottom_layers, damaged_layer]

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

    def _resolve_bottom_layers(self, rng: np.random.Generator) -> tuple[str, float, list[LayerSpec]]:
        """Класс, угол объекта и слои пресета (без defect-слоя) — из `rng`.

        Порядок розыгрышей — часть контракта seed (LS-006): `integers` (класс) -> `uniform`
        (угол) -> `get_sprite`. Общий для `make()` и `nominal_layers()`, чтобы для одного seed
        класс в ленте, плитке превью и раскладке слоёв совпадал.
        """
        if self._catalog is None:
            # Пресет без catalog_dir (только layers — гарантировано ScenePreset._catalog_or_layers,
            # там же отдельно запрещён слой class:// без catalog_dir, так что self._extra_layers
            # здесь всегда обычные загруженные RGBA-слои, без class-маркера) — класса нет.
            class_name = ""
            angle_deg = float(rng.uniform(*self._preset.angle_range_deg))
            bottom_layers = list(self._extra_layers)
        else:
            class_index = int(rng.integers(self.num_classes))
            class_name = self._catalog.entry(class_index).name
            angle_deg = float(rng.uniform(*self._preset.angle_range_deg))
            base_sprite = self._catalog.get_sprite(class_index, rng)

            if self._has_class_layer:
                # Слой class:// (ровно один — проверено ScenePreset) заменяется разыгранным
                # base_sprite на месте, сохраняя позицию в списке слоёв пресета (порядок слоёв —
                # часть контракта seed, LS-006) — "base"-слой отдельно не добавляется.
                bottom_layers = [
                    layer.model_copy(update={"sprite_source": base_sprite})
                    if isinstance(layer.sprite_source, str) and layer.sprite_source == CLASS_SPRITE_SOURCE
                    else layer
                    for layer in self._extra_layers
                ]
            else:
                bottom_layers = [
                    LayerSpec(name="base", mode="static", sprite_source=base_sprite),
                    *self._extra_layers,
                ]
        return class_name, angle_deg, bottom_layers

    def nominal_layers(self, rng: np.random.Generator) -> tuple[str, list[tuple[str, np.ndarray, float, float]]]:
        """Слои пресета по отдельности в НОМИНАЛЕ: `(class_name, [(имя, RGBA, offset_x, offset_y)])`.

        Класс и спрайт — как в `make()` для того же `rng` (`_resolve_bottom_layers`); угол объекта
        игнорируется (раскладка при угле 0). Каждый слой — тот же `LayeredObject._transform`
        (заливка -> scale -> поворот слоя), но БЕЗ выборки augment; defect-слои пропускаются.
        Только читает: `force_defect_next()` не читается и не гасится (это просмотр, не объект ленты).
        Массивы — read-only виды (не копии): ссылки на кэш фабрики наружу не уходят записываемыми.
        """
        class_name, _angle_deg, bottom_layers = self._resolve_bottom_layers(rng)
        layers = [
            (
                layer.name,
                _read_only_view(
                    LayeredObject._transform(_load_sprite(layer), layer.scale, layer.angle_deg, 0.0, layer.color_rgb)
                ),
                layer.offset_px[0],
                layer.offset_px[1],
            )
            for layer in bottom_layers
            if layer.mode != "defect"
        ]
        return class_name, layers

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
