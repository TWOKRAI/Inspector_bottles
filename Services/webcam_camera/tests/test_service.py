"""Smoke-тесты для WebcamCameraService.

Проверяют базовый контракт: start / stop / get_status / get_current_frame.
Реальная камера не открывается — cv2.VideoCapture подменяется моком.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from Services.webcam_camera.service import WebcamCameraService


class TestWebcamCameraServiceInit:
    """Тесты инициализации."""

    def test_initial_status_is_stopped(self):
        """После создания сервис находится в состоянии stopped."""
        svc = WebcamCameraService()
        assert svc.status == "stopped"

    def test_initial_config_is_empty(self):
        """После создания конфиг пустой."""
        svc = WebcamCameraService()
        assert svc.config == {}

    def test_name_constant(self):
        """Имя сервиса совпадает с ожидаемым идентификатором."""
        svc = WebcamCameraService()
        assert svc.name == "webcam_camera"

    def test_logger_defaults_to_none(self):
        """При создании без аргументов logger не установлен."""
        svc = WebcamCameraService()
        assert svc._logger is None

    def test_cap_initially_none(self):
        """После создания _cap равен None."""
        svc = WebcamCameraService()
        assert svc._cap is None


class TestWebcamCameraServiceStart:
    """Тесты метода start()."""

    def test_start_sets_status_running(self):
        """start() переводит статус в running."""
        svc = WebcamCameraService()
        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap_cls.return_value.isOpened.return_value = False
            svc.start({})
        assert svc.status == "running"

    def test_start_returns_true(self):
        """start() возвращает True."""
        svc = WebcamCameraService()
        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap_cls.return_value.isOpened.return_value = False
            result = svc.start({"device_id": 0})
        assert result is True

    def test_start_saves_config(self):
        """start() сохраняет переданный конфиг."""
        svc = WebcamCameraService()
        cfg = {"device_id": 1, "width": 1920, "height": 1080}
        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap_cls.return_value.isOpened.return_value = False
            svc.start(cfg)
        assert svc.config == cfg

    def test_start_with_empty_config(self):
        """start() принимает пустой конфиг без ошибок."""
        svc = WebcamCameraService()
        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap_cls.return_value.isOpened.return_value = False
            result = svc.start({})
        assert result is True
        assert svc.status == "running"

    def test_start_opens_cap_when_isopened_true(self):
        """start() устанавливает _cap когда VideoCapture.isOpened() → True."""
        svc = WebcamCameraService()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        with patch("cv2.VideoCapture", return_value=mock_cap):
            svc.start({"device_id": 0})
        assert svc._cap is mock_cap

    def test_start_leaves_cap_none_when_not_opened(self):
        """start() оставляет _cap=None если VideoCapture не открылась."""
        svc = WebcamCameraService()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False
        with patch("cv2.VideoCapture", return_value=mock_cap):
            svc.start({"device_id": 0})
        assert svc._cap is None

    def test_start_does_not_raise_on_cv2_exception(self):
        """start() не падает если VideoCapture бросает исключение."""
        svc = WebcamCameraService()
        with patch("cv2.VideoCapture", side_effect=RuntimeError("camera error")):
            result = svc.start({"device_id": 0})
        assert result is True
        assert svc.status == "running"
        assert svc._cap is None


class TestWebcamCameraServiceStop:
    """Тесты метода stop()."""

    def test_stop_sets_status_stopped(self):
        """stop() переводит статус обратно в stopped."""
        svc = WebcamCameraService()
        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap_cls.return_value.isOpened.return_value = False
            svc.start({})
        svc.stop()
        assert svc.status == "stopped"

    def test_stop_returns_true(self):
        """stop() возвращает True."""
        svc = WebcamCameraService()
        result = svc.stop()
        assert result is True

    def test_stop_idempotent(self):
        """Повторный stop() не вызывает ошибок, статус остаётся stopped."""
        svc = WebcamCameraService()
        svc.stop()
        svc.stop()
        assert svc.status == "stopped"

    def test_stop_releases_cap(self):
        """stop() вызывает release() на _cap и обнуляет его."""
        svc = WebcamCameraService()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        with patch("cv2.VideoCapture", return_value=mock_cap):
            svc.start({"device_id": 0})
        assert svc._cap is mock_cap

        svc.stop()

        mock_cap.release.assert_called_once()
        assert svc._cap is None

    def test_stop_when_cap_none_does_not_raise(self):
        """stop() не падает если _cap=None (камера не была открыта)."""
        svc = WebcamCameraService()
        assert svc._cap is None
        # Не должно бросить исключение
        svc.stop()
        assert svc.status == "stopped"


class TestWebcamCameraServiceGetStatus:
    """Тесты метода get_status()."""

    def test_get_status_returns_dict(self):
        """get_status() возвращает словарь."""
        svc = WebcamCameraService()
        result = svc.get_status()
        assert isinstance(result, dict)

    def test_get_status_has_required_keys(self):
        """get_status() содержит ключи name, status, config."""
        svc = WebcamCameraService()
        result = svc.get_status()
        assert "name" in result
        assert "status" in result
        assert "config" in result

    def test_get_status_reflects_current_state(self):
        """get_status() отражает актуальное состояние после start/stop."""
        svc = WebcamCameraService()
        cfg = {"device_id": 0}

        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap_cls.return_value.isOpened.return_value = False
            svc.start(cfg)

        status_running = svc.get_status()
        assert status_running["status"] == "running"
        assert status_running["config"] == cfg
        assert status_running["name"] == "webcam_camera"

        svc.stop()
        status_stopped = svc.get_status()
        assert status_stopped["status"] == "stopped"


class TestWebcamCameraServiceLogger:
    """Тесты инъекции logger."""

    def test_logger_info_called_on_start(self):
        """start() вызывает logger.info при наличии логгера."""

        class _FakeLogger:
            def __init__(self):
                self.calls: list[str] = []

            def info(self, msg: str) -> None:
                self.calls.append(msg)

            def warning(self, msg: str) -> None:
                self.calls.append(msg)

        logger = _FakeLogger()
        svc = WebcamCameraService(logger=logger)
        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap_cls.return_value.isOpened.return_value = False
            svc.start({"device_id": 0})
        assert len(logger.calls) >= 1

    def test_logger_info_called_on_stop(self):
        """stop() вызывает logger.info при наличии логгера."""

        class _FakeLogger:
            def __init__(self):
                self.calls: list[str] = []

            def info(self, msg: str) -> None:
                self.calls.append(("info", msg))

            def warning(self, msg: str) -> None:
                self.calls.append(("warning", msg))

        logger = _FakeLogger()
        svc = WebcamCameraService(logger=logger)
        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap_cls.return_value.isOpened.return_value = False
            svc.start({})
        svc.stop()
        # start вызывает info/warning + stop вызывает info
        info_calls = [c for c in logger.calls if c[0] == "info"]
        assert len(info_calls) >= 1  # хотя бы stop() записал info

    def test_no_logger_no_error(self):
        """Без логгера start/stop работают без ошибок."""
        svc = WebcamCameraService()  # logger=None
        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap_cls.return_value.isOpened.return_value = False
            svc.start({"device_id": 0})
        svc.stop()
        assert svc.status == "stopped"


class TestGetCurrentFrame:
    """Тесты метода get_current_frame() — основная новая функциональность Phase 6."""

    def test_returns_none_when_stopped(self):
        """get_current_frame() возвращает None если статус stopped."""
        svc = WebcamCameraService()
        assert svc.status == "stopped"
        assert svc.get_current_frame() is None

    def test_returns_none_when_cap_none(self):
        """get_current_frame() возвращает None если _cap is None (даже при running)."""
        svc = WebcamCameraService()
        svc.status = "running"  # принудительно running
        svc._cap = None
        assert svc.get_current_frame() is None

    def test_returns_none_when_read_fails(self):
        """get_current_frame() → None если _cap.read() вернул ret=False."""
        svc = WebcamCameraService()
        mock_cap = MagicMock()
        mock_cap.read.return_value = (False, None)
        with patch("cv2.VideoCapture", return_value=mock_cap):
            mock_cap.isOpened.return_value = True
            svc.start({"device_id": 0})

        result = svc.get_current_frame()
        assert result is None

    def test_returns_frame_when_read_succeeds(self):
        """get_current_frame() → numpy array если _cap.read() вернул (True, frame)."""
        svc = WebcamCameraService()
        fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, fake_frame)

        with patch("cv2.VideoCapture", return_value=mock_cap):
            svc.start({"device_id": 0})

        result = svc.get_current_frame()
        assert result is not None
        assert result.shape == (480, 640, 3)

    def test_returns_none_after_stop(self):
        """После stop() get_current_frame() → None."""
        svc = WebcamCameraService()
        fake_frame = np.zeros((10, 10, 3), dtype=np.uint8)
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, fake_frame)

        with patch("cv2.VideoCapture", return_value=mock_cap):
            svc.start({"device_id": 0})

        # Пока running — возвращает кадр
        assert svc.get_current_frame() is not None

        svc.stop()
        # После stop — None
        assert svc.get_current_frame() is None

    def test_does_not_raise_on_cap_read_exception(self):
        """get_current_frame() не бросает исключение если _cap.read() упал."""
        svc = WebcamCameraService()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.side_effect = RuntimeError("camera disconnected")

        with patch("cv2.VideoCapture", return_value=mock_cap):
            svc.start({"device_id": 0})

        # Не должно бросить исключение
        result = svc.get_current_frame()
        assert result is None
