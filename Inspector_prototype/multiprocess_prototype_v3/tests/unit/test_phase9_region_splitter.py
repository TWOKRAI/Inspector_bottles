"""Unit-тесты для RegionSplitterOp (Task 9.4)."""

from __future__ import annotations

import numpy as np
import pytest

from multiprocess_prototype_v3.services.processor.operations.base import (
    ChainContext,
    ProcessingOperation,
)
from multiprocess_prototype_v3.services.processor.operations.roi.region_splitter_op import (
    RegionSplitterOp,
)


def _make_ctx() -> ChainContext:
    return ChainContext()


def _solid_frame(h: int = 200, w: int = 200, color: tuple = (128, 128, 128)) -> np.ndarray:
    """Создать тестовый BGR-кадр с однородным цветом."""
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:] = color
    return frame


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


def test_region_splitter_protocol_compliance():
    """RegionSplitterOp реализует Protocol ProcessingOperation."""
    op = RegionSplitterOp()
    assert isinstance(op, ProcessingOperation)


# ---------------------------------------------------------------------------
# Основные сценарии
# ---------------------------------------------------------------------------


def test_region_splitter_two_regions():
    """Кадр 200×200 → два региона L (0,0,100,100) и R (100,0,100,100)."""
    op = RegionSplitterOp()
    op.configure({
        "regions": [
            {"name": "L", "x": 0, "y": 0, "width": 100, "height": 100},
            {"name": "R", "x": 100, "y": 0, "width": 100, "height": 100},
        ]
    })
    frame = _solid_frame(200, 200)
    result = op.execute_dag({"in": frame}, _make_ctx())

    assert "out_L" in result
    assert "out_R" in result
    assert result["out_L"].shape == (100, 100, 3)
    assert result["out_R"].shape == (100, 100, 3)


def test_region_splitter_clamps_out_of_bounds():
    """Регион (150, 150, 100, 100) на кадре 200×200 → crop 50×50."""
    op = RegionSplitterOp()
    op.configure({
        "regions": [
            {"name": "corner", "x": 150, "y": 150, "width": 100, "height": 100},
        ]
    })
    frame = _solid_frame(200, 200)
    result = op.execute_dag({"in": frame}, _make_ctx())

    assert "out_corner" in result
    # Реально доступная область: x=[150..200], y=[150..200] → 50×50
    assert result["out_corner"] is not None
    assert result["out_corner"].shape == (50, 50, 3)


def test_region_splitter_zero_area_returns_none():
    """Регион с нулевой площадью (width=0, height=0) → out_x is None."""
    op = RegionSplitterOp()
    op.configure({
        "regions": [
            {"name": "zero", "x": 0, "y": 0, "width": 0, "height": 0},
        ]
    })
    frame = _solid_frame(200, 200)
    result = op.execute_dag({"in": frame}, _make_ctx())

    assert "out_zero" in result
    assert result["out_zero"] is None


def test_region_splitter_no_input_returns_none_per_region():
    """execute_dag({"in": None}, ctx) → все out_* = None."""
    op = RegionSplitterOp()
    op.configure({
        "regions": [
            {"name": "A", "x": 0, "y": 0, "width": 100, "height": 100},
            {"name": "B", "x": 100, "y": 0, "width": 100, "height": 100},
        ]
    })
    result = op.execute_dag({"in": None}, _make_ctx())

    assert "out_A" in result
    assert "out_B" in result
    assert result["out_A"] is None
    assert result["out_B"] is None


def test_region_splitter_empty_regions():
    """Без регионов → пустой dict."""
    op = RegionSplitterOp()
    op.configure({"regions": []})
    frame = _solid_frame(200, 200)
    result = op.execute_dag({"in": frame}, _make_ctx())
    assert result == {}


def test_region_splitter_copy_is_independent():
    """Кроп — независимая копия, изменение не влияет на оригинал."""
    op = RegionSplitterOp()
    op.configure({
        "regions": [
            {"name": "X", "x": 0, "y": 0, "width": 50, "height": 50},
        ]
    })
    frame = _solid_frame(100, 100, color=(100, 100, 100))
    result = op.execute_dag({"in": frame}, _make_ctx())
    crop = result["out_X"]
    crop[:] = 0  # Меняем кроп
    # Оригинал должен остаться неизменным
    assert frame[0, 0, 0] == 100


def test_region_splitter_execute_fallback_returns_first_crop():
    """execute() (Protocol-fallback) возвращает первый ненулевой crop."""
    op = RegionSplitterOp()
    op.configure({
        "regions": [
            {"name": "first", "x": 0, "y": 0, "width": 60, "height": 60},
        ]
    })
    frame = _solid_frame(200, 200)
    result = op.execute(frame, _make_ctx())
    assert result.shape == (60, 60, 3)
