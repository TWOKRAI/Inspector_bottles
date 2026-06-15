"""Тесты препроцессинга — формы, layout, нормализация, цветопорядок."""

from __future__ import annotations

import logging

import numpy as np
import pytest

from Services.ml_inference.core.model_spec import ModelSpec, Normalize
from Services.ml_inference.core.preprocess import letterbox, preprocess

# core/__init__ реэкспортит функцию preprocess, затеняя одноимённый модуль →
# до его namespace добираемся через __globals__ функции (для сброса dedup-кэша).
_PREPROCESS_NS = preprocess.__globals__


def _spec(**kw) -> ModelSpec:
    base = dict(name="t", weights_path="x.onnx", input_size=(224, 224))
    base.update(kw)
    return ModelSpec(**base)


def test_preprocess_nchw_shape():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    out = preprocess(frame, _spec(layout="NCHW"))
    assert out.shape == (1, 3, 224, 224)
    assert out.dtype == np.float32


def test_preprocess_nhwc_shape():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    out = preprocess(frame, _spec(layout="NHWC"))
    assert out.shape == (1, 224, 224, 3)


def test_normalization_applied():
    # белый кадр, mean=0 std=1 → значения 1.0 (255/255)
    frame = np.full((100, 100, 3), 255, dtype=np.uint8)
    spec = _spec(normalize=Normalize(mean=(0, 0, 0), std=(1, 1, 1)))
    out = preprocess(frame, spec)
    assert np.allclose(out, 1.0)


def test_color_swap_rgb():
    # кадр BGR с разными каналами → при color=RGB каналы переставлены
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frame[:, :, 0] = 255  # B
    spec = _spec(input_size=(10, 10), color="RGB", normalize=Normalize(mean=(0, 0, 0), std=(1, 1, 1)))
    out = preprocess(frame, spec, keep_aspect=False)  # NCHW (1,3,10,10)
    # после BGR→RGB синий канал (исходно индекс 0) попадает в R (индекс 2)
    assert np.allclose(out[0, 2], 1.0)
    assert np.allclose(out[0, 0], 0.0)


def test_letterbox_keeps_target_size():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    out = letterbox(frame, (224, 224))
    assert out.shape == (224, 224, 3)


def test_invalid_frame_raises():
    with pytest.raises(ValueError):
        preprocess(np.zeros((10, 10), dtype=np.uint8), _spec())


def test_stretch_nonsquare_warns_once(caplog):
    """stretch на НЕквадратном кадре искажает геометрию/угол → один warning на форму."""
    _PREPROCESS_NS["_WARNED_STRETCH_SHAPES"].clear()
    frame = np.zeros((90, 160, 3), dtype=np.uint8)  # 16:9, не квадрат
    spec = _spec(input_size=(128, 128), resize_policy="stretch")
    with caplog.at_level(logging.WARNING, logger="Services.ml_inference.core.preprocess"):
        out1 = preprocess(frame, spec)
        out2 = preprocess(frame, spec)  # та же форма → повторно НЕ логируем
    assert out1.shape == (1, 3, 128, 128)
    warnings = [r for r in caplog.records if "stretch" in r.message]
    assert len(warnings) == 1  # анти-спам: одна форма → один warning
    assert out2.shape == (1, 3, 128, 128)


def test_stretch_square_no_warn(caplog):
    """Квадратный вход под stretch — без предупреждения (геометрия не искажается)."""
    _PREPROCESS_NS["_WARNED_STRETCH_SHAPES"].clear()
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    spec = _spec(input_size=(128, 128), resize_policy="stretch")
    with caplog.at_level(logging.WARNING, logger="Services.ml_inference.core.preprocess"):
        preprocess(frame, spec)
    assert not [r for r in caplog.records if "stretch" in r.message]
