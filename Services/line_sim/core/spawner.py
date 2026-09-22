"""ObjectSpawner — непрерывный поток объектов на ленте: спавн по интервалу, деспавн за
границей сцены, пауза, форс-хук брака.

Часы и очередь спавна принадлежат спавнеру целиком (LS-008): `tick()` — единственная
точка входа, вызывающий передаёт только "что сейчас" (`now_encoder`, `now_wall_s`, `rng`).
Единственный producer — поток-продюсер кадров (Task 3.4); лок не нужен, это НЕ
многопоточный доступ к одному инстансу (если появится второй вызывающий — тогда лок).
"""

from __future__ import annotations

import numpy as np

from Services.line_sim.core.belt import encoder_to_offset_mm
from Services.line_sim.core.factory import ObjectFactory
from Services.line_sim.core.layered_object import LayeredObject


class ObjectSpawner:
    """Спавнит объекты на ленте по интервалу, снимает уехавшие за `scene_length_mm`.

    Пауза (`set_paused(True)`) останавливает только НОВЫЙ спавн — деспавн работает как
    обычно на каждом `tick()` (существующие объекты продолжают двигаться и уезжать со
    сцены, останов ленты — отдельный контрол, см. `VfdDriver`).

    Форс-хук «выпусти брак сейчас» (`force_defect_next()`, делегат `ObjectFactory.
    force_defect_next()`, LS-007) на паузе объект НЕ создаёт — только помечает СЛЕДУЮЩИЙ
    реальный спавн (после снятия паузы) как дефектный: оператор не получает объект на
    остановленном потоке, а нажатие не теряется, потому что фабрика гасит флаг лишь
    после того, как объект успешно собран (LS-006/LS-007).

    Pre: `interval_s = (lo, hi)` с `0 < lo <= hi`; `scene_length_mm > 0`.
    Post: `tick()` создаёт не больше одного объекта за вызов; пропущенные интервалы не
    догоняются — следующий срок считается от `now_wall_s` текущего тика, не от
    просроченного срока.
    """

    def __init__(self, factory: ObjectFactory, interval_s: tuple[float, float], scene_length_mm: float) -> None:
        lo, hi = interval_s
        if lo > hi:
            raise ValueError(f"interval_s: lo={lo} > hi={hi} — нижняя граница интервала больше верхней")
        if lo <= 0:
            raise ValueError(f"interval_s: lo={lo} <= 0 — интервал спавна должен быть положительным")
        if scene_length_mm <= 0:
            raise ValueError(f"scene_length_mm={scene_length_mm} <= 0 — длина сцены должна быть положительной")

        self._factory = factory
        self._interval_s = interval_s
        self._scene_length_mm = scene_length_mm
        self._active: list[LayeredObject] = []
        self._deadline: float | None = None
        self._paused = False
        self._next_id_n = 1

    def tick(self, *, now_encoder: float, now_wall_s: float, rng: np.random.Generator) -> None:
        """Один шаг часов спавнера: сперва деспавн (на КАЖДОМ тике), затем — спавн.

        Первый `tick()` только взводит срок (`now_wall_s + rng.uniform(*interval_s)`) и
        не создаёт объект. Если `factory.make()` бросает исключение — объект не
        добавляется, срок НЕ сдвигается (сдвигается только после успешной сборки), так
        что следующий `tick()` на просроченном сроке повторит попытку, а не потеряет её
        и не создаст сразу два объекта за одну.
        """
        self._active = [
            obj
            for obj in self._active
            if encoder_to_offset_mm(now_encoder, obj.passport.spawn_encoder) <= self._scene_length_mm
        ]

        if self._deadline is None:
            self._deadline = now_wall_s + float(rng.uniform(*self._interval_s))
            return

        if self._paused:
            return

        if now_wall_s >= self._deadline:
            object_id = f"obj-{self._next_id_n}"
            obj = self._factory.make(object_id, spawn_encoder=now_encoder, rng=rng)
            self._active.append(obj)
            self._next_id_n += 1
            self._deadline = now_wall_s + float(rng.uniform(*self._interval_s))

    def active_objects(self) -> list[LayeredObject]:
        """Копия списка активных объектов — мутация результата не трогает спавнер."""
        return list(self._active)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def force_defect_next(self) -> None:
        """Тонкий делегат `ObjectFactory.force_defect_next()` — см. докстринг класса."""
        self._factory.force_defect_next()
