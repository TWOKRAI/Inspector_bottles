"""ObjectFactory ленты — наследник `Services.layer_render.factory.ObjectFactory` (Task 2.4b).

Картинку и выбор класса/угла/дефекта делает база (`render`); здесь только своё: флаг оператора
`force_defect_next()` и паспорт ленты (`LayeredObject.from_rendered`).

`_DEFECT_SIDE_FRAC`, `_DEFECT_OFFSET_FRAC`, `apply_occlusion`, `load_layer_sprite` модуль сам не
использует — их читают тесты как глобалы модуля; в `__all__`, иначе ruff F401 снимет импорт.
"""

from __future__ import annotations

import numpy as np

from Services.layer_render import load_layer_sprite
from Services.layer_render.effects import apply_occlusion
from Services.layer_render.factory import _DEFECT_OFFSET_FRAC, _DEFECT_SIDE_FRAC
from Services.layer_render.factory import ObjectFactory as _RenderFactory
from Services.layer_render.preset import ScenePreset
from Services.line_sim.core.layered_object import LayeredObject

__all__ = ["_DEFECT_OFFSET_FRAC", "_DEFECT_SIDE_FRAC", "ObjectFactory", "apply_occlusion", "load_layer_sprite"]


class ObjectFactory(_RenderFactory):
    """Строит `LayeredObject` ленты: база рисует объект, этот класс добавляет паспорт и форс оператора.

    Дефект `"damaged"` — с вероятностью пресета или форсированно через `force_defect_next()`.
    """

    def __init__(self, preset: ScenePreset) -> None:
        super().__init__(preset)
        self._force_defect_pending = False

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
        """Собрать объект ленты: `render` базы + паспорт.

        `force_defect_next()` ТОЛЬКО читается здесь (`forced`), а гасится лишь ПОСЛЕ того,
        как объект успешно построен — транзитная ошибка (например каталог на сетевом
        томе моргнул на одном вызове) не должна съедать нажатие оператора: следующий успешный
        `make()` обязан получить дефект, а не "он как будто сработал и пропал" (пин ревью,
        см. test_hazards_3_2.py — репродукция флаки-каталога).
        """
        forced = self._force_defect_pending
        rendered = self.render(rng, force_defect=forced, label=object_id)
        obj = LayeredObject.from_rendered(rendered, object_id=object_id, spawn_encoder=spawn_encoder)
        self._force_defect_pending = False  # гасим ТОЛЬКО после успеха — см. докстринг выше
        return obj
