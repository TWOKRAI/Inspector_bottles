# multiprocess_prototype\tests\test_processor_mask_contours.py
"""
Тест ProcessorProcess: mask и contours в detection_result.

Проверяет, что _detect_color_blobs возвращает (detections, mask, contours)
и что mask имеет форму H×W×3, contours — list of np.ndarray.
"""

import numpy as np
import pytest


def test_detect_color_blobs_returns_mask_and_contours():
    """Processor._detect_color_blobs возвращает (detections, mask, contours)."""
    from multiprocess_prototype.backend.processes import ProcessorProcess

    # Минимальный mock shared_resources (без memory_manager для unit-теста)
    class MockSR:
        memory_manager = None
        get_process_state = lambda *a, **k: {}
        update_process_state = lambda *a, **k: None

    proc = ProcessorProcess("processor", shared_resources=MockSR(), config={
        "min_area": 100,
        "color_lower": [0, 0, 150],
        "color_upper": [100, 100, 255],
    })
    proc._min_area = 100
    proc._color_lower = np.array([0, 0, 150], dtype=np.uint8)
    proc._color_upper = np.array([100, 100, 255], dtype=np.uint8)

    # Кадр с красным пятном (BGR)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[200:250, 300:350, :] = [0, 0, 255]  # Красный в BGR

    detections, mask, contours = proc._detect_color_blobs(frame)

    assert isinstance(detections, list)
    assert isinstance(mask, np.ndarray)
    assert mask.shape == (480, 640, 3)
    assert mask.dtype == np.uint8
    assert isinstance(contours, list)
    # contours — list of np.ndarray
    for c in contours:
        assert isinstance(c, np.ndarray)
    # Должна быть хотя бы одна детекция (красное пятно)
    assert len(detections) >= 1
    assert "bbox" in detections[0]
    assert "center" in detections[0]
    assert "area" in detections[0]
