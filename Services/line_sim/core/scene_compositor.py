"""SceneCompositor — конкретная реализация `SceneCompositorProtocol` (Task 3.4):
держит `ObjectSpawner` и рисует его активные объекты на фон камеры.

Геометрия объекта в кадре (контракт лида, план Task 3.4 ред. 2):
`cx = encoder_to_offset_mm(now_encoder, passport.spawn_encoder) * px_per_mm - x_px`,
`cy = belt_y_px - y_px`. Кадр — RGB uint8 `(h_px, w_px, 3)`; в BGR переводит вызывающий
(плагин), НЕ этот класс (LS-009).

`render()` НЕ зовёт `spawner.tick()` — тик (часы + rng) принадлежит вызывающему.
"""

from __future__ import annotations

import numpy as np

from Services.dataset_gen.core.compose import composite
from Services.line_sim.core.belt import encoder_to_offset_mm
from Services.line_sim.core.spawner import ObjectSpawner
from Services.line_sim.interfaces import ObjectPassport


class SceneCompositor:
    """Сцена «лента с объектами»: фон + активные объекты спавнера, альфа-композиция.

    Pre: `px_per_mm > 0`... — не проверяется явно (числовой параметр камеры, не
    пользовательский конфиг с валидацией на границе; проверка — Task 3.4/Ф4, если
    понадобится).
    Post: `render()` не мутирует `spawner` (не зовёт `tick()`/`active_objects()` кроме
    чтения); пустой спавнер даёт кадр одного фона, без исключений; возвращённые паспорта —
    объекты, чей bbox пересекается с `camera_rect` (частично видимый считается видимым),
    в порядке спавна (порядок `spawner.active_objects()`).
    """

    def __init__(
        self,
        spawner: ObjectSpawner,
        px_per_mm: float,
        belt_y_px: float,
        background_bgr: tuple[int, int, int] = (60, 60, 60),
    ) -> None:
        self._spawner = spawner
        self._px_per_mm = px_per_mm
        self._belt_y_px = belt_y_px
        self._background_bgr = background_bgr

    def render(
        self, now_encoder: float, camera_rect: tuple[float, float, float, float]
    ) -> tuple[np.ndarray, list[ObjectPassport]]:
        """Кадр сцены (фон + активные объекты) + паспорта объектов в кадре."""
        x_px, y_px, w_px, h_px = camera_rect
        w, h = int(round(w_px)), int(round(h_px))
        frame = np.empty((h, w, 3), dtype=np.uint8)
        # background_bgr — концептуально BGR (имя параметра из контракта тестера);
        # кадр хранится в RGB, поэтому каналы переставляются при заливке фона.
        b, g, r = self._background_bgr
        frame[:, :, 0] = r
        frame[:, :, 1] = g
        frame[:, :, 2] = b

        passports: list[ObjectPassport] = []
        for obj in self._spawner.active_objects():
            sprite = obj.render()
            offset_mm = encoder_to_offset_mm(now_encoder, obj.passport.spawn_encoder)
            cx = offset_mm * self._px_per_mm - x_px
            cy = self._belt_y_px - y_px
            sh, sw = sprite.shape[:2]
            if not _bbox_intersects(cx, cy, sw, sh, w, h):
                continue
            frame = composite(frame, sprite, (cx, cy))
            passports.append(obj.passport)
        return frame, passports


def _bbox_intersects(cx: float, cy: float, sw: int, sh: int, w: int, h: int) -> bool:
    """bbox объекта (центр `cx,cy`, размер `sw x sh`) пересекает кадр `[0,w) x [0,h)`.

    Строгие неравенства: bbox, касающийся края ровно (`x1 == 0` или `x0 == w`), СЧИТАЕТСЯ
    невидимым — нулевая по площади пересечения полоса не даёт видимых пикселей (решение
    автора, hazard-тест закрепляет границу).
    """
    x0, x1 = cx - sw / 2.0, cx + sw / 2.0
    y0, y1 = cy - sh / 2.0, cy + sh / 2.0
    return x1 > 0 and x0 < w and y1 > 0 and y0 < h
