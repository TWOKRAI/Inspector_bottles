"""Тесты RenderOverlayPlugin: configure, process(), команды."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_prototype.plugins.render_overlay.plugin import RenderOverlayPlugin


def _make_mock_ctx(config: dict | None = None) -> MagicMock:
    """Создать mock PluginContext."""
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.command_manager = MagicMock()
    return ctx


def _black_frame(h: int = 100, w: int = 100) -> np.ndarray:
    """Чёрный BGR-кадр."""
    return np.zeros((h, w, 3), dtype=np.uint8)


def _white_frame(h: int = 100, w: int = 100) -> np.ndarray:
    """Белый BGR-кадр."""
    return np.full((h, w, 3), 255, dtype=np.uint8)


def _make_mask(h: int = 100, w: int = 100) -> np.ndarray:
    """Маска с белой областью (20:60, 20:60)."""
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[20:60, 20:60] = 255
    return mask


def _sample_detections() -> list[dict]:
    """Тестовые detections с bbox и area."""
    return [{"bbox": [50, 50, 100, 100], "center": [75, 75], "area": 2500}]


class TestConfigure:
    def test_configure(self):
        """Парсинг параметров: alpha, color, draw_detections."""
        plugin = RenderOverlayPlugin()
        ctx = _make_mock_ctx({
            "mask_alpha": 0.7,
            "mask_color_b": 128,
            "mask_color_g": 64,
            "mask_color_r": 32,
            "draw_detections": False,
            "line_thickness": 4,
            "label_font_scale": 0.8,
        })

        plugin.configure(ctx)

        assert plugin._reg.mask_alpha == pytest.approx(0.7)
        assert [plugin._reg.mask_color_b, plugin._reg.mask_color_g, plugin._reg.mask_color_r] == [128, 64, 32]
        assert plugin._reg.draw_detections is False
        assert plugin._reg.line_thickness == 4
        assert plugin._reg.label_font_scale == pytest.approx(0.8)

    def test_configure_defaults(self):
        """Значения по умолчанию без config."""
        plugin = RenderOverlayPlugin()
        plugin.configure(_make_mock_ctx({}))

        assert plugin._reg.mask_alpha == pytest.approx(0.5)
        assert [plugin._reg.mask_color_b, plugin._reg.mask_color_g, plugin._reg.mask_color_r] == [0, 255, 0]
        assert plugin._reg.draw_detections is True
        assert plugin._reg.line_thickness == 2
        assert plugin._reg.label_font_scale == pytest.approx(0.5)


class TestProcess:
    def test_process_no_frame(self):
        """item без frame → отфильтрован (пустой список)."""
        plugin = RenderOverlayPlugin()
        plugin.configure(_make_mock_ctx())

        result = plugin.process([{}])

        # @for_each фильтрует None — item отбрасывается
        assert result == []

    def test_process_frame_only(self):
        """Кадр без mask и detections → rendered_frame == frame.copy()."""
        plugin = RenderOverlayPlugin()
        plugin.configure(_make_mock_ctx())

        frame = _black_frame()
        result = plugin.process([{"frame": frame}])

        assert len(result) == 1
        rendered = result[0]["rendered_frame"]
        # Пиксельно совпадает с оригиналом
        assert np.array_equal(rendered, frame)

    def test_mask_overlay(self):
        """Маска с alpha blending — пиксели под маской изменены."""
        plugin = RenderOverlayPlugin()
        plugin.configure(_make_mock_ctx({
            "mask_alpha": 0.5,
            "mask_color_b": 0,
            "mask_color_g": 255,
            "mask_color_r": 0,
        }))

        # Чёрный кадр + маска в области (20:60, 20:60)
        frame = _black_frame(100, 100)
        mask = _make_mask(100, 100)

        result = plugin.process([{"frame": frame, "mask": mask}])
        rendered = result[0]["rendered_frame"]

        # Пиксели под маской: black*(0.5) + green*(0.5) ≈ (0, 127, 0)
        # Проверяем центральный пиксель маскированной области
        pixel = rendered[40, 40]
        assert pixel[1] > 100, f"Зелёный канал должен быть > 100, получено {pixel[1]}"
        assert pixel[0] == 0, f"Синий канал должен быть 0, получено {pixel[0]}"
        assert pixel[2] == 0, f"Красный канал должен быть 0, получено {pixel[2]}"

        # Пиксели вне маски не изменились (остаются чёрными)
        pixel_outside = rendered[5, 5]
        assert np.all(pixel_outside == 0)

    def test_mask_3d(self):
        """Маска (H, W, 1) обрабатывается корректно (squeeze до 2D)."""
        plugin = RenderOverlayPlugin()
        plugin.configure(_make_mock_ctx({
            "mask_alpha": 0.5,
            "mask_color_b": 0,
            "mask_color_g": 255,
            "mask_color_r": 0,
        }))

        frame = _black_frame(100, 100)
        # Маска с лишним измерением (H, W, 1)
        mask_2d = _make_mask(100, 100)
        mask_3d = mask_2d[:, :, np.newaxis]  # (100, 100, 1)

        result = plugin.process([{"frame": frame, "mask": mask_3d}])
        rendered = result[0]["rendered_frame"]

        # Пиксель под маской должен быть окрашен (зелёный канал > 0)
        pixel = rendered[40, 40]
        assert pixel[1] > 100

    def test_draw_bboxes(self):
        """draw_detections=True + detections → прямоугольники нарисованы."""
        plugin = RenderOverlayPlugin()
        plugin.configure(_make_mock_ctx({
            "draw_detections": True,
            "mask_color_b": 0,
            "mask_color_g": 255,
            "mask_color_r": 0,
            "line_thickness": 2,
        }))

        # Белый кадр 200x200, detection с bbox=[50, 50, 150, 150]
        frame = _white_frame(200, 200)
        detections = [{"bbox": [50, 50, 150, 150], "area": 10000}]

        result = plugin.process([{"frame": frame, "detections": detections}])
        rendered = result[0]["rendered_frame"]

        # На границе bbox (y=50, x=50..150) должен быть зелёный пиксель (0, 255, 0)
        # Белый кадр, рисуем зелёным — граница bbox будет зелёной
        bbox_pixels = rendered[50, 50:150]
        has_green = np.any(bbox_pixels[:, 1] == 255)
        assert has_green, "На границе bbox должны быть зелёные пиксели"

    def test_no_draw_bboxes(self):
        """draw_detections=False → detections игнорируются, кадр не изменён."""
        plugin = RenderOverlayPlugin()
        plugin.configure(_make_mock_ctx({
            "draw_detections": False,
        }))

        frame = _black_frame(200, 200)
        frame_copy = frame.copy()
        detections = _sample_detections()

        result = plugin.process([{"frame": frame, "detections": detections}])
        rendered = result[0]["rendered_frame"]

        # Без bounding boxes и без маски — rendered_frame равен оригиналу
        assert np.array_equal(rendered, frame_copy)

    def test_rendered_frame_is_copy(self):
        """rendered_frame — новый массив, оригинал не модифицирован."""
        plugin = RenderOverlayPlugin()
        plugin.configure(_make_mock_ctx())

        frame = _black_frame()
        original_data = frame.copy()

        result = plugin.process([{"frame": frame}])
        rendered = result[0]["rendered_frame"]

        # rendered_frame не разделяет память с оригиналом
        assert not np.shares_memory(frame, rendered)
        # Оригинальный кадр не изменился
        assert np.array_equal(frame, original_data)

    def test_mask_plus_detections(self):
        """Маска + detections одновременно → оба применены."""
        plugin = RenderOverlayPlugin()
        plugin.configure(_make_mock_ctx({
            "mask_alpha": 0.5,
            "mask_color_b": 0,
            "mask_color_g": 255,
            "mask_color_r": 0,
            "draw_detections": True,
            "line_thickness": 2,
        }))

        # Чёрный кадр 200x200
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        # Маска в верхнем левом квадранте
        mask = np.zeros((200, 200), dtype=np.uint8)
        mask[10:80, 10:80] = 255
        # Detection в нижнем правом квадранте (вне маски)
        detections = [{"bbox": [120, 120, 180, 180], "area": 3600}]

        result = plugin.process([{"frame": frame, "mask": mask, "detections": detections}])
        rendered = result[0]["rendered_frame"]

        # Пиксель под маской окрашен в зелёный
        pixel_under_mask = rendered[40, 40]
        assert pixel_under_mask[1] > 100

        # Граница bbox — зелёная линия на чёрном фоне
        bbox_border = rendered[120, 120:180]
        assert np.any(bbox_border[:, 1] == 255), "Bbox граница должна быть зелёной"


class TestCommands:
    def test_cmd_set_alpha(self):
        """set_alpha обновляет mask_alpha с clamp 0-1."""
        plugin = RenderOverlayPlugin()
        plugin.configure(_make_mock_ctx())

        # Нормальное значение
        response = plugin.set_alpha({"alpha": 0.8})
        assert response["status"] == "ok"
        assert response["alpha"] == pytest.approx(0.8)
        assert plugin._reg.mask_alpha == pytest.approx(0.8)

        # Clamp: > 1.0 → 1.0
        plugin.set_alpha({"alpha": 1.5})
        assert plugin._reg.mask_alpha == pytest.approx(1.0)

        # Clamp: < 0.0 → 0.0
        plugin.set_alpha({"alpha": -0.3})
        assert plugin._reg.mask_alpha == pytest.approx(0.0)

    def test_cmd_set_color(self):
        """set_color обновляет mask_color_b/g/r по ключам b, g, r."""
        plugin = RenderOverlayPlugin()
        plugin.configure(_make_mock_ctx())

        response = plugin.set_color({"b": 100, "g": 150, "r": 200})
        assert response["status"] == "ok"
        assert response["color_bgr"] == [100, 150, 200]
        assert [plugin._reg.mask_color_b, plugin._reg.mask_color_g, plugin._reg.mask_color_r] == [100, 150, 200]

        # Частичное обновление — только синий
        plugin.set_color({"b": 0})
        assert plugin._reg.mask_color_b == 0
        assert plugin._reg.mask_color_g == 150  # зелёный не изменился
        assert plugin._reg.mask_color_r == 200  # красный не изменился

        # Clamp: > 255 → 255
        plugin.set_color({"g": 300})
        assert plugin._reg.mask_color_g == 255

    def test_cmd_toggle_detections(self):
        """toggle_detections переключает bool draw_detections."""
        plugin = RenderOverlayPlugin()
        plugin.configure(_make_mock_ctx({"draw_detections": True}))

        assert plugin._reg.draw_detections is True

        response = plugin.toggle_detections({})
        assert response["status"] == "ok"
        assert response["draw_detections"] is False
        assert plugin._reg.draw_detections is False

        # Повторный toggle — снова True
        plugin.toggle_detections({})
        assert plugin._reg.draw_detections is True
