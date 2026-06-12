"""Регрессионный тест Б-3: hik_release НЕ использует blocking request.

cmd_start_capture для hikvision НЕ зовёт blocking request в текущем
потоке — использует fire-and-forget (send_fire_and_forget / send_async),
не блокируя приёмный поток message_processor.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestHikReleaseBestEffort:
    """Б-3: _hik_release_best_effort использует fire-and-forget."""

    def _make_plugin(self) -> tuple:
        """Создать CameraServicePlugin с моками."""
        from Plugins.sources.camera_service.plugin import CameraServicePlugin

        plugin = CameraServicePlugin()
        ctx = MagicMock()
        ctx.config = {
            "camera_type": "hikvision",
            "camera_id": 0,
            "device_id": 0,
            "auto_start": False,
        }
        ctx.registers = None
        ctx.state_proxy = MagicMock()
        ctx.router_manager = MagicMock()
        ctx.process_name = "camera_source"
        ctx.log_info = MagicMock()
        ctx.log_warning = MagicMock()
        plugin.configure(ctx)
        return plugin, ctx

    def test_hik_release_uses_send_fire_and_forget(self) -> None:
        """_hik_release_best_effort вызывает send_fire_and_forget, НЕ request."""
        plugin, ctx = self._make_plugin()

        with (
            patch(
                "Plugins.hub.device_hub.client.DeviceHubClient.send_fire_and_forget",
                return_value=True,
            ) as mock_send,
            patch(
                "Plugins.hub.device_hub.client.DeviceHubClient.request",
            ) as mock_request,
        ):
            plugin._hik_release_best_effort(ctx)

        # send_fire_and_forget ДОЛЖЕН быть вызван
        mock_send.assert_called_once()
        # blocking request НЕ должен вызываться
        mock_request.assert_not_called()

    def test_hik_release_sends_correct_command(self) -> None:
        """Команда hik_release отправляется с правильными аргументами."""
        plugin, ctx = self._make_plugin()

        with patch(
            "Plugins.hub.device_hub.client.DeviceHubClient.send_fire_and_forget",
            return_value=True,
        ) as mock_send:
            plugin._hik_release_best_effort(ctx)

        args = mock_send.call_args
        assert args[0][0] == "hik_release"  # команда

    def test_hik_release_graceful_when_client_unavailable(self) -> None:
        """Если DeviceHubClient недоступен — warning, не crash."""
        plugin, ctx = self._make_plugin()

        with patch(
            "Plugins.hub.device_hub.client.DeviceHubClient.__init__",
            side_effect=ImportError("нет модуля"),
        ):
            # Не должен падать
            plugin._hik_release_best_effort(ctx)

        ctx.log_info.assert_called()

    def test_cmd_start_capture_hikvision_no_blocking_request(self) -> None:
        """cmd_start_capture для hikvision НЕ вызывает blocking request."""
        plugin, ctx = self._make_plugin()

        # Мокаем backend чтобы start не падал
        mock_backend = MagicMock()
        plugin._backend = mock_backend

        with (
            patch(
                "Plugins.hub.device_hub.client.DeviceHubClient.send_fire_and_forget",
                return_value=True,
            ),
            patch(
                "Plugins.hub.device_hub.client.DeviceHubClient.request",
            ) as mock_request,
            patch(
                "Plugins.sources.camera_service.plugin.create_backend",
                return_value=mock_backend,
            ),
        ):
            plugin.cmd_start_capture({})

        # Blocking request НИКОГДА не зовётся из cmd_start_capture
        mock_request.assert_not_called()
