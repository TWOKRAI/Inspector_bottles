"""ObjectFactory — собирает объект из слоёв поверх каталога классов (Task 3.2, переехала в Task 2.4b).

Единственное место, которое знает про `SpriteCatalog`: `ScenePreset` остаётся чистым
конфигом (LS-007). Дефект `"damaged"` — occlusion-пятно (`layer_render.effects.apply_occlusion`)
поверх базового спрайта, отдельный `LayerSpec(mode="defect", ...)`, рисуется ПОСЛЕДНИМ после слоёв
пресета — тот же принцип, что LS-006 (порядок слоёв — часть контракта seed; дефект в конце и только
в конце даёт "defect=None побитово равен объекту без defect-слоя").

`render(rng, ...)` отдаёт `RenderedObject` (картинка + класс + угол + дефект + выбранные параметры слоёв).
Паспорт ленты и флаг оператора «форсировать брак» — у наследника `Services.line_sim.ObjectFactory`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from Services.layer_render.catalog import load_catalog
from Services.layer_render.effects import apply_occlusion
from Services.layer_render.io import load_image_rgba
from Services.layer_render.layers import LayerSpec, compose_layers, load_layer_sprite, transform_layer
from Services.layer_render.preset import CLASS_SPRITE_SOURCE, ScenePreset

__all__ = ["ObjectFactory", "RenderedObject"]

_DEFECT_LAYER_NAME = "damaged"
_DEFECT_COLOR_RGB = (60.0, 60.0, 60.0)  # тёмно-серый — грязь/скол
_DEFECT_SIDE_FRAC = 0.35  # ~35% меньшей стороны базового спрайта
_DEFECT_OFFSET_FRAC = 0.15  # смещение пятна к верхнему левому углу (не по центру)


def _read_only_view(arr: np.ndarray) -> np.ndarray:
    """Read-only вид без копии: `transform_layer` без трансформа возвращает сам кэш фабрики,
    запись через ответ испортила бы все следующие `render()`."""
    view = arr.view()
    view.flags.writeable = False
    return view


@dataclass(frozen=True, eq=False)
class RenderedObject:
    """Результат `ObjectFactory.render`: готовая картинка объекта и то, что при этом выбрано.

    `rgba` — RGBA uint8, read-only. `defect` — имена активных defect-слоёв через запятую или None
    (как `passport.defect`). `layer_params` — выбранные значения по слоям. Сравнения по значению нет
    (`eq=False`): `==` по ndarray неоднозначно.
    """

    rgba: np.ndarray
    class_name: str
    angle_deg: float
    defect: str | None
    layer_params: dict[str, dict[str, Any]]


class ObjectFactory:
    """Строит объект из слоёв (`RenderedObject`): класс/угол — из rng, дефект `"damaged"` —
    с вероятностью пресета или форсированно через `render(..., force_defect=True)`.

    Pre: `preset.catalog_dir` задан ИЛИ `preset.layers` непуст (проверено `ScenePreset`).
    Post: `num_classes` >= 1, если каталог загружен, иначе 0. Пресет без `catalog_dir`
    (только `layers`, Task 1.1b) — `render()` строит объект из одних слоёв пресета,
    без класса (`class_name == ""`); слой `class://` в таком пресете запрещён
    отдельно (`ScenePreset`), так что выбирать в `render()` нечего.

    Состояния, кроме кэшей слоёв и каталога, нет: фабрику можно делить (кэш превью). Флаг оператора
    «форсировать брак» и паспорт ленты — у наследника `Services.line_sim.ObjectFactory`.
    """

    def __init__(self, preset: ScenePreset) -> None:
        self._preset = preset
        self._catalog = (
            load_catalog(preset.resolve_path(preset.catalog_dir)) if preset.catalog_dir is not None else None
        )
        # Доп. слои пресета резолвятся один раз здесь (id -> RGBA); каждый render() их
        # переиспользует как есть — compose_layers их только читает, не мутирует.
        # preset.resolve_path() — относительные строки от preset.base_dir (Task 1.0, LS-013),
        # абсолютные и id-схемы (fixture://...) пропускает без изменений.
        # Слой class:// (Task 1.1b, блок A) — не картинка, а маркер: спрайт неизвестен до
        # render() (нужен разыгранный класс), поэтому картинка НЕ грузится — сам LayerSpec
        # остаётся как есть, render() подставляет base_sprite на каждый вызов.
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

    def render(self, rng: np.random.Generator, *, force_defect: bool = False, label: str = "") -> RenderedObject:
        """Собрать объект: класс и угол — из `rng`, слои — база + пресет + дефект (последним).

        `force_defect=True` включает слой `"damaged"` без розыгрыша (форс оператора ленты — снаружи,
        здесь только параметр). `label` — имя объекта в текстах ошибок (`LayeredObject '<label>': ...`).
        Порядок расхода `rng`: `integers` (класс) -> `uniform` (угол) -> `get_sprite` -> `compose_layers`
        (`rng.spawn(len(layers))`); сборка блоба дефекта `rng` не тратит.
        """
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

        forced = (_DEFECT_LAYER_NAME,) if force_defect else ()
        composed = compose_layers(layers, rng, angle_deg, forced, label=label)
        composed.rgba.flags.writeable = False  # результат не портится через возвращённую ссылку
        return RenderedObject(
            rgba=composed.rgba,
            class_name=class_name,
            angle_deg=angle_deg,
            defect=",".join(composed.active_defects) or None,
            layer_params=composed.layer_params,
        )

    def _resolve_bottom_layers(self, rng: np.random.Generator) -> tuple[str, float, list[LayerSpec]]:
        """Класс, угол объекта и слои пресета (без defect-слоя) — из `rng`.

        Порядок розыгрышей — часть контракта seed (LS-006): `integers` (класс) -> `uniform`
        (угол) -> `get_sprite`. Общий для `render()` и `nominal_layers()`, чтобы для одного seed
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

        Класс и спрайт — как в `render()` для того же `rng` (`_resolve_bottom_layers`); угол объекта
        игнорируется (раскладка при угле 0). Каждый слой — `transform_layer`
        (заливка -> scale -> поворот слоя), но БЕЗ выборки augment; defect-слои пропускаются.
        Только читает: это просмотр, не объект ленты.
        Массивы — read-only виды (не копии): ссылки на кэш фабрики наружу не уходят записываемыми.
        """
        class_name, _angle_deg, bottom_layers = self._resolve_bottom_layers(rng)
        layers = [
            (
                layer.name,
                _read_only_view(
                    transform_layer(load_layer_sprite(layer), layer.scale, layer.angle_deg, 0.0, layer.color_rgb)
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
        никогда не красит область ЗА пределами объекта (круглый объект, а не квадратный спрайт
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
