# -*- coding: utf-8 -*-
"""Тесты CameraParameters, get_parameters, set_parameters."""

from __future__ import annotations

from unittest.mock import patch

from Services.hikvision_camera.core.parameters import (
    CameraParameters,
    get_parameters,
    set_parameters,
)


class TestCameraParameters:
    """Тесты dataclass CameraParameters."""

    def test_creation_with_defaults(self):
        """CameraParameters создаётся с дефолтными значениями."""
        params = CameraParameters()

        assert params.frame_rate == 0.0
        assert params.exposure_time == 0.0
        assert params.gain == 0.0

    def test_creation_with_values(self):
        """CameraParameters хранит переданные значения."""
        params = CameraParameters(
            frame_rate=30.0,
            exposure_time=10000.0,
            gain=5.5,
        )

        assert params.frame_rate == 30.0
        assert params.exposure_time == 10000.0
        assert params.gain == 5.5

    def test_is_mutable(self):
        """CameraParameters — НЕ frozen (можно менять поля)."""
        params = CameraParameters()
        params.frame_rate = 60.0

        assert params.frame_rate == 60.0


class TestGetParameters:
    """Тесты функции get_parameters."""

    def test_get_parameters_none_camera(self):
        """None вместо camera → None."""
        result = get_parameters(None)
        assert result is None

    def test_get_parameters_no_sdk(self):
        """SDK недоступен → None."""
        from unittest.mock import MagicMock

        mock_camera = MagicMock()
        with patch("Services.hikvision_camera.core.parameters.SDK_AVAILABLE", False):
            result = get_parameters(mock_camera)

        assert result is None


class TestSetParameters:
    """Тесты функции set_parameters."""

    def test_set_parameters_none_camera(self):
        """None вместо camera → False."""
        params = CameraParameters(frame_rate=30.0, exposure_time=10000.0, gain=5.0)
        result = set_parameters(None, params)
        assert result is False

    def test_set_parameters_no_sdk(self):
        """SDK недоступен → False."""
        from unittest.mock import MagicMock

        mock_camera = MagicMock()
        params = CameraParameters(frame_rate=30.0, exposure_time=10000.0, gain=5.0)

        with patch("Services.hikvision_camera.core.parameters.SDK_AVAILABLE", False):
            result = set_parameters(mock_camera, params)

        assert result is False
