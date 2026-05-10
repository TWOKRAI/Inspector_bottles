"""Тесты RobotControlPlugin: configure, process(), команды."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from Plugins.control.robot_control.plugin import RobotControlPlugin


def _make_mock_ctx(config: dict | None = None) -> MagicMock:
    """Создать mock PluginContext."""
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.command_manager = MagicMock()
    return ctx


def _make_frame(h: int = 100, w: int = 100) -> np.ndarray:
    """Создать чёрный BGR-кадр для тестов."""
    return np.zeros((h, w, 3), dtype=np.uint8)


def _make_detection(area: int = 1600) -> dict:
    """Создать тестовую детекцию с заданной площадью."""
    return {"bbox": [10, 10, 50, 50], "center": [30, 30], "area": area}


class TestConfigure:
    def test_configure(self):
        """Парсинг параметров из ctx.config."""
        plugin = RobotControlPlugin()
        ctx = _make_mock_ctx({
            "enabled": False,
            "min_defect_area": 300,
            "reject_delay_ms": 50,
            "max_detections_for_reject": 3,
        })

        plugin.configure(ctx)

        assert plugin._reg.enabled is False
        assert plugin._reg.min_defect_area == 300
        assert plugin._reg.reject_delay_ms == 50
        assert plugin._reg.max_detections_for_reject == 3
        # Счётчики должны быть обнулены
        assert plugin._total_inspected == 0
        assert plugin._total_rejected == 0

    def test_configure_defaults(self):
        """Параметры по умолчанию применяются при пустом конфиге."""
        plugin = RobotControlPlugin()
        plugin.configure(_make_mock_ctx({}))

        assert plugin._reg.enabled is True
        assert plugin._reg.min_defect_area == 500
        assert plugin._reg.reject_delay_ms == 0
        assert plugin._reg.max_detections_for_reject == 0


class TestProcess:
    def test_pass_no_detections(self):
        """Нет детекций → action=pass."""
        plugin = RobotControlPlugin()
        plugin.configure(_make_mock_ctx({"min_defect_area": 500}))

        item = {"frame": _make_frame(), "detections": []}
        result = plugin.process([item])

        assert len(result) == 1
        assert result[0]["inspection_result"]["action"] == "pass"

    def test_pass_small_defects(self):
        """Детекции с area < min_defect_area → action=pass."""
        plugin = RobotControlPlugin()
        plugin.configure(_make_mock_ctx({"min_defect_area": 500}))

        # area=50 меньше порога 500
        item = {"frame": _make_frame(), "detections": [_make_detection(area=50)]}
        result = plugin.process([item])

        assert result[0]["inspection_result"]["action"] == "pass"
        assert result[0]["inspection_result"]["defect_count"] == 0

    def test_reject_large_defect(self):
        """Детекция с area >= min_defect_area → action=reject."""
        plugin = RobotControlPlugin()
        plugin.configure(_make_mock_ctx({"min_defect_area": 500}))

        # area=1000 >= 500
        item = {"frame": _make_frame(), "detections": [_make_detection(area=1000)]}
        result = plugin.process([item])

        assert result[0]["inspection_result"]["action"] == "reject"
        assert result[0]["inspection_result"]["defect_count"] == 1

    def test_reject_multiple_defects(self):
        """Несколько дефектов → reject, defect_count корректен."""
        plugin = RobotControlPlugin()
        plugin.configure(_make_mock_ctx({"min_defect_area": 500}))

        detections = [
            _make_detection(area=800),
            _make_detection(area=1200),
            _make_detection(area=600),
        ]
        item = {"frame": _make_frame(), "detections": detections}
        result = plugin.process([item])

        assert result[0]["inspection_result"]["action"] == "reject"
        assert result[0]["inspection_result"]["defect_count"] == 3

    def test_disabled(self):
        """enabled=False → всегда pass с reason=disabled."""
        plugin = RobotControlPlugin()
        plugin.configure(_make_mock_ctx({"enabled": False, "min_defect_area": 100}))

        # Даже крупный дефект не даёт reject при disabled
        item = {"frame": _make_frame(), "detections": [_make_detection(area=9999)]}
        result = plugin.process([item])

        assert result[0]["inspection_result"]["action"] == "pass"
        assert result[0]["inspection_result"]["reason"] == "disabled"

    def test_counters(self):
        """Счётчики total_inspected, total_rejected инкрементируются."""
        plugin = RobotControlPlugin()
        plugin.configure(_make_mock_ctx({"min_defect_area": 500}))

        # 3 вызова: 2 reject, 1 pass
        plugin.process([{"frame": _make_frame(), "detections": [_make_detection(area=1000)]}])
        plugin.process([{"frame": _make_frame(), "detections": []}])
        plugin.process([{"frame": _make_frame(), "detections": [_make_detection(area=800)]}])

        assert plugin._total_inspected == 3
        assert plugin._total_rejected == 2

    def test_reject_rate(self):
        """reject_rate вычисляется корректно."""
        plugin = RobotControlPlugin()
        plugin.configure(_make_mock_ctx({"min_defect_area": 500}))

        # 1 reject из 4 = 0.25
        plugin.process([{"frame": _make_frame(), "detections": [_make_detection(area=1000)]}])
        plugin.process([{"frame": _make_frame(), "detections": []}])
        plugin.process([{"frame": _make_frame(), "detections": []}])
        result = plugin.process([{"frame": _make_frame(), "detections": []}])

        rate = result[0]["inspection_result"]["reject_rate"]
        assert rate == 0.25

    def test_inspection_result_fields(self):
        """inspection_result содержит все обязательные поля."""
        plugin = RobotControlPlugin()
        plugin.configure(_make_mock_ctx({"min_defect_area": 500}))

        item = {"frame": _make_frame(), "detections": [_make_detection(area=1000)]}
        result = plugin.process([item])

        ir = result[0]["inspection_result"]
        assert "action" in ir
        assert "defect_count" in ir
        assert "total_inspected" in ir
        assert "total_rejected" in ir
        assert "reject_rate" in ir

    def test_max_detections_for_reject(self):
        """max_detections_for_reject ограничивает кол-во дефектов для анализа."""
        plugin = RobotControlPlugin()
        plugin.configure(_make_mock_ctx({
            "min_defect_area": 100,
            "max_detections_for_reject": 2,
        }))

        detections = [
            _make_detection(area=500),
            _make_detection(area=600),
            _make_detection(area=700),
        ]
        item = {"frame": _make_frame(), "detections": detections}
        result = plugin.process([item])

        # defect_count должен быть ограничен 2 (не 3)
        assert result[0]["inspection_result"]["defect_count"] == 2
        assert result[0]["inspection_result"]["action"] == "reject"

    def test_pass_preserves_frame(self):
        """Кадр передаётся в item без изменений."""
        plugin = RobotControlPlugin()
        plugin.configure(_make_mock_ctx({"min_defect_area": 500}))

        frame = _make_frame()
        item = {"frame": frame, "detections": []}
        result = plugin.process([item])

        # frame должен остаться тем же объектом
        assert result[0]["frame"] is frame


class TestCommands:
    def test_cmd_enable_disable(self):
        """enable/disable переключают enabled."""
        plugin = RobotControlPlugin()
        plugin.configure(_make_mock_ctx({"enabled": True}))

        # Отключаем
        resp = plugin.cmd_disable({})
        assert resp["status"] == "ok"
        assert plugin._reg.enabled is False

        # Включаем обратно
        resp = plugin.cmd_enable({})
        assert resp["status"] == "ok"
        assert plugin._reg.enabled is True

    def test_cmd_set_delay(self):
        """set_delay обновляет reject_delay_ms."""
        plugin = RobotControlPlugin()
        plugin.configure(_make_mock_ctx({}))

        resp = plugin.cmd_set_delay({"delay_ms": 150})
        assert resp["status"] == "ok"
        assert resp["delay_ms"] == 150
        assert plugin._reg.reject_delay_ms == 150

    def test_cmd_set_delay_negative_clamped(self):
        """Отрицательная задержка зажимается до 0."""
        plugin = RobotControlPlugin()
        plugin.configure(_make_mock_ctx({}))

        resp = plugin.cmd_set_delay({"delay_ms": -100})
        assert resp["delay_ms"] == 0
        assert plugin._reg.reject_delay_ms == 0

    def test_cmd_reset_counters(self):
        """reset_counters обнуляет счётчики."""
        plugin = RobotControlPlugin()
        plugin.configure(_make_mock_ctx({"min_defect_area": 500}))

        # Накопить статистику
        plugin.process([{"frame": _make_frame(), "detections": [_make_detection(area=1000)]}])
        plugin.process([{"frame": _make_frame(), "detections": [_make_detection(area=1000)]}])
        assert plugin._total_inspected == 2

        resp = plugin.cmd_reset_counters({})
        assert resp["status"] == "ok"
        assert plugin._total_inspected == 0
        assert plugin._total_rejected == 0

    def test_cmd_get_stats(self):
        """get_stats возвращает текущую статистику."""
        plugin = RobotControlPlugin()
        plugin.configure(_make_mock_ctx({"min_defect_area": 500}))

        # 2 inspected, 1 rejected
        plugin.process([{"frame": _make_frame(), "detections": [_make_detection(area=1000)]}])
        plugin.process([{"frame": _make_frame(), "detections": []}])

        resp = plugin.cmd_get_stats({})
        assert resp["status"] == "ok"
        assert resp["total_inspected"] == 2
        assert resp["total_rejected"] == 1
        assert resp["reject_rate"] == 0.5
