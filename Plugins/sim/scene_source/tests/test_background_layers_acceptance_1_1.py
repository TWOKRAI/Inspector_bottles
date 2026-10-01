# -*- coding: utf-8 -*-
"""Слепые acceptance-тесты Task 1.1 `layer-render`: ключ `background_layers` плагина `scene_source`.

Источник контракта: `plans/layer-render/phase-1.md`, Task 1.1 (DESIGN + Acceptance). Написаны ДО
реализации: ключа `background_layers` в `plugin.py` этого дерева нет (worktree на коммите «только план»).

ЗАПРЕЩЁННЫЕ ПУТИ (не читались): `.claude/worktrees/layer-render`, другие ветки, реализация Task 1.1 и
тесты автора. Готовая зависимость: `plugin.py` (ветка `background_texture`, 3.6), паттерны фикстур из
`test_scene_source_task_3_6.py` и `test_acceptance_lateral_offset_plugin.py` (копия, файл самодостаточен).

Кадр плагина — BGR. Файл картинки пишется в BGR(A), поэтому пиксель файла (b, g, r) приходит в кадр как
(b, g, r); цвет `solid` в конфиге — RGB, в кадре BGR он переставлен: `solid: [10, 20, 30]` -> (30, 20, 10).
"""

from __future__ import annotations

import hashlib
import os
import threading
import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from Plugins.sim.scene_source.plugin import SceneSourcePlugin
from Services.dataset_gen.core.catalog import imwrite_unicode

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEADLINE_S = 60.0


def _run_with_deadline(fn, deadline_s: float = _DEADLINE_S):
    box: dict = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "exc" in box:
        raise box["exc"]
    return box["value"]


class _FakeStateProxy:
    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []

    def subscribe(self, pattern, callback, exclude_self=True, sync=True):
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit(self, deltas: list[Delta]) -> None:
        for cb in self._callbacks:
            cb(deltas)

    def set(self, path: str, value: object) -> None:  # публикация паспортов — тесту не нужна
        pass


def _push_creation(sp: _FakeStateProxy, value: int) -> None:
    sp.emit([Delta(path="sim.belt.encoder", old_value=MISSING, new_value={"value": value, "t": 0.0}, source="robot")])


def _push_value(sp: _FakeStateProxy, value: int) -> None:
    sp.emit([Delta(path="sim.belt.encoder.value", old_value=None, new_value=value, source="robot")])


def _make_preset(tmp_path: Path) -> Path:
    """Каталог из одного класса (красный диск 25x25 на прозрачном) + YAML-пресет со случайным углом."""
    class_dir = tmp_path / "catalog" / "only_class"
    class_dir.mkdir(parents=True, exist_ok=True)
    size = 25
    sprite = np.zeros((size, size, 4), dtype=np.uint8)
    yy, xx = np.mgrid[0:size, 0:size]
    inside = (xx - size // 2) ** 2 + (yy - size // 2) ** 2 <= (size // 2) ** 2
    sprite[inside] = (0, 0, 255, 255)
    imwrite_unicode(class_dir / "sprite.png", sprite)
    preset = tmp_path / "preset.yaml"
    preset.write_text(
        "catalog_dir: catalog\nangle_range_deg: [0.0, 360.0]\nlayers: []\ndefect_probability: 0.0\n", encoding="utf-8"
    )
    return preset


def _cfg(tmp_path: Path, **overrides) -> dict:
    cfg = {
        "resolution_width": 160,
        "resolution_height": 120,
        "px_per_mm": 1.0,
        "belt_y_px": 60,
        "spawn_spacing_mm": [60.0, 60.0],
        "scene_length_mm": 1e9,
        "preset_path": str(_make_preset(tmp_path)),
        "seed": 7,
    }
    cfg.update(overrides)
    return cfg


def _build(cfg: dict) -> tuple[SceneSourcePlugin, _FakeStateProxy, MagicMock]:
    """configure + start; ValueError конфигурации обязан вылететь ЗДЕСЬ."""
    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.config = cfg
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, state_proxy, ctx


def _frames_sha(cfg: dict, steps: int = 6) -> str:
    """sha256 `steps` кадров плагина (энкодер 0, 500, 1000, ...) — объекты спавнятся и едут."""
    plugin, sp, _ctx = _build(cfg)
    digest = hashlib.sha256()
    _push_creation(sp, 0)
    for step in range(1, steps + 1):
        _push_value(sp, step * 500)
        digest.update(plugin.produce()[0]["frame"].tobytes())
    return digest.hexdigest()


def _write_rgb_tile(path: Path, th: int, tw: int, seed: int = 0) -> np.ndarray:
    """Пишет BGR-тайл в файл, возвращает массив ровно так, как он лежит в файле (BGR)."""
    tile = np.random.default_rng(seed).integers(0, 256, size=(th, tw, 3), dtype=np.uint8)
    imwrite_unicode(path, tile)
    return tile


def _first_frame(cfg: dict) -> np.ndarray:
    plugin, _sp, _ctx = _build(cfg)
    return plugin.produce()[0]["frame"]


def _uniform(frame: np.ndarray) -> tuple[int, int, int] | None:
    flat = frame.reshape(-1, 3)
    return tuple(int(v) for v in flat[0]) if (flat == flat[0]).all() else None


# --------------------------------------------------------------------------------------
# Без ключа — кадр байт в байт прежний (литералы сняты с кода ДО задачи)
# --------------------------------------------------------------------------------------

# Литералы сняты прогоном ЭТОГО набора на дереве до реализации (см. `_frames_sha`), не пересчитываются.
_GOLDEN_NO_BACKGROUND_KEY_SHA = "be289ebfa70a8a1e1084537293e1727a5337bcc62393983eb4ac125ba31b603e"
_GOLDEN_BACKGROUND_TEXTURE_SHA = "5dc6ff14006e6e3d707de4ec30dac05289410936a896875baa64fac63627709a"


def test_no_background_key_frames_are_byte_identical_to_pre_task(tmp_path):
    """[GREEN-контроль, обязан остаться зелёным] Конфиг без фоновых ключей — прежний серый фон + объекты."""
    assert _frames_sha(_cfg(tmp_path)) == _GOLDEN_NO_BACKGROUND_KEY_SHA


def test_background_texture_only_frames_are_byte_identical_to_pre_task(tmp_path):
    """[GREEN-контроль] Старый путь `background_texture` (ветка 3.6) — кадры не меняются."""
    texture = tmp_path / "tile.png"
    _write_rgb_tile(texture, th=40, tw=23)
    assert _frames_sha(_cfg(tmp_path, background_texture=str(texture))) == _GOLDEN_BACKGROUND_TEXTURE_SHA


# --------------------------------------------------------------------------------------
# Эквивалентность через плагин: layers [solid, tile] == background_texture, цвет RGB -> BGR
# --------------------------------------------------------------------------------------


def test_layers_solid_plus_tile_frames_equal_background_texture_frames_with_objects(tmp_path):
    """Тайл 120 строк при belt_y_px=60 закрывает кадр 160x120 целиком — заливка фона не видна, значит кадры
    (с движущимися объектами на 6 шагах энкодера) обязаны совпасть побайтно со старым ключом."""
    texture = tmp_path / "tile.png"
    _write_rgb_tile(texture, th=120, tw=23, seed=4)
    old = _frames_sha(_cfg(tmp_path / "old", background_texture=str(texture)))
    new = _frames_sha(_cfg(tmp_path / "new", background_layers=[{"solid": [10, 20, 30]}, {"tile": str(texture)}]))
    assert new == old


def test_layers_solid_outside_short_tile_is_rgb_config_color_in_bgr_frame(tmp_path):
    """Тайл 40 строк по центру кадра 120: выше и ниже — `solid: [10, 20, 30]` (RGB) -> в BGR-кадре (30, 20, 10)."""
    texture = tmp_path / "tile.png"
    tile_bgr = _write_rgb_tile(texture, th=40, tw=23, seed=2)
    frame = _first_frame(_cfg(tmp_path, background_layers=[{"solid": [10, 20, 30]}, {"tile": str(texture)}]))
    assert frame.shape == (120, 160, 3)
    assert _uniform(frame[:40]) == (30, 20, 10)  # tile top = 60 - 20 = 40
    assert _uniform(frame[80:]) == (30, 20, 10)
    # внутри полосы тайла видны пиксели файла (BGR как в файле), не залитые
    assert tuple(int(v) for v in frame[41, 0]) in {tuple(int(v) for v in tile_bgr[1, c]) for c in range(23)}


def test_layers_solid_only_fills_whole_frame_in_bgr(tmp_path):
    frame = _first_frame(_cfg(tmp_path, background_layers=[{"solid": [10, 20, 30]}]))
    assert _uniform(frame) == (30, 20, 10)


# --------------------------------------------------------------------------------------
# RGBA-тайл из файла: IMREAD_UNCHANGED, BGRA -> RGBA, прозрачный столбец
# --------------------------------------------------------------------------------------


def test_rgba_png_tile_transparent_column_is_black_over_black_solid(tmp_path):
    """Файл BGRA 4x4 (пиксель (200,10,30,255), столбец 2 с альфой 0 и ярким цветом) поверх solid [0,0,0]:
    в кадре BGR — (200,10,30) на непрозрачных, (0,0,0) на прозрачном столбце."""
    tile_bgra = np.zeros((4, 4, 4), dtype=np.uint8)
    tile_bgra[:, :] = (200, 10, 30, 255)
    tile_bgra[:, 2] = (255, 255, 255, 0)
    texture = tmp_path / "rgba.png"
    imwrite_unicode(texture, tile_bgra)
    cfg = _cfg(
        tmp_path,
        resolution_width=4,
        resolution_height=4,
        belt_y_px=2,
        background_layers=[{"solid": [0, 0, 0]}, {"tile": str(texture)}],
    )
    frame = _first_frame(cfg)
    assert frame.shape == (4, 4, 3)
    for row in range(4):
        assert tuple(int(v) for v in frame[row, 2]) == (0, 0, 0)
        for col in (0, 1, 3):
            assert tuple(int(v) for v in frame[row, col]) == (200, 10, 30), (row, col)


def test_tile_path_relative_to_repo_root_is_resolved(tmp_path, repo_texture_dir):
    """Путь `tile` — «от корня репо» (как `background_texture`/`preset_path`)."""
    tile_bgr = np.zeros((64, 64, 3), dtype=np.uint8)
    tile_bgr[:, :] = (200, 10, 30)
    texture = repo_texture_dir / "tile.png"
    imwrite_unicode(texture, tile_bgr)
    rel = os.path.relpath(texture, _REPO_ROOT)
    cfg = _cfg(
        tmp_path,
        resolution_width=64,
        resolution_height=64,
        belt_y_px=32,
        background_layers=[{"solid": [0, 0, 0]}, {"tile": rel}],
    )
    assert _uniform(_first_frame(cfg)) == (200, 10, 30)


# --------------------------------------------------------------------------------------
# Строка лога configure(): фон=слои[...]
# --------------------------------------------------------------------------------------


def _log_info_text(ctx: MagicMock) -> str:
    return "\n".join(str(call.args[0]) for call in ctx.log_info.call_args_list if call.args)


def test_configure_log_line_names_the_layers_with_tile_size_and_mode(tmp_path):
    """`фон=слои[solid(0,0,0), tile(<путь>, 410x484, RGBA)]` — тут тайл 7 шириной x 5 высотой, RGBA."""
    tile_bgra = np.full((5, 7, 4), 255, dtype=np.uint8)
    texture = tmp_path / "belt_log_tile.png"
    imwrite_unicode(texture, tile_bgra)
    _plugin, _sp, ctx = _build(_cfg(tmp_path, background_layers=[{"solid": [0, 0, 0]}, {"tile": str(texture)}]))
    text = _log_info_text(ctx)
    assert "фон=слои[solid(0,0,0), tile(" in text, text
    assert "belt_log_tile.png" in text, text
    assert ", 7x5, RGBA)]" in text, text


def test_configure_log_line_marks_rgb_tile_as_rgb(tmp_path):
    texture = tmp_path / "belt_rgb_tile.png"
    _write_rgb_tile(texture, th=5, tw=7)
    _plugin, _sp, ctx = _build(_cfg(tmp_path, background_layers=[{"tile": str(texture)}]))
    text = _log_info_text(ctx)
    assert "фон=слои[tile(" in text, text
    assert ", 7x5, RGB)]" in text, text


# --------------------------------------------------------------------------------------
# Ошибки конфигурации: ValueError выходит из configure() (вне try/except сборки движка)
# --------------------------------------------------------------------------------------

_BAD_LAYERS = [
    pytest.param([], id="empty_list"),
    pytest.param([{}], id="empty_dict"),
    pytest.param([{"solid": [0, 0, 0], "tile": "x.png"}], id="two_keys"),
    pytest.param([{"zq_fill": [0, 0, 0]}], id="unknown_key"),
    pytest.param([{"solid": [0, 0]}], id="color_len_2"),
    pytest.param([{"solid": [0, 0, 256]}], id="color_above_255"),
    pytest.param([{"solid": [0, 0, -1]}], id="color_negative"),
]


@pytest.mark.parametrize("bad", _BAD_LAYERS)
def test_bad_background_layers_schema_raises_valueerror_out_of_configure(tmp_path, bad):
    ctx = MagicMock()
    ctx.state_proxy = _FakeStateProxy()
    ctx.config = _cfg(tmp_path, background_layers=bad)
    plugin = SceneSourcePlugin()
    with pytest.raises(ValueError):
        plugin.configure(ctx)


def test_bad_item_index_is_named_in_the_error_from_configure(tmp_path):
    ctx = MagicMock()
    ctx.state_proxy = _FakeStateProxy()
    ctx.config = _cfg(tmp_path, background_layers=[{"solid": [0, 0, 0]}, {"solid": [0, 0, 999]}])
    plugin = SceneSourcePlugin()
    with pytest.raises(ValueError) as info:
        plugin.configure(ctx)
    text = str(info.value)
    assert "1" in text and "999" in text, text


def test_both_background_layers_and_background_texture_raise_valueerror_out_of_configure(tmp_path):
    texture = tmp_path / "tile.png"
    _write_rgb_tile(texture, th=10, tw=10)
    ctx = MagicMock()
    ctx.state_proxy = _FakeStateProxy()
    ctx.config = _cfg(tmp_path, background_layers=[{"solid": [0, 0, 0]}], background_texture=str(texture))
    plugin = SceneSourcePlugin()
    with pytest.raises(ValueError):
        plugin.configure(ctx)


# --------------------------------------------------------------------------------------
# Нечитаемая картинка слоя tile: 1 log_error, слой выброшен, движок жив
# --------------------------------------------------------------------------------------


def test_unreadable_tile_logs_exactly_one_error_and_produce_survives_10_calls(tmp_path):
    cfg = _cfg(
        tmp_path,
        background_layers=[{"solid": [10, 20, 30]}, {"tile": str(tmp_path / "missing_tile.png")}],
    )
    plugin, sp, ctx = _build(cfg)
    assert ctx.log_error.call_count == 1, f"ожидался ровно 1 log_error, вызовов: {ctx.log_error.call_count}"

    def ten_frames():
        frames = []
        for i in range(10):
            _push_value(sp, i * 300)
            frames.append(plugin.produce()[0]["frame"])
        return frames

    frames = _run_with_deadline(ten_frames)
    assert len(frames) == 10
    assert all(f.shape == (120, 160, 3) for f in frames)
    assert ctx.log_error.call_count == 1, "produce() не должен добавлять log_error по причине тайла"


def test_unreadable_tile_is_dropped_remaining_solid_layer_still_paints_the_background(tmp_path):
    frame = _first_frame(
        _cfg(tmp_path, background_layers=[{"solid": [10, 20, 30]}, {"tile": str(tmp_path / "missing_tile.png")}])
    )
    assert _uniform(frame) == (30, 20, 10)


def test_all_tile_layers_unreadable_gives_empty_stack_black_background_engine_alive(tmp_path):
    """Выброшены все слои -> стек пуст -> фон чёрный (а не серый fallback «движок недоступен»)."""
    cfg = _cfg(tmp_path, background_layers=[{"tile": str(tmp_path / "missing_tile.png")}])
    plugin, _sp, ctx = _build(cfg)
    assert ctx.log_error.call_count == 1
    frame = plugin.produce()[0]["frame"]
    assert _uniform(frame) == (0, 0, 0)
