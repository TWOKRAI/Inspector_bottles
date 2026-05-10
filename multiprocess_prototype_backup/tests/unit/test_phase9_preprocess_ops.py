"""Unit-тесты для Preprocess-операций (Task 9.4)."""

from __future__ import annotations

import numpy as np
import pytest

from multiprocess_prototype.services.processor.operations.base import (
    ChainContext,
    ProcessingOperation,
)
from multiprocess_prototype.services.processor.operations.preprocess.resize_op import ResizeOp
from multiprocess_prototype.services.processor.operations.preprocess.color_convert_op import (
    ColorConvertOp,
)
from multiprocess_prototype.services.processor.operations.preprocess.clahe_op import ClaheOp
from multiprocess_prototype.services.processor.operations.preprocess.blur_op import BlurOp
from multiprocess_prototype.services.processor.operations.preprocess.threshold_op import (
    ThresholdOp,
)


def _make_ctx() -> ChainContext:
    return ChainContext()


def _bgr_frame(h: int = 100, w: int = 100) -> np.ndarray:
    """Создать тестовый BGR-кадр."""
    frame = np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)
    return frame


def _gray_frame(h: int = 100, w: int = 100) -> np.ndarray:
    """Создать тестовый grayscale-кадр."""
    return np.random.randint(0, 256, (h, w), dtype=np.uint8)


# ---------------------------------------------------------------------------
# ResizeOp
# ---------------------------------------------------------------------------


def test_resize_protocol_compliance():
    """ResizeOp реализует Protocol ProcessingOperation."""
    op = ResizeOp()
    assert isinstance(op, ProcessingOperation)


def test_resize_changes_dimensions():
    """Входной кадр 480×640×3 → после resize shape (240, 320, 3)."""
    op = ResizeOp()
    op.configure({"width": 320, "height": 240})
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = op.execute(frame, _make_ctx())
    assert result.shape == (240, 320, 3)


def test_resize_default_params():
    """ResizeOp с дефолтными params: width=640, height=480."""
    op = ResizeOp()
    op.configure({})
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    result = op.execute(frame, _make_ctx())
    assert result.shape == (480, 640, 3)


def test_resize_interpolation_options():
    """ResizeOp принимает все строковые значения интерполяции без ошибок."""
    for interp in ("nearest", "linear", "cubic", "area"):
        op = ResizeOp()
        op.configure({"width": 50, "height": 50, "interpolation": interp})
        frame = _bgr_frame(100, 100)
        result = op.execute(frame, _make_ctx())
        assert result.shape == (50, 50, 3), f"Ошибка для interpolation={interp}"


# ---------------------------------------------------------------------------
# ColorConvertOp
# ---------------------------------------------------------------------------


def test_color_convert_protocol_compliance():
    """ColorConvertOp реализует Protocol ProcessingOperation."""
    op = ColorConvertOp()
    assert isinstance(op, ProcessingOperation)


def test_color_convert_bgr2gray():
    """BGR-кадр → после bgr2gray выход 2D grayscale."""
    op = ColorConvertOp()
    op.configure({"mode": "bgr2gray"})
    frame = _bgr_frame(100, 100)
    result = op.execute(frame, _make_ctx())
    assert result.ndim == 2
    assert result.shape == (100, 100)


def test_color_convert_bgr2hsv():
    """BGR-кадр → после bgr2hsv выход 3-канальный HSV."""
    op = ColorConvertOp()
    op.configure({"mode": "bgr2hsv"})
    frame = _bgr_frame(50, 50)
    result = op.execute(frame, _make_ctx())
    assert result.ndim == 3
    assert result.shape == (50, 50, 3)


def test_color_convert_bgr2rgb():
    """BGR-кадр → после bgr2rgb каналы переставлены."""
    op = ColorConvertOp()
    op.configure({"mode": "bgr2rgb"})
    frame = _bgr_frame(50, 50)
    result = op.execute(frame, _make_ctx())
    assert result.shape == frame.shape


def test_color_convert_invalid_mode_warns():
    """gray2bgr на BGR-входе: предупреждение в context, кадр возвращается без изменений."""
    op = ColorConvertOp()
    op.configure({"mode": "gray2bgr"})  # ожидает 1-канальный вход
    frame = _bgr_frame(50, 50)  # BGR — 3 канала
    ctx = _make_ctx()
    result = op.execute(frame, ctx)
    # Кадр должен вернуться без изменений
    assert np.array_equal(result, frame)
    # Должно быть предупреждение
    assert len(ctx.warnings) >= 1
    assert "gray2bgr" in ctx.warnings[0]


def test_color_convert_gray2bgr():
    """Gray-кадр → после gray2bgr выход 3-канальный."""
    op = ColorConvertOp()
    op.configure({"mode": "gray2bgr"})
    frame = _gray_frame(50, 50)
    result = op.execute(frame, _make_ctx())
    assert result.ndim == 3
    assert result.shape == (50, 50, 3)


# ---------------------------------------------------------------------------
# ClaheOp
# ---------------------------------------------------------------------------


def test_clahe_protocol_compliance():
    """ClaheOp реализует Protocol ProcessingOperation."""
    op = ClaheOp()
    assert isinstance(op, ProcessingOperation)


def test_clahe_applies_to_gray_frame():
    """Gray-кадр → CLAHE сохраняет shape и dtype uint8."""
    op = ClaheOp()
    op.configure({"clip_limit": 2.0, "tile_grid_size": 8})
    frame = _gray_frame(64, 64)
    result = op.execute(frame, _make_ctx())
    assert result.shape == (64, 64)
    assert result.dtype == np.uint8


def test_clahe_applies_to_bgr_frame():
    """BGR-кадр → CLAHE по LAB, выход BGR с теми же размерами."""
    op = ClaheOp()
    op.configure({"clip_limit": 3.0, "tile_grid_size": 4})
    frame = _bgr_frame(64, 64)
    result = op.execute(frame, _make_ctx())
    assert result.shape == (64, 64, 3)
    assert result.dtype == np.uint8


def test_clahe_no_warnings_on_bgr():
    """BGR-вход для CLAHE не генерирует предупреждения — это нормальный режим."""
    op = ClaheOp()
    op.configure({})
    frame = _bgr_frame(32, 32)
    ctx = _make_ctx()
    op.execute(frame, ctx)
    assert ctx.warnings == []


# ---------------------------------------------------------------------------
# BlurOp
# ---------------------------------------------------------------------------


def test_blur_protocol_compliance():
    """BlurOp реализует Protocol ProcessingOperation."""
    op = BlurOp()
    assert isinstance(op, ProcessingOperation)


def test_blur_odd_kernel_no_warning():
    """Нечётный kernel_size — предупреждений нет."""
    op = BlurOp()
    op.configure({"kernel_size": 5, "sigma": 0.0})
    frame = _bgr_frame(50, 50)
    ctx = _make_ctx()
    result = op.execute(frame, ctx)
    assert result.shape == frame.shape
    assert ctx.warnings == []


def test_blur_kernel_size_coerces_even_to_odd():
    """Чётный kernel_size=4 → используется 5, предупреждение в context."""
    op = BlurOp()
    op.configure({"kernel_size": 4, "sigma": 0.0})
    frame = _bgr_frame(50, 50)
    ctx = _make_ctx()
    result = op.execute(frame, ctx)
    assert result.shape == frame.shape
    assert len(ctx.warnings) >= 1
    assert "5" in ctx.warnings[0]


def test_blur_preserves_shape():
    """BlurOp не меняет shape кадра."""
    op = BlurOp()
    op.configure({"kernel_size": 7, "sigma": 1.5})
    frame = _bgr_frame(80, 120)
    result = op.execute(frame, _make_ctx())
    assert result.shape == frame.shape


# ---------------------------------------------------------------------------
# ThresholdOp
# ---------------------------------------------------------------------------


def test_threshold_protocol_compliance():
    """ThresholdOp реализует Protocol ProcessingOperation."""
    op = ThresholdOp()
    assert isinstance(op, ProcessingOperation)


def test_threshold_binary_produces_mask():
    """Gray-кадр → threshold binary → только значения 0 и max_value."""
    op = ThresholdOp()
    op.configure({"thresh_value": 128.0, "max_value": 255.0, "mode": "binary"})
    # Кадр с явными значениями ниже и выше порога
    frame = np.array([[50, 200], [100, 255]], dtype=np.uint8)
    ctx = _make_ctx()
    result = op.execute(frame, ctx)
    unique_values = set(result.flatten().tolist())
    assert unique_values.issubset({0, 255})
    assert ctx.warnings == []  # grayscale — без предупреждений


def test_threshold_bgr_input_warns():
    """ThresholdOp на BGR-входе — предупреждение в context."""
    op = ThresholdOp()
    op.configure({"thresh_value": 128.0, "max_value": 255.0, "mode": "binary"})
    frame = _bgr_frame(50, 50)
    ctx = _make_ctx()
    result = op.execute(frame, ctx)
    # Предупреждение о конвертации в grayscale
    assert len(ctx.warnings) >= 1
    # Результат — бинарная маска (2D)
    assert result.ndim == 2


def test_threshold_binary_inv():
    """mode='binary_inv' → значения инвертированы."""
    op = ThresholdOp()
    op.configure({"thresh_value": 128.0, "max_value": 255.0, "mode": "binary_inv"})
    frame = np.array([[50, 200]], dtype=np.uint8)
    result = op.execute(frame, _make_ctx())
    # 50 < 128 → при binary_inv → 255 (выше порога инвертируется)
    assert result[0, 0] == 255
    # 200 > 128 → при binary_inv → 0
    assert result[0, 1] == 0


def test_threshold_otsu_mode():
    """mode='otsu' не бросает исключений для grayscale-кадра."""
    op = ThresholdOp()
    op.configure({"thresh_value": 0.0, "max_value": 255.0, "mode": "otsu"})
    frame = _gray_frame(32, 32)
    result = op.execute(frame, _make_ctx())
    assert result.ndim == 2
    assert result.dtype == np.uint8
