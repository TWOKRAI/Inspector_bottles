"""Тесты Task 7.4 — ConnectionMap.

Проверяем:
1. from_topology() — построение из topology dict
2. resolve() — (plugin, field) → ResolvedTarget
3. get_process() — plugin → process
4. plugins_in_process() — process → [plugins]
5. Edge cases: несуществующий плагин, пустая topology
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.registers.connection_map import ConnectionMap


@pytest.fixture
def topology() -> dict:
    """Topology dict с тремя процессами."""
    return {
        "processes": [
            {
                "process_name": "camera_0",
                "plugins": [
                    {"plugin_name": "capture", "device_id": 0},
                ],
            },
            {
                "process_name": "processor_0",
                "plugins": [
                    {"plugin_name": "color_mask", "h_min": 10},
                    {"plugin_name": "blob_detector"},
                ],
            },
            {
                "process_name": "output_0",
                "plugins": [
                    {"plugin_name": "frame_saver"},
                ],
            },
        ],
    }


@pytest.fixture
def cmap(topology) -> ConnectionMap:
    return ConnectionMap.from_topology(topology)


class TestFromTopology:
    """ConnectionMap.from_topology()."""

    def test_builds_mapping(self, cmap):
        """Все плагины смаплены на процессы."""
        assert cmap.get_process("capture") == "camera_0"
        assert cmap.get_process("color_mask") == "processor_0"
        assert cmap.get_process("blob_detector") == "processor_0"
        assert cmap.get_process("frame_saver") == "output_0"

    def test_empty_topology(self):
        """Пустая topology → пустой map."""
        cmap = ConnectionMap.from_topology({"processes": []})
        assert cmap.plugins() == []

    def test_no_processes_key(self):
        """Topology без ключа processes."""
        cmap = ConnectionMap.from_topology({})
        assert cmap.plugins() == []


class TestResolve:
    """resolve() → ResolvedTarget."""

    def test_resolve_known_plugin(self, cmap):
        """Известный плагин → ResolvedTarget."""
        target = cmap.resolve("color_mask", "h_min")
        assert target is not None
        assert target.process_name == "processor_0"
        assert target.command_name == "set_h_min"
        assert target.arg_key == "h_min"

    def test_resolve_unknown_plugin(self, cmap):
        """Неизвестный плагин → None."""
        assert cmap.resolve("nonexistent", "field") is None

    def test_resolve_different_fields(self, cmap):
        """Разные поля → разные command_name."""
        t1 = cmap.resolve("color_mask", "h_min")
        t2 = cmap.resolve("color_mask", "s_max")
        assert t1.command_name == "set_h_min"
        assert t2.command_name == "set_s_max"


class TestHelpers:
    """Вспомогательные методы."""

    def test_plugins_list(self, cmap):
        """plugins() возвращает все плагины."""
        assert set(cmap.plugins()) == {"capture", "color_mask", "blob_detector", "frame_saver"}

    def test_processes_list(self, cmap):
        """processes() возвращает уникальные процессы."""
        assert set(cmap.processes()) == {"camera_0", "processor_0", "output_0"}

    def test_plugins_in_process(self, cmap):
        """plugins_in_process() — фильтрация по процессу."""
        plugins = cmap.plugins_in_process("processor_0")
        assert set(plugins) == {"color_mask", "blob_detector"}

    def test_to_dict(self, cmap):
        """to_dict() для FW RegistersManager.connection_map."""
        d = cmap.to_dict()
        assert d["capture"] == "camera_0"
        assert d["color_mask"] == "processor_0"
