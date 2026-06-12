"""Регрессионный тест н5/ADR-PH-001: GUI индикация устаревших данных по ts.

Контроллеры vfd/robot при обновлении из bindings проверяют возраст ts.
Если ts устарел (time.time() - ts > порога) — показывается stale/«нет связи
с hub», даже если quality поле говорит «good» (hub мог упасть).
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock


class TestVfdStalenessIndicator:
    """н5: VfdWidgetController показывает stale при устаревшем ts."""

    def _make_controller(self):
        """Создать VfdWidgetController с моками."""
        from multiprocess_prototype.frontend.widgets.tabs.services.vfd.controller import (
            VfdWidgetController,
            _STALE_THRESHOLD_S,
        )

        widget = MagicMock()
        presenter = MagicMock()
        controller = VfdWidgetController(widget, presenter)
        return controller, widget, _STALE_THRESHOLD_S

    def test_fresh_data_shows_good(self) -> None:
        """Свежие данные (ts < порога) → quality=good → 'Данные актуальны'."""
        controller, widget, _ = self._make_controller()
        controller._apply_vfd_status(
            {
                "quality": "good",
                "ts": time.time(),  # свежий
                "running": True,
                "out_freq_hz": 25.0,
                "current_a": 1.5,
                "dcbus_v": 300.0,
                "heartbeat": 42,
                "comm_errors": 0,
            }
        )
        # set_quality вызван с «актуальны»
        calls = [str(c) for c in widget.set_quality.call_args_list]
        assert any("актуальн" in c for c in calls)

    def test_stale_ts_shows_no_hub(self) -> None:
        """Устаревший ts → «нет связи с hub» даже при quality=good."""
        controller, widget, threshold = self._make_controller()
        controller._apply_vfd_status(
            {
                "quality": "good",  # hub замёрз с «good»
                "ts": time.time() - threshold - 1.0,  # устарел
                "running": True,
                "out_freq_hz": 10.0,
                "current_a": 0.5,
                "dcbus_v": 280.0,
                "heartbeat": 10,
                "comm_errors": 0,
            }
        )
        # set_quality вызван с «нет связи» / «устарели»
        calls = [str(c) for c in widget.set_quality.call_args_list]
        assert any("связи с hub" in c.lower() or "устарел" in c.lower() for c in calls)

    def test_no_ts_falls_through_to_quality(self) -> None:
        """Если ts отсутствует — работает по quality (обратная совместимость)."""
        controller, widget, _ = self._make_controller()
        controller._apply_vfd_status(
            {
                "quality": "bad",
                "running": False,
                "out_freq_hz": 0,
                "current_a": 0,
                "dcbus_v": 0,
                "comm_errors": 0,
            }
        )
        calls = [str(c) for c in widget.set_quality.call_args_list]
        assert any("Нет данных" in c for c in calls)


class TestRobotStalenessIndicator:
    """н5: RobotWidgetController показывает stale при устаревшем ts."""

    def _make_controller(self):
        """Создать RobotWidgetController с моками."""
        from multiprocess_prototype.frontend.widgets.tabs.services.robot.controller import (
            RobotWidgetController,
            _STALE_THRESHOLD_S,
        )

        widget = MagicMock()
        presenter = MagicMock()
        controller = RobotWidgetController(widget, presenter)
        return controller, widget, _STALE_THRESHOLD_S

    def test_fresh_data_shows_active(self) -> None:
        """Свежие данные → 'Связь с роботом активна'."""
        controller, widget, _ = self._make_controller()
        controller._apply_telemetry(
            {
                "ts": time.time(),
                "telemetry": {"x_mm": 0, "y_mm": 0, "z_mm": 0, "rz_deg": 0, "servo": True},
                "free": True,
                "encoder": 100,
                "queue_len": 0,
            }
        )
        calls = [str(c) for c in widget.set_status.call_args_list]
        assert any("активна" in c for c in calls)

    def test_stale_ts_shows_no_hub(self) -> None:
        """Устаревший ts → «нет связи с hub», mode_switch disabled."""
        controller, widget, threshold = self._make_controller()
        controller._apply_telemetry(
            {
                "ts": time.time() - threshold - 2.0,
                "telemetry": {"x_mm": 0, "y_mm": 0, "z_mm": 0, "rz_deg": 0, "servo": True},
                "free": True,
                "encoder": 100,
                "queue_len": 0,
            }
        )
        # set_status с «нет связи»
        calls = [str(c) for c in widget.set_status.call_args_list]
        assert any("связи с hub" in c.lower() or "устарел" in c.lower() for c in calls)
        # mode_switch выключен
        widget.set_mode_switch_enabled.assert_called_with(False)

    def test_no_ts_shows_telemetry(self) -> None:
        """Без ts — обычное отображение (обратная совместимость)."""
        controller, widget, _ = self._make_controller()
        controller._apply_telemetry(
            {
                "telemetry": {"x_mm": 1, "y_mm": 2, "z_mm": 3, "rz_deg": 4, "servo": False},
                "free": False,
                "encoder": 50,
                "queue_len": 1,
            }
        )
        calls = [str(c) for c in widget.set_status.call_args_list]
        assert any("активна" in c for c in calls)
