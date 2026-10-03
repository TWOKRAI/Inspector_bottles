"""SceneCompositor — конкретная реализация `SceneCompositorProtocol` (Task 3.4):
держит `ObjectSpawner` и рисует его активные объекты на фон камеры.

Геометрия объекта в кадре (контракт лида, план Task 3.4 ред. 2):
`cx = encoder_to_offset_mm(now_encoder, passport.spawn_encoder) * px_per_mm - x_px`,
`cy = belt_y_px + passport.lateral_px - y_px` (`lateral_px` — поперечное смещение диска,
по умолчанию `0.0` -> прежний кадр байт в байт). Кадр — RGB uint8 `(h_px, w_px, 3)`; в BGR переводит вызывающий
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

**Фон (layer-render, Task 1.1 / 1.3).** Способов задать фон два: сплошная заливка `background_bgr`
(BGR) или стек слоёв `background_layers` — необязательный список `SolidFill | ScrollingTile`
снизу вверх (`Services/layer_render`). Стек задан — заменяет заливку `background_bgr`; под всеми
слоями чёрный, цвета слоёв — сразу RGB (не BGR, как `background_bgr`). Тайлы стека сдвигаются на
`encoder_to_offset_mm(now_encoder, 0.0) * px_per_mm` с тем же знаком `belt_direction`, что у объектов
(та же формула и тот же `px_per_mm` — единственный инвариант, ради которого сдвиг существует: разойдись
формулы, диски поедут «по льду» относительно ленты). `None` — сплошная заливка `background_bgr`.
Прежний параметр одиночного тайла удалён в Task 1.3 (LR-002): та же картинка задаётся слоем `tile`.

**Кадр рисует `layer_render.render_scene` (Task 2.5, LR-003).** Здесь остаются геометрия ленты, отсечение объектов
по bbox и список паспортов; фон, порядок объектов и композиция — в `render_scene`. Без `background_layers` фон —
стек из одного `SolidFill` (цвет `background_bgr` переставлен в RGB): правила цвета живут в одном месте.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from Services.line_sim.core.belt import encoder_to_offset_mm
from Services.line_sim.core.spawner import ObjectSpawner
from Services.layer_render import (
    PlacedObject,
    SceneBackground,
    ScrollingTile,
    SolidFill,
    fold_background,
    render_scene,
)
from Services.line_sim.interfaces import ObjectPassport


class SceneCompositor:
    """Сцена «лента с объектами»: фон + активные объекты спавнера, альфа-композиция.

    Pre: `px_per_mm > 0`... — не проверяется явно (числовой параметр камеры, не
    пользовательский конфиг с валидацией на границе; проверка — Task 3.4/Ф4, если
    понадобится). Со стеком слоёв `now_encoder` и `x_px`/`y_px` из `camera_rect` обязаны быть конечными: NaN/inf
    дают исключение при округлении сдвига и начала окна (без стека — не дают: сдвиг и начало окна не считаются,
    кадр — чистый фон). Со стеком `belt_y_px` NaN/inf даёт ту же ошибку, что прежде, но позже: после чтения
    спавнера и `render()` объектов (прежде до). Форму тайла слоя проверяет `ScrollingTile`, не этот класс.
    `background_bgr` (без стека) — три `int` 0..255 в порядке (B, G, R): иначе `ValueError` в `__init__` (прежде
    `(300, 0, 0)` падал `OverflowError` в `render()`, а дробный цвет усекался молча; `np.int64` и `60.0` теперь тоже
    отклоняются, как и `bool` вроде `(True, 0, 0)` — правила цвета в одном месте, `SolidFill`). Не тройка — ошибка
    распаковки, тоже в `__init__`.
    Прочие сужения Task 2.5 (проверки `render_scene`, LR-003): спрайт спавнера не RGBA `uint8` (float32, uint16, RGB) —
    `ValueError` из `PlacedObject` (прежде кадр; RGB со bbox, задевающим кадр, давал паспорт); элемент
    `background_layers` не `SolidFill`/`ScrollingTile` (в том числе «утиный» тайл) — `ValueError`
    `SceneBackground.layers[i]`, где `i` — индекс СВЁРНУТОГО стека, не пользовательского (прежде `AttributeError`
    или кадр).
    Post: `render()` не мутирует `spawner` (не зовёт `tick()`/`active_objects()` кроме
    чтения); пустой спавнер даёт кадр одного фона, без исключений; возвращённые паспорта —
    объекты, чей bbox пересекается с `camera_rect` (частично видимый считается видимым),
    в порядке спавна (порядок `spawner.active_objects()`). Без `background_layers` рендер
    идентичен байт в байт версии до Task 3.6 (сплошная заливка).
    """

    def __init__(
        self,
        spawner: ObjectSpawner,
        px_per_mm: float,
        belt_y_px: float,
        background_bgr: tuple[int, int, int] = (60, 60, 60),
        belt_direction: int = 1,
        entry_x_px: float = 0.0,
        background_layers: Sequence[SolidFill | ScrollingTile] | None = None,
    ) -> None:
        # bool — подкласс int (True == 1), дробное 1.0 тоже равно 1: оба отклоняются (ревью 5.3b п.3).
        if isinstance(belt_direction, bool) or not isinstance(belt_direction, int) or belt_direction not in (1, -1):
            raise ValueError(f"belt_direction: ожидалось ±1, получено {belt_direction!r}")
        self._spawner = spawner
        self._px_per_mm = px_per_mm
        self._belt_y_px = belt_y_px
        self._belt_direction = belt_direction
        self._entry_x_px = entry_x_px
        # Сдвиг тайлов считается только со стеком: без него `now_encoder=NaN` не должен бросать (docstring класса).
        self._has_stack = background_layers is not None
        if background_layers is None:
            # `background_bgr` — BGR, `SolidFill` — RGB: каналы переставляются здесь; цвет проверяет `SolidFill`.
            b, g, r = background_bgr
            try:
                self._bg_layers: list[SolidFill | ScrollingTile] = [SolidFill(color_rgb=(r, g, b))]
            except ValueError as exc:
                # В тексте `SolidFill` чужое имя и обратный порядок каналов; значение не повторяем.
                raise ValueError("SceneCompositor.background_bgr: ожидались три целых 0..255 (B, G, R)") from exc
        else:
            # Стек слоёв (layer-render 1.1) сворачивается один раз.
            self._bg_layers = fold_background(list(background_layers))

    def render(
        self, now_encoder: float, camera_rect: tuple[float, float, float, float]
    ) -> tuple[np.ndarray, list[ObjectPassport]]:
        """Кадр сцены (фон + активные объекты) + паспорта объектов в кадре; рисует `render_scene`."""
        x_px, y_px, w_px, h_px = camera_rect
        w, h = int(round(w_px)), int(round(h_px))
        scroll_px = 0
        origin_xy = (0, 0)  # SolidFill origin не читает: без стека x_px/y_px NaN/inf округлять нельзя (прежний кадр)
        if self._has_stack:
            origin_xy = (int(round(x_px)), int(round(y_px)))
            # shift_px — тот же encoder_to_offset_mm * px_per_mm, что у объектов (начало отсчёта spawn_enc=0.0
            # фиксировано, не завязано на конкретный объект); знак — belt_direction, как у объектов.
            shift_px = int(round(float(encoder_to_offset_mm(now_encoder, 0.0) * self._px_per_mm)))
            scroll_px = self._belt_direction * shift_px
        background = SceneBackground(
            self._bg_layers,
            (w, h),
            center_y=self._belt_y_px,
            scroll_px=scroll_px,
            origin_xy=origin_xy,
        )

        placed: list[PlacedObject] = []
        passports: list[ObjectPassport] = []
        for obj in self._spawner.active_objects():
            sprite = obj.render()
            offset_mm = encoder_to_offset_mm(now_encoder, obj.passport.spawn_encoder)
            cx = self._entry_x_px + self._belt_direction * offset_mm * self._px_per_mm - x_px
            cy = self._belt_y_px + obj.passport.lateral_px - y_px
            sh, sw = sprite.shape[:2]
            if not _bbox_intersects(cx, cy, sw, sh, w, h):
                continue
            placed.append(PlacedObject(sprite, (cx, cy)))
            passports.append(obj.passport)
        return render_scene(background, placed, (), None), passports


def _bbox_intersects(cx: float, cy: float, sw: int, sh: int, w: int, h: int) -> bool:
    """bbox объекта (центр `cx,cy`, размер `sw x sh`) пересекает кадр `[0,w) x [0,h)`.

    Строгие неравенства: bbox, касающийся края ровно (`x1 == 0` или `x0 == w`), СЧИТАЕТСЯ
    невидимым — нулевая по площади пересечения полоса не даёт видимых пикселей (решение
    автора, hazard-тест закрепляет границу).
    """
    x0, x1 = cx - sw / 2.0, cx + sw / 2.0
    y0, y1 = cy - sh / 2.0, cy + sh / 2.0
    return x1 > 0 and x0 < w and y1 > 0 and y0 < h
