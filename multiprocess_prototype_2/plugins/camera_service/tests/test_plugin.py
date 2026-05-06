"""Тесты CameraServicePlugin: lifecycle, produce(), shutdown."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_prototype_2.plugins.camera_service.plugin import (
    CameraServicePlugin,
    _FRAME_ID_MODULO,
)


def _make_mock_ctx(config: dict | None = None) -> MagicMock:
    """Создать mock PluginContext."""
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.command_manager = MagicMock()
    return ctx


class TestConfigure:
    """Тесты configure()."""

    def test_configure(self):
        """plugin.configure(mock_ctx) → state correct."""
        plugin = CameraServicePlugin()
        ctx = _make_mock_ctx({
            "camera_type": "simulator",
            "camera_id": 2,
            "resolution_width": 320,
            "resolution_height": 240,
        })

        plugin.configure(ctx)

        assert plugin._camera_type == "simulator"
        assert plugin._camera_id == 2
        assert plugin._width == 320
        assert plugin._height == 240
        assert plugin._is_capturing is False
        assert plugin._backend is None

    def test_auto_start(self):
        """start(ctx) с auto_start=True → _is_capturing."""
        plugin = CameraServicePlugin()
        ctx = _make_mock_ctx({
            "auto_start": True,
            "camera_type": "simulator",
        })

        plugin.configure(ctx)
        plugin.start(ctx)

        assert plugin._is_capturing is True
        assert plugin._backend is not None

        plugin.shutdown(ctx)


class TestProduce:
    """Тесты produce()."""

    def test_produce_not_capturing(self):
        """produce() → [] если не захватываем."""
        plugin = CameraServicePlugin()
        ctx = _make_mock_ctx({"camera_type": "simulator"})

        plugin.configure(ctx)

        result = plugin.produce()
        assert result == []

    def test_produce_with_simulator(self):
        """Simulator backend → produce() → [item с frame]."""
        plugin = CameraServicePlugin()
        ctx = _make_mock_ctx({
            "camera_type": "simulator",
            "resolution_width": 320,
            "resolution_height": 240,
        })

        plugin.configure(ctx)
        # Запустить захват вручную
        plugin._do_start_capture(ctx)

        result = plugin.produce()
        assert len(result) == 1

        item = result[0]
        assert isinstance(item["frame"], np.ndarray)
        assert item["frame"].shape == (240, 320, 3)

        plugin.shutdown(ctx)

    def test_produce_item_fields(self):
        """Проверить все обязательные поля в item."""
        plugin = CameraServicePlugin()
        ctx = _make_mock_ctx({
            "camera_type": "simulator",
            "camera_id": 5,
            "resolution_width": 320,
            "resolution_height": 240,
        })

        plugin.configure(ctx)
        plugin._do_start_capture(ctx)

        result = plugin.produce()
        assert len(result) == 1

        item = result[0]
        # Обязательные поля
        assert "frame" in item
        assert "camera_id" in item
        assert "seq_id" in item
        assert "frame_id" in item
        assert "timestamp" in item
        assert "camera_type" in item
        assert "width" in item
        assert "height" in item
        assert "channels" in item
        assert "dtype" in item

        # Значения
        assert item["camera_id"] == 5
        assert item["camera_type"] == "simulator"
        assert item["width"] == 320
        assert item["height"] == 240
        assert item["channels"] == 3
        assert item["dtype"] == "uint8"
        assert isinstance(item["timestamp"], float)

        plugin.shutdown(ctx)

    def test_frame_id_rollover(self):
        """После _FRAME_ID_MODULO итераций → frame_id wrap."""
        plugin = CameraServicePlugin()
        ctx = _make_mock_ctx({
            "camera_type": "simulator",
            "resolution_width": 64,
            "resolution_height": 48,
        })

        plugin.configure(ctx)
        plugin._do_start_capture(ctx)

        # Прокрутить _FRAME_ID_MODULO итераций
        for _ in range(_FRAME_ID_MODULO):
            plugin.produce()

        # После 121 итерации frame_count должен обернуться в 0
        assert plugin._frame_count == 0

        # Следующий produce даст frame_id = 1
        result = plugin.produce()
        assert result[0]["frame_id"] == 1

        plugin.shutdown(ctx)


class TestShutdown:
    """Тесты shutdown()."""

    def test_shutdown(self):
        """backend.close() вызывается при shutdown."""
        plugin = CameraServicePlugin()
        ctx = _make_mock_ctx({
            "camera_type": "simulator",
        })

        plugin.configure(ctx)
        plugin._do_start_capture(ctx)
        assert plugin._backend is not None

        plugin.shutdown(ctx)

        assert plugin._is_capturing is False
        assert plugin._backend is None
