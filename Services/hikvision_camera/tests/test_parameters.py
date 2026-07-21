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


class TestSetParametersReturnCodes:
    """A-8 (bug-hunt 2026-07-20): раньше коды возврата AcquisitionFrameRateEnable
    и ExposureAuto не проверялись вовсе — функция считалась успешной, даже
    если SDK эти вызовы отверг (камера оставалась в автоэкспозиции)."""

    def test_frame_rate_enable_error_returns_false(self):
        """SetBoolValue(AcquisitionFrameRateEnable) вернул код ошибки -> False."""
        from unittest.mock import MagicMock

        mock_camera = MagicMock()
        mock_camera.MV_CC_SetBoolValue.return_value = 0x80000004  # MV_E_PARAMETER
        params = CameraParameters(frame_rate=30.0, exposure_time=10000.0, gain=5.0)

        with (
            patch("Services.hikvision_camera.core.parameters.SDK_AVAILABLE", True),
            patch("Services.hikvision_camera.core.parameters.time.sleep"),
        ):
            result = set_parameters(mock_camera, params)

        assert result is False

    def test_exposure_auto_error_returns_false(self):
        """SetEnumValue(ExposureAuto) вернул код ошибки -> False (камера осталась в auto)."""
        from unittest.mock import MagicMock

        mock_camera = MagicMock()
        mock_camera.MV_CC_SetBoolValue.return_value = 0  # MV_OK
        mock_camera.MV_CC_SetEnumValue.return_value = 0x80000004  # MV_E_PARAMETER
        params = CameraParameters(frame_rate=30.0, exposure_time=10000.0, gain=5.0)

        with (
            patch("Services.hikvision_camera.core.parameters.SDK_AVAILABLE", True),
            patch("Services.hikvision_camera.core.parameters.time.sleep"),
        ):
            result = set_parameters(mock_camera, params)

        assert result is False

    def test_success_when_all_codes_ok(self):
        """Все коды возврата MV_OK -> True (фикс не ломает счастливый путь)."""
        from unittest.mock import MagicMock

        mock_camera = MagicMock()
        mock_camera.MV_CC_SetBoolValue.return_value = 0
        mock_camera.MV_CC_SetEnumValue.return_value = 0
        mock_camera.MV_CC_SetFloatValue.return_value = 0
        params = CameraParameters(frame_rate=30.0, exposure_time=10000.0, gain=5.0)

        with (
            patch("Services.hikvision_camera.core.parameters.SDK_AVAILABLE", True),
            patch("Services.hikvision_camera.core.parameters.time.sleep"),
        ):
            result = set_parameters(mock_camera, params)

        assert result is True
