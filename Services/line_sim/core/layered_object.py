"""LayeredObject — объект ленты из слоёв: выборка и рендер один раз, при создании.

Сцена рисует каждый активный объект на каждом кадре; выборка внутри рендера дала
бы дрожание этикетки от кадра к кадру. Поэтому вся случайность (аугментация,
розыгрыш дефекта) потребляется в `__init__`, там же объект компонуется в RGBA и
кэшируется; `render()` случайности не потребляет и возвращает тот же массив.

Розыгрыш и композиция стека слоёв — `Services.layer_render.layers.compose_layers` (Task 2.3);
здесь остаются паспорт (разбор `passport.defect`, `replace`) и read-only кэш. Конвенция холста —
в докстринге `Services.layer_render.layers`.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from Services.layer_render.factory import RenderedObject
from Services.layer_render.layers import LayerSpec, canvas_size, compose_layers, transform_layer
from Services.line_sim.interfaces import ObjectPassport

# `canvas_size` — в `__all__` ради старого пути импорта (test_acceptance_2_3_layers.py:1153); иначе ruff F401 снимет.
__all__ = ["LayeredObject", "canvas_size"]


class LayeredObject:
    """Объект = паспорт + слои; RGBA компонуется один раз при создании.

    Pre:
      - `layers` не пуст; спрайты — RGBA uint8 (строковые id грузит `ObjectFactory`)
    Post:
      - `render()` возвращает один и тот же read-only RGBA-массив, альфа не пуста
      - `passport.layer_params` содержит выбранные значения; `passport.defect` —
        имена активных defect-слоёв через запятую или None
      - входной `passport.defect` (имена через запятую) принудительно включает эти
        defect-слои без розыгрыша; неизвестное имя — ValueError
      - слой i берёт случайность из `rng.spawn(len(layers))[i]`: порядок слоёв —
        часть контракта seed, розыгрыш одного слоя не сдвигает другие
      - входной `passport` не мутируется (у объекта своя копия)
    """

    # Алиас для потребителей прежнего имени (`core/factory.py`, тесты line_sim): тот же объект.
    _transform = staticmethod(transform_layer)

    def __init__(self, passport: ObjectPassport, layers: list[LayerSpec], rng: np.random.Generator) -> None:
        forced = [n.strip() for n in (passport.defect or "").split(",") if n.strip()]
        composed = compose_layers(layers, rng, passport.angle_deg, forced, label=passport.object_id)
        self.passport = replace(
            passport, layer_params=composed.layer_params, defect=",".join(composed.active_defects) or None
        )
        self._rgba = composed.rgba
        self._rgba.flags.writeable = False  # кэш не портится через возвращённую ссылку

    @classmethod
    def from_rendered(cls, rendered: RenderedObject, *, object_id: str, spawn_encoder: float) -> LayeredObject:
        """Объект ленты из готового `RenderedObject` (Task 2.4b): паспорт из его полей, без нового розыгрыша.

        `render()` вернёт ТОТ ЖЕ массив `rendered.rgba` (копии нет); `lateral_px` — дефолт (его ставит спавнер).
        """
        obj = cls.__new__(cls)
        obj.passport = ObjectPassport(
            object_id=object_id,
            class_name=rendered.class_name,
            angle_deg=rendered.angle_deg,
            defect=rendered.defect,
            spawn_encoder=spawn_encoder,
            layer_params=rendered.layer_params,
        )
        obj._rgba = rendered.rgba
        obj._rgba.flags.writeable = False  # без копии: render() is rendered.rgba; read-only, как в __init__
        return obj

    def render(self) -> np.ndarray:
        """Закэшированный RGBA объекта (read-only; копию делать вызывающему)."""
        return self._rgba
