"""Тесты BlobDetectorPlugin: configure, process(), команды."""

from __future__ import annotations

from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from multiprocess_prototype_2.plugins.blob_detector.plugin import BlobDetectorPlugin


def _make_mock_ctx(config: dict | None = None) -> MagicMock:
    """Создать mock PluginContext."""
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.command_manager = MagicMock()
    return ctx


def _white_blob_config(**kwargs) -> dict:
    """Конфиг для детекции белых областей (s_min=0, v_min=200)."""
    base = {
        "h_min": 0, "h_max": 180,
        "s_min": 0, "s_max": 255,
        "v_min": 200, "v_max": 255,
        "min_area": 10,
        "max_area": 0,
        "draw_contours": False,
    }
    base.update(kwargs)
    return base


def _make_black_frame(h: int = 200, w: int = 200) -> np.ndarray:
    """Создать чёрный BGR-кадр заданного размера."""
    return np.zeros((h, w, 3), dtype=np.uint8)


class TestConfigure:
    def test_configure(self):
        """plugin.configure() парсит все параметры из ctx.config."""
        plugin = BlobDetectorPlugin()
        ctx = _make_mock_ctx({
            "h_min": 10, "h_max": 170,
            "s_min": 30, "s_max": 200,
            "v_min": 40, "v_max": 220,
            "min_area": 50,
            "max_area": 5000,
            "draw_contours": True,
            "contour_color_bgr": [255, 0, 0],
            "contour_thickness": 3,
        })

        plugin.configure(ctx)

        assert plugin._lower.tolist() == [10, 30, 40]
        assert plugin._upper.tolist() == [170, 200, 220]
        assert plugin._min_area == 50
        assert plugin._max_area == 5000
        assert plugin._draw_contours is True
        assert plugin._contour_color == [255, 0, 0]
        assert plugin._contour_thickness == 3


class TestProcess:
    def test_process_no_frame(self):
        """item без ключа frame → @for_each отбрасывает (пустой список)."""
        plugin = BlobDetectorPlugin()
        plugin.configure(_make_mock_ctx(_white_blob_config()))

        result = plugin.process([{}])
        # @for_each фильтрует None — item отбрасывается
        assert result == []

    def test_process_black_frame(self):
        """Чёрный кадр при s_min=50 → detections пустой."""
        plugin = BlobDetectorPlugin()
        # Чёрный кадр имеет s=0, v=0 → не попадёт под s_min=50
        plugin.configure(_make_mock_ctx({
            "h_min": 0, "h_max": 180,
            "s_min": 50, "s_max": 255,
            "v_min": 50, "v_max": 255,
            "min_area": 10,
            "max_area": 0,
        }))

        frame = _make_black_frame(100, 100)
        result = plugin.process([{"frame": frame}])

        assert len(result) == 1
        assert result[0]["detections"] == []

    def test_detect_single_blob(self):
        """Белый прямоугольник 30x30 на чёрном кадре → 1 detection."""
        plugin = BlobDetectorPlugin()
        plugin.configure(_make_mock_ctx(_white_blob_config(min_area=10)))

        frame = _make_black_frame(200, 200)
        # Белый прямоугольник (50,50)-(80,80) — 30x30 пикселей
        cv2.rectangle(frame, (50, 50), (80, 80), (255, 255, 255), -1)

        result = plugin.process([{"frame": frame}])

        assert len(result) == 1
        assert len(result[0]["detections"]) == 1

    def test_detect_multiple_blobs(self):
        """Три белых прямоугольника → 3 detections."""
        plugin = BlobDetectorPlugin()
        plugin.configure(_make_mock_ctx(_white_blob_config(min_area=10)))

        frame = _make_black_frame(300, 300)
        # Три прямоугольника в разных углах кадра
        cv2.rectangle(frame, (10, 10), (40, 40), (255, 255, 255), -1)
        cv2.rectangle(frame, (130, 10), (160, 40), (255, 255, 255), -1)
        cv2.rectangle(frame, (10, 130), (40, 160), (255, 255, 255), -1)

        result = plugin.process([{"frame": frame}])

        assert len(result[0]["detections"]) == 3

    def test_detection_fields(self):
        """Проверить bbox, center, area в detection."""
        plugin = BlobDetectorPlugin()
        plugin.configure(_make_mock_ctx(_white_blob_config(min_area=10)))

        frame = _make_black_frame(200, 200)
        # Прямоугольник (50,50)-(80,80): ширина=30, высота=30
        cv2.rectangle(frame, (50, 50), (80, 80), (255, 255, 255), -1)

        result = plugin.process([{"frame": frame}])
        det = result[0]["detections"][0]

        assert "bbox" in det
        assert "center" in det
        assert "area" in det
        # bbox = [x1, y1, x2, y2]
        assert len(det["bbox"]) == 4
        # center примерно [65, 65]
        assert abs(det["center"][0] - 65) <= 1
        assert abs(det["center"][1] - 65) <= 1
        # area ≈ 900 (30x30)
        assert det["area"] > 800

    def test_min_area_filter(self):
        """Маленький блоб 3x3 (area≈9) при min_area=100 → отфильтрован."""
        plugin = BlobDetectorPlugin()
        plugin.configure(_make_mock_ctx(_white_blob_config(min_area=100)))

        frame = _make_black_frame(100, 100)
        # Маленький прямоугольник 3x3
        cv2.rectangle(frame, (10, 10), (13, 13), (255, 255, 255), -1)

        result = plugin.process([{"frame": frame}])

        assert result[0]["detections"] == []

    def test_max_area_filter(self):
        """Большой блоб 100x100 при max_area=5000 → отфильтрован."""
        plugin = BlobDetectorPlugin()
        plugin.configure(_make_mock_ctx(_white_blob_config(min_area=10, max_area=5000)))

        frame = _make_black_frame(300, 300)
        # Большой прямоугольник 100x100 (area≈10000)
        cv2.rectangle(frame, (50, 50), (150, 150), (255, 255, 255), -1)

        result = plugin.process([{"frame": frame}])

        assert result[0]["detections"] == []

    def test_max_area_zero_no_filter(self):
        """max_area=0 → без ограничения, большой блоб проходит."""
        plugin = BlobDetectorPlugin()
        plugin.configure(_make_mock_ctx(_white_blob_config(min_area=10, max_area=0)))

        frame = _make_black_frame(300, 300)
        # Большой прямоугольник 100x100
        cv2.rectangle(frame, (50, 50), (150, 150), (255, 255, 255), -1)

        result = plugin.process([{"frame": frame}])

        assert len(result[0]["detections"]) == 1

    def test_draw_contours(self):
        """draw_contours=True → кадр изменён по сравнению с оригиналом."""
        plugin = BlobDetectorPlugin()
        plugin.configure(_make_mock_ctx(_white_blob_config(
            min_area=10, draw_contours=True, contour_color_bgr=[0, 0, 255]
        )))

        frame = _make_black_frame(200, 200)
        cv2.rectangle(frame, (50, 50), (80, 80), (255, 255, 255), -1)
        # Копируем до обработки
        frame_before = frame.copy()

        result = plugin.process([{"frame": frame}])
        frame_after = result[0]["frame"]

        # Кадр должен отличаться (нарисованы контуры)
        assert not np.array_equal(frame_before, frame_after)

    def test_mask_output(self):
        """item['mask'] — uint8 ndarray shape (H, W)."""
        plugin = BlobDetectorPlugin()
        plugin.configure(_make_mock_ctx(_white_blob_config(min_area=10)))

        frame = _make_black_frame(100, 100)

        result = plugin.process([{"frame": frame}])
        mask = result[0]["mask"]

        assert isinstance(mask, np.ndarray)
        assert mask.dtype == np.uint8
        assert mask.shape == (100, 100)


class TestCommands:
    def test_cmd_set_color_range(self):
        """set_color_range обновляет _lower и _upper."""
        plugin = BlobDetectorPlugin()
        plugin.configure(_make_mock_ctx({}))

        response = plugin.set_color_range({
            "h_min": 20, "h_max": 160,
            "s_min": 40, "s_max": 210,
            "v_min": 60, "v_max": 230,
        })

        assert response["status"] == "ok"
        assert plugin._lower.tolist() == [20, 40, 60]
        assert plugin._upper.tolist() == [160, 210, 230]

    def test_cmd_set_area_range(self):
        """set_area_range обновляет _min_area и _max_area."""
        plugin = BlobDetectorPlugin()
        plugin.configure(_make_mock_ctx({}))

        response = plugin.set_area_range({"min_area": 200, "max_area": 8000})

        assert response["status"] == "ok"
        assert plugin._min_area == 200
        assert plugin._max_area == 8000

    def test_cmd_toggle_draw(self):
        """toggle_draw_contours переключает _draw_contours."""
        plugin = BlobDetectorPlugin()
        plugin.configure(_make_mock_ctx({"draw_contours": False}))

        assert plugin._draw_contours is False

        response = plugin.toggle_draw_contours({})
        assert response["status"] == "ok"
        assert plugin._draw_contours is True

        plugin.toggle_draw_contours({})
        assert plugin._draw_contours is False
