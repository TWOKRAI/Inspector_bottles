"""Тесты CapturePlugin: lifecycle, produce(), pause/resume, frame_id."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from multiprocess_prototype_2.plugins.capture.plugin import (
    CapturePlugin,
    _FRAME_ID_MODULO,
)


def _make_mock_ctx(config: dict | None = None) -> MagicMock:
    """Создать mock PluginContext для тестов."""
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.command_manager = MagicMock()
    return ctx


def _make_fake_cap(width: int = 640, height: int = 480) -> MagicMock:
    """Создать mock cv2.VideoCapture, возвращающий синтетический кадр."""
    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.get.side_effect = lambda prop: {
        3: float(width),   # CAP_PROP_FRAME_WIDTH
        4: float(height),  # CAP_PROP_FRAME_HEIGHT
    }.get(prop, 0.0)
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    cap.read.return_value = (True, frame)
    return cap


class TestConfigure:
    """Тесты configure(): параметры сохранены, команды зарегистрированы."""

    def test_configure_defaults(self):
        """configure() с пустым конфигом → defaults применены."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx()
        plugin.configure(ctx)

        assert plugin._camera_id == 0
        assert plugin._device_id == 0
        assert plugin._fps == 25
        assert plugin._width == 640
        assert plugin._height == 480
        assert plugin._is_capturing is False
        assert plugin._paused is False
        assert plugin._frame_count == 0

    def test_configure_custom_values(self):
        """configure() с кастомным конфигом → значения сохранены."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx({
            "camera_id": 3,
            "device_id": 1,
            "fps": 30,
            "resolution_width": 1280,
            "resolution_height": 720,
        })
        plugin.configure(ctx)

        assert plugin._camera_id == 3
        assert plugin._device_id == 1
        assert plugin._fps == 30
        assert plugin._width == 1280
        assert plugin._height == 720

    def test_commands_registered(self):
        """configure() регистрирует start/stop/pause/resume команды."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx()
        plugin.configure(ctx)

        # Проверяем что все 4 команды зарегистрированы
        registered = [
            call[0][0]
            for call in ctx.command_manager.register_command.call_args_list
        ]
        assert "start_capture" in registered
        assert "stop_capture" in registered
        assert "pause_capture" in registered
        assert "resume_capture" in registered


class TestProduceNotCapturing:
    """Тесты produce() когда камера не запущена."""

    def test_produce_not_started(self):
        """produce() → [] если захват не запущен."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx()
        plugin.configure(ctx)

        assert plugin.produce() == []

    def test_produce_paused_without_capture(self):
        """produce() → [] если paused и не запущен."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx()
        plugin.configure(ctx)
        plugin._paused = True

        assert plugin.produce() == []


class TestProduceMetadata:
    """Тесты полей metadata из produce()."""

    def test_produce_metadata_fields(self):
        """produce() возвращает item со всеми обязательными полями."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx({
            "camera_id": 7,
            "resolution_width": 320,
            "resolution_height": 240,
        })
        plugin.configure(ctx)

        # Подменяем VideoCapture через mock
        fake_cap = _make_fake_cap(320, 240)
        plugin._cap = fake_cap
        plugin._is_capturing = True

        result = plugin.produce()
        assert len(result) == 1

        item = result[0]
        # Все обязательные поля
        assert "frame" in item
        assert "camera_id" in item
        assert "frame_id" in item
        assert "seq_id" in item
        assert "timestamp" in item
        assert "width" in item
        assert "height" in item
        assert "channels" in item
        assert "dtype" in item

        # Значения
        assert item["camera_id"] == 7
        assert item["width"] == 320
        assert item["height"] == 240
        assert item["channels"] == 3
        assert item["dtype"] == "uint8"
        assert isinstance(item["timestamp"], float)
        assert item["frame_id"] == item["seq_id"]

    def test_produce_frame_is_ndarray(self):
        """produce() → frame является np.ndarray."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx({"resolution_width": 320, "resolution_height": 240})
        plugin.configure(ctx)

        fake_cap = _make_fake_cap(320, 240)
        plugin._cap = fake_cap
        plugin._is_capturing = True

        result = plugin.produce()
        assert isinstance(result[0]["frame"], np.ndarray)


class TestFrameResize:
    """Тесты resize: если камера отдаёт другое разрешение."""

    def test_frame_resized_if_different_resolution(self):
        """Кадр 800x600 при конфиге 320x240 → resize → frame 240x320x3."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx({"resolution_width": 320, "resolution_height": 240})
        plugin.configure(ctx)

        # Камера отдаёт 800x600, а конфиг требует 320x240
        fake_cap = _make_fake_cap(800, 600)
        plugin._cap = fake_cap
        plugin._is_capturing = True

        result = plugin.produce()
        assert len(result) == 1
        assert result[0]["frame"].shape == (240, 320, 3)

    def test_frame_not_resized_if_same_resolution(self):
        """Кадр уже в нужном разрешении → resize не вызывается."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx({"resolution_width": 320, "resolution_height": 240})
        plugin.configure(ctx)

        fake_cap = _make_fake_cap(320, 240)
        plugin._cap = fake_cap
        plugin._is_capturing = True

        result = plugin.produce()
        assert result[0]["frame"].shape == (240, 320, 3)


class TestPauseResume:
    """Тесты команд pause_capture / resume_capture."""

    def test_pause_stops_produce(self):
        """pause → produce() == []."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx({"resolution_width": 320, "resolution_height": 240})
        plugin.configure(ctx)

        fake_cap = _make_fake_cap(320, 240)
        plugin._cap = fake_cap
        plugin._is_capturing = True

        # Без паузы produce работает
        assert len(plugin.produce()) == 1

        # Устанавливаем паузу
        plugin._paused = True
        assert plugin.produce() == []

    def test_resume_restores_produce(self):
        """resume после pause → produce() снова возвращает кадры."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx({"resolution_width": 320, "resolution_height": 240})
        plugin.configure(ctx)

        fake_cap = _make_fake_cap(320, 240)
        plugin._cap = fake_cap
        plugin._is_capturing = True
        plugin._paused = True

        # Пауза — нет кадров
        assert plugin.produce() == []

        # Снимаем паузу
        plugin._paused = False
        assert len(plugin.produce()) == 1

    def test_pause_command_sets_paused(self):
        """Команда pause_capture устанавливает _paused = True."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx()
        plugin.configure(ctx)

        # Находим зарегистрированную команду pause_capture
        pause_fn = None
        for call in ctx.command_manager.register_command.call_args_list:
            if call[0][0] == "pause_capture":
                pause_fn = call[0][1]
                break

        assert pause_fn is not None
        pause_fn({})
        assert plugin._paused is True

    def test_resume_command_clears_paused(self):
        """Команда resume_capture сбрасывает _paused = False."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx()
        plugin.configure(ctx)
        plugin._paused = True

        # Находим зарегистрированную команду resume_capture
        resume_fn = None
        for call in ctx.command_manager.register_command.call_args_list:
            if call[0][0] == "resume_capture":
                resume_fn = call[0][1]
                break

        assert resume_fn is not None
        resume_fn({})
        assert plugin._paused is False


class TestFrameIdCounter:
    """Тесты инкремента frame_id и rollover."""

    def test_frame_id_increments(self):
        """frame_id увеличивается с каждым produce()."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx({"resolution_width": 64, "resolution_height": 48})
        plugin.configure(ctx)

        fake_cap = _make_fake_cap(64, 48)
        plugin._cap = fake_cap
        plugin._is_capturing = True

        ids = []
        for _ in range(5):
            result = plugin.produce()
            ids.append(result[0]["frame_id"])

        assert ids == [1, 2, 3, 4, 5]

    def test_frame_id_rollover(self):
        """После _FRAME_ID_MODULO итераций frame_id оборачивается в 1."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx({"resolution_width": 64, "resolution_height": 48})
        plugin.configure(ctx)

        fake_cap = _make_fake_cap(64, 48)
        plugin._cap = fake_cap
        plugin._is_capturing = True

        # Устанавливаем счётчик прямо перед rollover
        plugin._frame_count = _FRAME_ID_MODULO - 1

        result = plugin.produce()
        assert result[0]["frame_id"] == _FRAME_ID_MODULO

        # Следующий produce должен дать rollover
        result = plugin.produce()
        assert result[0]["frame_id"] == 1
        assert plugin._frame_count == 1

    def test_frame_count_after_rollover(self):
        """_frame_count равен 0 после полного цикла _FRAME_ID_MODULO."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx({"resolution_width": 64, "resolution_height": 48})
        plugin.configure(ctx)

        fake_cap = _make_fake_cap(64, 48)
        plugin._cap = fake_cap
        plugin._is_capturing = True

        # Ставим счётчик в позицию перед rollover
        plugin._frame_count = _FRAME_ID_MODULO

        # После rollover frame_count должен обнулиться и стать 1
        plugin.produce()
        assert plugin._frame_count == 1


class TestShutdown:
    """Тесты shutdown()."""

    def test_shutdown_stops_capture(self):
        """shutdown() устанавливает _is_capturing = False и освобождает _cap."""
        plugin = CapturePlugin()
        ctx = _make_mock_ctx()
        plugin.configure(ctx)

        fake_cap = _make_fake_cap()
        plugin._cap = fake_cap
        plugin._is_capturing = True

        plugin.shutdown(ctx)

        assert plugin._is_capturing is False
        assert plugin._cap is None
        fake_cap.release.assert_called_once()
