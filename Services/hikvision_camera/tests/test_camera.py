# -*- coding: utf-8 -*-
"""Тесты state machine HikvisionCamera (mock MvCamera, без реального SDK)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock

from hikvision_camera_module_2.core.camera import HikvisionCamera, CameraState


# ---------------------------------------------------------------------------
# Хелпер: подготовить camera с замоканным SDK
# ---------------------------------------------------------------------------

def _make_camera_with_mock_sdk(
    *,
    on_status: MagicMock | None = None,
    on_error: MagicMock | None = None,
) -> tuple[HikvisionCamera, MagicMock]:
    """Создать HikvisionCamera с замоканным MvCamera внутри.

    Возвращает (camera, mock_mv) — сам объект камеры и mock SDK-обёртки.
    Переводит камеру в состояние OPEN, чтобы тесты start_grabbing и capture
    не зависели от enum_devices.
    """
    status_cb = on_status or MagicMock()
    error_cb = on_error or MagicMock()

    cam = HikvisionCamera(on_status=status_cb, on_error=error_cb)

    # Подменяем внутренние поля, чтобы обойти реальный open()
    mock_mv = MagicMock()
    cam._camera = mock_mv
    cam._state = CameraState.OPEN

    return cam, mock_mv


class TestInitialState:
    """Тесты начального состояния."""

    def test_initial_state_closed(self):
        """Новая камера всегда в состоянии CLOSED."""
        cam = HikvisionCamera()
        assert cam.state == CameraState.CLOSED

    def test_initial_camera_index(self):
        """Начальный индекс камеры = 0."""
        cam = HikvisionCamera()
        assert cam.camera_index == 0


class TestOpenNoSdk:
    """Тесты open() без SDK."""

    def test_open_no_sdk(self):
        """SDK недоступен → open() возвращает False, остаётся CLOSED."""
        with patch(
            "hikvision_camera_module_2.core.camera.SDK_AVAILABLE", False
        ):
            error_cb = MagicMock()
            cam = HikvisionCamera(on_error=error_cb)
            result = cam.open(0)

        assert result is False
        assert cam.state == CameraState.CLOSED
        # Callback on_error должен быть вызван
        error_cb.assert_called_once()


class TestStateTransitions:
    """Тесты переходов state machine."""

    def test_open_to_grabbing_to_open_to_closed(self):
        """OPEN → start_grabbing → GRABBING → stop → OPEN → close → CLOSED."""
        cam, mock_mv = _make_camera_with_mock_sdk()

        # OPEN уже установлен хелпером
        assert cam.state == CameraState.OPEN

        # OPEN → GRABBING
        mock_mv.MV_CC_StartGrabbing.return_value = 0  # MV_OK
        with patch(
            "hikvision_camera_module_2.core.camera.SDK_AVAILABLE", True
        ):
            result = cam.start_grabbing()

        assert result is True
        assert cam.state == CameraState.GRABBING

        # GRABBING → OPEN
        cam.stop_grabbing()
        assert cam.state == CameraState.OPEN
        mock_mv.MV_CC_StopGrabbing.assert_called_once()

        # OPEN → CLOSED
        cam.close()
        assert cam.state == CameraState.CLOSED
        mock_mv.MV_CC_CloseDevice.assert_called_once()
        mock_mv.MV_CC_DestroyHandle.assert_called_once()


class TestCaptureWithoutGrabbing:
    """Тесты capture_frame в неправильном состоянии."""

    def test_capture_without_grabbing(self):
        """state != GRABBING → capture_frame возвращает (None, 0)."""
        cam = HikvisionCamera()
        # Состояние CLOSED
        frame, pixel_type = cam.capture_frame()

        assert frame is None
        assert pixel_type == 0

    def test_capture_in_open_state(self):
        """OPEN (но не GRABBING) → (None, 0)."""
        cam, _ = _make_camera_with_mock_sdk()
        assert cam.state == CameraState.OPEN

        frame, pixel_type = cam.capture_frame()

        assert frame is None
        assert pixel_type == 0


class TestCloseFromGrabbing:
    """Тесты каскадного закрытия из GRABBING."""

    def test_close_from_grabbing(self):
        """close() из GRABBING → каскад: stop_grabbing → close → CLOSED."""
        cam, mock_mv = _make_camera_with_mock_sdk()

        # Переводим в GRABBING
        cam._state = CameraState.GRABBING

        cam.close()

        assert cam.state == CameraState.CLOSED
        # stop_grabbing вызвал MV_CC_StopGrabbing
        mock_mv.MV_CC_StopGrabbing.assert_called_once()
        # close вызвал MV_CC_CloseDevice и MV_CC_DestroyHandle
        mock_mv.MV_CC_CloseDevice.assert_called_once()
        mock_mv.MV_CC_DestroyHandle.assert_called_once()


class TestOpenIdempotent:
    """Тесты идемпотентности open()."""

    def test_open_when_already_open(self):
        """Повторный open() из OPEN → True без ошибок."""
        cam, _ = _make_camera_with_mock_sdk()
        assert cam.state == CameraState.OPEN

        with patch(
            "hikvision_camera_module_2.core.camera.SDK_AVAILABLE", True
        ):
            result = cam.open(0)

        assert result is True
        assert cam.state == CameraState.OPEN

    def test_open_when_grabbing(self):
        """open() из GRABBING → True (идемпотентно)."""
        cam, _ = _make_camera_with_mock_sdk()
        cam._state = CameraState.GRABBING

        with patch(
            "hikvision_camera_module_2.core.camera.SDK_AVAILABLE", True
        ):
            result = cam.open(0)

        assert result is True
        assert cam.state == CameraState.GRABBING


class TestCallbacks:
    """Тесты callback-ов on_status и on_error."""

    def test_on_status_called_on_grabbing(self):
        """on_status вызывается при успешном start_grabbing."""
        status_cb = MagicMock()
        cam, mock_mv = _make_camera_with_mock_sdk(on_status=status_cb)

        mock_mv.MV_CC_StartGrabbing.return_value = 0

        with patch(
            "hikvision_camera_module_2.core.camera.SDK_AVAILABLE", True
        ):
            cam.start_grabbing()

        # on_status должен быть вызван с сообщением о захвате
        status_cb.assert_called()
        # Хотя бы один вызов содержит слово о захвате
        calls = [str(c) for c in status_cb.call_args_list]
        assert any("Захват" in c or "захват" in c.lower() for c in calls)

    def test_on_error_called_on_sdk_unavailable(self):
        """on_error вызывается если SDK недоступен при open()."""
        error_cb = MagicMock()
        cam = HikvisionCamera(on_error=error_cb)

        with patch(
            "hikvision_camera_module_2.core.camera.SDK_AVAILABLE", False
        ):
            cam.open(0)

        error_cb.assert_called_once()

    def test_on_status_called_on_stop(self):
        """on_status вызывается при stop_grabbing."""
        status_cb = MagicMock()
        cam, mock_mv = _make_camera_with_mock_sdk(on_status=status_cb)
        cam._state = CameraState.GRABBING

        cam.stop_grabbing()

        status_cb.assert_called()


class TestSdkAvailableProperty:
    """Тесты свойства sdk_available."""

    def test_sdk_available_true(self):
        """sdk_available возвращает True когда SDK доступен."""
        cam = HikvisionCamera()
        with patch(
            "hikvision_camera_module_2.core.camera.SDK_AVAILABLE", True
        ):
            assert cam.sdk_available is True

    def test_sdk_available_false(self):
        """sdk_available возвращает False когда SDK недоступен."""
        cam = HikvisionCamera()
        with patch(
            "hikvision_camera_module_2.core.camera.SDK_AVAILABLE", False
        ):
            assert cam.sdk_available is False


class TestCloseFromClosed:
    """Дополнительные тесты close()."""

    def test_close_from_closed_is_safe(self):
        """close() из CLOSED — безопасный no-op."""
        cam = HikvisionCamera()
        assert cam.state == CameraState.CLOSED

        # Не должно бросить ничего
        cam.close()
        assert cam.state == CameraState.CLOSED


class TestStartGrabbingNoSdk:
    """Тесты start_grabbing без SDK."""

    def test_start_grabbing_no_sdk(self):
        """SDK недоступен → start_grabbing() возвращает False."""
        with patch(
            "hikvision_camera_module_2.core.camera.SDK_AVAILABLE", False
        ):
            cam = HikvisionCamera()
            result = cam.start_grabbing()

        assert result is False
        assert cam.state == CameraState.CLOSED
