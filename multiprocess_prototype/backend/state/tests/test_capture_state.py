"""Тесты публикации метрик CapturePlugin через state_proxy.

Проверяет, что плагин корректно вызывает proxy.merge() при:
- FPS-интервале (раз в секунду)
- старте и остановке захвата
- потере кадров (camera.read() → False)
- pause/resume командах
- state_proxy=None (обратная совместимость)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import numpy as np

# Фиктивный кадр (H=480, W=640, C=3)
_FAKE_FRAME = np.zeros((480, 640, 3), dtype="uint8")


def _make_ctx(
    *,
    state_proxy=None,
    process_name: str = "test_process",
    camera_id: int = 0,
    device_id: int = 0,
) -> MagicMock:
    """Создать минимальный mock-контекст PluginContext."""
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.process_name = process_name
    ctx.config = {
        "camera_id": camera_id,
        "device_id": device_id,
        "fps": 25,
        "resolution_width": 640,
        "resolution_height": 480,
        "auto_start": False,
    }
    # Логирование — молчащие no-op
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    return ctx


def _make_plugin_with_open_camera(state_proxy=None, process_name="test_process"):
    """Создать плагин с настроенной mock-камерой, которая всегда открыта."""
    from Plugins.sources.capture.plugin import CapturePlugin

    ctx = _make_ctx(state_proxy=state_proxy, process_name=process_name)
    plugin = CapturePlugin()

    # mock cv2.VideoCapture
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (True, _FAKE_FRAME)
    mock_cap.get.return_value = 640.0  # CAP_PROP_FRAME_WIDTH / HEIGHT

    with patch("Plugins.sources.capture.plugin.cv2.VideoCapture", return_value=mock_cap):
        plugin.configure(ctx)
        plugin._start_capture(ctx)

    return plugin, ctx, mock_cap


# ---------------------------------------------------------------------------
# Тест 1: FPS-интервал вызывает merge()
# ---------------------------------------------------------------------------


def test_publish_state_on_fps_interval():
    """produce() вызывает _publish_state() когда прошло >= 1 секунды."""
    state_proxy = MagicMock()
    plugin, ctx, mock_cap = _make_plugin_with_open_camera(state_proxy=state_proxy)

    # Убеждаемся, что merge() вызван при старте (из _start_capture → _publish_state)
    initial_calls = state_proxy.merge.call_count

    # Сдвигаем fps_timer назад, чтобы сэмулировать прошедшую секунду
    plugin._fps_timer = time.monotonic() - 1.5
    plugin._fps_counter = 10

    mock_cap.read.return_value = (True, _FAKE_FRAME)
    plugin.produce()

    # Должен быть ещё один вызов merge() — из fps-блока
    assert state_proxy.merge.call_count > initial_calls

    # Проверяем, что путь и структура данных корректны
    call_args = state_proxy.merge.call_args
    path, data = call_args[0]
    assert path == f"processes.{ctx.process_name}.state"
    assert "fps" in data
    assert "frame_count" in data
    assert "status" in data
    assert "drops" in data
    assert "paused" in data


# ---------------------------------------------------------------------------
# Тест 2: _start_capture публикует status=running
# ---------------------------------------------------------------------------


def test_publish_state_on_start_capture():
    """_start_capture() вызывает merge() с status='running'."""
    state_proxy = MagicMock()
    plugin, ctx, mock_cap = _make_plugin_with_open_camera(state_proxy=state_proxy)

    # Ищем последний вызов merge() — должен быть с status=running
    assert state_proxy.merge.called
    last_call = state_proxy.merge.call_args
    _, data = last_call[0]
    assert data["status"] == "running"


# ---------------------------------------------------------------------------
# Тест 3: _stop_capture публикует status=stopped
# ---------------------------------------------------------------------------


def test_publish_state_on_stop_capture():
    """_stop_capture() вызывает merge() с status='stopped' и fps=0.0."""
    state_proxy = MagicMock()
    plugin, ctx, mock_cap = _make_plugin_with_open_camera(state_proxy=state_proxy)

    state_proxy.merge.reset_mock()
    plugin._stop_capture(ctx)

    assert state_proxy.merge.called
    _, data = state_proxy.merge.call_args[0]
    assert data["status"] == "stopped"
    assert data["fps"] == 0.0


# ---------------------------------------------------------------------------
# Тест 4: drops инкрементируется при неудачном read()
# ---------------------------------------------------------------------------


def test_drops_counted():
    """Если camera.read() возвращает (False, None) — drops растёт."""
    state_proxy = MagicMock()
    plugin, ctx, mock_cap = _make_plugin_with_open_camera(state_proxy=state_proxy)

    assert plugin._drops == 0

    # Симулируем неудачный read
    mock_cap.read.return_value = (False, None)
    plugin.produce()
    assert plugin._drops == 1

    mock_cap.read.return_value = (False, None)
    plugin.produce()
    assert plugin._drops == 2


# ---------------------------------------------------------------------------
# Тест 5: state_proxy=None — не падает
# ---------------------------------------------------------------------------


def test_none_state_proxy_no_error():
    """При state_proxy=None produce() работает без ошибок."""
    plugin, ctx, mock_cap = _make_plugin_with_open_camera(state_proxy=None)

    # Успешный кадр
    mock_cap.read.return_value = (True, _FAKE_FRAME)
    result = plugin.produce()
    assert len(result) == 1

    # Потерянный кадр — тоже не падает
    mock_cap.read.return_value = (False, None)
    result = plugin.produce()
    assert result == []


# ---------------------------------------------------------------------------
# Тест 6: pause/resume публикует paused=True/False
# ---------------------------------------------------------------------------


def test_pause_resume_publishes():
    """cmd_pause_capture → merge(paused=True), cmd_resume_capture → merge(paused=False)."""
    state_proxy = MagicMock()
    plugin, ctx, mock_cap = _make_plugin_with_open_camera(state_proxy=state_proxy)

    state_proxy.merge.reset_mock()

    # Пауза
    plugin.cmd_pause_capture({})
    assert state_proxy.merge.called
    _, data = state_proxy.merge.call_args[0]
    assert data["paused"] is True

    state_proxy.merge.reset_mock()

    # Возобновление
    plugin.cmd_resume_capture({})
    assert state_proxy.merge.called
    _, data = state_proxy.merge.call_args[0]
    assert data["paused"] is False
