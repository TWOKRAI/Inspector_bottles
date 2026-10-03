# -*- coding: utf-8 -*-
"""Task 2.5 (слепой тест тестера): `render_scene(background, placed, effects, rng)` — одна функция кадра.

Пишется по acceptance-критериям A1-A9 из `plans/layer-render/phase-2-core-2.5.md` (A10-A11 — проверки лида, не pytest).
Реализации в дереве нет по построению (worktree тестера на коммите спеки 920c11475): модуля `Services.layer_render.scene`
и имён `render_scene` / `SceneBackground` / `PlacedObject` нет. Импорт нового API идёт ВНУТРИ теста (`importlib`),
не при сборе: нет модуля — падают его кейсы, а не весь файл. `Services.line_sim` тоже импортируется лениво, внутри
функций (граница sentrux `layer_render ↛ line_sim` смотрит на статические импорты; прецедент — тесты 2.2 и 2.4b).

ЗЕЛЁНЫЕ ДО ЗАДАЧИ (старый код держит эти свойства; такими они обязаны остаться после переезда):
  * A7  кадры и паспорта `SceneCompositor.render` побайтно прежние (литералы sha256 сняты с кода ДО задачи)
  * A9  п.1-2: без `background_layers` `render(nan, rect)` не бросает; со стеком — бросает; валидный цвет принимается
КРАСНЫЕ ДО ЗАДАЧИ (нового API нет — `ModuleNotFoundError` / `ImportError`; A9 п.3 — `ValueError` не брошен):
  * A1-A6, A8   (всё, что зовёт `Services.layer_render.scene`)
  * A9 п.3      `background_bgr=(300, 0, 0)` -> `ValueError` в `SceneCompositor(...)`; плюс остальные четыре случая
                сужения из DESIGN и цвета вне 0..255 (отдельные тесты `test_a9_extra_*`)

ОРАКУЛЫ. Ожидаемые значения — литералы или ручные формулы спеки (`cols`, формула `composite`), не значения из
проверяемого кода. Равенство с `composite()` / `apply_effects()` / `render_background()` как отдельными юнитами
допускается там, где спека это прямо говорит (A3 цепочка, A4, A8). Литералы A7 сняты скриптом захвата на коде ДО
задачи (SceneCompositor из этого worktree), команда и вывод — в отчёте тестера.

Окружение снимка A7: Windows-10-10.0.19045-SP0, CPython 3.12.12, numpy 2.4.4, SHA 920c11475. Шаги арифметики —
целочисленные округления и `float64` на `round(...)`: расхождение на другой платформе маловероятно, но возможно
(округление дробных центров идёт через `int(round(...))` в `composite` — банковское, одинаковое везде).

Зависшего теста нет: плагина pytest-timeout в venv нет; все вызовы — чистая численная работа без ожидания, а
подпроцесс A1 запущен с `timeout=`.
"""

# ruff: noqa: E501 -- литералы снимка (sha256, JSON) длинные; перенос строки ломает сверку глазами
from __future__ import annotations

import copy
import dataclasses
import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from Services.layer_render.background import fold_background, render_background
from Services.layer_render.compose import composite
from Services.layer_render.effects import EffectSpec, apply_effects
from Services.layer_render.interfaces import ScrollingTile, SolidFill

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _scene():
    """Модуль нового API. Отсутствует до задачи -> `ModuleNotFoundError` (красный кейс, не ошибка сбора)."""
    return importlib.import_module("Services.layer_render.scene")


def _bg(layers, size_wh, center_y=2.0, scroll_px=0, origin_xy=(0, 0)):
    return _scene().SceneBackground(layers, size_wh, center_y=center_y, scroll_px=scroll_px, origin_xy=origin_xy)


def _po(rgba, center_xy):
    return _scene().PlacedObject(rgba, center_xy)


def _solid_sprite(h: int, w: int, rgb: tuple[int, int, int], alpha: int = 255) -> np.ndarray:
    sprite = np.zeros((h, w, 4), dtype=np.uint8)
    sprite[:, :, 0], sprite[:, :, 1], sprite[:, :, 2], sprite[:, :, 3] = rgb[0], rgb[1], rgb[2], alpha
    return sprite


def _random_rgba(rng_seed: int, h: int, w: int) -> np.ndarray:
    """Случайный (фиксированный) RGBA с частичной альфой — ВХОД теста, не ожидание."""
    gen = np.random.default_rng(rng_seed)
    sprite = gen.integers(0, 256, size=(h, w, 4), dtype=np.uint8)
    sprite[:, :, 3] = np.where(gen.random((h, w)) < 0.25, gen.integers(0, 256, size=(h, w)), 255).astype(np.uint8)
    return sprite


# ======================================================================================================
# A1. Имена и граница
# ======================================================================================================

_A1_CHILD = (
    "import sys, json\n"
    "import Services.layer_render.scene\n"
    "prefixes = ('Services.line_sim', 'Services.dataset_gen', 'Services.ml_train')\n"
    "bad = sorted(m for m in sys.modules if m.startswith(prefixes))\n"
    "print(json.dumps({'has_scene': 'Services.layer_render.scene' in sys.modules, 'forbidden': bad}))\n"
)


def test_a1_import_in_clean_process_reaches_scene_and_pulls_no_forbidden_service():
    """A1 (КРАСНЫЙ до задачи: модуля нет, код возврата подпроцесса 1). Чистый процесс: код 0, модуль в `sys.modules`,
    ни одного модуля `Services.line_sim*` / `Services.dataset_gen*` / `Services.ml_train*`."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", _A1_CHILD], cwd=_REPO_ROOT, env=env, capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, f"код возврата {proc.returncode}, stderr:\n{proc.stderr[-1500:]}"
    report = json.loads(proc.stdout.strip().splitlines()[-1])
    # достижимость — якорь для пункта «отсутствия»: пустой список запрещённых модулей что-то значит, только если
    # импорт реально состоялся
    assert report["has_scene"] is True
    assert report["forbidden"] == []


@pytest.mark.parametrize("name", ["render_scene", "SceneBackground", "PlacedObject"])
def test_a1_names_are_the_same_objects_in_package_and_in_scene_module(name):
    """A1 (КРАСНЫЙ до задачи). Три имени достижимы из пакета и из `scene`, это одни и те же объекты."""
    import Services.layer_render as pkg

    scene = _scene()
    assert getattr(pkg, name) is getattr(scene, name)


def test_a1_package_exports_three_names_explicitly_in_all():
    """A1 / Files п.2 (КРАСНЫЙ до задачи). Экспорт явный — все три имени в `__all__` пакета; буквальная строка критерия
    `from Services.layer_render import render_scene, SceneBackground, PlacedObject` исполняется без ошибки."""
    import Services.layer_render as pkg

    for name in ("render_scene", "SceneBackground", "PlacedObject"):
        assert name in pkg.__all__, name
    namespace: dict = {}
    exec("from Services.layer_render import render_scene, SceneBackground, PlacedObject", namespace)  # noqa: S102
    assert {"render_scene", "SceneBackground", "PlacedObject"} <= namespace.keys()


# ======================================================================================================
# A2. Фон
# ======================================================================================================


def test_a2_solid_fill_background_gives_uniform_frame_of_right_shape():
    """A2 (КРАСНЫЙ до задачи). `SolidFill((10,20,30))`, размер (5, 4) -> форма (4, 5, 3), uint8, все пиксели [10, 20, 30]."""
    frame = _scene().render_scene(_bg([SolidFill((10, 20, 30))], (5, 4), center_y=2.0), [], [], None)
    assert frame.shape == (4, 5, 3)
    assert frame.dtype == np.uint8
    assert (frame == np.array([10, 20, 30], dtype=np.uint8)).all()


def test_a2_empty_layers_give_black_frame():
    """A2 (КРАСНЫЙ до задачи). Пустой `layers` -> все пиксели 0 (форма при этом верная — якорь против пустого массива)."""
    frame = _scene().render_scene(_bg([], (5, 4), center_y=2.0), [], [], None)
    assert frame.shape == (4, 5, 3)
    assert frame.dtype == np.uint8
    assert not frame.any()


# Тайл th=2, tw=7: пиксель (y, x) = (10*y + x, 100 + x, 200 - 3*x - y) — каждый столбец и строка различимы.
def _tile_2x7() -> np.ndarray:
    tile = np.zeros((2, 7, 3), dtype=np.uint8)
    for y in range(2):
        for x in range(7):
            tile[y, x] = (10 * y + x, 100 + x, 200 - 3 * x - y)
    return tile


# (scroll_px, origin_xy, ожидаемые столбцы тайла, ожидаемые строки тайла, строки кадра [r0, r1)).
# Столбцы — литералы формулы cols = (arange(5) + origin_x - scroll_px) % 7, посчитанной от руки:
#   scroll 0, origin_x 0 -> 0..4; scroll 3 -> (-3..1) % 7 = 4,5,6,0,1; origin_x 6 -> 6..10 % 7 = 6,0,1,2,3;
#   scroll 4, origin_x 9 -> 5..9 % 7 = 5,6,0,1,2; scroll 10 -> (-10..-6) % 7 = 4,5,6,0,1 (сдвиг больше ширины тайла).
# Строки: center_y=2.0, th=2 -> top=round(2.0-1)=1. origin_y=0: тайл занимает строки кадра 1..2, берёт строки тайла 0,1.
#   origin_y=1: r0=max(0, top-origin_y)=0, r1=min(4, top+th-origin_y)=2, берёт строки тайла (0+1-1, 1+1-1) = 0,1.
_A2_TILE_CASES = [
    pytest.param(0, (0, 0), [0, 1, 2, 3, 4], [0, 1], (1, 3), id="no-shift"),
    pytest.param(3, (0, 0), [4, 5, 6, 0, 1], [0, 1], (1, 3), id="scroll-3"),
    pytest.param(0, (6, 0), [6, 0, 1, 2, 3], [0, 1], (1, 3), id="origin-x-6"),
    pytest.param(4, (9, 0), [5, 6, 0, 1, 2], [0, 1], (1, 3), id="scroll-4-origin-x-9"),
    pytest.param(10, (0, 0), [4, 5, 6, 0, 1], [0, 1], (1, 3), id="scroll-10-wraps"),
    pytest.param(0, (0, 1), [0, 1, 2, 3, 4], [0, 1], (0, 2), id="origin-y-1"),
]


@pytest.mark.parametrize(("scroll_px", "origin_xy", "cols", "tile_rows", "frame_rows"), _A2_TILE_CASES)
def test_a2_rgb_tile_columns_follow_scroll_and_origin_formula(scroll_px, origin_xy, cols, tile_rows, frame_rows):
    """A2 (КРАСНЫЙ до задачи). RGB-тайл со сдвигом `scroll_px` и `origin_xy`: столбцы кадра — по формуле
    `cols = (arange(w) + origin_x - scroll_px) % tw`, ожидание — литералы (см. таблицу выше); вне полосы тайла — чёрный."""
    tile = _tile_2x7()
    frame = _scene().render_scene(
        _bg([ScrollingTile(tile)], (5, 4), center_y=2.0, scroll_px=scroll_px, origin_xy=origin_xy), [], [], None
    )
    expected = np.zeros((4, 5, 3), dtype=np.uint8)
    r0, r1 = frame_rows
    for dst, src_row in zip(range(r0, r1), tile_rows):
        for x, col in enumerate(cols):
            expected[dst, x] = tile[src_row, col]
    assert frame.shape == (4, 5, 3)
    assert np.array_equal(frame, expected)


# ======================================================================================================
# A3. Объекты
# ======================================================================================================

_RED, _GREEN, _BLUE = (255, 0, 0), (0, 255, 0), (0, 0, 255)


def _bg10x6(rgb=(50, 50, 50)):
    return _bg([SolidFill(rgb)], (10, 6), center_y=3.0)


@pytest.mark.parametrize("red_first", [True, False])
def test_a3_later_placed_object_wins_in_overlap(red_first):
    """A3 (КРАСНЫЙ до задачи). Порядок `placed` = порядок слоёв: два непрозрачных спрайта 4x4 (красный с центром (3, 3) —
    столбцы 1..4, зелёный с центром (5, 3) — столбцы 3..6, строки 1..4 у обоих); столбцы 3 и 4 перекрыты — там пиксели
    ВТОРОГО в списке. Обратный порядок даёт обратный цвет (иначе тест не различил бы порядок)."""
    red = _po(_solid_sprite(4, 4, _RED), (3.0, 3.0))
    green = _po(_solid_sprite(4, 4, _GREEN), (5.0, 3.0))
    frame = _scene().render_scene(_bg10x6(), [red, green] if red_first else [green, red], [], None)
    winner = _GREEN if red_first else _RED
    assert tuple(int(v) for v in frame[2, 3]) == winner
    assert tuple(int(v) for v in frame[2, 4]) == winner
    # вне перекрытия — свои цвета; вне обоих спрайтов — фон
    assert tuple(int(v) for v in frame[2, 1]) == _RED and tuple(int(v) for v in frame[2, 2]) == _RED
    assert tuple(int(v) for v in frame[2, 5]) == _GREEN and tuple(int(v) for v in frame[2, 6]) == _GREEN
    for y, x in ((0, 0), (2, 7), (5, 3)):
        assert tuple(int(v) for v in frame[y, x]) == (50, 50, 50)


def test_a3_half_transparent_sprite_matches_composite_formula_literal():
    """A3 (КРАСНЫЙ до задачи). Спрайт (200, 30, 255) с альфой 128 на фоне (50, 100, 150): по формуле
    `floor(fg*a/255 + bg*(1 - a/255) + 0.5)` от руки: R=(200*128+50*127)/255=125.29 -> 125; G=(30*128+100*127)/255=64.86 -> 65;
    B=(255*128+150*127)/255=202.71 -> 203. Пиксели вне спрайта — чистый фон."""
    sprite = _solid_sprite(2, 2, (200, 30, 255), alpha=128)
    frame = _scene().render_scene(
        _bg([SolidFill((50, 100, 150))], (10, 6), center_y=3.0), [_po(sprite, (3.0, 3.0))], [], None
    )
    # центр (3,3), 2x2 -> x0 = round(3 - 1) = 2, y0 = 2 -> пиксели x 2..3, y 2..3
    for y in (2, 3):
        for x in (2, 3):
            assert tuple(int(v) for v in frame[y, x]) == (125, 65, 203)
    assert tuple(int(v) for v in frame[2, 4]) == (50, 100, 150)
    assert tuple(int(v) for v in frame[1, 2]) == (50, 100, 150)


@pytest.mark.parametrize(
    "center",
    [
        pytest.param((-50.0, -50.0), id="far-outside"),
        pytest.param((-2.0, 3.0), id="touches-left-edge"),
        pytest.param((12.0, 3.0), id="touches-right-edge"),
        pytest.param((5.0, -2.0), id="touches-top-edge"),
        pytest.param((5.0, 8.0), id="touches-bottom-edge"),
    ],
)
def test_a3_object_fully_outside_frame_changes_nothing(center):
    """A3 (КРАСНЫЙ до задачи). Объект целиком за кадром (в том числе касающийся края ровно, полоса нулевой площади)
    -> кадр равен чистому фону (50, 50, 50). Положительный контроль — следующий тест (объект на краю рисует столбец)."""
    frame = _scene().render_scene(_bg10x6(), [_po(_solid_sprite(4, 4, _RED), center)], [], None)
    assert frame.shape == (6, 10, 3)
    assert (frame == np.array([50, 50, 50], dtype=np.uint8)).all()


def test_a3_object_partly_outside_frame_draws_only_the_visible_part():
    """A3 (КРАСНЫЙ до задачи). Положительный контроль к предыдущему: спрайт 4x4 с центром (-1, 3) занимает x -3..0 ->
    виден ровно столбец 0, строки 1..4; остальное — фон."""
    frame = _scene().render_scene(_bg10x6(), [_po(_solid_sprite(4, 4, _RED), (-1.0, 3.0))], [], None)
    for y in range(6):
        for x in range(10):
            expected = _RED if (x == 0 and 1 <= y <= 4) else (50, 50, 50)
            assert tuple(int(v) for v in frame[y, x]) == expected, (y, x)


def test_a3_frame_equals_composite_chain_over_same_centers():
    """A3 (КРАСНЫЙ до задачи). Кадр == цепочка `composite(...)` по тем же центрам (равенство с юнитом разрешено спекой):
    три случайных RGBA с частичной альфой, дробные центры, один частично за краем."""
    sprites = [_random_rgba(11, 12, 9), _random_rgba(12, 7, 15), _random_rgba(13, 10, 10)]
    centers = [(10.4, 12.6), (14.5, 15.5), (38.7, 2.2)]
    layers = [SolidFill((20, 40, 60))]
    frame = _scene().render_scene(
        _bg(layers, (40, 30), center_y=15.0), [_po(s, c) for s, c in zip(sprites, centers)], [], None
    )
    expected = np.empty((30, 40, 3), dtype=np.uint8)
    render_background(expected, layers, scroll_px=0, origin_xy=(0, 0), center_y=15.0)
    for s, c in zip(sprites, centers):
        expected = composite(expected, s, c)
    assert np.array_equal(frame, expected)


# ======================================================================================================
# A4. Эффекты и rng
# ======================================================================================================


def _fx_noise_gamma():
    return [EffectSpec("noise", 1.0), EffectSpec("gamma", 0.5)]


def _scene_with_object():
    bg = _bg([SolidFill((50, 100, 150))], (30, 20), center_y=10.0)
    placed = [_po(_random_rgba(21, 8, 8), (12.3, 9.7))]
    return bg, placed


def test_a4_effects_frame_equals_apply_effects_over_plain_frame_and_rng_state_matches():
    """A4 (КРАСНЫЙ до задачи). Непустой `effects`, `rng=default_rng(7)` -> кадр == `apply_effects(кадр_без_эффектов,
    effects, default_rng(7))`; состояние `rng` после вызова == состоянию копии после `apply_effects`."""
    scene = _scene()
    bg, placed = _scene_with_object()
    effects = _fx_noise_gamma()
    plain = scene.render_scene(bg, placed, [], None)
    rng = np.random.default_rng(7)
    ref_rng = np.random.default_rng(7)
    frame = scene.render_scene(bg, placed, effects, rng)
    expected = apply_effects(plain, effects, ref_rng)
    assert not np.array_equal(frame, plain), "эффекты ничего не изменили — тест вакуумный"
    assert np.array_equal(frame, expected)
    assert rng.bit_generator.state == ref_rng.bit_generator.state
    assert rng.bit_generator.state != np.random.default_rng(7).bit_generator.state, "ни одного розыгрыша — вакуум"


def test_a4_effects_apply_after_objects_literal():
    """A4 (КРАСНЫЙ до задачи). Эффект кадра идёт ПОСЛЕ объектов: яркость +30 (диапазон (30, 30), контраст 1.0 — шаг
    детерминирован). Пиксель объекта 200 -> 230 (оракул-литерал: порядок «эффект, потом объект» оставил бы 200), фон 50 -> 80."""
    bg = _bg([SolidFill((50, 50, 50))], (10, 6), center_y=3.0)
    placed = [_po(_solid_sprite(2, 2, (200, 200, 200)), (4.0, 3.0))]  # x0 = 3, y0 = 2 -> пиксели x 3..4, y 2..3
    effects = [EffectSpec("brightness_contrast", 1.0, {"brightness": (30.0, 30.0), "contrast": (1.0, 1.0)})]
    frame = _scene().render_scene(bg, placed, effects, np.random.default_rng(1))
    assert tuple(int(v) for v in frame[2, 3]) == (230, 230, 230)
    assert tuple(int(v) for v in frame[0, 0]) == (80, 80, 80)


def test_a4_empty_effects_with_rng_draws_nothing():
    """A4 (КРАСНЫЙ до задачи). Пустой `effects` при переданном `rng`: `bit_generator.state` до == после (ноль розыгрышей);
    кадр при этом построен (якорь: форма и цвет)."""
    bg = _bg([SolidFill((10, 20, 30))], (5, 4), center_y=2.0)
    rng = np.random.default_rng(7)
    before = copy.deepcopy(rng.bit_generator.state)
    frame = _scene().render_scene(bg, [], [], rng)
    assert frame.shape == (4, 5, 3) and (frame == np.array([10, 20, 30], dtype=np.uint8)).all()
    assert rng.bit_generator.state == before


def test_a4_rng_none_with_nonempty_effects_raises_value_error_naming_rng():
    """A4 (КРАСНЫЙ до задачи). `rng=None` + непустой `effects` -> `ValueError`, в тексте `rng`."""
    bg = _bg([SolidFill((10, 20, 30))], (5, 4), center_y=2.0)
    with pytest.raises(ValueError, match="rng"):
        _scene().render_scene(bg, [], [EffectSpec("noise", 1.0)], None)


def test_a4_empty_effects_accept_rng_none():
    """A4 (КРАСНЫЙ до задачи). Пустой `effects` — `rng=None` допустим (кадр строится без исключения)."""
    frame = _scene().render_scene(_bg([SolidFill((1, 2, 3))], (3, 3), center_y=1.0), [], (), None)
    assert frame.shape == (3, 3, 3)


def test_a4_non_effectspec_element_raises_value_error_with_index():
    """A4 (КРАСНЫЙ до задачи). Элемент `effects` не `EffectSpec` -> `ValueError` с индексом (плохой элемент на позиции 3
    из четырёх — цифра 3 в тексте не случайна)."""
    bg = _bg([SolidFill((10, 20, 30))], (5, 4), center_y=2.0)
    effects = [EffectSpec("noise", 1.0), EffectSpec("gamma", 1.0), EffectSpec("noise", 1.0), object()]
    with pytest.raises(ValueError) as info:
        _scene().render_scene(bg, [], effects, np.random.default_rng(7))
    assert "3" in str(info.value)
    assert "effects" in str(info.value)


def test_a4_non_placedobject_element_raises_value_error_with_index():
    """A4 (КРАСНЫЙ до задачи). Элемент `placed` не `PlacedObject` -> `ValueError` с индексом (плохой — на позиции 2)."""
    bg = _bg([SolidFill((10, 20, 30))], (5, 4), center_y=2.0)
    ok = _po(_solid_sprite(1, 1, _RED), (1.0, 1.0))
    with pytest.raises(ValueError) as info:
        _scene().render_scene(bg, [ok, ok, (ok.rgba, (1.0, 1.0))], [], None)
    assert "2" in str(info.value)
    assert "placed" in str(info.value)


def test_a4_error_order_effects_element_before_rng():
    """A4 (КРАСНЫЙ до задачи). Порядок проверок: `render_scene(bg, [], [object()], None)` -> ошибка про элемент `effects`,
    не про `rng` (в тексте нет `rng`)."""
    bg = _bg([SolidFill((10, 20, 30))], (5, 4), center_y=2.0)
    with pytest.raises(ValueError) as info:
        _scene().render_scene(bg, [], [object()], None)
    message = str(info.value)
    assert "effects" in message
    assert "rng" not in message


def test_a4_error_order_placed_element_before_effects_element_and_rng():
    """A4 / DESIGN «порядок проверок» (КРАСНЫЙ до задачи). Плохие `placed` И `effects` И `rng=None` одновременно ->
    ошибка про `placed` (п.1), без упоминания `effects` и `rng`."""
    bg = _bg([SolidFill((10, 20, 30))], (5, 4), center_y=2.0)
    with pytest.raises(ValueError) as info:
        _scene().render_scene(bg, [object()], [object()], None)
    message = str(info.value)
    assert "placed" in message
    assert "effects" not in message
    assert "rng" not in message


# ======================================================================================================
# A5. Входы не меняются, выход свой
# ======================================================================================================


def _a5_inputs():
    tile_src = np.random.default_rng(31).integers(0, 256, size=(6, 9, 4), dtype=np.uint8)
    tile = ScrollingTile(tile_src)
    sprite = _random_rgba(32, 8, 8)
    sprite.flags.writeable = False  # как `LayeredObject.render()`: read-only
    bg = _bg([SolidFill((40, 50, 60)), tile], (20, 12), center_y=6.0, scroll_px=3, origin_xy=(2, 0))
    return bg, tile, tile_src, sprite


def test_a5_inputs_are_untouched_bytewise_and_read_only_rgba_is_accepted():
    """A5 (КРАСНЫЙ до задачи). После вызова `rgba` объекта, `image` тайла (и исходник тайла) побайтно те же; `rgba` с
    `writeable=False` принимается без исключения (и результат осмыслен — объект нарисован)."""
    bg, tile, tile_src, sprite = _a5_inputs()
    sprite_before, tile_before, src_before = sprite.tobytes(), tile.image.tobytes(), tile_src.tobytes()
    placed = [_po(sprite, (10.0, 6.0))]
    out = _scene().render_scene(bg, placed, [], None)
    assert sprite.tobytes() == sprite_before
    assert tile.image.tobytes() == tile_before
    assert tile_src.tobytes() == src_before
    assert sprite.flags.writeable is False
    assert out.shape == (12, 20, 3)
    assert not np.array_equal(out, _scene().render_scene(bg, [], [], None)), "объект не нарисован — тест вакуумный"


def test_a5_writing_into_output_does_not_change_inputs_and_output_does_not_alias_them():
    """A5 (КРАСНЫЙ до задачи). Запись в выходной кадр не меняет `rgba`/`image`; выход — собственный записываемый массив
    (не делит память ни со спрайтом, ни с тайлом)."""
    bg, tile, _src, sprite = _a5_inputs()
    sprite_before, tile_before = sprite.tobytes(), tile.image.tobytes()
    out = _scene().render_scene(bg, [_po(sprite, (10.0, 6.0))], [], None)
    assert out.flags.writeable is True
    assert not np.shares_memory(out, sprite)
    assert not np.shares_memory(out, tile.image)
    out[...] = 255
    assert sprite.tobytes() == sprite_before
    assert tile.image.tobytes() == tile_before


def test_a5_two_calls_give_distinct_arrays_with_equal_content():
    """A5 (КРАСНЫЙ до задачи). Два вызова дают разные массивы (`not np.shares_memory`), содержимое одинаково; запись в
    первый не видна во втором (в том числе на пути «фон без объектов»)."""
    bg, _tile, _src, sprite = _a5_inputs()
    scene = _scene()
    for placed in ([_po(sprite, (10.0, 6.0))], []):
        a = scene.render_scene(bg, placed, [], None)
        b = scene.render_scene(bg, placed, [], None)
        assert not np.shares_memory(a, b)
        assert np.array_equal(a, b)
        a[...] = 0
        assert b.any()


def test_a5_output_with_effects_is_also_an_owned_array():
    """A5 (КРАСНЫЙ до задачи). Путь с эффектами: два вызова с одинаковым состоянием rng — разные массивы, равные по
    содержимому."""
    bg, _tile, _src, sprite = _a5_inputs()
    effects = [EffectSpec("noise", 1.0)]
    scene = _scene()
    a = scene.render_scene(bg, [_po(sprite, (10.0, 6.0))], effects, np.random.default_rng(5))
    b = scene.render_scene(bg, [_po(sprite, (10.0, 6.0))], effects, np.random.default_rng(5))
    assert not np.shares_memory(a, b)
    assert np.array_equal(a, b)


# ======================================================================================================
# A6. Валидация
# ======================================================================================================

_SOLID = SolidFill((1, 2, 3))


@pytest.mark.parametrize(
    "size_wh",
    [
        pytest.param((True, 4), id="bool-w"),
        pytest.param((5, True), id="bool-h"),
        pytest.param((5.0, 4), id="float-w"),
        pytest.param((5, 4.5), id="float-h"),
        pytest.param((np.float64(5.0), 4), id="np-float64"),
        pytest.param((-1, 4), id="negative-w"),
        pytest.param((5, -1), id="negative-h"),
        pytest.param((np.int64(-1), 4), id="np-negative"),
        pytest.param((5, 4, 3), id="length-3"),
        pytest.param((5,), id="length-1"),
        pytest.param((), id="length-0"),
        pytest.param(np.array([5, 4]), id="ndarray-not-tuple-or-list"),
        pytest.param("54", id="str"),
        pytest.param(5, id="int"),
        pytest.param(None, id="none"),
    ],
)
def test_a6_bad_size_wh_raises_value_error(size_wh):
    """A6 (КРАСНЫЙ до задачи). `size_wh` с bool, float, отрицательным числом, длиной не 2 или не tuple/list -> `ValueError`."""
    with pytest.raises(ValueError):
        _scene().SceneBackground([_SOLID], size_wh, center_y=2.0)


@pytest.mark.parametrize(
    "size_wh",
    [
        pytest.param([5, 4], id="list"),
        pytest.param((np.int64(5), 4), id="np-int64"),
        pytest.param((np.int32(5), np.uint8(4)), id="np-int32-uint8"),
        pytest.param((5, 4), id="plain-tuple"),
    ],
)
def test_a6_good_size_wh_is_accepted_and_stored_as_pair_of_python_int(size_wh):
    """A6 (КРАСНЫЙ до задачи). `[5, 4]` и `(np.int64(5), 4)` принимаются, `size_wh` после — `(5, 4)` из Python `int`
    (ровно `int`, не numpy-скаляр и не список)."""
    bg = _scene().SceneBackground([_SOLID], size_wh, center_y=2.0)
    assert bg.size_wh == (5, 4)
    assert isinstance(bg.size_wh, tuple)
    assert type(bg.size_wh[0]) is int and type(bg.size_wh[1]) is int


def test_a6_integer_center_y_is_accepted_and_equals_float_center_y():
    """A6 (КРАСНЫЙ до задачи). Целый `center_y=2` принимается (целый `belt_y_px` допустим) и даёт тот же кадр, что 2.0."""
    scene = _scene()
    tile = ScrollingTile(_tile_2x7())
    frame_int = scene.render_scene(scene.SceneBackground([tile], (5, 4), center_y=2), [], [], None)
    frame_float = scene.render_scene(scene.SceneBackground([tile], (5, 4), center_y=2.0), [], [], None)
    assert frame_int.shape == (4, 5, 3)
    assert frame_int.any()
    assert np.array_equal(frame_int, frame_float)


def test_a6_layers_are_stored_as_tuple_keeping_the_same_elements():
    """A6 / DESIGN (КРАСНЫЙ до задачи). `layers` хранится tuple из тех же слоёв, список вызывающего после создания не
    влияет на фон (правка списка не меняет кадр)."""
    tile = ScrollingTile(_tile_2x7())
    layers = [SolidFill((9, 9, 9)), tile]
    bg = _scene().SceneBackground(layers, (5, 4), center_y=2.0)
    assert isinstance(bg.layers, tuple)
    assert len(bg.layers) == 2 and bg.layers[0] is layers[0] and bg.layers[1] is tile
    layers.clear()
    assert len(bg.layers) == 2


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(object(), id="object"),
        pytest.param((10, 20, 30), id="rgb-tuple"),
        pytest.param("tile", id="str"),
        pytest.param(np.zeros((2, 2, 3), dtype=np.uint8), id="bare-ndarray"),
        pytest.param(None, id="none"),
    ],
)
def test_a6_bad_layer_element_raises_value_error_with_index(bad):
    """A6 (КРАСНЫЙ до задачи). Элемент `layers` не `SolidFill`/`ScrollingTile` -> `ValueError` с индексом (плохой — на
    позиции 2 из трёх)."""
    with pytest.raises(ValueError) as info:
        _scene().SceneBackground([_SOLID, ScrollingTile(_tile_2x7()), bad], (5, 4), center_y=2.0)
    assert "2" in str(info.value)


@pytest.mark.parametrize(
    "make_rgba",
    [
        pytest.param(lambda: np.zeros((4, 4, 3), dtype=np.uint8), id="shape-3-channels"),
        pytest.param(lambda: np.zeros((4, 4), dtype=np.uint8), id="shape-2d"),
        pytest.param(lambda: np.zeros((4, 4, 5), dtype=np.uint8), id="shape-5-channels"),
        pytest.param(lambda: np.zeros((1, 4, 4, 4), dtype=np.uint8), id="shape-4d"),
        pytest.param(lambda: np.zeros((4, 4, 4), dtype=np.float32), id="dtype-float32"),
        pytest.param(lambda: np.zeros((4, 4, 4), dtype=np.uint16), id="dtype-uint16"),
        pytest.param(lambda: np.zeros((4, 4, 4), dtype=np.int32), id="dtype-int32"),
    ],
)
def test_a6_bad_placed_rgba_raises_value_error_naming_shape_or_dtype(make_rgba):
    """A6 (КРАСНЫЙ до задачи). `PlacedObject`: `rgba` не `(h, w, 4)` или не `uint8` -> `ValueError`, в тексте shape или
    dtype (спека: «в тексте shape или dtype» — достаточно любого из двух слов)."""
    with pytest.raises(ValueError) as info:
        _scene().PlacedObject(make_rgba(), (1.0, 1.0))
    message = str(info.value).lower()
    assert "shape" in message or "dtype" in message, message


def test_a6_valid_placed_rgba_is_accepted():
    """A6 (КРАСНЫЙ до задачи). Положительный контроль к предыдущему: `(h, w, 4)` uint8 принимается."""
    obj = _scene().PlacedObject(np.zeros((3, 2, 4), dtype=np.uint8), (1.0, 1.0))
    assert obj.rgba.shape == (3, 2, 4)


@pytest.mark.parametrize(
    ("size_wh", "shape"),
    [
        pytest.param((0, 4), (4, 0, 3), id="zero-width"),
        pytest.param((5, 0), (0, 5, 3), id="zero-height"),
        pytest.param((0, 0), (0, 0, 3), id="zero-both"),
    ],
)
def test_a6_zero_size_gives_empty_frame_without_exception(size_wh, shape):
    """A6 (КРАСНЫЙ до задачи). Нулевой размер `(0, 4)` -> кадр формы `(4, 0, 3)` без исключения (аналогично высота и оба)."""
    frame = _scene().render_scene(_bg([SolidFill((10, 20, 30))], size_wh, center_y=2.0), [], [], None)
    assert frame.shape == shape
    assert frame.dtype == np.uint8


def test_a6_extra_zero_size_with_tile_and_object_does_not_raise():
    """РАСШИРЕНИЕ A6 (вне буквы критерия; КРАСНЫЙ до задачи). Нулевой кадр с тайлом и объектом тоже не бросает: тайл и
    `composite` на пустом кадре — штатный путь."""
    scene = _scene()
    for size_wh, shape in (((0, 4), (4, 0, 3)), ((5, 0), (0, 5, 3))):
        bg = scene.SceneBackground([ScrollingTile(_tile_2x7())], size_wh, center_y=2.0)
        frame = scene.render_scene(bg, [_po(_solid_sprite(2, 2, _RED), (1.0, 1.0))], [], None)
        assert frame.shape == shape


# ======================================================================================================
# A7. Сим побайтно прежний (зелёный до задачи)
# ======================================================================================================

# Сценарий. Камера (10.4, 5.6, 300.4, 200.2) -> кадр 300x200; лента едет влево (`belt_direction=-1`), вход `entry_x_px=320.0`,
# `belt_y_px=100.0`, `px_per_mm=3.0`. Четыре объекта с разными размерами, смещениями `lateral_px` (0, 11.5, -9.0, 4.25) и
# энкодерами спавна (0, 100, 200, 450): соседние перекрываются и по X, и по Y; на входе и выходе объекты частично за краем.
# 14 шагов энкодера: 0, 150, ..., 1950.
_A7_RECT = (10.4, 5.6, 300.4, 200.2)
_A7_ENCODERS = [150.0 * k for k in range(14)]
_A7_SPRITES = [  # (seed, h, w, spawn_encoder, lateral_px)
    (101, 30, 40, 0.0, 0.0),
    (102, 50, 60, 100.0, 11.5),
    (103, 25, 25, 200.0, -9.0),
    (104, 35, 45, 450.0, 4.25),
]


class _StubSpawner:
    """Заглушка спавнера: `SceneCompositor` читает только `active_objects()`."""

    def __init__(self, objects):
        self._objects = list(objects)

    def active_objects(self):
        return list(self._objects)


def _a7_objects():
    from Services.layer_render.factory import RenderedObject
    from Services.line_sim.core.layered_object import LayeredObject

    objects = []
    for i, (seed, h, w, spawn_encoder, lateral_px) in enumerate(_A7_SPRITES):
        rendered = RenderedObject(
            rgba=_random_rgba(seed, h, w), class_name=f"cls{i}", angle_deg=float(10 * i), defect=None, layer_params={}
        )
        obj = LayeredObject.from_rendered(rendered, object_id=f"obj-{i}", spawn_encoder=spawn_encoder)
        obj.passport = dataclasses.replace(obj.passport, lateral_px=lateral_px)
        objects.append(obj)
    return objects


def _a7_stack():
    """Стек `[SolidFill, RGBA-тайл]`: тайл 70x37 с частичной альфой, полоса вокруг `belt_y_px`."""
    return [SolidFill((20, 40, 60)), ScrollingTile(_random_rgba(201, 70, 37))]


def _a7_compositor(with_stack: bool):
    from Services.line_sim import SceneCompositor

    kwargs = dict(px_per_mm=3.0, belt_y_px=100.0, belt_direction=-1, entry_x_px=320.0)
    if with_stack:
        return SceneCompositor(_StubSpawner(_a7_objects()), background_layers=_a7_stack(), **kwargs)
    return SceneCompositor(_StubSpawner(_a7_objects()), background_bgr=(200, 10, 30), **kwargs)


def _a7_run(with_stack: bool):
    """Прогон сценария: (sha256 всех кадров подряд, sha256[:16] каждого кадра, паспорта по шагам, sha256 паспортов)."""
    comp = _a7_compositor(with_stack)
    total = hashlib.sha256()
    per_frame: list[str] = []
    visible: list[list[str]] = []
    passport_dump: list[list[dict]] = []
    for enc in _A7_ENCODERS:
        frame, passports = comp.render(enc, _A7_RECT)
        assert frame.shape == (200, 300, 3) and frame.dtype == np.uint8
        total.update(frame.tobytes())
        per_frame.append(hashlib.sha256(frame.tobytes()).hexdigest()[:16])
        visible.append([p.object_id for p in passports])
        passport_dump.append([p.to_dict() for p in passports])
    passports_sha = hashlib.sha256(json.dumps(passport_dump, sort_keys=True).encode("utf-8")).hexdigest()
    return total.hexdigest(), per_frame, visible, passports_sha


# --- Литералы снимка (СНЯТЫ с SceneCompositor ДО задачи; Windows-10-10.0.19045-SP0, CPython 3.12.12, numpy 2.4.4, SHA 920c11475) ---
_A7_STACK_FRAMES_SHA = "f27c5f5d14da3c20e22775163553db4b0e945553274026f4d06304a5199c26b1"
_A7_STACK_PER_FRAME = [
    "0bfe358a10d3860e",
    "b3e321c9393e5c8b",
    "9c3b7e51a935d39a",
    "27337b42fc4c03ca",
    "a3ca19a109a22546",
    "07443cc0d4ab6d99",
    "3ac65bf5ba980949",
    "727d0604e9aeb34b",
    "d8733d41ac73c87c",
    "f2d10e3d7947b2db",
    "cd2c7dd3a5be279e",
    "d8e632c27729b70c",
    "aa786111c5938b05",
    "a7e9543db0ec32a1",
]
_A7_NOSTACK_FRAMES_SHA = "97c8537872a39842b48efc02116e900d4ec2bb301a59febd7b0acebc8d7f2c70"
_A7_NOSTACK_PER_FRAME = [
    "4cf17e3cb4610193",
    "76b7ef053fe37eb8",
    "45310ee998313f17",
    "3040c4fa16e5f8cd",
    "32112d70a8eb6083",
    "f2083ef4b779ff2e",
    "af9d787464f2fa87",
    "1638f6edd7511f9e",
    "8ea65550596b61f7",
    "e1245cf3711fdf56",
    "e1245cf3711fdf56",
    "e1245cf3711fdf56",
    "e1245cf3711fdf56",
    "e1245cf3711fdf56",
]
_A7_VISIBLE_PER_STEP = [
    ["obj-0"],
    ["obj-0", "obj-1"],
    ["obj-0", "obj-1", "obj-2"],
    ["obj-0", "obj-1", "obj-2", "obj-3"],
    ["obj-0", "obj-1", "obj-2", "obj-3"],
    ["obj-0", "obj-1", "obj-2", "obj-3"],
    ["obj-2", "obj-3"],
    ["obj-3"],
    ["obj-3"],
    [],
    [],
    [],
    [],
    [],
]
_A7_STACK_PASSPORTS_SHA = "676042e961cc6cf76019b545f20bb1cd72b8d8e13c1c5b15c13db685a17a3ba2"
_A7_NOSTACK_PASSPORTS_SHA = "676042e961cc6cf76019b545f20bb1cd72b8d8e13c1c5b15c13db685a17a3ba2"


def test_a7_scenario_is_not_degenerate_overlap_and_edges_are_really_exercised():
    """A7 (ЗЕЛЁНЫЙ до задачи). Защита от вырожденного сценария: ≥3 объекта видны одновременно, есть шаги без
    объектов и с частично видимыми; список видимых объектов — литерал (порядок = порядок спавна)."""
    _total, _per, visible, _psha = _a7_run(with_stack=True)
    assert visible == _A7_VISIBLE_PER_STEP
    sizes = [len(v) for v in visible]
    assert max(sizes) >= 3
    assert min(sizes) <= 1
    assert len(visible) >= 10


def test_a7_frames_with_background_stack_are_bytewise_the_same():
    """A7 (ЗЕЛЁНЫЙ до задачи). Кадры `SceneCompositor.render` со стеком `[SolidFill, RGBA-тайл]`, `belt_direction=-1`,
    `entry_x_px=320`, `lateral_px≠0`, 14 шагов энкодера: общий sha256 и sha256[:16] каждого кадра — литералы."""
    total, per_frame, _visible, _psha = _a7_run(with_stack=True)
    assert per_frame == _A7_STACK_PER_FRAME
    assert total == _A7_STACK_FRAMES_SHA


def test_a7_frames_with_solid_background_bgr_are_bytewise_the_same():
    """A7 (ЗЕЛЁНЫЙ до задачи). Тот же сценарий без стека, сплошная заливка `background_bgr=(200, 10, 30)` (НЕ серый: порядок
    BGR/RGB различим)."""
    total, per_frame, _visible, _psha = _a7_run(with_stack=False)
    assert per_frame == _A7_NOSTACK_PER_FRAME
    assert total == _A7_NOSTACK_FRAMES_SHA


def test_a7_solid_background_bgr_is_blue_green_red_ordered_literal():
    """A7 / TRAPS «BGR→RGB» (ЗЕЛЁНЫЙ до задачи). `background_bgr=(200, 10, 30)` — B=200, G=10, R=30: пиксель кадра без
    объектов в RGB — `(30, 10, 200)`. Серый `(60, 60, 60)` эту перестановку не ловит."""
    from Services.line_sim import SceneCompositor

    comp = SceneCompositor(_StubSpawner([]), px_per_mm=3.0, belt_y_px=100.0, background_bgr=(200, 10, 30))
    frame, passports = comp.render(0.0, _A7_RECT)
    assert passports == []
    assert (frame == np.array([30, 10, 200], dtype=np.uint8)).all()


def test_a7_passports_are_the_same_list_in_the_same_order():
    """A7 (ЗЕЛЁНЫЙ до задачи). Паспорта по шагам — тот же список в том же порядке: sha256 JSON (`to_dict`, sort_keys) —
    литералы; одинаковы для обоих вариантов фона (отсечение от фона не зависит)."""
    _t1, _p1, visible_stack, sha_stack = _a7_run(with_stack=True)
    _t2, _p2, visible_plain, sha_plain = _a7_run(with_stack=False)
    assert visible_stack == visible_plain == _A7_VISIBLE_PER_STEP
    assert sha_stack == _A7_STACK_PASSPORTS_SHA
    assert sha_plain == _A7_NOSTACK_PASSPORTS_SHA


# ======================================================================================================
# A8. Делегирование: кадр SceneCompositor == render_scene по формулам DESIGN
# ======================================================================================================

_A8_FACTOR_MM = 0.144473  # мм на счёт энкодера (Services/robot_comm/core/registers.py, значение — литерал)


def _a8_expected_frame(with_stack: bool, encoder: float, fold: bool) -> np.ndarray:
    """Кадр по формулам DESIGN: фон/объекты собираются ВРУЧНУЮ, без вызова кода `SceneCompositor`."""
    scene = _scene()
    x_px, y_px, w_px, h_px = _A7_RECT
    w, h = int(round(w_px)), int(round(h_px))
    px_per_mm, belt_y_px, direction, entry_x_px = 3.0, 100.0, -1, 320.0
    if with_stack:
        layers = _a7_stack()
        layers = fold_background(layers) if fold else layers
        scroll_px = direction * int(round(float((encoder - 0.0) * _A8_FACTOR_MM * px_per_mm)))
    else:
        b, g, r = (200, 10, 30)
        layers = [SolidFill(color_rgb=(r, g, b))]
        scroll_px = 0
    background = scene.SceneBackground(
        layers, (w, h), center_y=belt_y_px, scroll_px=scroll_px, origin_xy=(int(round(x_px)), int(round(y_px)))
    )
    placed = []
    for obj in _a7_objects():
        sprite = obj.render()
        offset_mm = (encoder - obj.passport.spawn_encoder) * _A8_FACTOR_MM
        cx = entry_x_px + direction * offset_mm * px_per_mm - x_px
        cy = belt_y_px + obj.passport.lateral_px - y_px
        sh, sw = sprite.shape[:2]
        x0, x1, y0, y1 = cx - sw / 2.0, cx + sw / 2.0, cy - sh / 2.0, cy + sh / 2.0
        if x1 > 0 and x0 < w and y1 > 0 and y0 < h:
            placed.append(scene.PlacedObject(sprite, (cx, cy)))
    return scene.render_scene(background, placed, (), None)


@pytest.mark.parametrize("encoder", _A7_ENCODERS)
@pytest.mark.parametrize("with_stack", [True, False], ids=["stack", "bgr"])
def test_a8_compositor_frame_equals_render_scene_built_by_design_formulas(with_stack, encoder):
    """A8 (КРАСНЫЙ до задачи: `scene` нет). На сценарии A7 кадр `SceneCompositor.render` == `render_scene` с фоном и
    объектами, собранными по формулам DESIGN (cx, cy, строгие неравенства отсечения; scroll_px/origin_xy/center_y; стек
    `[SolidFill(RGB из BGR)]` без стека). Стек для проверки берётся СВЁРНУТЫЙ, как делает компоновщик."""
    expected = _a8_expected_frame(with_stack, encoder, fold=True)
    frame, _passports = _a7_compositor(with_stack).render(encoder, _A7_RECT)
    assert np.array_equal(frame, expected)


@pytest.mark.parametrize("encoder", [0.0, 600.0, 1350.0])
def test_a8_unfolded_stack_gives_the_same_frame_as_folded(encoder):
    """A8 / DESIGN «свёртка — у вызывающего» (КРАСНЫЙ до задачи). `render_scene` рисует стек как дан: несвёрнутый и
    свёрнутый стеки дают один кадр (Task 1.1 держит это в `render_background`)."""
    assert np.array_equal(_a8_expected_frame(True, encoder, fold=True), _a8_expected_frame(True, encoder, fold=False))


# ======================================================================================================
# A9. Старые контракты
# ======================================================================================================


def _a9_compositor(**kwargs):
    from Services.line_sim import SceneCompositor

    return SceneCompositor(_StubSpawner(_a7_objects()), px_per_mm=3.0, belt_y_px=100.0, **kwargs)


def test_a9_without_stack_nan_encoder_does_not_raise():
    """A9 п.1 (ЗЕЛЁНЫЙ до задачи). Без `background_layers` `render(float("nan"), rect)` не бросает (сдвиг тайла считается только
    со стеком) — ни с пустым спавнером, ни с объектами."""
    from Services.line_sim import SceneCompositor

    empty = SceneCompositor(_StubSpawner([]), px_per_mm=3.0, belt_y_px=100.0)
    frame, passports = empty.render(float("nan"), _A7_RECT)
    assert frame.shape == (200, 300, 3) and passports == []
    frame2, _p2 = _a9_compositor().render(float("nan"), _A7_RECT)
    assert frame2.shape == (200, 300, 3)


def test_a9_with_stack_nan_encoder_raises():
    """A9 п.2 (ЗЕЛЁНЫЙ до задачи). Со стеком `render(nan, rect)` бросает (сдвиг тайла `int(round(nan))`)."""
    comp = _a9_compositor(background_layers=[SolidFill((1, 2, 3)), ScrollingTile(_tile_2x7())])
    with pytest.raises((ValueError, OverflowError)):
        comp.render(float("nan"), _A7_RECT)


@pytest.mark.parametrize("bgr", [(0, 0, 0), (255, 255, 255), (255, 0, 0), (60, 60, 60)])
def test_a9_boundary_valid_background_bgr_is_accepted(bgr):
    """A9 (ЗЕЛЁНЫЙ до задачи). Граница валидного цвета: три `int` 0..255 принимаются (и дают кадр) — парный контроль к
    тестам отказа ниже."""
    frame, _p = _a9_compositor(background_bgr=bgr).render(0.0, _A7_RECT)
    assert frame.shape == (200, 300, 3)


def test_a9_invalid_background_bgr_300_raises_value_error_in_constructor():
    """A9 п.3 (КРАСНЫЙ до задачи: ошибка прежде всплывала в `render()` как `OverflowError`). `background_bgr=(300, 0, 0)` ->
    `ValueError` в `SceneCompositor(...)`, в тексте `background_bgr`."""
    with pytest.raises(ValueError, match="background_bgr"):
        _a9_compositor(background_bgr=(300, 0, 0))


@pytest.mark.parametrize(
    "bgr",
    [
        pytest.param((256, 0, 0), id="256"),
        pytest.param((-1, 0, 0), id="negative"),
        pytest.param((60.5, 60, 60), id="fractional-float"),
        pytest.param((np.int64(60), 60, 60), id="np-int64"),
        pytest.param((60.0, 60.0, 60.0), id="whole-floats"),
    ],
)
def test_a9_extra_other_invalid_background_bgr_raise_value_error_in_constructor(bgr):
    """РАСШИРЕНИЕ A9 (пять случаев «сужения» из DESIGN, A9 называет только `(300, 0, 0)`; КРАСНЫЙ до задачи). Все —
    `ValueError` в `__init__`, в тексте `background_bgr`; граница 255/256 парой к тесту принятия выше."""
    with pytest.raises(ValueError, match="background_bgr"):
        _a9_compositor(background_bgr=bgr)


@pytest.mark.parametrize("bgr", [pytest.param((1, 2, 3, 4), id="four"), pytest.param(60, id="scalar")])
def test_a9_extra_non_triple_background_bgr_fails_in_constructor(bgr):
    """РАСШИРЕНИЕ A9 (КРАСНЫЙ до задачи). Вход не тройкой -> ошибка распаковки (`ValueError`/`TypeError`) теперь в `__init__`,
    не в `render()`."""
    with pytest.raises((ValueError, TypeError)):
        _a9_compositor(background_bgr=bgr)
