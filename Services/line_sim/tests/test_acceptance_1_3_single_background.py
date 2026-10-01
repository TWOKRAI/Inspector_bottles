# -*- coding: utf-8 -*-
"""Слепые acceptance-тесты layer-render Task 1.3 (уровень компоновщика): один способ задать фон.

Источник контракта: `plans/layer-render/phase-1.md`, Task 1.3 (DESIGN + Acceptance A1, A3, A4). Написаны ДО
реализации: из `SceneCompositor` убирается kwarg `background_tile` вместе с `_validate_background_tile`;
`background_layers` (Task 1.1) остаётся единственным способом задать тайловый фон, `background_bgr`
(сплошная заливка без слоёв) остаётся.

ЗАПРЕЩЁННЫЕ ПУТИ (не читались): `.claude/worktrees/layer-render` (рабочее дерево автора) и любой diff/реализация
Task 1.3 — её в этом дереве нет по построению (worktree на коммите «только план»). Прочитано как ГОТОВАЯ
ЗАВИСИМОСТЬ: `Services/line_sim/core/scene_compositor.py` и `Services/layer_render/interfaces.py` (до 1.3),
старые тесты 3.6/5.3b (источник свойств, которые переносятся).

Что здесь НЕ делается: у старых тестов компоновщика (`test_acceptance_3_6.py`, `test_hazards_3_6.py`,
`test_hazards_5_3b.py`) НЕТ литералов sha256 — они пинят пиксели/столбцы. Единственный sha256-литерал старого
пути (`_GOLDEN_BACKGROUND_TEXTURE_SHA`) живёт в плагинном тесте и переносится в
`Plugins/sim/scene_source/tests/test_acceptance_1_3_stand.py`. Здесь свойства старых тестов повторены
дословно на `background_layers=[SolidFill(<тот же цвет RGB>), ScrollingTile(<тот же тайл>)]`.

Таблица «старый тест -> эквивалент здесь» (A3/A4):
  test_acceptance_3_6::test_background_moves_with_object        -> test_layers_background_moves_with_object
  test_acceptance_3_6::test_background_shift_is_cyclic          -> test_layers_shift_is_cyclic
  test_acceptance_3_6::test_narrow_tile_fills_frame_without_stretch
      -> test_layers_narrow_tile_fills_frame_without_stretch
  test_acceptance_3_6::test_any_image_is_valid_background       -> test_layers_any_image_is_valid_background
  test_hazards_3_6::test_h1 (px_per_mm, ненулевой энкодер)      -> test_layers_h1_follows_object_...
  test_hazards_3_6::test_h3 (нечётная высота, нецелые belt_y/y) -> test_layers_h3_odd_tile_height_...
  test_hazards_3_6::test_h4 (tile=None == сплошная заливка)      -> test_background_bgr_solid_fill_stays_without_layers
  test_hazards_3_6::test_h5 (энкодер 1e9, цикличность)           -> test_layers_h5_very_large_encoder_cyclic
  test_hazards_3_6::test_h10 (x_px входит в сдвиг)                -> test_layers_h10_camera_rect_x_offset_...
  test_hazards_3_6::test_h11 (копия, не ссылка)                   -> test_layers_h11_tile_array_mutation_...
  test_hazards_5_3b::test_background_tile_shifts_same_direction.. -> test_layers_tile_shifts_same_direction_as_objects
  test_hazards_3_6::test_h2 (валидация формы/dtype тайла)         -> НЕ переносится: kwarg исчезает; валидацию
      тайла держит `ScrollingTile.__post_init__` (его тесты — `Services/layer_render/tests`, не этот файл).

Кадр компоновщика — RGB (тайл `ScrollingTile` и цвет `SolidFill` — тоже RGB). Прежний `background_bgr` — BGR:
`background_bgr=(60, 61, 62)` соответствует `SolidFill((62, 61, 60))`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.layer_render import ScrollingTile, SolidFill
from Services.line_sim import (
    FACTOR_MM,
    ObjectFactory,
    ObjectSpawner,
    SceneCompositor,
    ScenePreset,
    encoder_to_offset_mm,
)
from Services.line_sim.interfaces import ObjectPassport

# Services/line_sim/tests/<файл> -> parents[3] == корень репозитория.
_REPO_ROOT = Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------------------
# Хелперы (копии паттернов старых тестов; сами ничего не тестируют)
# --------------------------------------------------------------------------------------


def _make_spawner(tmp_path: Path, color_bgr: tuple[int, int, int] = (0, 0, 255), **spawner_kwargs) -> ObjectSpawner:
    class_dir = tmp_path / "classes" / "square"
    class_dir.mkdir(parents=True)
    b, g, r = color_bgr
    sprite_bgra = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite_bgra[:, :, 0], sprite_bgra[:, :, 1], sprite_bgra[:, :, 2], sprite_bgra[:, :, 3] = b, g, r, 255
    imwrite_unicode(class_dir / "sprite.png", sprite_bgra)
    preset = ScenePreset(catalog_dir=str(tmp_path / "classes"), angle_range_deg=(0.0, 0.0), defect_probability=0.0)
    kwargs = {"interval_s": (1000.0, 1000.0), "scene_length_mm": 1_000_000.0, "max_active": 200}
    kwargs.update(spawner_kwargs)
    return ObjectSpawner(ObjectFactory(preset), **kwargs)


def _spawn_one_at(spawner: ObjectSpawner, spawn_encoder: float, seed: int = 0):
    """Ровно один объект с `passport.spawn_encoder == spawn_encoder` (первый tick только взводит срок)."""
    rng = np.random.default_rng(seed)
    spawner.tick(now_encoder=spawn_encoder, now_wall_s=0.0, rng=rng)
    spawner.tick(now_encoder=spawn_encoder, now_wall_s=2000.0, rng=rng)
    objs = spawner.active_objects()
    assert len(objs) == 1, "setup sanity: ожидался ровно один заспавненный объект"
    return objs[0]


def _stack(tile: np.ndarray, solid_rgb: tuple[int, int, int] = (60, 60, 60)) -> list:
    """Стек `[solid, tile]` — новый эквивалент пары (`background_bgr`, `background_tile`) старого пути."""
    return [SolidFill(solid_rgb), ScrollingTile(tile)]


class _FakeObj:
    def __init__(self, passport: ObjectPassport, sprite: np.ndarray) -> None:
        self.passport = passport
        self._sprite = sprite

    def render(self) -> np.ndarray:
        return self._sprite


class _FakeSpawner:
    def __init__(self, obj: _FakeObj) -> None:
        self._obj = obj

    def active_objects(self) -> list[_FakeObj]:
        return [self._obj]


# --------------------------------------------------------------------------------------
# A1 — kwarg `background_tile` удалён
# --------------------------------------------------------------------------------------

_ANY_TILE_ARRAYS = [
    pytest.param(np.zeros((10, 10, 3), dtype=np.uint8), id="valid_rgb_tile"),
    pytest.param(np.zeros((10, 10), dtype=np.uint8), id="invalid_2d_array"),
    pytest.param(None, id="none"),
]


@pytest.mark.parametrize("tile", _ANY_TILE_ARRAYS)
def test_a1_background_tile_kwarg_is_rejected_with_typeerror(tmp_path, tile):
    """A1: `SceneCompositor(..., background_tile=<что угодно>)` -> `TypeError` «неожиданный kwarg» (а не
    ValueError валидации и не тихий приём). Ожидание ДО прогона: КРАСНЫЙ — сегодня kwarg принимается
    (valid / None — `DID NOT RAISE`; 2-D массив — `ValueError`, не `TypeError`)."""
    spawner = _make_spawner(tmp_path)
    with pytest.raises(TypeError) as info:
        SceneCompositor(spawner, px_per_mm=1.0, belt_y_px=10.0, background_tile=tile)
    assert "background_tile" in str(info.value), str(info.value)


def test_a1_scene_compositor_source_has_no_background_tile_name():
    """A1: в `scene_compositor.py` нет имени `background_tile` (ни kwarg, ни `_validate_background_tile`, ни
    докстринга-упоминания). Текстовая проверка, а не AST: по A6 имя не должно жить ни в комментарии, ни в строке.
    Ожидание ДО прогона: КРАСНЫЙ — сегодня имя встречается десятки раз."""
    text = (_REPO_ROOT / "Services" / "line_sim" / "core" / "scene_compositor.py").read_text(encoding="utf-8")
    assert "background_tile" not in text, "в scene_compositor.py осталось имя background_tile"


# --------------------------------------------------------------------------------------
# Сплошная заливка `background_bgr` без слоёв остаётся (порт test_hazards_3_6::test_h4)
# --------------------------------------------------------------------------------------


def test_background_bgr_solid_fill_stays_without_layers(tmp_path):
    """`background_bgr=(11, 22, 33)` (BGR) без `background_layers` -> кадр целиком заливается цветом; кадр RGB, значит
    каналы (33, 22, 11). Ожидание ДО прогона: ЗЕЛЁНЫЙ (страховочная сеть удаления)."""
    spawner = _make_spawner(tmp_path)
    compositor = SceneCompositor(spawner, px_per_mm=1.0, belt_y_px=20.0, background_bgr=(11, 22, 33))
    frame, passports = compositor.render(now_encoder=0.0, camera_rect=(0.0, 0.0, 40.0, 40.0))
    assert passports == []
    assert np.all(frame[:, :, 0] == 33) and np.all(frame[:, :, 1] == 22) and np.all(frame[:, :, 2] == 11)


# --------------------------------------------------------------------------------------
# A3/A4 — свойства старого пути держатся на `background_layers` (все ЗЕЛЁНЫЕ ДО прогона)
# --------------------------------------------------------------------------------------


def test_layers_background_moves_with_object(tmp_path):
    """Порт test_acceptance_3_6::test_background_moves_with_object. Столбец тайла под центром объекта
    (spawn_encoder=0, x_px=0) на любом энкодере ~0 (допуск ±1 px с учётом цикличности)."""
    tw, th = 50, 60
    tile = np.zeros((th, tw, 3), dtype=np.uint8)
    for u in range(tw):
        tile[:, u, 0] = u
    spawner = _make_spawner(tmp_path)
    obj = _spawn_one_at(spawner, spawn_encoder=0.0)
    compositor = SceneCompositor(spawner, px_per_mm=1.0, belt_y_px=100.0, background_layers=_stack(tile))
    read_row = 75  # полоса тайла [70, 130), спрайт 16x16 при cy=100 занимает [92, 108) -> строка 75 чистый фон
    for now_encoder in (0.0, 500.0, 1300.0):
        u = round(encoder_to_offset_mm(now_encoder, obj.passport.spawn_encoder) * 1.0)
        frame, _passports = compositor.render(now_encoder=now_encoder, camera_rect=(0.0, 0.0, 300.0, 200.0))
        tile_col = int(frame[read_row, u, 0])
        diff = min(tile_col % tw, (tw - tile_col) % tw)
        assert diff <= 1, f"encoder={now_encoder}: ожидался столбец тайла ~0, получен {tile_col}"


@pytest.mark.parametrize("px_per_mm", [0.6, 3.7, 12.5])
def test_layers_h1_follows_object_at_nonzero_encoder_and_stand_px_per_mm(tmp_path, px_per_mm):
    """Порт test_hazards_3_6::test_h1: нестандартный `px_per_mm` и объект на НЕнулевом энкодере — столбец
    тайла под центром объекта не уезжает с ростом энкодера."""
    tw, th = 200, 60
    tile = np.zeros((th, tw, 3), dtype=np.uint8)
    for u in range(tw):
        tile[:, u, 0] = u
    spawner = _make_spawner(tmp_path)
    spawn_encoder = 700.0
    obj = _spawn_one_at(spawner, spawn_encoder=spawn_encoder)
    compositor = SceneCompositor(spawner, px_per_mm=px_per_mm, belt_y_px=100.0, background_layers=_stack(tile))
    read_row = 75
    columns: list[int] = []
    span = 350.0 / (px_per_mm * FACTOR_MM)
    for now_encoder in (spawn_encoder, spawn_encoder + 0.37 * span, spawn_encoder + 0.81 * span):
        u = int(round(encoder_to_offset_mm(now_encoder, obj.passport.spawn_encoder) * px_per_mm))
        frame, _passports = compositor.render(now_encoder=now_encoder, camera_rect=(0.0, 0.0, 400.0, 200.0))
        columns.append(int(frame[read_row, u, 0]))
    base = columns[0]
    for c in columns[1:]:
        diff = min(abs(c - base) % tw, tw - (abs(c - base) % tw))
        assert diff <= 1, f"столбец тайла под объектом уехал при росте энкодера: {columns}"


def test_layers_shift_is_cyclic(tmp_path):
    """Порт test_acceptance_3_6::test_background_shift_is_cyclic: сдвиг ровно на ширину тайла даёт тот же кадр."""
    tw, th = 50, 40
    tile = np.zeros((th, tw, 3), dtype=np.uint8)
    for u in range(tw):
        tile[:, u, 0] = (u * 5) % 256
    compositor = SceneCompositor(_make_spawner(tmp_path), px_per_mm=1.0, belt_y_px=50.0, background_layers=_stack(tile))
    frame_zero, passports_zero = compositor.render(now_encoder=0.0, camera_rect=(0.0, 0.0, 200.0, 100.0))
    frame_full, passports_full = compositor.render(now_encoder=tw / FACTOR_MM, camera_rect=(0.0, 0.0, 200.0, 100.0))
    assert passports_zero == [] and passports_full == []
    assert np.array_equal(frame_zero, frame_full)


def test_layers_h5_very_large_encoder_cyclic(tmp_path):
    """Порт test_hazards_3_6::test_h5: энкодер ~1e9, tw=37 (взаимно просто с шагом узора 3) — цикличность держится."""
    tw, th = 37, 20
    tile = np.zeros((th, tw, 3), dtype=np.uint8)
    for u in range(tw):
        tile[:, u, 0] = (u * 3) % 256
    compositor = SceneCompositor(_make_spawner(tmp_path), px_per_mm=1.0, belt_y_px=15.0, background_layers=_stack(tile))
    frame_big, passports_big = compositor.render(now_encoder=1e9, camera_rect=(0.0, 0.0, 80.0, 40.0))
    frame_shifted, passports_shifted = compositor.render(
        now_encoder=1e9 + tw / FACTOR_MM, camera_rect=(0.0, 0.0, 80.0, 40.0)
    )
    assert passports_big == [] and passports_shifted == []
    assert np.array_equal(frame_big, frame_shifted)


def test_layers_narrow_tile_fills_frame_without_stretch(tmp_path):
    """Порт test_acceptance_3_6::test_narrow_tile_fills_frame_without_stretch: тайл 200 px в кадре 640 px — каждый
    столбец строки равен `u mod tw` (повторение, без растяжения и чёрных полей)."""
    tw, th = 200, 40
    tile = np.zeros((th, tw, 3), dtype=np.uint8)
    for u in range(tw):
        tile[:, u, 0] = u
    compositor = SceneCompositor(_make_spawner(tmp_path), px_per_mm=1.0, belt_y_px=50.0, background_layers=_stack(tile))
    frame_w, frame_h = 640, 100
    frame, passports = compositor.render(now_encoder=0.0, camera_rect=(0.0, 0.0, float(frame_w), float(frame_h)))
    assert passports == []
    read_row = 35  # top = round(50 - 40/2) = 30 -> строка 35 внутри полосы [30, 70)
    expected_row = np.zeros((frame_w, 3), dtype=np.uint8)
    for u in range(frame_w):
        expected_row[u, 0] = u % tw
    assert np.array_equal(frame[read_row], expected_row)


def test_layers_any_image_is_valid_background(tmp_path):
    """Порт test_acceptance_3_6::test_any_image_is_valid_background: однотонная картинка с диагональю."""
    tw, th = 40, 40
    flat = (10, 20, 30)
    tile = np.empty((th, tw, 3), dtype=np.uint8)
    tile[:, :, 0], tile[:, :, 1], tile[:, :, 2] = flat
    diag_marker = (250, 5, 5)
    for i in range(min(tw, th)):
        tile[i, i] = diag_marker
    compositor = SceneCompositor(_make_spawner(tmp_path), px_per_mm=1.0, belt_y_px=50.0, background_layers=_stack(tile))
    frame, passports = compositor.render(now_encoder=0.0, camera_rect=(0.0, 0.0, 80.0, 100.0))
    top = 30  # round(50 - 40/2)
    assert passports == []
    assert frame.dtype == np.uint8
    assert tuple(int(v) for v in frame[top + 5, 5]) == diag_marker
    assert tuple(int(v) for v in frame[top + 5, 6]) == flat


def test_layers_h3_odd_tile_height_noninteger_belt_y_and_y_px_outside_band_is_exact_solid(tmp_path):
    """Порт test_hazards_3_6::test_h3. Нечётная высота (41), `belt_y_px=50.7`, `y_px=3.4`: граница полосы по
    формуле `top = round(belt_y_px - th/2)`, вне полосы РОВНО цвет solid. Старое `background_bgr=(60, 61, 62)`
    == `SolidFill((62, 61, 60))`; в RGB-кадре ожидается (62, 61, 60)."""
    tw, th = 20, 41
    tile = np.full((th, tw, 3), fill_value=200, dtype=np.uint8)
    belt_y_px, y_px = 50.7, 3.4
    compositor = SceneCompositor(
        _make_spawner(tmp_path), px_per_mm=1.0, belt_y_px=belt_y_px, background_layers=_stack(tile, (62, 61, 60))
    )
    frame, passports = compositor.render(now_encoder=0.0, camera_rect=(0.0, y_px, 30.0, 100.0))
    assert passports == []
    top = round(belt_y_px - th / 2)  # round(30.2) == 30 — целое, без banker's-неоднозначности
    assert top == 30
    for v in range(100):
        row_in_tile = v + round(y_px) - top
        if 0 <= row_in_tile < th:
            assert frame[v, 0, 0] == 200, f"строка {v} должна быть тайлом (row_in_tile={row_in_tile})"
        else:
            assert tuple(int(c) for c in frame[v, 0]) == (62, 61, 60), f"строка {v} должна быть цветом solid"


def test_layers_h10_camera_rect_x_offset_shifts_tile_columns(tmp_path):
    """Порт test_hazards_3_6::test_h10: `x_px` камеры входит в сдвиг: столбец тайла в u -> `(u + round(x_px)) % tw`."""
    tw, th = 100, 30
    tile = np.zeros((th, tw, 3), dtype=np.uint8)
    for u in range(tw):
        tile[:, u, 0] = u
    compositor = SceneCompositor(_make_spawner(tmp_path), px_per_mm=1.0, belt_y_px=20.0, background_layers=_stack(tile))
    read_row = 10  # top = round(20 - 15) = 5 -> row_in_tile = 5, внутри полосы
    for x_px in (7.0, 12.4):
        w, h = 60, 40
        frame, passports = compositor.render(now_encoder=0.0, camera_rect=(x_px, 0.0, float(w), float(h)))
        assert passports == []
        for u in (0, 1, w - 1):
            expected_col = (u + round(x_px)) % tw
            assert frame[read_row, u, 0] == expected_col, f"x_px={x_px}, u={u}: столбец тайла не учитывает x_px"


def test_layers_h11_tile_array_mutation_after_construction_does_not_leak_into_render(tmp_path):
    """Порт test_hazards_3_6::test_h11: массив, из которого сделан `ScrollingTile`, мутируется ПОСЛЕ сборки
    компоновщика — кадр остаётся прежним (слой держит свою копию)."""
    tile = np.full((10, 10, 3), fill_value=50, dtype=np.uint8)
    compositor = SceneCompositor(_make_spawner(tmp_path), px_per_mm=1.0, belt_y_px=5.0, background_layers=_stack(tile))
    tile[:, :, :] = 200
    frame, passports = compositor.render(now_encoder=0.0, camera_rect=(0.0, 0.0, 10.0, 10.0))
    assert passports == []
    assert np.all(frame == 50), "мутация исходного массива после сборки протекла в рендер"


@pytest.mark.parametrize(
    ("belt_direction", "entry_x_px"),
    [pytest.param(1, 50.0, id="forward"), pytest.param(-1, 150.0, id="reversed")],
)
def test_layers_tile_shifts_same_direction_as_objects(belt_direction, entry_x_px):
    """Порт test_hazards_5_3b::test_background_tile_shifts_same_direction_as_objects_when_reversed (+ прямое
    направление): между двумя энкодерами объект и маркер тайла сдвигаются в ОДНУ сторону, ненулевую, при
    `belt_direction` ±1 — «диски не едут по льду» и при развороте ленты."""
    tw, th = 200, 5
    tile = np.full((th, tw, 3), 60, dtype=np.uint8)
    tile[:, tw // 2, 2] = 255  # одна отмеченная колонка, канал 2
    sprite = np.zeros((10, 10, 4), dtype=np.uint8)
    sprite[:, :, 0] = 200
    sprite[:, :, 3] = 255
    spawner = _FakeSpawner(
        _FakeObj(ObjectPassport(object_id="o1", class_name="A", angle_deg=0.0, defect=None, spawn_encoder=0.0), sprite)
    )
    compositor = SceneCompositor(
        spawner,
        px_per_mm=1.0,
        belt_y_px=2.5,
        background_layers=_stack(tile),
        belt_direction=belt_direction,
        entry_x_px=entry_x_px,
    )

    def _cx_and_marker(now_encoder: float) -> tuple[float, float]:
        frame, passports = compositor.render(now_encoder=now_encoder, camera_rect=(0.0, 0.0, 200.0, 5.0))
        assert passports
        obj_cols = np.nonzero(frame[2, :, 0] > 150)[0]
        assert obj_cols.size > 0, "объект не найден в кадре"
        marker_cols = np.nonzero(frame[2, :, 2] > 200)[0]
        assert marker_cols.size > 0, "маркер тайла не найден в кадре"
        return float(obj_cols.mean()), float(marker_cols.mean())

    enc1 = 50.0 / FACTOR_MM  # offset ~50 мм — меньше половины ширины тайла, без wraparound
    cx0, marker0 = _cx_and_marker(0.0)
    cx1, marker1 = _cx_and_marker(enc1)
    obj_delta, marker_delta = cx1 - cx0, marker1 - marker0
    assert obj_delta != 0 and marker_delta != 0
    assert (obj_delta > 0) == (marker_delta > 0), (
        f"belt_direction={belt_direction}: объект {cx0:.1f}->{cx1:.1f}, фон {marker0:.1f}->{marker1:.1f}"
    )
    assert (obj_delta > 0) == (belt_direction == 1)
