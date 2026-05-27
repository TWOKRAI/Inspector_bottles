"""Тесты BlurPlugin: configure, process(), валидация конфига."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from Plugins.processing.blur.plugin import BlurPlugin
from Plugins.processing.blur.config import BlurPluginConfig


def _make_mock_ctx(config: dict | None = None) -> MagicMock:
    """Создать mock PluginContext с нужными атрибутами."""
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.command_manager = MagicMock()
    return ctx


def _make_bgr_frame(h: int = 480, w: int = 640, value: int = 128) -> np.ndarray:
    """Создать однородный BGR-кадр заданного размера."""
    return np.ones((h, w, 3), dtype=np.uint8) * value


class TestBlurPluginConfig:
    def test_default_config(self):
        """BlurPluginConfig() — значения по умолчанию корректны."""
        cfg = BlurPluginConfig()
        assert cfg.kernel_size == 5
        assert cfg.sigma == 0.0
        assert "BlurPlugin" in cfg.plugin_class

    def test_custom_config(self):
        """BlurPluginConfig с kernel_size=7 принимается без ошибок."""
        cfg = BlurPluginConfig(kernel_size=7, sigma=1.5)
        assert cfg.kernel_size == 7
        assert cfg.sigma == 1.5

    def test_even_kernel_size_rejected(self):
        """Чётный kernel_size отвергается Pydantic-валидацией."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="нечётным"):
            BlurPluginConfig(kernel_size=4)

    def test_zero_kernel_size_rejected(self):
        """kernel_size=0 отвергается Pydantic-валидацией."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="должен быть > 0"):
            BlurPluginConfig(kernel_size=0)

    def test_negative_kernel_size_rejected(self):
        """Отрицательный kernel_size отвергается Pydantic-валидацией."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="должен быть > 0"):
            BlurPluginConfig(kernel_size=-3)


class TestBlurPluginConfigure:
    def test_configure_default(self):
        """configure() с пустым config устанавливает значения по умолчанию."""
        plugin = BlurPlugin()
        ctx = _make_mock_ctx({})
        plugin.configure(ctx)

        assert plugin._kernel_size == 5
        assert plugin._sigma == 0.0
        ctx.log_info.assert_called_once()

    def test_configure_custom(self):
        """configure() применяет параметры из ctx.config."""
        plugin = BlurPlugin()
        ctx = _make_mock_ctx({"kernel_size": 9, "sigma": 2.0})
        plugin.configure(ctx)

        assert plugin._kernel_size == 9
        assert plugin._sigma == 2.0

    def test_configure_even_kernel_corrected(self):
        """Чётный kernel_size в config корректируется (увеличивается на 1)."""
        plugin = BlurPlugin()
        ctx = _make_mock_ctx({"kernel_size": 4})
        plugin.configure(ctx)

        # 4 → 5
        assert plugin._kernel_size == 5
        ctx.log_info.assert_called()


class TestBlurPluginProcess:
    def test_process_bgr_image(self):
        """process() сохраняет форму кадра."""
        plugin = BlurPlugin()
        plugin.configure(_make_mock_ctx({"kernel_size": 5, "sigma": 0.0}))

        frame = _make_bgr_frame(480, 640)
        result = plugin.process([{"frame": frame}])

        assert len(result) == 1
        assert result[0]["frame"].shape == (480, 640, 3)

    def test_process_returns_none_on_missing_frame(self):
        """item без ключа 'frame' → @for_each отбрасывает (пустой список)."""
        plugin = BlurPlugin()
        plugin.configure(_make_mock_ctx({}))

        result = plugin.process([{}])
        # @for_each фильтрует None — item отбрасывается
        assert result == []

    def test_process_preserves_metadata(self):
        """process() пробрасывает метаданные без изменений."""
        plugin = BlurPlugin()
        plugin.configure(_make_mock_ctx({"kernel_size": 5}))

        frame = _make_bgr_frame(100, 100)
        item = {"frame": frame, "source_id": "cam_0", "timestamp": 12345}
        result = plugin.process([item])

        assert result[0]["source_id"] == "cam_0"
        assert result[0]["timestamp"] == 12345

    def test_process_blurs_image(self):
        """process() действительно изменяет пиксели (не pass-through)."""
        plugin = BlurPlugin()
        plugin.configure(_make_mock_ctx({"kernel_size": 15, "sigma": 0.0}))

        # Кадр с шумом — blur должен его сгладить
        rng = np.random.default_rng(42)
        frame = rng.integers(0, 256, (100, 100, 3), dtype=np.uint8)
        frame_copy = frame.copy()

        result = plugin.process([{"frame": frame}])
        blurred = result[0]["frame"]

        # Форма сохранена
        assert blurred.shape == frame_copy.shape
        # Пиксели изменены (размытие меняет кадр с шумом)
        assert not np.array_equal(blurred, frame_copy)

    def test_process_multiple_items(self):
        """process() обрабатывает несколько items подряд."""
        plugin = BlurPlugin()
        plugin.configure(_make_mock_ctx({"kernel_size": 3}))

        items = [
            {"frame": _make_bgr_frame(100, 100, 50)},
            {"frame": _make_bgr_frame(100, 100, 200)},
        ]
        result = plugin.process(items)

        assert len(result) == 2
        assert result[0]["frame"].shape == (100, 100, 3)
        assert result[1]["frame"].shape == (100, 100, 3)


class TestBlurPluginRegistration:
    def test_plugin_name_and_category(self):
        """BlurPlugin.name == 'blur', category == 'processing'."""
        assert BlurPlugin.name == "blur"
        assert BlurPlugin.category == "processing"

    def test_plugin_registered_in_registry(self):
        """Импорт plugin.py регистрирует 'blur' в PluginRegistry (singleton)."""
        import Plugins.processing.blur.plugin  # noqa: F401  — побочный эффект регистрации

        from multiprocess_framework.modules.process_module.plugins import PluginRegistry

        # PluginRegistry — глобальный singleton (_PluginRegistry instance), не класс
        entry = PluginRegistry.get("blur")
        assert entry is not None
        assert entry.name == "blur"
