# -*- coding: utf-8 -*-
"""Юнит-тесты волны C (Ф2 Task 2.5): исправленные сайты реально кормят health.

Репрезентативные сайты двух типов:
- hot-path обработки (circle_detector: HoughCircles падает → report_error + [] детекций);
- операционная загрузка (pixel_to_robot: битый файл калибровки → report_error + passthrough).

Мок ctx = MagicMock → ctx.health.report_error считает вызовы; проверяем и
contain (поведение сохранено), и report (счётчик health вырос).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np


def _make_mock_ctx(config: dict | None = None) -> MagicMock:
    """Mock PluginContext: log_* и health — MagicMock (считают вызовы)."""
    ctx = MagicMock()
    ctx.config = config or {}
    return ctx


class TestCircleDetectorHotPath:
    """HoughCircles упал → contain (пустые детекции) + report_error."""

    def test_hough_failure_reports_and_returns_empty(self):
        from Plugins.processing.circle_detector.plugin import CircleDetectorPlugin

        plugin = CircleDetectorPlugin()
        ctx = _make_mock_ctx({})
        plugin.configure(ctx)

        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        with patch("cv2.HoughCircles", side_effect=RuntimeError("Unknown C++ exception")):
            result = plugin.process([{"frame": frame}])

        # contain: пайплайн жив, item вернулся с пустыми детекциями
        assert isinstance(result, list) and len(result) == 1
        assert result[0].get("detections") == []
        # report: health получил ровно одну ошибку с контекстом сайта
        assert ctx.health.report_error.call_count == 1
        exc = ctx.health.report_error.call_args.args[0]
        assert isinstance(exc, RuntimeError)
        assert ctx.health.report_error.call_args.kwargs["context"] == "circle_detector.hough"

    def test_happy_path_does_not_report(self):
        from Plugins.processing.circle_detector.plugin import CircleDetectorPlugin

        plugin = CircleDetectorPlugin()
        ctx = _make_mock_ctx({})
        plugin.configure(ctx)

        result = plugin.process([{"frame": np.zeros((64, 64, 3), dtype=np.uint8)}])

        assert isinstance(result, list) and len(result) == 1
        assert ctx.health.report_error.call_count == 0


class TestPixelToRobotLoad:
    """Битый файл калибровки → contain (last_error, не падаем) + report_error."""

    def test_broken_calibration_reports(self):
        from Plugins.processing.pixel_to_robot.plugin import PixelToRobotPlugin

        plugin = PixelToRobotPlugin()
        ctx = _make_mock_ctx({"use_linear": False})
        with patch(
            "Plugins.calibration.camera_robot.store.load_calibration",
            side_effect=ValueError("кривой YAML"),
        ):
            plugin.configure(ctx)

        # contain: плагин сконфигурирован, ошибка в регистре, загрузки нет
        assert plugin._reg.loaded is False
        assert plugin._reg.last_error.startswith("load:")
        # report: health получил ошибку с контекстом сайта
        assert ctx.health.report_error.call_count == 1
        assert (
            ctx.health.report_error.call_args.kwargs["context"]
            == "pixel_to_robot.load_calibration"
        )
