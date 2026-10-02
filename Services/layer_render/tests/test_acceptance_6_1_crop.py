# -*- coding: utf-8 -*-
"""Слепые acceptance-тесты Task 6.1 `layer-render`: `Services/layer_render/crop.py`.

Источник контракта: `plans/layer-render/phase-6-train.md`, Task 6.1 (Goal, DESIGN, Acceptance A1-A7) плюс
ТЕКУЩИЙ код, с которого сняты литералы: `Plugins/processing/center_crop/{plugin,registers}.py` и
`Services/ml_train/holdout_eval.py::_crop_disk`. Worktree на коммите ДО реализации: `crop.py` не существует.

ЗАПРЕЩЁННЫЕ ПУТИ (не читались): реализация `Services/layer_render/crop.py` (её нет по конструкции),
`.claude/worktrees/*`, любые другие ветки, существующие тесты за пределами хелперов сборки плагина.

Как устроен файл.
  * Тесты, бьющие только в СЕГОДНЯШНЕЕ API (плагин, `_crop_disk`), зелёные уже сейчас — это страховочная сетка:
    после задачи те же литералы обязаны держаться (A1).
  * Тесты `square_crop` / `resize_square` / `side_from_radius` красные до реализации: `Services.layer_render.crop`
    импортируется ВНУТРИ каждого теста, поэтому каждый падает сам (ModuleNotFoundError), а не одной ошибкой сбора.
  * Ожидаемые значения — литералы (sha256 + форма), снятые на коде ДО задачи. Нигде не пересчитываются из
    тестируемого кода; единственные «оракулы» — `np.pad(mode="edge")` и срез numpy.

Кадр A1: форма (H, W, C) = (200, 160, 3) uint8 (H=200 строк, W=160 столбцов). Строится арифметикой от seed, а не
через RNG: поток `default_rng` между версиями numpy не гарантирован, а литералы должны жить годами.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[3]
_LAYER_RENDER = _REPO / "Services" / "layer_render"

# ---------------------------------------------------------------------------------------------------------------
# Входные данные
# ---------------------------------------------------------------------------------------------------------------

_H, _W = 200, 160
_PAD = (10, 20, 30)  # pad_color_bgr / pad_value: НЕ нули, чтобы заливку было видно


def _pattern(h: int, w: int, c: int = 3, seed: int = 20260902) -> np.ndarray:
    """Детерминированный «шумный» кадр без RNG: каждый пиксель/канал различим, у краёв нет симметрии."""
    y = np.arange(h, dtype=np.int64)[:, None, None]
    x = np.arange(w, dtype=np.int64)[None, :, None]
    ch = np.arange(c, dtype=np.int64)[None, None, :]
    v = (y * 7 + x * 13 + ch * 29 + (x * y) % 251 + seed) % 256
    return v.astype(np.uint8)


def _frame() -> np.ndarray:
    return _pattern(_H, _W)


def _digest(a: np.ndarray | None):
    """(форма, sha256 по байтам) либо None. Форма входит в литерал: clamp отличается именно ею."""
    if a is None:
        return None
    return (tuple(a.shape), hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest())


# name -> (cx, cy, side). Кадр W=160, H=200.
_CASES: dict[str, tuple[int, int, int]] = {
    "inside": (80, 100, 64),
    "flush_left": (32, 100, 64),  # x0 == 0: ровно внутри
    "over1_left": (31, 100, 64),  # x0 == -1: на пиксель за краем
    "edge_left": (10, 100, 64),
    "corner_tl": (5, 5, 64),
    "flush_br": (128, 168, 64),  # x1 == W, y1 == H: ровно внутри
    "over1_br": (129, 169, 64),  # на пиксель за правым/нижним краем
    "centre_out_overlap": (-10, 100, 64),  # центр левее кадра, квадрат ещё перекрывает кадр
    "centre_out_corner": (170, 210, 64),  # центр вне кадра по обеим осям, перекрытие в углу
    "centre_out_nooverlap": (80, -100, 64),  # нет пересечения вообще
    "inside_odd": (80, 100, 65),  # нечётная сторона: x0 = cx - side//2, ширина ровно side
    "edge_odd": (10, 100, 65),
    "huge": (80, 100, 300),  # квадрат больше кадра, кадр целиком внутри квадрата
}

# Режим -> конфиг плагина (регистр не знает слова oob, DESIGN: drop_partial побеждает pad; оба False -> clamp).
_PLUGIN_CFG = {
    "drop": {"drop_partial": True, "pad_if_oob": True, "pad_color_bgr": list(_PAD)},  # drop ПОБЕЖДАЕТ pad
    "pad": {"drop_partial": False, "pad_if_oob": True, "pad_color_bgr": list(_PAD)},
    "clamp": {"drop_partial": False, "pad_if_oob": False, "pad_color_bgr": list(_PAD)},
}
_MODES = ("drop", "pad", "clamp")


def _make_plugin(cfg: dict):
    from Plugins.processing.center_crop.plugin import CenterCropPlugin

    ctx = MagicMock()
    ctx.config = dict(cfg)
    p = CenterCropPlugin()
    p.configure(ctx)
    return p


def _via_plugin(mode: str, frame: np.ndarray, cx: int, cy: int, side: int):
    return _make_plugin(_PLUGIN_CFG[mode])._crop_square(frame, cx, cy, side)


def _via_square_crop(mode: str, frame: np.ndarray, cx: int, cy: int, side: int):
    from Services.layer_render.crop import square_crop

    return square_crop(frame, cx, cy, side, mode, pad_value=_PAD)


# ---------------------------------------------------------------------------------------------------------------
# A1 / A2 — литералы ДО задачи (снято на b294a6afe: плагин `_crop_square` на кадре 200x160x3)
# ---------------------------------------------------------------------------------------------------------------
_A1_PLUGIN: dict[tuple[str, str], object] = {
    ("drop", "inside"): ((64, 64, 3), "1c7a0b940c60e845bafd28ce5c392e4d7e9c3486c9160bfa33c321dffad7aa56"),
    ("drop", "flush_left"): ((64, 64, 3), "49c9127a2ac2970f1418c93db40f270df7eb0b0142f26edf91b8c1b19e331b5e"),
    ("drop", "over1_left"): None,
    ("drop", "edge_left"): None,
    ("drop", "corner_tl"): None,
    ("drop", "flush_br"): ((64, 64, 3), "fb54ab0cfeb315a8d42aac4c5a5b9b5b804e9a26bc613b39c9221e9fa1b4b5ae"),
    ("drop", "over1_br"): None,
    ("drop", "centre_out_overlap"): None,
    ("drop", "centre_out_corner"): None,
    ("drop", "centre_out_nooverlap"): None,
    ("drop", "inside_odd"): ((65, 65, 3), "293c0a5ff61a39696c93fb3b2df034242328e161faa3cfa1bd97eaf7f03c7718"),
    ("drop", "edge_odd"): None,
    ("drop", "huge"): None,
    ("pad", "inside"): ((64, 64, 3), "1c7a0b940c60e845bafd28ce5c392e4d7e9c3486c9160bfa33c321dffad7aa56"),
    ("pad", "flush_left"): ((64, 64, 3), "49c9127a2ac2970f1418c93db40f270df7eb0b0142f26edf91b8c1b19e331b5e"),
    ("pad", "over1_left"): ((64, 64, 3), "9db6f9ceeb979b10787598aec850c41b95608bd9d47aa551cee7ecce4533385f"),
    ("pad", "edge_left"): ((64, 64, 3), "2ca3eeec67b7e6cfe80176d1d5830707089298d6624aa98a3c73aac906bd89fa"),
    ("pad", "corner_tl"): ((64, 64, 3), "686dea154ccb0dc7ee3bfc1c523517b18cf8851ca1a4089662342acf09c53106"),
    ("pad", "flush_br"): ((64, 64, 3), "fb54ab0cfeb315a8d42aac4c5a5b9b5b804e9a26bc613b39c9221e9fa1b4b5ae"),
    ("pad", "over1_br"): ((64, 64, 3), "45ca075201b682dfb65fb96d4be4fbd0cecb8e804c53839b50fbe5a1f2da013e"),
    ("pad", "centre_out_overlap"): ((64, 64, 3), "44f1f6aa2cfe3a048643baf1d10fb2d30d41d49bd2ae5c7a4f51b324183a2a53"),
    ("pad", "centre_out_corner"): ((64, 64, 3), "9d2f8abe53fdc8c69c4b169b3366f7ed29611f971c8dc5248373085e2b317557"),
    ("pad", "centre_out_nooverlap"): ((64, 64, 3), "f2afb17b25fca093ddb4d6af917c32347ee0fdd1c4c6e65627227ba4405e5391"),
    ("pad", "inside_odd"): ((65, 65, 3), "293c0a5ff61a39696c93fb3b2df034242328e161faa3cfa1bd97eaf7f03c7718"),
    ("pad", "edge_odd"): ((65, 65, 3), "e4344466798264df21c1bda1595c09568035c84493e7dd2b7077c47e2da71a79"),
    ("pad", "huge"): ((300, 300, 3), "a7771f558ded31d0706c15bbbd9c3642a644a134dd4a937dbcf699f58d88a8f7"),
    ("clamp", "inside"): ((64, 64, 3), "1c7a0b940c60e845bafd28ce5c392e4d7e9c3486c9160bfa33c321dffad7aa56"),
    ("clamp", "flush_left"): ((64, 64, 3), "49c9127a2ac2970f1418c93db40f270df7eb0b0142f26edf91b8c1b19e331b5e"),
    ("clamp", "over1_left"): ((64, 63, 3), "a5748965509ac64cffd2d8960a31a419359948bcd3b37e64bc3ebe24ead53a32"),
    ("clamp", "edge_left"): ((64, 42, 3), "037bd3a873f63572334e1ef94262ca05b33834930d23a320e1d8840172bbea5d"),
    ("clamp", "corner_tl"): ((37, 37, 3), "31332c00a81770a784830b014d32a508d99c8005d424dd1661619d89ded144fc"),
    ("clamp", "flush_br"): ((64, 64, 3), "fb54ab0cfeb315a8d42aac4c5a5b9b5b804e9a26bc613b39c9221e9fa1b4b5ae"),
    ("clamp", "over1_br"): ((63, 63, 3), "fdcb1340188944bd4a7a48289cea6d2d101b2f7f13868b8f0547d9e956dd8abb"),
    ("clamp", "centre_out_overlap"): ((64, 22, 3), "a9dc1bc0a69cc150a98f3dbee8d8125b0cdecb22fd72fa94547c95af85ee75bf"),
    ("clamp", "centre_out_corner"): ((22, 22, 3), "6c9044acca2ff8ef54c6c547de2b53610cd3aba212721c539bad48546e509c6d"),
    ("clamp", "centre_out_nooverlap"): None,
    ("clamp", "inside_odd"): ((65, 65, 3), "293c0a5ff61a39696c93fb3b2df034242328e161faa3cfa1bd97eaf7f03c7718"),
    ("clamp", "edge_odd"): ((65, 43, 3), "cd19b75aa0ea945ab6c7ee7b5488e5fd8dd47b29ed7270d980fa0af82adbe7c7"),
    ("clamp", "huge"): ((200, 160, 3), "f92e361d1a1e73ac318b8755dc8a009305eaf7c61f4ae1aaf4866cd81ef38fab"),
}
_A1_DISK: dict[str, object] = {
    "left_edge": ((70, 70, 3), "ed0ca5baa43633a5288609fc48ad52ed73c523b14db97ad7c013ecdb735e8002"),
    "top_right_corner": ((60, 60, 3), "77a3c9822d2de272571e84dd1cd7f6ee65bce975a769a994111a62b263c61848"),
    "bottom_edge_other_frame": ((82, 82, 3), "bc0d9b1456b6ca0bb3bc4e7bbe5fe870bb1a6b02763ec2e72feabbcb1f34ef0a"),
}
_A6: dict[str, object] = {
    "area_328_128": ((128, 128, 3), "66b905b2d9aec7f4afbd67c2c6b3bcbb59e32e2985f79165fc7ff2183d971b4c"),
    "linear_64_128": ((128, 128, 3), "154a6f045b9c7d5246c9e49bd731438fec0b7923c40b52e993f9cbf553710c23"),
    "tall_100x40_64": ((64, 64, 3), "30a843a9e60a4b8d8dcd095818e837370eaf3e91eb9dc08e4a6b93a0dd9f8006"),
    "wide_64x40_64": ((64, 64, 3), "7261eeabe67de61024f5452b24199539e448cf9e83fa830d8c0f08366c61e68f"),
    "short_40x100_64": ((64, 64, 3), "07eb854491b0d1592c6a08e81e8b65206871b73783c9279740fd8983d2444363"),
}

_PLUGIN_PARAMS = [(m, n) for m in _MODES for n in _CASES]


@pytest.mark.parametrize(("mode", "name"), _PLUGIN_PARAMS)
def test_a1_plugin_output_matches_literals_taken_before_the_task(mode, name):
    """A1 (страховочная сетка, зелёная ДО задачи): плагин на кадре 200x160x3 даёт те же байты и ту же форму."""
    cx, cy, side = _CASES[name]
    out = _via_plugin(mode, _frame(), cx, cy, side)
    assert _digest(out) == _A1_PLUGIN[(mode, name)]


@pytest.mark.parametrize(("mode", "name"), _PLUGIN_PARAMS)
def test_a2_square_crop_matches_the_same_literals_as_the_plugin(mode, name):
    """A2: `square_crop(oob=mode)` на тех же входах = те же литералы, что у плагина (функция = поведение плагина)."""
    cx, cy, side = _CASES[name]
    out = _via_square_crop(mode, _frame(), cx, cy, side)
    assert _digest(out) == _A1_PLUGIN[(mode, name)]


def test_a1_literals_pin_the_branches_they_are_meant_to_pin():
    """Защита самих литералов: таблица различает режимы там, где они обязаны различаться (иначе A1 пуст)."""
    assert _A1_PLUGIN[("drop", "inside")] == _A1_PLUGIN[("pad", "inside")] == _A1_PLUGIN[("clamp", "inside")]
    assert _A1_PLUGIN[("drop", "over1_left")] is None
    assert _A1_PLUGIN[("clamp", "over1_left")][0] == (64, 63, 3)  # clamp: меньше стороны
    assert _A1_PLUGIN[("pad", "over1_left")][0] == (64, 64, 3)
    assert _A1_PLUGIN[("clamp", "centre_out_nooverlap")] is None
    assert _A1_PLUGIN[("pad", "centre_out_nooverlap")][0] == (64, 64, 3)  # чистый холст
    assert _A1_PLUGIN[("clamp", "huge")][0] == (_H, _W, 3)  # весь кадр
    assert _A1_PLUGIN[("pad", "huge")][0] == (300, 300, 3)


def test_pad_without_overlap_is_a_clean_canvas_of_pad_value():
    """DESIGN `pad`: без пересечения — чистый холст pad_value (литерал значения, не хэш)."""
    cx, cy, side = _CASES["centre_out_nooverlap"]
    out = _via_square_crop("pad", _frame(), cx, cy, side)
    assert out.shape == (64, 64, 3)
    assert out.dtype == np.uint8
    assert (out == np.array(_PAD, dtype=np.uint8)).all()


def test_pad_pastes_the_overlap_at_the_right_offset():
    """DESIGN `pad`: пересечение вклеено; over1_left -> x0=-1: столбец 0 холста = pad, столбец 1 = кадр[:, 0]."""
    f = _frame()
    cx, cy, side = _CASES["over1_left"]
    out = _via_square_crop("pad", f, cx, cy, side)
    assert (out[:, 0, :] == np.array(_PAD, dtype=np.uint8)).all()
    assert np.array_equal(out[:, 1:, :], f[68:132, 0:63, :])


def test_pad_two_dim_frame_uses_first_channel_of_pad_value():
    """DESIGN: для 2D-кадра заливка = `color[0]` (правило `_pad_canvas`)."""
    from Services.layer_render.crop import square_crop

    f2 = _pattern(_H, _W)[:, :, 0].copy()
    out = square_crop(f2, -10, 100, 64, "pad", pad_value=_PAD)
    assert out.shape == (64, 64)
    assert (out[:, 0] == 10).all()  # левее кадра на 42 px: x0 = -42, первые 42 столбца = pad
    assert np.array_equal(out[:, 42:], f2[68:132, 0:22])


def test_pad_four_channel_frame_uses_pad_value_extended_with_zero():
    """DESIGN: `(color + [0,0,0])[:c]` -> для 4 каналов заливка (10, 20, 30, 0)."""
    from Services.layer_render.crop import square_crop

    f4 = _pattern(_H, _W, c=4)
    out = square_crop(f4, 80, -100, 64, "pad", pad_value=_PAD)
    assert out.shape == (64, 64, 4)
    assert (out == np.array([10, 20, 30, 0], dtype=np.uint8)).all()


def test_pad_two_dim_frame_plugin_literal_safety_net():
    """Сетка (зелёная до задачи): тот же 2D-случай через плагин."""
    f2 = _pattern(_H, _W)[:, :, 0].copy()
    out = _make_plugin(_PLUGIN_CFG["pad"])._crop_square(f2, -10, 100, 64)
    assert out.shape == (64, 64)
    assert (out[:, 0] == 10).all()
    assert np.array_equal(out[:, 42:], f2[68:132, 0:22])


# --- A1 (диск) ---------------------------------------------------------------------------------------------------
# (cx, cy, r) на кадрах разного размера, диск у края, перекрытие только частичное. margin = 0.18 как в evaluate_holdout.
_DISK_CASES: dict[str, tuple[tuple[int, int], tuple[int, int, int]]] = {
    "left_edge": ((200, 160), (20, 100, 30)),  # half=35: x0=-15
    "top_right_corner": ((200, 160), (150, 12, 25)),  # half=30: y0=-18, x1=180>160
    "bottom_edge_other_frame": ((180, 240), (80, 170, 35)),  # half=41: y1=211>180
}
_MARGIN = 0.18


def _disk_frame(name: str) -> np.ndarray:
    (h, w), _ = _DISK_CASES[name]
    return _pattern(h, w, seed=777 + h + w)


def _run_crop_disk(monkeypatch, name: str):
    import Services.ml_train.holdout_eval as he

    _, (cx, cy, r) = _DISK_CASES[name]
    monkeypatch.setattr(he, "detect_disk", lambda bgr: (cx, cy, r))
    return he._crop_disk(_disk_frame(name), _MARGIN)


@pytest.mark.parametrize("name", list(_DISK_CASES))
def test_a1_crop_disk_output_matches_literals_taken_before_the_task(monkeypatch, name):
    """A1 (сетка, зелёная ДО задачи): `_crop_disk` (detect_disk подменён) = те же байты и форма после задачи.

    Сравниваем БАЙТЫ, не identity: сегодня внутри кадра `_crop_disk` отдаёт view, после задачи — копию.
    """
    assert _digest(_run_crop_disk(monkeypatch, name)) == _A1_DISK[name]


@pytest.mark.parametrize("name", list(_DISK_CASES))
def test_a2_square_crop_replicate_matches_the_crop_disk_literals(name):
    """A2: `square_crop(bgr, cx, cy, 2*half, "replicate")` даёт литералы `_crop_disk` (half = round(r*(1+margin)))."""
    from Services.layer_render.crop import square_crop

    _, (cx, cy, r) = _DISK_CASES[name]
    half = int(round(r * (1.0 + _MARGIN)))
    out = square_crop(_disk_frame(name), cx, cy, 2 * half, "replicate")
    assert _digest(out) == _A1_DISK[name]


def test_a1_crop_disk_literals_are_square_and_even():
    """Защита литералов: все три выреза квадратные чётной стороны 2*half (не clamp-обрезки)."""
    assert [_A1_DISK[n][0] for n in _DISK_CASES] == [(70, 70, 3), (60, 60, 3), (82, 82, 3)]


# ---------------------------------------------------------------------------------------------------------------
# replicate: независимый оракул np.pad(mode="edge") по сетке положений
# ---------------------------------------------------------------------------------------------------------------


def _edge_oracle(frame: np.ndarray, cx: int, cy: int, side: int) -> np.ndarray:
    """Квадрат side x side с репликацией края. Независим от кода выреза: целиком np.pad + срез."""
    h, w = frame.shape[:2]
    half = side // 2
    x0, y0 = cx - half, cy - half
    m = side + max(h, w)  # запас, чтобы любой квадрат с пересечением лёг в расширенный кадр
    big = np.pad(frame, ((m, m), (m, m), (0, 0)), mode="edge")
    return big[m + y0 : m + y0 + side, m + x0 : m + x0 + side].copy()


def _overlaps(cx: int, cy: int, side: int) -> bool:
    half = side // 2
    return min(_W, cx - half + side) > max(0, cx - half) and min(_H, cy - half + side) > max(0, cy - half)


_GRID = [
    (cx, cy, s)
    for s in (2, 3, 40, 65)
    for cx in (-50, -20, 0, 5, 80, 155, 170, 200)
    for cy in (-60, -10, 0, 7, 100, 195, 230)
]


def test_replicate_equals_edge_pad_oracle_on_a_grid_of_positions():
    """replicate с перекрытием = np.pad(edge) + срез на сетке центров/сторон (центр вне кадра, нечётная сторона)."""
    from Services.layer_render.crop import square_crop

    f = _frame()
    checked = 0
    for cx, cy, side in _GRID:
        if not _overlaps(cx, cy, side):
            continue
        out = square_crop(f, cx, cy, side, "replicate")
        assert out.shape == (side, side, 3), (cx, cy, side)
        assert np.array_equal(out, _edge_oracle(f, cx, cy, side)), (cx, cy, side)
        checked += 1
    assert checked > 80  # сетка не выродилась


def test_replicate_with_exactly_one_overlapping_row_replicates_that_row():
    """Граница перекрытия: cy=-31, side=64 -> y1=1, ровно ОДНА строка кадра (строка 0) — все 64 строки выреза = она."""
    from Services.layer_render.crop import square_crop

    f = _frame()
    out = square_crop(f, 80, -31, 64, "replicate")
    assert out.shape == (64, 64, 3)
    row0 = f[0, 48:112, :]
    assert all(np.array_equal(out[i], row0) for i in range(64))


@pytest.mark.parametrize("mode", ["drop", "pad", "clamp", "replicate"])
def test_modes_agree_with_a_slice_when_the_square_is_fully_inside(mode):
    """Во всех четырёх режимах квадрат внутри кадра = прямой срез (x0 = cx - side//2, размер ровно side)."""
    from Services.layer_render.crop import square_crop

    f = _frame()
    out = square_crop(f, 80, 100, 65, mode, pad_value=_PAD)
    assert np.array_equal(out, f[68:133, 48:113, :])  # side=65: half=32 -> x0=48, y0=68


# ---------------------------------------------------------------------------------------------------------------
# A3 — копия, не view; read-only кадр
# ---------------------------------------------------------------------------------------------------------------

# Положения, где результат режима НЕ None.
_A3_PARAMS = [
    ("drop", "inside"),
    ("drop", "flush_left"),
    ("pad", "inside"),
    ("pad", "over1_left"),
    ("pad", "centre_out_nooverlap"),
    ("clamp", "inside"),
    ("clamp", "flush_br"),
    ("clamp", "edge_left"),
    ("replicate", "inside"),
    ("replicate", "flush_left"),
    ("replicate", "edge_left"),
    ("replicate", "centre_out_overlap"),
]


@pytest.mark.parametrize(("mode", "name"), _A3_PARAMS)
def test_a3_output_does_not_share_memory_with_frame_and_writes_do_not_leak_back(mode, name):
    """A3: np.shares_memory(out, frame) is False; запись в выход не меняет кадр (наблюдаемый эффект, не имя API)."""
    from Services.layer_render.crop import square_crop

    f = _frame()
    snapshot = f.copy()
    cx, cy, side = _CASES[name]
    out = square_crop(f, cx, cy, side, mode, pad_value=_PAD)
    assert out is not None
    assert np.shares_memory(out, f) is False
    out[...] = 255
    assert np.array_equal(f, snapshot)


@pytest.mark.parametrize(("mode", "name"), _A3_PARAMS)
def test_a3_read_only_frame_works_and_output_is_writeable(mode, name):
    """A3: кадр с writeable=False (read-only view SHM) принимается; выход записываемый и не делит память."""
    from Services.layer_render.crop import square_crop

    f = _frame()
    f.flags.writeable = False
    cx, cy, side = _CASES[name]
    out = square_crop(f, cx, cy, side, mode, pad_value=_PAD)
    assert out is not None
    assert out.flags.writeable is True
    assert np.shares_memory(out, f) is False
    out[0, 0] = 1  # не бросает


def test_a3_read_only_frame_gives_the_same_bytes_as_writable():
    """Read-only кадр не меняет результат: байты = литерал A1."""
    from Services.layer_render.crop import square_crop

    f = _frame()
    f.flags.writeable = False
    cx, cy, side = _CASES["over1_left"]
    out = square_crop(f, cx, cy, side, "pad", pad_value=_PAD)
    assert _digest(out) == _A1_PLUGIN[("pad", "over1_left")]


# ---------------------------------------------------------------------------------------------------------------
# A4 — ошибки
# ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["inside", "edge_left", "centre_out_nooverlap"])
def test_a4_unknown_oob_raises_value_error_naming_the_value(name):
    """A4: oob="bogus" -> ValueError, текст называет значение — и внутри кадра (нет раннего возврата), и у края."""
    from Services.layer_render.crop import square_crop

    cx, cy, side = _CASES[name]
    with pytest.raises(ValueError, match="bogus"):
        square_crop(_frame(), cx, cy, side, "bogus")


@pytest.mark.parametrize(
    ("label", "cx", "cy"),
    [
        ("below_frame", 80, 300),  # центр ниже кадра: y0=268 > H
        ("far_above", 80, -100),  # cy + side//2 = -68 < 0
        ("far_left", -100, 100),  # cx + side//2 = -68 < 0
        ("touching_above", 80, -32),  # y1 == 0: граница, пересечения нет
        ("touching_left", -32, 100),  # x1 == 0
        ("far_right", 400, 100),
    ],
)
def test_a4_replicate_without_overlap_raises_value_error(label, cx, cy):
    """A4: replicate без пересечения -> ValueError (сегодня `_crop_disk` отдаёт мусор неверной формы — не переносим)."""
    from Services.layer_render.crop import square_crop

    with pytest.raises(ValueError):
        square_crop(_frame(), cx, cy, 64, "replicate")


def test_a4_replicate_no_overlap_error_is_not_swallowed_into_a_none_or_array():
    """Анти-мусор: цель ревью спеки — центр (100, -100), r=30 — раньше давал (230, 70, 3); теперь ValueError."""
    from Services.layer_render.crop import square_crop

    f = _pattern(180, 240, seed=5)
    half = int(round(30 * (1.0 + _MARGIN)))
    with pytest.raises(ValueError):
        square_crop(f, 100, -100, 2 * half, "replicate")


# ---------------------------------------------------------------------------------------------------------------
# A5 — side_from_radius
# ---------------------------------------------------------------------------------------------------------------


def test_a5_side_from_radius_recipe_literal():
    """A5: рецепт `letter_robot_sim.yaml:250-254`: r=150, scale=1.0, margin=14 -> 328."""
    from Services.layer_render.crop import side_from_radius

    assert side_from_radius(150, 1.0, 14) == 328


def test_a5_side_from_radius_floor_is_two():
    """A5: нулевой радиус -> нижняя граница 2 (а не 0)."""
    from Services.layer_render.crop import side_from_radius

    assert side_from_radius(0, 1.0, 0) == 2


@pytest.mark.parametrize(
    ("radius", "scale", "margin", "expected"),
    [
        (1, 0.5, 0, 2),  # round(1.0)=1 -> max(2, 1)
        (10, 1.0, 3, 26),  # 20 + 2*3
        (10, 1.5, 0, 30),
        (5, 0.25, 0, 2),  # 2*5*0.25 = 2.5 -> round() банковское = 2 (не 3)
        (7, 0.25, 0, 4),  # 3.5 -> 4
        (9, 0.25, 0, 4),  # 4.5 -> 4 (банковское, не 5)
        (10, 1.0, 2.9, 24),  # int(2.9) = 2 -> 20 + 4 (усечение, не округление)
    ],
)
def test_a5_side_from_radius_formula_literals(radius, scale, margin, expected):
    """Формула `plugin.py:121-122` дословно: max(2, int(round(2*r*scale)) + 2*int(margin)). Литералы руками."""
    from Services.layer_render.crop import side_from_radius

    out = side_from_radius(radius, scale, margin)
    assert out == expected
    assert type(out) is int


@pytest.mark.parametrize(
    ("radius", "scale", "margin", "expected"),
    [(150, 1.0, 14, 328), (1, 0.5, 0, 2), (10, 1.0, 3, 26), (5, 0.25, 0, 2), (7, 0.25, 0, 4), (9, 0.25, 0, 4)],
)
def test_a5_plugin_resolve_side_formula_safety_net(radius, scale, margin, expected):
    """Сетка (зелёная ДО и ПОСЛЕ задачи): `_resolve_side` плагина даёт те же числа, что литералы `side_from_radius`."""
    p = _make_plugin({"size_mode": "radius", "radius_scale": scale, "margin_px": margin})
    assert p._resolve_side(radius) == expected


def test_a5_plugin_resolve_side_literals_without_new_api():
    """Сетка, зелёная ДО задачи и ПОСЛЕ: `_resolve_side` на тех же числах (без импорта crop)."""
    p = _make_plugin({"size_mode": "radius", "radius_scale": 1.0, "margin_px": 14})
    assert p._resolve_side(150) == 328
    assert p._resolve_side(None) == 200  # радиус неизвестен -> side_px, это остаётся в плагине
    assert p._resolve_side(0) == 200
    p2 = _make_plugin({"size_mode": "fixed", "side_px": 77, "radius_scale": 1.0, "margin_px": 14})
    assert p2._resolve_side(150) == 77


# ---------------------------------------------------------------------------------------------------------------
# A6 — resize_square
# ---------------------------------------------------------------------------------------------------------------

_BIG = _pattern(328, 328, seed=31)
_SMALL = _pattern(64, 64, seed=32)
_TALL = _pattern(100, 40, seed=33)  # shape[0]=100 > out, ширина 40 < out: интерполяция выбирается по shape[0]
_WIDE = _pattern(64, 40, seed=34)  # shape[0]=64 == out, но не out x out -> LINEAR (не "уже готов")
_SHORT = _pattern(40, 100, seed=35)  # shape[0]=40 < out, но ширина 100 > out: всё равно LINEAR (по shape[0])


@pytest.mark.parametrize(
    ("key", "src", "out"),
    [
        ("area_328_128", _BIG, 128),
        ("linear_64_128", _SMALL, 128),
        ("tall_100x40_64", _TALL, 64),
        ("wide_64x40_64", _WIDE, 64),
        ("short_40x100_64", _SHORT, 64),
    ],
)
def test_a6_resize_square_literals(key, src, out):
    """A6: INTER_AREA при уменьшении (328->128), INTER_LINEAR при увеличении; выбор по `shape[0]`. Литералы sha256."""
    from Services.layer_render.crop import resize_square

    res = resize_square(src, out)
    assert res.shape == (out, out, 3)
    assert res.dtype == np.uint8
    assert _digest(res) == _A6[key]


def test_a6_literals_distinguish_area_from_linear_at_downscale():
    """Защита литерала: на 328->128 AREA и LINEAR дают РАЗНЫЕ байты (иначе тест интерполяции вакуумен)."""
    lin = cv2.resize(_BIG, (128, 128), interpolation=cv2.INTER_LINEAR)
    assert _digest(lin) != _A6["area_328_128"]


@pytest.mark.parametrize("out", [0, -1, -128])
def test_a6_non_positive_out_returns_the_input_itself(out):
    """A6: out <= 0 -> вход как есть (`is`), без копии."""
    from Services.layer_render.crop import resize_square

    assert resize_square(_BIG, out) is _BIG


def test_a6_already_out_by_out_returns_the_input_itself():
    """A6: уже out x out -> вход как есть (`is`)."""
    from Services.layer_render.crop import resize_square

    c = _pattern(128, 128, seed=36)
    assert resize_square(c, 128) is c


def test_a6_plugin_output_size_resize_matches_literal_safety_net():
    """Сетка (зелёная ДО задачи): `_resize_output` плагина с output_size=128 на 328-квадрате = литерал A6."""
    p = _make_plugin({"output_size": 128})
    assert _digest(p._resize_output(_BIG)) == _A6["area_328_128"]
    assert _digest(p._resize_output(_pattern(64, 64, seed=32))) == _A6["linear_64_128"]
    p64 = _make_plugin({"output_size": 64})
    assert _digest(p64._resize_output(_TALL)) == _A6["tall_100x40_64"]
    assert _digest(p64._resize_output(_WIDE)) == _A6["wide_64x40_64"]
    assert _digest(p64._resize_output(_SHORT)) == _A6["short_40x100_64"]


# ---------------------------------------------------------------------------------------------------------------
# Публичный API пакета, границы слоёв (A7: AST)
# ---------------------------------------------------------------------------------------------------------------


def test_public_api_is_reexported_from_the_package():
    """Files п.2: `Services/layer_render/__init__.py` экспортирует три функции (те же объекты, что в crop.py)."""
    crop = importlib.import_module("Services.layer_render.crop")
    pkg = importlib.import_module("Services.layer_render")
    for name in ("side_from_radius", "square_crop", "resize_square"):
        assert getattr(pkg, name) is getattr(crop, name)
        assert name in pkg.__all__


_FORBIDDEN_ROOTS = ("Services.dataset_gen", "Services.line_sim", "Services.ml_train")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            mods.add(base)
            mods.update(f"{base}.{a.name}" for a in node.names)
    return mods


def test_a7_layer_render_package_does_not_import_dataset_gen_line_sim_ml_train():
    """A7 (AST, не подстрока): ни один не-тестовый модуль `layer_render` не тянет dataset_gen / line_sim / ml_train."""
    files = [p for p in _LAYER_RENDER.rglob("*.py") if "tests" not in p.relative_to(_LAYER_RENDER).parts]
    assert files  # пакет не пуст
    bad = {
        str(p.relative_to(_REPO)): sorted(m for m in _imported_modules(p) if m.startswith(_FORBIDDEN_ROOTS))
        for p in files
    }
    assert {k: v for k, v in bad.items() if v} == {}


def test_a7_crop_module_exists_and_has_only_allowed_imports():
    """A7: `crop.py` существует (красный до реализации) и не импортирует запрещённые слои (AST)."""
    crop = _LAYER_RENDER / "crop.py"
    assert crop.is_file()
    assert [m for m in _imported_modules(crop) if m.startswith(_FORBIDDEN_ROOTS)] == []
