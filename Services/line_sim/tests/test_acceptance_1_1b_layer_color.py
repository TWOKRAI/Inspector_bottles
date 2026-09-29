"""RED-приёмка Task 1.1b, блок B — заливка слоя цветом (`LayerSpec.color_rgb`).

Независимый тест (blind): пишется ДО реализации, по спеке `plans/line-sim-layer-editor/phase-1-engine.md`
(раздел Task 1.1b, критерии B1-B3). НЕ читает `Services/line_sim/core/*.py`.

B1/B2 идут через `ScenePreset` (Dict at Boundary) — `ScenePreset.layers[*].sprite_source`
обязан быть строкой-id уже сегодня (найдено при первом прогоне: raw ndarray там отклоняется
до всякого отношения к 1.1b), поэтому спрайты пишутся PNG-файлами в `tmp_path` и передаются
путём. B3 конструирует голый `LayerSpec` без `ScenePreset` — там сырой ndarray/`interfaces.py`
`SpriteSource = str | np.ndarray | Callable` подходит напрямую.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from Services.line_sim import ObjectFactory, ScenePreset
from Services.line_sim.interfaces import LayerAugment, LayerSpec


def _white_square(size: int = 20) -> np.ndarray:
    img = np.zeros((size, size, 4), dtype=np.uint8)
    img[:, :, 0:3] = 255
    img[:, :, 3] = 255
    return img


def _black_square(size: int = 20) -> np.ndarray:
    img = np.zeros((size, size, 4), dtype=np.uint8)
    img[:, :, 3] = 255
    return img


def _write_rgba_png(path: Path, rgba: np.ndarray) -> None:
    """Записать RGBA-массив на диск как BGRA (cv2.imwrite ждёт BGR(A))."""
    bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
    ok = cv2.imwrite(str(path), bgra)
    assert ok, f"cv2.imwrite не смог записать {path}"


def _center_rgb(frame: np.ndarray, offset_px: tuple[float, float] = (0.0, 0.0)) -> tuple[int, int, int]:
    """RGB в точке объект-центр + offset (объект-центр == центр массива render())."""
    cy = frame.shape[0] // 2 + int(round(offset_px[1]))
    cx = frame.shape[1] // 2 + int(round(offset_px[0]))
    return tuple(int(v) for v in frame[cy, cx, 0:3])


def test_color_fill_recolors_white_and_black_keeps_alpha(tmp_path: Path) -> None:
    """B1: color_rgb на белом диске и на чёрной букве — внутренние пиксели ±2; альфа как без заливки."""
    white_path = tmp_path / "white.png"
    black_path = tmp_path / "black.png"
    _write_rgba_png(white_path, _white_square())
    _write_rgba_png(black_path, _black_square())

    disk_plain = LayerSpec(name="disk", mode="static", sprite_source=str(white_path))
    disk_colored = LayerSpec(name="disk", mode="static", sprite_source=str(white_path), color_rgb=(255, 0, 0))
    preset_plain = ScenePreset(layers=[disk_plain], defect_probability=0.0, angle_range_deg=(0.0, 0.0))
    preset_colored = ScenePreset(layers=[disk_colored], defect_probability=0.0, angle_range_deg=(0.0, 0.0))

    frame_plain = ObjectFactory(preset_plain).make("o1", 0.0, np.random.default_rng(1)).render()
    frame_colored = ObjectFactory(preset_colored).make("o1", 0.0, np.random.default_rng(1)).render()

    r, g, b = _center_rgb(frame_colored)
    assert abs(r - 255) <= 2 and abs(g - 0) <= 2 and abs(b - 0) <= 2
    assert np.array_equal(frame_plain[:, :, 3], frame_colored[:, :, 3])

    letter_plain = LayerSpec(name="letter", mode="static", sprite_source=str(black_path))
    letter_colored = LayerSpec(name="letter", mode="static", sprite_source=str(black_path), color_rgb=(0, 0, 255))
    preset_letter_plain = ScenePreset(layers=[letter_plain], defect_probability=0.0, angle_range_deg=(0.0, 0.0))
    preset_letter_colored = ScenePreset(layers=[letter_colored], defect_probability=0.0, angle_range_deg=(0.0, 0.0))

    frame_letter_plain = ObjectFactory(preset_letter_plain).make("o1", 0.0, np.random.default_rng(1)).render()
    frame_letter_colored = ObjectFactory(preset_letter_colored).make("o1", 0.0, np.random.default_rng(1)).render()

    r2, g2, b2 = _center_rgb(frame_letter_colored)
    assert abs(r2 - 0) <= 2 and abs(g2 - 0) <= 2 and abs(b2 - 255) <= 2
    assert np.array_equal(frame_letter_plain[:, :, 3], frame_letter_colored[:, :, 3])


def test_color_fill_then_hue_shift_and_passport(tmp_path: Path) -> None:
    """B2: заливка (255,0,0) + hue_shift_deg=(120,120) -> (0,255,0) ±3; layer_params отражает это;
    у static-слоя с заливкой (255,0,0) в layer_params ровно [255, 0, 0] (без вариации)."""
    sprite_path = tmp_path / "white10.png"
    _write_rgba_png(sprite_path, _white_square(10))

    static_layer = LayerSpec(
        name="static_fill",
        mode="static",
        sprite_source=str(sprite_path),
        offset_px=(-15.0, 0.0),
        color_rgb=(255, 0, 0),
    )
    augmented_layer = LayerSpec(
        name="aug_fill",
        mode="augmented",
        sprite_source=str(sprite_path),
        offset_px=(15.0, 0.0),
        color_rgb=(255, 0, 0),
        augment=LayerAugment(hue_shift_deg=(120.0, 120.0)),
    )
    preset = ScenePreset(layers=[static_layer, augmented_layer], defect_probability=0.0, angle_range_deg=(0.0, 0.0))
    obj = ObjectFactory(preset).make("o1", 0.0, np.random.default_rng(2))
    frame = obj.render()

    r, g, b = _center_rgb(frame, offset_px=(15.0, 0.0))
    assert abs(r - 0) <= 3 and abs(g - 255) <= 3 and abs(b - 0) <= 3

    aug_color = obj.passport.layer_params["aug_fill"]["color_rgb"]
    assert abs(int(aug_color[0]) - 0) <= 3 and abs(int(aug_color[1]) - 255) <= 3 and abs(int(aug_color[2]) - 0) <= 3

    static_color = obj.passport.layer_params["static_fill"]["color_rgb"]
    assert list(static_color) == [255, 0, 0]


@pytest.mark.parametrize(
    "bad_color_rgb",
    [(256, 0, 0), (0, 0)],
    ids=["channel_256_out_of_range", "two_element_tuple"],
)
def test_color_rgb_validation(bad_color_rgb) -> None:
    """B3: color_rgb с каналом 256 или из двух чисел — ValidationError с именем слоя."""
    with pytest.raises(ValidationError) as exc_info:
        LayerSpec(name="bad_color_layer", mode="static", sprite_source=_white_square(), color_rgb=bad_color_rgb)

    assert "bad_color_layer" in str(exc_info.value)
