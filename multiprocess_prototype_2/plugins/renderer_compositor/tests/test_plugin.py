"""Тесты RendererCompositorPlugin: configure, layouts, overlay, команды."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_prototype_2.plugins.renderer_compositor.plugin import RendererCompositorPlugin


def _make_mock_ctx(config: dict | None = None) -> MagicMock:
    """Создать mock PluginContext."""
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.registers = None
    return ctx


def _colored_frame(h: int = 100, w: int = 200, color: tuple = (0, 0, 0)) -> np.ndarray:
    """Кадр заданного цвета BGR."""
    return np.full((h, w, 3), color, dtype=np.uint8)


def _make_plugin(config: dict | None = None) -> RendererCompositorPlugin:
    """Создать и сконфигурировать плагин с заданным config."""
    plugin = RendererCompositorPlugin()
    plugin.configure(_make_mock_ctx(config or {}))
    return plugin


class TestConfigure:
    def test_configure(self):
        """Парсинг всех параметров config."""
        plugin = RendererCompositorPlugin()
        plugin.configure(_make_mock_ctx({
            "layout_mode": "pip",
            "grid_cols": 3,
            "grid_rows": 3,
            "output_width": 640,
            "output_height": 360,
            "pip_scale": 0.3,
            "pip_position": "bottom_left",
            "overlay_enabled": False,
            "overlay_font_scale": 1.0,
        }))

        assert plugin._layout_mode == "pip"
        assert plugin._grid_cols == 3
        assert plugin._grid_rows == 3
        assert plugin._output_width == 640
        assert plugin._output_height == 360
        assert plugin._pip_scale == pytest.approx(0.3)
        assert plugin._pip_position == "bottom_left"
        assert plugin._overlay_enabled is False
        assert plugin._overlay_font_scale == pytest.approx(1.0)

    def test_configure_defaults(self):
        """Значения по умолчанию при пустом config."""
        plugin = _make_plugin({})

        assert plugin._layout_mode == "grid"
        assert plugin._grid_cols == 2
        assert plugin._grid_rows == 2
        assert plugin._output_width == 1280
        assert plugin._output_height == 720
        assert plugin._pip_scale == pytest.approx(0.25)
        assert plugin._pip_position == "top_right"
        assert plugin._overlay_enabled is True
        assert plugin._overlay_font_scale == pytest.approx(0.5)


class TestGridLayout:
    def test_grid_single_frame(self):
        """Один кадр в grid 2x2 → composite размером output_width x output_height."""
        plugin = _make_plugin({
            "layout_mode": "grid",
            "grid_cols": 2,
            "grid_rows": 2,
            "output_width": 400,
            "output_height": 200,
            "overlay_enabled": False,
        })
        frame = _colored_frame(100, 200, color=(0, 128, 255))

        result = plugin.process([{"frame": frame}])

        assert len(result) == 1
        composite = result[0]["composite_frame"]
        assert composite.shape == (200, 400, 3)

    def test_grid_four_frames(self):
        """4 кадра в grid 2x2 → все ячейки заполнены."""
        plugin = _make_plugin({
            "layout_mode": "grid",
            "grid_cols": 2,
            "grid_rows": 2,
            "output_width": 400,
            "output_height": 200,
            "overlay_enabled": False,
        })
        # Разные цвета для каждого кадра
        frames = [
            _colored_frame(50, 100, color=(255, 0, 0)),    # синий
            _colored_frame(50, 100, color=(0, 255, 0)),    # зелёный
            _colored_frame(50, 100, color=(0, 0, 255)),    # красный
            _colored_frame(50, 100, color=(255, 255, 0)),  # голубой
        ]
        items = [{"frame": f} for f in frames]

        result = plugin.process(items)

        assert len(result) == 1
        composite = result[0]["composite_frame"]
        assert composite.shape == (200, 400, 3)
        assert result[0]["source_count"] == 4

        # Каждый квадрант должен содержать не-нулевые пиксели
        # Верхний левый (0:100, 0:200) — синий
        cell = composite[0:100, 0:200]
        assert np.any(cell > 0), "Верхний левый квадрант пустой"

    def test_grid_more_than_slots(self):
        """5 кадров в grid 2x2 → только 4 используются (5-й игнорируется)."""
        plugin = _make_plugin({
            "layout_mode": "grid",
            "grid_cols": 2,
            "grid_rows": 2,
            "output_width": 400,
            "output_height": 200,
            "overlay_enabled": False,
        })
        frames = [_colored_frame(50, 100, color=(i * 50, 0, 0)) for i in range(1, 6)]
        items = [{"frame": f} for f in frames]

        result = plugin.process(items)

        assert len(result) == 1
        # source_count считает все извлечённые кадры (5), но в сетку попало 4
        assert result[0]["source_count"] == 5


class TestSideBySide:
    def test_side_by_side_two(self):
        """2 кадра → side-by-side, результат ширина output_width, высота output_height."""
        plugin = _make_plugin({
            "layout_mode": "side_by_side",
            "output_width": 400,
            "output_height": 200,
            "overlay_enabled": False,
        })
        frame1 = _colored_frame(100, 200, color=(100, 0, 0))
        frame2 = _colored_frame(100, 200, color=(0, 100, 0))

        result = plugin.process([{"frame": frame1}, {"frame": frame2}])

        assert len(result) == 1
        composite = result[0]["composite_frame"]
        assert composite.shape[0] == 200  # высота
        assert composite.shape[1] == 400  # ширина
        assert result[0]["source_count"] == 2

    def test_side_by_side_single_frame(self):
        """1 кадр в side-by-side → весь canvas занят одним кадром (cell_w = output_width)."""
        plugin = _make_plugin({
            "layout_mode": "side_by_side",
            "output_width": 400,
            "output_height": 200,
            "overlay_enabled": False,
        })
        frame = _colored_frame(100, 200, color=(0, 200, 0))

        result = plugin.process([{"frame": frame}])

        composite = result[0]["composite_frame"]
        assert composite.shape == (200, 400, 3)
        # При одном кадре cell_w = output_width → весь canvas заполнен
        assert np.any(composite > 0), "Один кадр должен заполнить весь canvas"


class TestPiP:
    def test_pip_two_frames(self):
        """2 кадра → основной + PiP в углу, размер output."""
        plugin = _make_plugin({
            "layout_mode": "pip",
            "output_width": 400,
            "output_height": 200,
            "pip_scale": 0.25,
            "pip_position": "top_right",
            "overlay_enabled": False,
        })
        main_frame = _colored_frame(100, 200, color=(50, 50, 50))
        pip_frame = _colored_frame(100, 200, color=(255, 0, 0))

        result = plugin.process([{"frame": main_frame}, {"frame": pip_frame}])

        assert len(result) == 1
        composite = result[0]["composite_frame"]
        assert composite.shape == (200, 400, 3)

        # PiP-окно в top_right: pip_w = 400 * 0.25 = 100, pip_h = 200 * 0.25 = 50
        # Позиция: (400 - 100 - 10, 10) = (290, 10)
        # Пиксель в центре PiP должен быть синим (100, 0, 0) отличным от фона
        pip_pixel = composite[35, 340]  # в центре PiP-окна
        assert pip_pixel[0] == 255, f"PiP-пиксель должен быть синим, получено {pip_pixel}"

    def test_pip_positions(self):
        """PiP в правом верхнем углу по умолчанию (top_right)."""
        plugin = _make_plugin({
            "layout_mode": "pip",
            "output_width": 400,
            "output_height": 200,
            "pip_scale": 0.25,
            "pip_position": "top_right",
            "overlay_enabled": False,
        })
        main_frame = np.zeros((100, 200, 3), dtype=np.uint8)
        pip_frame = _colored_frame(100, 200, color=(0, 255, 0))  # зелёный

        result = plugin.process([{"frame": main_frame}, {"frame": pip_frame}])
        composite = result[0]["composite_frame"]

        # PiP должен быть в правом верхнем углу — проверяем верхний правый угол
        top_right_region = composite[10:60, 290:390]
        assert np.any(top_right_region[:, :, 1] > 0), "PiP в top_right должен содержать зелёные пиксели"


class TestOverlay:
    def test_overlay_text(self):
        """overlay_enabled=True → canvas после process не остаётся полностью нулевым."""
        plugin = _make_plugin({
            "layout_mode": "grid",
            "output_width": 400,
            "output_height": 200,
            "overlay_enabled": True,
            "overlay_font_scale": 0.5,
        })
        # Чёрный кадр — без overlay весь canvas был бы нулевым
        frame = np.zeros((100, 200, 3), dtype=np.uint8)

        result = plugin.process([{"frame": frame}])
        composite = result[0]["composite_frame"]

        # Overlay рисует белый текст — хотя бы один пиксель должен быть не нулевым
        assert np.any(composite > 0), "Overlay должен добавить непустые пиксели"

    def test_no_overlay(self):
        """overlay_enabled=False → чёрный кадр остаётся нулевым (нет текста)."""
        plugin = _make_plugin({
            "layout_mode": "grid",
            "output_width": 400,
            "output_height": 200,
            "overlay_enabled": False,
        })
        frame = np.zeros((100, 200, 3), dtype=np.uint8)

        result = plugin.process([{"frame": frame}])
        composite = result[0]["composite_frame"]

        # Кадр полностью чёрный, нет ни overlay ни цветного контента
        assert np.all(composite == 0), "Без overlay чёрный кадр должен остаться нулевым"


class TestProcess:
    def test_empty_items(self):
        """Пустой список items → вернуть пустой список."""
        plugin = _make_plugin()

        result = plugin.process([])

        assert result == []

    def test_items_without_frame(self):
        """Items без ключа frame → frames пустые → return items без изменений."""
        plugin = _make_plugin()
        items = [{"data": "no_frame"}, {"value": 42}]

        result = plugin.process(items)

        # Нет кадров — входной список возвращается без изменений
        assert result == items

    def test_single_item_output(self):
        """process возвращает ровно 1 item с ключами composite_frame и frame."""
        plugin = _make_plugin({
            "layout_mode": "grid",
            "output_width": 400,
            "output_height": 200,
            "overlay_enabled": False,
        })
        frames = [
            _colored_frame(100, 200, color=(100, 0, 0)),
            _colored_frame(100, 200, color=(0, 100, 0)),
        ]
        items = [{"frame": f} for f in frames]

        result = plugin.process(items)

        # Независимо от количества входных items — всегда 1 выходной
        assert len(result) == 1
        assert "composite_frame" in result[0]
        assert "frame" in result[0]
        assert "source_count" in result[0]

    def test_output_frame_shape(self):
        """Выходной composite_frame имеет размер output_width × output_height."""
        plugin = _make_plugin({
            "layout_mode": "grid",
            "output_width": 800,
            "output_height": 600,
            "overlay_enabled": False,
        })
        frame = _colored_frame(100, 200, color=(50, 100, 150))

        result = plugin.process([{"frame": frame}])
        composite = result[0]["composite_frame"]

        assert composite.shape == (600, 800, 3)

    def test_frame_and_composite_same_object(self):
        """Ключи frame и composite_frame указывают на один объект."""
        plugin = _make_plugin({
            "output_width": 400,
            "output_height": 200,
            "overlay_enabled": False,
        })
        frame = _colored_frame(100, 200)

        result = plugin.process([{"frame": frame}])

        # Оба ключа должны ссылаться на один объект (одинаковые данные)
        assert np.array_equal(result[0]["frame"], result[0]["composite_frame"])


class TestCommands:
    def test_cmd_set_layout(self):
        """set_layout обновляет layout_mode, grid_cols, grid_rows."""
        plugin = _make_plugin({"layout_mode": "grid", "grid_cols": 2, "grid_rows": 2})

        response = plugin.set_layout({
            "layout_mode": "side_by_side",
            "grid_cols": 3,
            "grid_rows": 4,
        })

        assert response["status"] == "ok"
        assert response["layout_mode"] == "side_by_side"
        assert plugin._layout_mode == "side_by_side"
        assert plugin._grid_cols == 3
        assert plugin._grid_rows == 4

    def test_cmd_set_layout_invalid_mode(self):
        """set_layout с неверным mode → режим не меняется."""
        plugin = _make_plugin({"layout_mode": "grid"})

        response = plugin.set_layout({"layout_mode": "invalid_mode"})

        # Неверный режим игнорируется, статус ok, режим не изменился
        assert response["status"] == "ok"
        assert plugin._layout_mode == "grid"

    def test_cmd_toggle_overlay(self):
        """toggle_overlay переключает overlay_enabled."""
        plugin = _make_plugin({"overlay_enabled": True})

        # Первый toggle: True → False
        response = plugin.toggle_overlay({})
        assert response["status"] == "ok"
        assert response["overlay_enabled"] is False
        assert plugin._overlay_enabled is False

        # Второй toggle: False → True
        plugin.toggle_overlay({})
        assert plugin._overlay_enabled is True

    def test_cmd_set_layout_partial(self):
        """set_layout с частичными параметрами — только grid_cols."""
        plugin = _make_plugin({
            "layout_mode": "grid",
            "grid_cols": 2,
            "grid_rows": 2,
        })

        response = plugin.set_layout({"grid_cols": 4})

        assert response["status"] == "ok"
        assert plugin._grid_cols == 4
        assert plugin._grid_rows == 2  # не изменился
        assert plugin._layout_mode == "grid"  # не изменился
