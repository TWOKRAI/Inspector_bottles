# multiprocess_prototype\tests\test_processor_mask_contours.py
"""
Тест ColorBlobDetector: mask и contours в detection_result.

Проверяет, что detect возвращает (detections, mask, contours)
и что mask имеет форму H×W×3, contours — list of np.ndarray.
"""

import numpy as np

from multiprocess_prototype.backend.modules.processor_frame.detection import ColorBlobDetector


def test_detect_color_blobs_returns_mask_and_contours():
    """ColorBlobDetector.detect возвращает (detections, mask, contours)."""
    detector = ColorBlobDetector(
        [0, 0, 150],
        [100, 100, 255],
        min_area=100,
        max_area=50000,
    )

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[200:250, 300:350, :] = [0, 0, 255]

    detections, mask, contours = detector.detect(frame)

    assert isinstance(detections, list)
    assert isinstance(mask, np.ndarray)
    assert mask.shape == (480, 640, 3)
    assert mask.dtype == np.uint8
    assert isinstance(contours, list)
    for c in contours:
        assert isinstance(c, np.ndarray)
    assert len(detections) >= 1
    assert "bbox" in detections[0]
    assert "center" in detections[0]
    assert "area" in detections[0]
