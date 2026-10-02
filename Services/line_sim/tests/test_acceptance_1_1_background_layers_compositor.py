# -*- coding: utf-8 -*-
"""Слепые acceptance-тесты Task 1.1 `layer-render`: `SceneCompositor(background_layers=...)`.

Источник контракта: `plans/layer-render/phase-1.md`, Task 1.1 (DESIGN + Acceptance). Написаны ДО
реализации; ключевого аргумента `background_layers` в `SceneCompositor` и пакета `Services.layer_render`
в этом дереве нет (worktree на коммите «только план»).

Почему файл лежит в тестах `line_sim`, а не в `Services/layer_render/tests/`: правило слоёв плана
(`layer_render` ↛ `line_sim`, граница sentrux над каталогом `Services/layer_render/`) — тесты пакета
тоже не должны импортировать `line_sim`. Компоновщик — `line_sim`, значит и тесты на нём здесь.

ЗАПРЕЩЁННЫЕ ПУТИ (не читались): `.claude/worktrees/layer-render`, другие ветки, реализация Task 1.1 и
тесты автора. Готовая зависимость: `scene_compositor.py` (ветка 3.6), `test_acceptance_3_6.py` (паттерн
фикстур спавнера).

Принятые из плана сигнатуры: `SceneCompositor(spawner, px_per_mm, belt_y_px, background_bgr,
belt_direction, entry_x_px, background_layers=None)` (параметр одиночного тайла удалён в layer-render 1.3,
тесты сравнения со старым путём перенесены на независимый оракул формулы — см. ниже); `SolidFill(color_rgb)`,
`ScrollingTile(image)`; `background_layers_from_config(items, load_image)`. Кадр компоновщика — RGB.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import ObjectFactory, ObjectSpawner, SceneCompositor, ScenePreset, encoder_to_offset_mm


def _iface():
    return importlib.import_module("Services.layer_render.interfaces")


def _solid(r: int, g: int, b: int):
    return _iface().SolidFill(color_rgb=(r, g, b))


def _tile_layer(image: np.ndarray):
    return _iface().ScrollingTile(image=image)


def _from_config_fn():
    return importlib.import_module("Services.layer_render.background").background_layers_from_config


# --------------------------------------------------------------------------------------
# Хелперы
# --------------------------------------------------------------------------------------


def _spawner(tmp_path: Path) -> ObjectSpawner:
    """Спавнер, который не тикали: `active_objects()` пуст -> кадр = чистый фон."""
    class_dir = tmp_path / "classes" / "square"
    class_dir.mkdir(parents=True)
    sprite = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite[:, :, :3] = 128
    sprite[:, :, 3] = 255
    imwrite_unicode(class_dir / "sprite.png", sprite)
    preset = ScenePreset(catalog_dir=str(tmp_path / "classes"), angle_range_deg=(0.0, 0.0), defect_probability=0.0)
    return ObjectSpawner(ObjectFactory(preset), interval_s=(1000.0, 1000.0), scene_length_mm=1e6, max_active=10)


def _asym_rgb_tile(th: int, tw: int, seed: int = 0) -> np.ndarray:
    """Несимметричный RGB-тайл случайного (но фиксированного) содержания — это ВХОД, не ожидание."""
    return np.random.default_rng(seed).integers(0, 256, size=(th, tw, 3), dtype=np.uint8)


def _render(comp: SceneCompositor, encoder: float, rect) -> np.ndarray:
    frame, passports = comp.render(encoder, rect)
    assert passports == []
    return frame


def _uniform(frame: np.ndarray) -> tuple[int, int, int] | None:
    flat = frame.reshape(-1, 3)
    first = tuple(int(v) for v in flat[0])
    return first if (flat == flat[0]).all() else None


# --------------------------------------------------------------------------------------
# Свойства слоёв `solid [10,20,30]` + RGB-тайл против независимого оракула формулы фона
# (до layer-render 1.3 сравнивалось с удалённым параметром одиночного тайла; формула — его буквальная копия)
# --------------------------------------------------------------------------------------

_W, _H, _BELT_Y, _X_PX = 97, 61, 30.0, 5.0
# 0 — нулевой сдвиг, 1000 -> сдвиг 144 px, 77777 -> 11236 px (много оборотов тайла шириной 23)
_ENCODERS = [0, 1000, 77777]
# th=40: тайл целиком внутри кадра (solid виден сверху и снизу при y_px=0), при y_px=13 уходит за верх;
# th=80: тайл выходит за верх И низ кадра (top=-10, низ 70 > 61).
_TILE_HEIGHTS = [40, 80]
_Y_PX = [0.0, 13.0]


def _oracle_frame(tile, solid_rgb, direction, encoder, rect, belt_y, px_per_mm=1.0):
    """Кадр фона по формуле контракта: заливка `solid_rgb`, тайл по X циклично со знаком `direction`, по Y — полоса
    вокруг `belt_y` (строки вне полосы — заливка)."""
    x_px, y_px, w_px, h_px = rect
    w, h = int(round(w_px)), int(round(h_px))
    th, tw = tile.shape[:2]
    frame = np.empty((h, w, 3), dtype=np.uint8)
    frame[:, :] = solid_rgb
    shift_px = int(round(float(encoder_to_offset_mm(encoder, 0.0) * px_per_mm)))
    cols = (np.arange(w) + int(round(x_px)) - direction * shift_px) % tw
    top = int(round(belt_y - th / 2))
    rows = np.arange(h) + int(round(y_px)) - top
    valid = (rows >= 0) & (rows < th)
    frame[valid] = tile[rows[valid]][:, cols]
    return frame


@pytest.mark.parametrize("y_px", _Y_PX)
@pytest.mark.parametrize("th", _TILE_HEIGHTS)
@pytest.mark.parametrize("direction", [1, -1])
@pytest.mark.parametrize("encoder", _ENCODERS)
def test_layers_solid_plus_rgb_tile_matches_formula_oracle(tmp_path, encoder, direction, th, y_px):
    tile = _asym_rgb_tile(th, 23)
    layers = _from_config_fn()([{"solid": [10, 20, 30]}, {"tile": "tile.png"}], lambda path: tile)
    comp = SceneCompositor(
        _spawner(tmp_path),
        px_per_mm=1.0,
        belt_y_px=_BELT_Y,
        background_layers=layers,
        belt_direction=direction,
    )
    rect = (_X_PX, y_px, float(_W), float(_H))
    frame = _render(comp, encoder, rect)
    assert frame.shape == (_H, _W, 3)
    assert frame.dtype == np.uint8
    assert np.array_equal(frame, _oracle_frame(tile, (10, 20, 30), direction, encoder, rect, _BELT_Y))


def test_oracle_fixture_is_not_vacuous_layer_frames_differ_across_encoders(tmp_path):
    """Контроль фикстуры: стек на трёх энкодерах и двух направлениях даёт РАЗНЫЕ кадры, а за пределами тайла виден
    заданный фон — иначе сравнение с оракулом выше ничего не ловит."""
    tile = _asym_rgb_tile(40, 23)
    frames = []
    for direction in (1, -1):
        comp = SceneCompositor(
            _spawner(tmp_path / f"d{direction}"),
            px_per_mm=1.0,
            belt_y_px=_BELT_Y,
            background_layers=[_solid(10, 20, 30), _tile_layer(tile)],
            belt_direction=direction,
        )
        for enc in _ENCODERS:
            frames.append(_render(comp, enc, (_X_PX, 0.0, float(_W), float(_H))).tobytes())
    assert len(set(frames)) >= 4
    # строка 0 вне тайла (tile top = 10): фон в RGB = (10, 20, 30) — литерал, не пересчёт
    comp = SceneCompositor(
        _spawner(tmp_path / "lit"),
        px_per_mm=1.0,
        belt_y_px=_BELT_Y,
        background_layers=[_solid(10, 20, 30), _tile_layer(tile)],
    )
    frame = _render(comp, 0, (0.0, 0.0, float(_W), float(_H)))
    assert tuple(int(v) for v in frame[0, 0]) == (10, 20, 30)


def test_layers_solid_alone_is_rgb_not_bgr_literal(tmp_path):
    """Ловушка плана: цвет в новой схеме сразу RGB — кадр хранит RGB, ничего не переставляется."""
    iface = _iface()
    comp = SceneCompositor(
        _spawner(tmp_path),
        px_per_mm=1.0,
        belt_y_px=30.0,
        background_layers=[iface.SolidFill(color_rgb=(10, 20, 30))],
    )
    frame = _render(comp, 0, (0.0, 0.0, 20.0, 12.0))
    assert _uniform(frame) == (10, 20, 30)


def test_background_layers_none_is_solid_fill_byte_identical(tmp_path):
    """`background_layers=None` (явно) — сплошная заливка `background_bgr`: кадр байт в байт как без аргумента."""
    kw = dict(px_per_mm=1.0, belt_y_px=_BELT_Y, background_bgr=(30, 20, 10))
    omitted = SceneCompositor(_spawner(tmp_path / "a"), **kw)
    explicit = SceneCompositor(_spawner(tmp_path / "b"), background_layers=None, **kw)
    rect = (_X_PX, 7.0, float(_W), float(_H))
    for enc in _ENCODERS:
        assert np.array_equal(_render(explicit, enc, rect), _render(omitted, enc, rect))


def test_default_compositor_without_layers_keeps_default_gray_literal(tmp_path):
    """Контроль (зелёный и сегодня): без ключа и без тайла фон — прежний `background_bgr=(60,60,60)`."""
    comp = SceneCompositor(_spawner(tmp_path), px_per_mm=1.0, belt_y_px=30.0)
    assert _uniform(_render(comp, 0, (0.0, 0.0, 20.0, 12.0))) == (60, 60, 60)


# --------------------------------------------------------------------------------------
# Альфа: RGBA-тайл, «over», точность на краях 0 и 255
# --------------------------------------------------------------------------------------


def _rgba_tile_4x4() -> np.ndarray:
    tile = np.zeros((4, 4, 4), dtype=np.uint8)
    for u in range(4):
        tile[:, u, :3] = (100 + 20 * u, 50, 200)  # разные R по столбцам: R=100,120,140,160
    tile[:, :, 3] = 255
    tile[:, 2, :3] = (255, 255, 255)  # прозрачный столбец прячет яркий цвет — он не должен просочиться
    tile[:, 2, 3] = 0
    return tile


def test_rgba_tile_alpha_zero_column_shows_black_solid_other_columns_show_tile_rgb(tmp_path):
    iface = _iface()
    tile = _rgba_tile_4x4()
    comp = SceneCompositor(
        _spawner(tmp_path),
        px_per_mm=1.0,
        belt_y_px=2.0,  # top = round(2 - 4/2) = 0: тайл занимает весь кадр 4x4
        background_layers=[iface.SolidFill(color_rgb=(0, 0, 0)), iface.ScrollingTile(image=tile)],
    )
    frame = _render(comp, 0, (0.0, 0.0, 4.0, 4.0))
    for row in range(4):
        assert tuple(int(v) for v in frame[row, 2]) == (0, 0, 0), f"row {row}: прозрачный столбец не чёрный"
        for col, red in ((0, 100), (1, 120), (3, 160)):
            assert tuple(int(v) for v in frame[row, col]) == (red, 50, 200), f"row {row} col {col}"


@pytest.mark.parametrize("direction", [1, -1])
@pytest.mark.parametrize("encoder", [0, 1000])
def test_rgba_transparent_column_scrolls_together_with_the_tile(tmp_path, encoder, direction):
    """Альфа едет с тайлом: прозрачны ровно те пиксели кадра, под которыми лежит столбец тайла с альфой 0.
    Положение столбца берётся из кадра со слоем RGB без альфы (R-канал кодирует индекс столбца), формулу сдвига
    тест не пересчитывает."""
    iface = _iface()
    tw = 7
    rgb = np.zeros((7, tw, 3), dtype=np.uint8)
    for u in range(tw):
        rgb[:, u] = (10 * u + 5, 77, 99)  # R=25 <=> столбец 2
    rgba = np.concatenate([rgb, np.full((7, tw, 1), 255, dtype=np.uint8)], axis=2)
    rgba[:, 2, 3] = 0

    opaque = SceneCompositor(
        _spawner(tmp_path / "opaque"),
        px_per_mm=1.0,
        belt_y_px=3.5,
        background_layers=[iface.SolidFill(color_rgb=(0, 0, 0)), iface.ScrollingTile(image=rgb)],
        belt_direction=direction,
    )
    new = SceneCompositor(
        _spawner(tmp_path / "new"),
        px_per_mm=1.0,
        belt_y_px=3.5,
        background_layers=[iface.SolidFill(color_rgb=(0, 0, 0)), iface.ScrollingTile(image=rgba)],
        belt_direction=direction,
    )
    rect = (0.0, 0.0, 30.0, 7.0)
    frame_opaque = _render(opaque, encoder, rect)
    expected = frame_opaque.copy()
    transparent = frame_opaque[:, :, 0] == 25
    assert transparent.any(), "фикстура: столбец 2 обязан быть виден в кадре"
    expected[transparent] = (0, 0, 0)
    assert np.array_equal(_render(new, encoder, rect), expected)


def test_alpha_255_rgba_tile_is_pixel_exact_equal_to_rgb_tile(tmp_path):
    iface = _iface()
    rgb = _asym_rgb_tile(40, 23, seed=3)
    rgba = np.concatenate([rgb, np.full((40, 23, 1), 255, dtype=np.uint8)], axis=2)
    rect = (_X_PX, 0.0, float(_W), float(_H))
    kw = dict(px_per_mm=1.0, belt_y_px=_BELT_Y)
    opaque_rgb = SceneCompositor(
        _spawner(tmp_path / "a"),
        background_layers=[iface.SolidFill(color_rgb=(10, 20, 30)), iface.ScrollingTile(image=rgb)],
        **kw,
    )
    opaque_rgba = SceneCompositor(
        _spawner(tmp_path / "b"),
        background_layers=[iface.SolidFill(color_rgb=(10, 20, 30)), iface.ScrollingTile(image=rgba)],
        **kw,
    )
    assert np.array_equal(_render(opaque_rgba, 1000, rect), _render(opaque_rgb, 1000, rect))


def test_alpha_0_everywhere_gives_the_layer_below_exactly(tmp_path):
    iface = _iface()
    junk = np.full((40, 23, 4), 255, dtype=np.uint8)
    junk[:, :, 3] = 0
    comp = SceneCompositor(
        _spawner(tmp_path),
        px_per_mm=1.0,
        belt_y_px=_BELT_Y,
        background_layers=[iface.SolidFill(color_rgb=(10, 20, 30)), iface.ScrollingTile(image=junk)],
    )
    assert _uniform(_render(comp, 1000, (_X_PX, 0.0, float(_W), float(_H)))) == (10, 20, 30)


def test_alpha_128_over_black_solid_gives_half_brightness_within_1(tmp_path):
    iface = _iface()
    tile = np.zeros((4, 4, 4), dtype=np.uint8)
    tile[:, :] = (200, 100, 50, 128)
    comp = SceneCompositor(
        _spawner(tmp_path),
        px_per_mm=1.0,
        belt_y_px=2.0,
        background_layers=[iface.SolidFill(color_rgb=(0, 0, 0)), iface.ScrollingTile(image=tile)],
    )
    frame = _render(comp, 0, (0.0, 0.0, 4.0, 4.0))
    got = frame.reshape(-1, 3).astype(int)
    assert (np.abs(got - np.array([100, 50, 25])) <= 1).all(), got[0]


def test_alpha_128_mixes_with_nonblack_layer_below_not_only_with_black(tmp_path):
    """Литерал: (0,200,100) при альфе 128 над (200,0,100) -> ~(100,100,100) (±1)."""
    iface = _iface()
    tile = np.zeros((4, 4, 4), dtype=np.uint8)
    tile[:, :] = (0, 200, 100, 128)
    comp = SceneCompositor(
        _spawner(tmp_path),
        px_per_mm=1.0,
        belt_y_px=2.0,
        background_layers=[iface.SolidFill(color_rgb=(200, 0, 100)), iface.ScrollingTile(image=tile)],
    )
    got = _render(comp, 0, (0.0, 0.0, 4.0, 4.0)).reshape(-1, 3).astype(int)
    assert (np.abs(got - np.array([100, 100, 100])) <= 1).all(), got[0]


# --------------------------------------------------------------------------------------
# Порядок снизу вверх и «под всеми слоями — чёрный»
# --------------------------------------------------------------------------------------


def test_stack_order_is_bottom_to_top_for_opaque_layers(tmp_path):
    iface = _iface()
    covering_tile = _asym_rgb_tile(80, 23, seed=5)  # th=80 > кадра 61: закрывает кадр целиком
    stacks = {
        "solid_over_solid": [iface.SolidFill(color_rgb=(200, 0, 0)), iface.SolidFill(color_rgb=(0, 200, 0))],
        "solid_over_tile": [
            iface.SolidFill(color_rgb=(200, 0, 0)),
            iface.ScrollingTile(image=covering_tile),
            iface.SolidFill(color_rgb=(0, 200, 0)),
        ],
    }
    for name, layers in stacks.items():
        comp = SceneCompositor(_spawner(tmp_path / name), px_per_mm=1.0, belt_y_px=_BELT_Y, background_layers=layers)
        assert _uniform(_render(comp, 1000, (_X_PX, 0.0, float(_W), float(_H)))) == (0, 200, 0), name


def test_tile_over_nothing_leaves_black_outside_tile_rows_not_default_gray(tmp_path):
    """«Под всеми слоями — чёрный»: стек из одного тайла, строки вне тайла — (0,0,0), а не прежние (60,60,60)."""
    iface = _iface()
    tile = np.full((20, 23, 3), 200, dtype=np.uint8)
    comp = SceneCompositor(
        _spawner(tmp_path),
        px_per_mm=1.0,
        belt_y_px=_BELT_Y,  # tile top = 20: строки [20, 40) — тайл
        background_layers=[iface.ScrollingTile(image=tile)],
    )
    frame = _render(comp, 0, (0.0, 0.0, float(_W), float(_H)))
    assert _uniform(frame[:20]) == (0, 0, 0)
    assert _uniform(frame[40:]) == (0, 0, 0)
    assert _uniform(frame[20:40]) == (200, 200, 200)


def test_transparent_tile_rows_outside_tile_show_solid_below(tmp_path):
    """Строки вне тайла прозрачны — видно слой ниже (solid), не чёрный."""
    iface = _iface()
    tile = np.full((20, 23, 4), 255, dtype=np.uint8)
    comp = SceneCompositor(
        _spawner(tmp_path),
        px_per_mm=1.0,
        belt_y_px=_BELT_Y,
        background_layers=[iface.SolidFill(color_rgb=(10, 20, 30)), iface.ScrollingTile(image=tile)],
    )
    frame = _render(comp, 0, (0.0, 0.0, float(_W), float(_H)))
    assert _uniform(frame[:20]) == (10, 20, 30)
    assert _uniform(frame[40:]) == (10, 20, 30)
    assert _uniform(frame[20:40]) == (255, 255, 255)
