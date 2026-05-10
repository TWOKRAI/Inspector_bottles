"""Тесты backend'ов камеры: simulator, file, webcam mock, factory."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from Plugins.camera_service.backends import (
    CAMERA_TYPES,
    create_backend,
)
from Plugins.camera_service.backends.file_source import (
    FileSourceBackend,
)
from Plugins.camera_service.backends.simulator import (
    SimulatorBackend,
)
from Plugins.camera_service.backends.webcam import (
    WebcamBackend,
    _enum_webcam_devices,
)


# --- SimulatorBackend ---


class TestSimulatorLifecycle:
    """Тест жизненного цикла SimulatorBackend."""

    def test_simulator_lifecycle(self):
        """start → capture_frame → shape correct → stop → capture_frame → None."""
        backend = SimulatorBackend(width=320, height=240)

        # До start — None
        assert backend.capture_frame() is None

        # После start — кадр с правильной формой
        backend.start()
        frame = backend.capture_frame()
        assert frame is not None
        assert frame.shape == (240, 320, 3)
        assert frame.dtype == np.uint8

        # После stop — None
        backend.stop()
        assert backend.capture_frame() is None

    def test_simulator_timestamp_overlay(self):
        """capture_frame содержит timestamp overlay (пиксели не все чёрные в area)."""
        backend = SimulatorBackend(width=320, height=240)
        backend.start()
        frame = backend.capture_frame()
        assert frame is not None

        # Проверяем область где timestamp (верхний левый угол, y=10..40, x=0..200)
        # Там должны быть белые пиксели от текста
        ts_area = frame[5:40, 0:200]
        # Не все пиксели чёрные — есть текст
        assert ts_area.sum() > 0, "Timestamp overlay отсутствует — все пиксели чёрные"

        backend.close()

    def test_simulator_static_image(self):
        """С image_path — кадр НЕ чёрный (содержит изображение)."""
        # Создаём временное изображение
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name

        try:
            # Создаём цветное тестовое изображение
            test_img = np.full((100, 100, 3), 128, dtype=np.uint8)
            cv2.imwrite(tmp_path, test_img)

            backend = SimulatorBackend(width=100, height=100, image_path=tmp_path)
            backend.start()
            frame = backend.capture_frame()
            assert frame is not None
            # Кадр не должен быть полностью чёрным (есть изображение + timestamp)
            assert frame.sum() > 0, "Кадр полностью чёрный при использовании static image"
            backend.close()
        finally:
            os.unlink(tmp_path)


# --- FileSourceBackend ---


class TestFileSource:
    """Тесты FileSourceBackend."""

    def test_file_source_missing_file(self):
        """FileNotFoundError при start() если файл не найден."""
        backend = FileSourceBackend(file_path="/nonexistent/video.mp4")
        with pytest.raises(FileNotFoundError, match="файл не найден"):
            backend.start()

    def test_file_source_lifecycle(self):
        """Lifecycle с реальным temporary видеофайлом."""
        # Создаём временный видеофайл через cv2.VideoWriter
        with tempfile.NamedTemporaryFile(suffix=".avi", delete=False) as f:
            tmp_path = f.name

        try:
            # Записать 10 кадров
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            writer = cv2.VideoWriter(tmp_path, fourcc, 25.0, (64, 48))
            for i in range(10):
                frame = np.full((48, 64, 3), i * 20, dtype=np.uint8)
                writer.write(frame)
            writer.release()

            # Проверяем lifecycle
            backend = FileSourceBackend(file_path=tmp_path)
            backend.start()

            frame = backend.capture_frame()
            assert frame is not None
            assert frame.shape[2] == 3  # BGR

            backend.stop()
            # После stop — None
            assert backend.capture_frame() is None

            backend.close()
        finally:
            os.unlink(tmp_path)


# --- WebcamBackend (mock) ---


class TestWebcamMock:
    """Тесты WebcamBackend с mock cv2.VideoCapture."""

    def test_webcam_mock(self):
        """Mock cv2.VideoCapture — проверить start/capture/stop."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        mock_cap.read.return_value = (True, test_frame)

        backend = WebcamBackend(width=640, height=480, device_id=0)

        with patch("Plugins.camera_service.backends.webcam.cv2") as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            mock_cv2.CAP_DSHOW = 700
            mock_cv2.CAP_PROP_FRAME_WIDTH = 3
            mock_cv2.CAP_PROP_FRAME_HEIGHT = 4

            backend.start()
            assert backend._running is True

            frame = backend.capture_frame()
            assert frame is not None

            backend.stop()
            assert backend._running is False

            backend.close()
            assert backend._cap is None

    def test_webcam_enum_devices(self):
        """Mock cv2.VideoCapture для enum_devices."""
        mock_cap = MagicMock()
        # Первое устройство (индекс 0) — доступно, остальные — нет
        mock_cap.isOpened.side_effect = [True, False, False]

        with patch(
            "Plugins.camera_service.backends.webcam.cv2"
        ) as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            mock_cv2.CAP_DSHOW = 700

            result = _enum_webcam_devices(max_index=3)
            assert result["status"] == "ok"
            assert len(result["devices"]) == 1
            assert result["devices"][0]["index"] == 0


# --- Factory ---


class TestFactory:
    """Тест фабрики create_backend."""

    def test_factory_all_types(self):
        """create_backend для simulator, webcam, file (skip hikvision)."""
        # simulator
        backend = create_backend("simulator", width=320, height=240)
        assert isinstance(backend, SimulatorBackend)

        # webcam
        backend = create_backend("webcam", width=640, height=480, device_id=0)
        assert isinstance(backend, WebcamBackend)

        # file
        backend = create_backend("file", file_path="/tmp/test.avi")
        assert isinstance(backend, FileSourceBackend)

        # неизвестный тип → simulator (default)
        backend = create_backend("unknown_type", width=320, height=240)
        assert isinstance(backend, SimulatorBackend)

    def test_camera_types_constant(self):
        """CAMERA_TYPES содержит все 4 типа."""
        assert "simulator" in CAMERA_TYPES
        assert "webcam" in CAMERA_TYPES
        assert "hikvision" in CAMERA_TYPES
        assert "file" in CAMERA_TYPES
        assert len(CAMERA_TYPES) == 4
