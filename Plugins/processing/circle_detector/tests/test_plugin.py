"""Тесты CircleDetectorPlugin: configure, process(), команды, режимы."""

from __future__ import annotations

from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from Plugins.processing.circle_detector.plugin import CircleDetectorPlugin


def _make_mock_ctx(config: dict | None = None) -> MagicMock:
    """Создать mock PluginContext."""
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.command_manager = MagicMock()
    return ctx


def _frame_with_circle(h: int = 200, w: int = 200, cx: int = 100, cy: int = 100, r: int = 40) -> np.ndarray:
    """Чёрный BGR-кадр с одной белой залитой окружностью."""
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.circle(frame, (cx, cy), r, (255, 255, 255), -1)
    return frame


class TestConfigure:
    def test_configure_defaults(self):
        """configure() без конфига → дефолты register."""
        plugin = CircleDetectorPlugin()
        plugin.configure(_make_mock_ctx({}))

        assert plugin._reg.mode == "gradient"
        assert plugin._reg.blur_method == "median"
        assert plugin._reg.dp == pytest.approx(1.2)
        assert plugin._reg.draw_circles is True

    def test_configure_overrides(self):
        """configure() парсит параметры из ctx.config."""
        plugin = CircleDetectorPlugin()
        plugin.configure(
            _make_mock_ctx(
                {
                    "mode": "gradient_alt",
                    "blur_method": "gaussian",
                    "blur_ksize": 7,
                    "dp": 2.0,
                    "min_dist": 50,
                    "param1": 120,
                    "param2": 0.9,
                    "min_radius": 10,
                    "max_radius": 80,
                    "draw_circles": False,
                }
            )
        )

        assert plugin._reg.mode == "gradient_alt"
        assert plugin._reg.blur_method == "gaussian"
        assert plugin._reg.blur_ksize == 7
        assert plugin._reg.dp == pytest.approx(2.0)
        assert plugin._reg.min_dist == 50
        assert plugin._reg.param1 == 120
        assert plugin._reg.param2 == pytest.approx(0.9)
        assert plugin._reg.min_radius == 10
        assert plugin._reg.max_radius == 80
        assert plugin._reg.draw_circles is False


class TestProcess:
    def test_process_no_frame(self):
        """item без frame → @for_each отбрасывает."""
        plugin = CircleDetectorPlugin()
        plugin.configure(_make_mock_ctx({}))

        assert plugin.process([{}]) == []

    def test_process_empty_frame(self):
        """Чёрный кадр без окружностей → detections пустой."""
        plugin = CircleDetectorPlugin()
        plugin.configure(_make_mock_ctx({"draw_circles": False}))

        frame = np.zeros((150, 150, 3), dtype=np.uint8)
        result = plugin.process([{"frame": frame}])

        assert len(result) == 1
        assert result[0]["detections"] == []

    def test_detect_single_circle(self):
        """Одна окружность r=40 → найдена; центр и радиус близки к истине."""
        plugin = CircleDetectorPlugin()
        plugin.configure(
            _make_mock_ctx(
                {
                    "blur_method": "gaussian",
                    "param1": 100,
                    "param2": 25,
                    "min_dist": 50,
                    "min_radius": 20,
                    "max_radius": 60,
                    "draw_circles": False,
                }
            )
        )

        frame = _frame_with_circle(cx=100, cy=100, r=40)
        result = plugin.process([{"frame": frame}])

        dets = result[0]["detections"]
        assert len(dets) >= 1
        # Берём детекцию с центром ближе всего к (100, 100)
        best = min(dets, key=lambda d: abs(d["center"][0] - 100) + abs(d["center"][1] - 100))
        assert abs(best["center"][0] - 100) <= 10
        assert abs(best["center"][1] - 100) <= 10
        assert abs(best["radius"] - 40) <= 12

    def test_detection_fields(self):
        """detection содержит center [x,y] и radius (int)."""
        plugin = CircleDetectorPlugin()
        plugin.configure(
            _make_mock_ctx(
                {
                    "param2": 25,
                    "min_dist": 50,
                    "min_radius": 20,
                    "max_radius": 60,
                    "draw_circles": False,
                }
            )
        )

        frame = _frame_with_circle()
        result = plugin.process([{"frame": frame}])
        dets = result[0]["detections"]

        assert dets, "ожидалась хотя бы одна окружность"
        det = dets[0]
        assert "center" in det and "radius" in det
        assert len(det["center"]) == 2
        assert isinstance(det["radius"], int)

    def test_draw_circles_modifies_frame(self):
        """draw_circles=True → кадр изменён."""
        plugin = CircleDetectorPlugin()
        plugin.configure(
            _make_mock_ctx(
                {
                    "param2": 25,
                    "min_dist": 50,
                    "min_radius": 20,
                    "max_radius": 60,
                    "draw_circles": True,
                    "circle_color_bgr": [0, 0, 255],
                }
            )
        )

        frame = _frame_with_circle()
        before = frame.copy()
        result = plugin.process([{"frame": frame}])

        assert not np.array_equal(before, result[0]["frame"])

    def test_gray_input_supported(self):
        """Одноканальный grayscale-кадр обрабатывается без ошибок."""
        plugin = CircleDetectorPlugin()
        plugin.configure(
            _make_mock_ctx(
                {
                    "param2": 25,
                    "min_dist": 50,
                    "min_radius": 20,
                    "max_radius": 60,
                    "draw_circles": False,
                }
            )
        )

        gray = np.zeros((200, 200), dtype=np.uint8)
        cv2.circle(gray, (100, 100), 40, 255, -1)
        result = plugin.process([{"frame": gray}])

        assert len(result) == 1
        assert isinstance(result[0]["detections"], list)


class TestBlurAndMode:
    @pytest.mark.parametrize("blur_method", ["median", "gaussian", "none"])
    def test_blur_methods(self, blur_method):
        """Все методы сглаживания отрабатывают без ошибок."""
        plugin = CircleDetectorPlugin()
        plugin.configure(_make_mock_ctx({"blur_method": blur_method, "draw_circles": False}))

        result = plugin.process([{"frame": _frame_with_circle()}])
        assert len(result) == 1

    def test_even_ksize_coerced_to_odd(self):
        """Чётный blur_ksize не ломает обработку (приводится к нечётному)."""
        plugin = CircleDetectorPlugin()
        plugin.configure(_make_mock_ctx({"blur_method": "median", "blur_ksize": 6, "draw_circles": False}))

        result = plugin.process([{"frame": _frame_with_circle()}])
        assert len(result) == 1

    def test_gradient_alt_mode(self):
        """Режим gradient_alt отрабатывает (или fallback на классический)."""
        plugin = CircleDetectorPlugin()
        plugin.configure(
            _make_mock_ctx(
                {
                    "mode": "gradient_alt",
                    "param1": 300,
                    "param2": 0.85,
                    "min_dist": 50,
                    "min_radius": 20,
                    "max_radius": 60,
                    "draw_circles": False,
                }
            )
        )

        result = plugin.process([{"frame": _frame_with_circle()}])
        assert len(result) == 1
        assert isinstance(result[0]["detections"], list)


class TestParamSafety:
    """Параметры, которые роняют cv2.HoughCircles в cv2.error, должны
    нормализоваться плагином (клампинг под режим), а не падать."""

    def test_alt_with_gradient_param2_does_not_crash(self):
        """gradient_alt + дефолтный param2=30 (валиден для gradient) → не падает."""
        plugin = CircleDetectorPlugin()
        plugin.configure(_make_mock_ctx({"mode": "gradient_alt", "param2": 30, "draw_circles": False}))

        result = plugin.process([{"frame": _frame_with_circle()}])
        assert len(result) == 1
        assert isinstance(result[0]["detections"], list)

    @pytest.mark.parametrize("mode", ["gradient", "gradient_alt"])
    @pytest.mark.parametrize("param2", [0, 0.5, 1.0, 1.5, 30, 300])
    def test_settable_param2_never_crashes(self, mode, param2):
        """Любое допустимое register'ом param2 (в т.ч. «чужое» для режима) → без cv2.error."""
        plugin = CircleDetectorPlugin()
        plugin.configure(_make_mock_ctx({"mode": mode, "param2": param2, "draw_circles": False}))

        result = plugin.process([{"frame": _frame_with_circle()}])
        assert len(result) == 1

    def test_out_of_range_command_is_graceful(self):
        """Команда с min_dist=0/param1=0 (вне диапазона register) → не падает,
        значения отклонены, register сохраняет валидные дефолты."""
        plugin = CircleDetectorPlugin()
        plugin.configure(_make_mock_ctx({"draw_circles": False}))
        default_min_dist = plugin._reg.min_dist

        resp = plugin.set_hough_params({"min_dist": 0, "param1": 0})

        assert resp["status"] == "partial"
        assert set(resp["rejected"]) == {"min_dist", "param1"}
        assert plugin._reg.min_dist == default_min_dist  # не изменилось

        # И обработка кадра по-прежнему работает
        assert len(plugin.process([{"frame": _frame_with_circle()}])) == 1

    def test_inverted_radius_range(self):
        """max_radius < min_radius → плагин меняет местами, не теряет круг."""
        plugin = CircleDetectorPlugin()
        plugin.configure(
            _make_mock_ctx(
                {
                    "param2": 25,
                    "min_dist": 50,
                    "min_radius": 60,
                    "max_radius": 20,
                    "draw_circles": False,
                }
            )
        )

        result = plugin.process([{"frame": _frame_with_circle(r=40)}])
        assert len(result) == 1
        assert isinstance(result[0]["detections"], list)


class TestCommands:
    def test_cmd_set_hough_params(self):
        plugin = CircleDetectorPlugin()
        plugin.configure(_make_mock_ctx({}))

        resp = plugin.set_hough_params({"dp": 1.5, "min_dist": 40, "param1": 120, "param2": 22})

        assert resp["status"] == "ok"
        assert plugin._reg.dp == pytest.approx(1.5)
        assert plugin._reg.min_dist == 40
        assert plugin._reg.param1 == 120
        assert plugin._reg.param2 == pytest.approx(22)

    def test_cmd_set_mode(self):
        plugin = CircleDetectorPlugin()
        plugin.configure(_make_mock_ctx({}))

        resp = plugin.set_mode({"mode": "gradient_alt", "blur_method": "gaussian"})

        assert resp["status"] == "ok"
        assert plugin._reg.mode == "gradient_alt"
        assert plugin._reg.blur_method == "gaussian"

    def test_cmd_set_radius_range(self):
        plugin = CircleDetectorPlugin()
        plugin.configure(_make_mock_ctx({}))

        resp = plugin.set_radius_range({"min_radius": 15, "max_radius": 90})

        assert resp["status"] == "ok"
        assert plugin._reg.min_radius == 15
        assert plugin._reg.max_radius == 90

    def test_cmd_toggle_draw(self):
        plugin = CircleDetectorPlugin()
        plugin.configure(_make_mock_ctx({"draw_circles": True}))

        assert plugin._reg.draw_circles is True
        assert plugin.toggle_draw_circles({})["draw_circles"] is False
        assert plugin.toggle_draw_circles({})["draw_circles"] is True


class TestInputKey:
    """input_key: детекция по 'frame' (дефолт) или 'mask' (бинарная маска от hsv_mask)."""

    @staticmethod
    def _mask_with_circle(h=200, w=200, cx=100, cy=100, r=40):
        """Одноканальная бинарная маска (uint8) с белым залитым кругом."""
        m = np.zeros((h, w), dtype=np.uint8)
        cv2.circle(m, (cx, cy), r, 255, -1)
        return m

    def test_default_is_frame(self):
        plugin = CircleDetectorPlugin()
        plugin.configure(_make_mock_ctx({}))
        assert plugin._reg.input_key == "frame"

    def test_detect_on_mask_drops_mask_keeps_frame(self):
        """input_key='mask': детекция по маске; маска дропается, цветной кадр не тронут."""
        plugin = CircleDetectorPlugin()
        plugin.configure(
            _make_mock_ctx(
                {
                    "input_key": "mask",
                    "param2": 25,
                    "min_dist": 50,
                    "min_radius": 20,
                    "max_radius": 60,
                    "draw_circles": True,
                }
            )
        )
        color = np.zeros((200, 200, 3), dtype=np.uint8)  # «чистый» цветной кадр
        result = plugin.process([{"frame": color, "mask": self._mask_with_circle()}])

        assert len(result) == 1
        assert len(result[0]["detections"]) >= 1
        assert "mask" not in result[0]  # маска потреблена (не гоним по IPC)
        assert "frame" in result[0]
        assert int(result[0]["frame"].sum()) == 0  # цветной кадр чист (draw на 1ch пропущен)

    def test_missing_input_key_skipped(self):
        """input_key='mask', а маски в item нет → @for_each отбрасывает."""
        plugin = CircleDetectorPlugin()
        plugin.configure(_make_mock_ctx({"input_key": "mask"}))
        assert plugin.process([{"frame": np.zeros((50, 50, 3), dtype=np.uint8)}]) == []

    def test_keep_mask_preserves_mask(self):
        """keep_mask=True: маска остаётся в выходе (для display-ветки)."""
        plugin = CircleDetectorPlugin()
        plugin.configure(_make_mock_ctx({"input_key": "mask", "keep_mask": True, "draw_circles": False}))
        color = np.zeros((200, 200, 3), dtype=np.uint8)
        result = plugin.process([{"frame": color, "mask": self._mask_with_circle()}])
        assert "mask" in result[0]  # не дропнута
