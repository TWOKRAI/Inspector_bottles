"""Тесты DeviceHubClient — IPC-клиент для вызова команд devices."""

from __future__ import annotations

from unittest.mock import MagicMock


from Plugins.hub.device_hub.client import DeviceHubClient, _normalize_response


# ------------------------------------------------------------------ #
# _normalize_response
# ------------------------------------------------------------------ #


class TestNormalizeResponse:
    """Тесты нормализации ответов PM/router."""

    def test_direct_plugin_response(self) -> None:
        """Прямой ответ плагина (уже нормализован) — без изменений."""
        raw = {"status": "ok", "devices": []}
        assert _normalize_response(raw) == raw

    def test_pm_success_with_result(self) -> None:
        """PM success с вложенным result."""
        raw = {"success": True, "data": {"result": {"status": "ok", "count": 5}}}
        result = _normalize_response(raw)
        assert result["status"] == "ok"
        assert result["count"] == 5

    def test_pm_timeout(self) -> None:
        """PM timeout."""
        raw = {"success": False, "error": "timeout"}
        result = _normalize_response(raw)
        assert result["status"] == "error"
        assert "timeout" in result["message"]

    def test_pm_error(self) -> None:
        """PM ошибка."""
        raw = {"success": False, "error": "process not found"}
        result = _normalize_response(raw)
        assert result["status"] == "error"

    def test_non_dict_response(self) -> None:
        """Некорректный ответ (не dict)."""
        result = _normalize_response("garbage")  # type: ignore[arg-type]
        assert result["status"] == "error"


# ------------------------------------------------------------------ #
# DeviceHubClient
# ------------------------------------------------------------------ #


class TestDeviceHubClient:
    """Тесты DeviceHubClient."""

    def test_request_success(self) -> None:
        """Успешный запрос."""
        ctx = MagicMock()
        ctx.process_name = "worker_proc"
        ctx.router_manager.request.return_value = {"status": "ok", "devices": []}
        client = DeviceHubClient(ctx)
        result = client.request("device_list")
        assert result["status"] == "ok"
        ctx.router_manager.request.assert_called_once()

    def test_request_timeout(self) -> None:
        """Таймаут запроса."""
        ctx = MagicMock()
        ctx.process_name = "worker_proc"
        ctx.router_manager.request.return_value = {"success": False, "error": "timeout"}
        client = DeviceHubClient(ctx)
        result = client.request("device_list", timeout=0.5)
        assert result["status"] == "error"
        assert "timeout" in result["message"]

    def test_request_no_router(self) -> None:
        """Нет router_manager → ошибка."""
        ctx = MagicMock()
        ctx.router_manager = None
        client = DeviceHubClient(ctx)
        result = client.request("device_list")
        assert result["status"] == "error"
        assert "router" in result["message"]

    def test_request_exception(self) -> None:
        """Исключение при отправке → ошибка."""
        ctx = MagicMock()
        ctx.process_name = "worker_proc"
        ctx.router_manager.request.side_effect = ConnectionError("broken pipe")
        client = DeviceHubClient(ctx)
        result = client.request("device_list")
        assert result["status"] == "error"
        assert "broken pipe" in result["message"]

    def test_custom_target_and_timeout(self) -> None:
        """Кастомный target и timeout."""
        ctx = MagicMock()
        ctx.process_name = "worker_proc"
        ctx.router_manager.request.return_value = {"status": "ok"}
        client = DeviceHubClient(ctx, target_process="custom_hub", default_timeout=5.0)
        result = client.request("cmd_x", {"a": 1}, timeout=3.0)
        assert result["status"] == "ok"
        # Проверить что timeout передан
        call_kwargs = ctx.router_manager.request.call_args
        assert call_kwargs.kwargs.get("timeout") == 3.0 or call_kwargs[1].get("timeout") == 3.0


# ------------------------------------------------------------------ #
# send_fire_and_forget (Б-3 ревью Fable)
# ------------------------------------------------------------------ #


class TestSendFireAndForget:
    """Тесты fire-and-forget отправки (Б-3: безопасно из приёмного потока)."""

    def test_send_fire_and_forget_success(self) -> None:
        """send_fire_and_forget использует send_async (non-blocking)."""
        ctx = MagicMock()
        ctx.process_name = "camera_source"
        ctx.router_manager.send_async = MagicMock()
        client = DeviceHubClient(ctx)
        ok = client.send_fire_and_forget("hik_release", {"device_id": "cam_1"})
        assert ok is True
        ctx.router_manager.send_async.assert_called_once()

    def test_send_fire_and_forget_no_router(self) -> None:
        """Нет router_manager → False, не crash."""
        ctx = MagicMock()
        ctx.router_manager = None
        client = DeviceHubClient(ctx)
        ok = client.send_fire_and_forget("hik_release")
        assert ok is False

    def test_send_fire_and_forget_no_send_async(self) -> None:
        """Router без send_async → False."""
        ctx = MagicMock(spec=[])
        ctx.router_manager = MagicMock(spec=[])  # нет send_async
        client = DeviceHubClient(ctx)
        ok = client.send_fire_and_forget("hik_release")
        assert ok is False

    def test_send_fire_and_forget_does_not_call_request(self) -> None:
        """fire-and-forget НЕ вызывает blocking request."""
        ctx = MagicMock()
        ctx.process_name = "camera_source"
        ctx.router_manager.send_async = MagicMock()
        client = DeviceHubClient(ctx)
        client.send_fire_and_forget("hik_release")
        ctx.router_manager.request.assert_not_called()
