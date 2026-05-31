"""Integration-тесты ResizePlugin с framework RegistersManager.

Проверяем worker-side контракт live-параметров (Этап 2 pipeline-live-control):
1. ResizeRegisters — schema с FieldMeta (defaults, диапазоны, mutability)
2. register_schema() возвращает [ResizeRegisters] — иначе RegistersManager процесса
   не создаётся и handler register_update не регистрируется (мёртвый путь)
3. ResizePlugin — graceful degradation без RegistersManager (локальный register)
4. ResizePlugin — работа с managed register через RegistersManager
5. ResizePlugin.process() — ЖИВОЕ чтение scale_factor (правка регистра меняет вывод
   без рестарта плагина) — воспроизводит цель Этапа 2
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from multiprocess_framework.modules.process_module.plugins import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.process_module.plugins import RegistersManager

from Plugins.processing.resize.plugin import ResizePlugin
from Plugins.processing.resize.registers import ResizeRegisters


# --- Tests: ResizeRegisters schema ---


class TestResizeRegisters:
    """ResizeRegisters schema (V3_MY_PURE — живёт в plugins/resize/registers.py)."""

    def test_create_with_defaults(self):
        reg = ResizeRegisters()
        assert reg.scale_factor == 1.0
        assert reg.target_width == 0
        assert reg.target_height == 0

    def test_field_meta_present(self):
        reg = ResizeRegisters()
        for field_name in ["scale_factor", "target_width", "target_height"]:
            meta = reg.get_field_meta(field_name)
            assert meta is not None, f"FieldMeta отсутствует для {field_name}"

    def test_scale_factor_range(self):
        reg = ResizeRegisters()
        meta = reg.get_field_meta("scale_factor")
        assert meta.min == 0.1
        assert meta.max == 4.0

    def test_mutable(self):
        reg = ResizeRegisters()
        reg.scale_factor = 2.0
        assert reg.scale_factor == 2.0


# --- Tests: register_schema() замыкает живой путь ---


class TestResizeRegisterSchemaWiring:
    """register_schema() должен вернуть [ResizeRegisters] — иначе handler register_update мёртв."""

    def test_register_schema_non_empty(self):
        """register_schema() != [] — RegistersManager процесса создастся, handler появится."""
        schema = ResizePlugin.register_schema()
        assert schema == [ResizeRegisters], (
            "register_schema() пуст → PluginOrchestrator не создаст RegistersManager "
            "и не зарегистрирует register_update (живой путь оборвётся)"
        )


# --- Tests: ResizePlugin × RegistersManager integration ---


class TestResizePluginIntegration:
    """Интеграция ResizePlugin с RegistersManager (managed/unmanaged)."""

    def test_resize_without_register(self):
        """Без RegistersManager — локальный register с YAML overrides."""
        plugin = ResizePlugin()
        ctx = PluginContext(
            services=MockProcessServices(name="test"),
            config={"scale_factor": 0.5, "interpolation": "nearest"},
            io=MagicMock(),
            registers=None,
        )
        plugin.configure(ctx)
        assert plugin._reg is not None
        assert plugin._reg.scale_factor == 0.5

    def test_resize_with_register(self):
        """С managed регистром — читает scale_factor из него."""
        reg_instance = ResizeRegisters(scale_factor=2.0)
        rm = RegistersManager(registers={"resize": reg_instance})

        plugin = ResizePlugin()
        plugin.name = "resize"
        ctx = PluginContext(
            services=MockProcessServices(name="test"),
            config={},
            io=MagicMock(),
            registers=rm,
        )
        plugin.configure(ctx)
        assert plugin._reg is reg_instance
        assert plugin._reg.scale_factor == 2.0

    def test_process_reads_scale_factor_live(self):
        """process() читает scale_factor на каждом кадре — правка регистра видна без рестарта."""
        reg_instance = ResizeRegisters(scale_factor=0.5)
        rm = RegistersManager(registers={"resize": reg_instance})

        plugin = ResizePlugin()
        plugin.name = "resize"
        ctx = PluginContext(
            services=MockProcessServices(name="test"),
            config={},
            io=MagicMock(),
            registers=rm,
        )
        plugin.configure(ctx)

        frame = np.ones((100, 200, 3), dtype=np.uint8) * 255
        items = [{"frame": frame}]

        # scale_factor = 0.5 → 100x50
        out = plugin.process(items)
        assert out[0]["width"] == 100
        assert out[0]["height"] == 50

        # Живая правка регистра (как через register_update) → следующий кадр другой
        reg_instance.scale_factor = 2.0
        out2 = plugin.process(items)
        assert out2[0]["width"] == 400
        assert out2[0]["height"] == 200

    def test_process_target_dimensions_override_scale(self):
        """target_width/height > 0 имеют приоритет над scale_factor."""
        reg_instance = ResizeRegisters(scale_factor=0.5, target_width=320, target_height=240)
        rm = RegistersManager(registers={"resize": reg_instance})

        plugin = ResizePlugin()
        plugin.name = "resize"
        ctx = PluginContext(
            services=MockProcessServices(name="test"),
            config={},
            io=MagicMock(),
            registers=rm,
        )
        plugin.configure(ctx)

        frame = np.ones((100, 200, 3), dtype=np.uint8) * 255
        out = plugin.process([{"frame": frame}])
        assert out[0]["width"] == 320
        assert out[0]["height"] == 240
