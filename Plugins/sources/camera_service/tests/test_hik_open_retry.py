"""Регрессионный тест НР-5: HikvisionBackend.start() ретраит open при «занято».

После async hik_release handle освобождается не мгновенно. Первый open
может вернуть False — backend должен повторить с задержкой (паттерн
аналогичен WebcamBackend._open()). Без ретрая камера не откроется.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="HikvisionBackend только Windows")
class TestHikvisionOpenRetry:
    """НР-5: start() ретраит open при первом «занято»."""

    def _make_backend(self):
        """Создать HikvisionBackend с мок-камерой."""
        with (
            patch(
                "Plugins.sources.camera_service.backends.hikvision._HAS_PKG",
                True,
            ),
            patch(
                "Plugins.sources.camera_service.backends.hikvision.HikvisionCamera",
            ) as MockCam,
        ):
            mock_cam = MagicMock()
            MockCam.return_value = mock_cam
            from Plugins.sources.camera_service.backends.hikvision import (
                HikvisionBackend,
            )

            backend = HikvisionBackend(camera_index=0)
            return backend, mock_cam

    def test_open_succeeds_first_try(self) -> None:
        """open с первой попытки -> start() = running."""
        backend, mock_cam = self._make_backend()
        mock_cam.open.return_value = True
        mock_cam.start_grabbing.return_value = True

        backend.start()

        assert mock_cam.open.call_count == 1
        assert backend._running is True

    def test_open_fails_then_succeeds_on_retry(self) -> None:
        """open: False, False, True -> start() = running (3-я попытка)."""
        backend, mock_cam = self._make_backend()
        mock_cam.open.side_effect = [False, False, True]
        mock_cam.start_grabbing.return_value = True

        with patch("time.sleep") as mock_sleep:
            backend.start()

        assert mock_cam.open.call_count == 3
        assert backend._running is True
        # Задержка между попытками
        assert mock_sleep.call_count == 2

    def test_all_retries_fail(self) -> None:
        """Все 3 попытки open -> False -> _running = False."""
        backend, mock_cam = self._make_backend()
        mock_cam.open.return_value = False

        with patch("time.sleep"):
            backend.start()

        assert mock_cam.open.call_count == 3
        assert backend._running is False
