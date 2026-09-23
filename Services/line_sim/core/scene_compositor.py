"""SceneCompositor — конкретная реализация `SceneCompositorProtocol` (Task 3.4):
держит `ObjectSpawner` и рисует его активные объекты на фон камеры.

Геометрия объекта в кадре (контракт лида, план Task 3.4 ред. 2):
`cx = encoder_to_offset_mm(now_encoder, passport.spawn_encoder) * px_per_mm - x_px`,
`cy = belt_y_px - y_px`. Кадр — RGB uint8 `(h_px, w_px, 3)`; в BGR переводит вызывающий
(плагин), НЕ этот класс (LS-009).

**Направление ленты и точка входа (контракт лида 5.3b, §4.2.1).** `belt_direction`
(±1, дефолт `1`) и `entry_x_px` (дефолт `0.0`) обобщают формулу центра:
`cx = entry_x_px + belt_direction * offset_mm * px_per_mm - x_px`. Дефолты дают
байт-в-байт прежнее поведение (`entry_x_px=0`, `belt_direction=1` — формула
вырождается в исходную). Сдвиг фонового тайла по X использует тот же
`belt_direction` (тот же знак, что у объектов — иначе фон и диски «расходятся» при
развороте ленты). `belt_direction` вне `{-1, 1}` — `ValueError`, называющий
переданное значение.

`render()` НЕ зовёт `spawner.tick()` — тик (часы + rng) принадлежит вызывающему.

**Фон-текстура (Task 3.6).** `background_tile` — необязательный RGB uint8 тайл; если
задан, фон сцены — этот тайл, прокрученный по X на `encoder_to_offset_mm(now_encoder,
0.0) * px_per_mm` (та же формула и тот же `px_per_mm`, что у объектов — это единственный
инвариант, ради которого задача существует: разойдись формулы, диски поедут «по льду»
относительно ленты). Тайл не растягивается под кадр — уже кадра значит повторение
(циклический индекс по модулю ширины тайла). По Y тайл кладётся симметрично относительно
`belt_y_px`; строки выше/ниже полосы тайла закрашиваются `background_bgr`, как и раньше.
`background_tile=None` — поведение байт в байт как до Task 3.6 (сплошная заливка).
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
    понадобится). `background_tile`, если задан, — RGB uint8 `(th, tw, 3)`,
    `th >= 1`, `tw >= 1` — иное бросает `ValueError` в конструкторе, называя
    проблемное свойство тайла (форма/dtype/каналы). С тайлом `now_encoder` обязан быть
    конечным: NaN/inf дают исключение при округлении сдвига (без тайла — не дают).
    Post: `render()` не мутирует `spawner` (не зовёт `tick()`/`active_objects()` кроме
    чтения); пустой спавнер даёт кадр одного фона, без исключений; возвращённые паспорта —
    объекты, чей bbox пересекается с `camera_rect` (частично видимый считается видимым),
    в порядке спавна (порядок `spawner.active_objects()`). `background_tile=None` —
    рендер идентичен байт в байт версии до Task 3.6.
    """

    def __init__(
        self,
        spawner: ObjectSpawner,
        px_per_mm: float,
        belt_y_px: float,
        background_bgr: tuple[int, int, int] = (60, 60, 60),
        background_tile: np.ndarray | None = None,
        belt_direction: int = 1,
        entry_x_px: float = 0.0,
    ) -> None:
        if belt_direction not in (1, -1):
            raise ValueError(f"belt_direction: ожидалось ±1, получено {belt_direction!r}")
        self._spawner = spawner
        self._px_per_mm = px_per_mm
        self._belt_y_px = belt_y_px
        self._background_bgr = background_bgr
        self._background_tile = None if background_tile is None else _validate_background_tile(background_tile)
        self._belt_direction = belt_direction
        self._entry_x_px = entry_x_px

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

        if self._background_tile is not None:
            tile = self._background_tile
            th, tw = tile.shape[:2]
            # Тот же px_per_mm и тот же encoder_to_offset_mm, что у объектов (см.
            # докстринг модуля) — начало отсчёта тайла (spawn_enc=0.0) фиксировано, не
            # завязано на конкретный объект.
            shift_px = int(round(float(encoder_to_offset_mm(now_encoder, 0.0) * self._px_per_mm)))
            cols = (np.arange(w) + int(round(x_px)) - self._belt_direction * shift_px) % tw
            top = int(round(self._belt_y_px - th / 2))
            rows = np.arange(h) + int(round(y_px)) - top
            valid = (rows >= 0) & (rows < th)
            frame[valid] = tile[rows[valid]][:, cols]

        passports: list[ObjectPassport] = []
        for obj in self._spawner.active_objects():
            sprite = obj.render()
            offset_mm = encoder_to_offset_mm(now_encoder, obj.passport.spawn_encoder)
            cx = self._entry_x_px + self._belt_direction * offset_mm * self._px_per_mm - x_px
            cy = self._belt_y_px - y_px
            sh, sw = sprite.shape[:2]
            if not _bbox_intersects(cx, cy, sw, sh, w, h):
                continue
            frame = composite(frame, sprite, (cx, cy))
            passports.append(obj.passport)
        return frame, passports


def _validate_background_tile(tile: np.ndarray) -> np.ndarray:
    """Проверить `background_tile` (Task 3.6) и вернуть его копию.

    Post: RGB uint8 `(th, tw, 3)`, `th >= 1`, `tw >= 1` — иное `ValueError`,
    называющий конкретное проблемное свойство (форма/dtype/каналы/ширина/высота).
    """
    if not isinstance(tile, np.ndarray):
        raise ValueError(f"background_tile: ожидался np.ndarray, получено {type(tile)!r}")
    if tile.dtype != np.uint8:
        raise ValueError(f"background_tile: ожидался dtype=uint8, получено dtype={tile.dtype}")
    if tile.ndim != 3:
        raise ValueError(f"background_tile: ожидался ndim=3 (H, W, 3), получено ndim={tile.ndim}")
    if tile.shape[2] != 3:
        raise ValueError(f"background_tile: ожидалось 3 канала (RGB), получено shape[2]={tile.shape[2]}")
    if tile.shape[0] < 1:
        raise ValueError(f"background_tile: высота (shape[0]) должна быть >= 1, получено {tile.shape[0]}")
    if tile.shape[1] < 1:
        raise ValueError(f"background_tile: ширина (shape[1]) должна быть >= 1, получено {tile.shape[1]}")
    return tile.copy()


def _bbox_intersects(cx: float, cy: float, sw: int, sh: int, w: int, h: int) -> bool:
    """bbox объекта (центр `cx,cy`, размер `sw x sh`) пересекает кадр `[0,w) x [0,h)`.

    Строгие неравенства: bbox, касающийся края ровно (`x1 == 0` или `x0 == w`), СЧИТАЕТСЯ
    невидимым — нулевая по площади пересечения полоса не даёт видимых пикселей (решение
    автора, hazard-тест закрепляет границу).
    """
    x0, x1 = cx - sw / 2.0, cx + sw / 2.0
    y0, y1 = cy - sh / 2.0, cy + sh / 2.0
    return x1 > 0 and x0 < w and y1 > 0 and y0 < h
