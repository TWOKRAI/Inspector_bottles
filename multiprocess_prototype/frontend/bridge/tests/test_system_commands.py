"""Тесты system_commands — builders для system-level IPC-команд.

Pure Python, без Qt. Тестируем:
- build_process_start / stop / restart
- build_hot_add_process (defaults, explicit config)
- build_hot_remove_process (graceful / force)
- build_wire_setup (вызывает with_defaults())
- build_wire_teardown
- SYSTEM_COMMANDS реестр
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.frontend.bridge.system_commands import (
    SYSTEM_COMMANDS,
    build_hot_add_process,
    build_hot_remove_process,
    build_process_restart,
    build_process_start,
    build_process_stop,
    build_wire_setup,
    build_wire_teardown,
)
from multiprocess_prototype.frontend.bridge.wire_protocol import ShmConfig, WireConfig


# --- Fixtures ---


@pytest.fixture
def simple_wire() -> WireConfig:
    """Базовый wire без заполненных defaults."""
    return WireConfig(
        wire_key="wire_cam_proc",
        source="camera_0.capture.frame_out",
        target="processor_0.color_mask.frame_in",
    )


# --- Тесты process lifecycle ---


class TestProcessLifecycle:

    def test_build_process_start(self) -> None:
        """build_process_start возвращает cmd + process_name."""
        result = build_process_start("camera_0")
        assert result["cmd"] == "process.start"
        assert result["process_name"] == "camera_0"

    def test_build_process_stop(self) -> None:
        """build_process_stop возвращает cmd process.stop."""
        result = build_process_stop("processor_0")
        assert result["cmd"] == "process.stop"
        assert result["process_name"] == "processor_0"

    def test_build_process_restart(self) -> None:
        """build_process_restart возвращает cmd process.restart."""
        result = build_process_restart("worker_0")
        assert result["cmd"] == "process.restart"
        assert result["process_name"] == "worker_0"


# --- Тесты hot add/remove ---


class TestHotAddRemove:

    def test_build_hot_add_process(self) -> None:
        """build_hot_add_process с явным plugin_config."""
        result = build_hot_add_process(
            "new_worker",
            "color_mask",
            plugin_config={"h_min": 10, "h_max": 120},
        )
        assert result["cmd"] == "process.hot_add"
        assert result["process_name"] == "new_worker"
        assert result["plugin_name"] == "color_mask"
        assert result["plugin_config"] == {"h_min": 10, "h_max": 120}
        assert result["auto_start"] is True

    def test_build_hot_add_defaults(self) -> None:
        """build_hot_add_process без plugin_config → пустой dict, auto_start=True."""
        result = build_hot_add_process("proc", "some_plugin")
        assert result["plugin_config"] == {}
        assert result["auto_start"] is True

    def test_build_hot_add_no_auto_start(self) -> None:
        """build_hot_add_process с auto_start=False."""
        result = build_hot_add_process("proc", "plugin", auto_start=False)
        assert result["auto_start"] is False

    def test_build_hot_remove_graceful(self) -> None:
        """build_hot_remove_process с graceful=True (дефолт)."""
        result = build_hot_remove_process("old_worker")
        assert result["cmd"] == "process.hot_remove"
        assert result["process_name"] == "old_worker"
        assert result["graceful"] is True

    def test_build_hot_remove_force(self) -> None:
        """build_hot_remove_process с graceful=False (force kill)."""
        result = build_hot_remove_process("old_worker", graceful=False)
        assert result["graceful"] is False


# --- Тесты wire management ---


class TestWireManagement:

    def test_build_wire_setup(self, simple_wire: WireConfig) -> None:
        """build_wire_setup формирует полный dict с вложенным shm_config."""
        result = build_wire_setup(simple_wire)

        assert result["cmd"] == "wire.setup"
        assert result["wire_key"] == "wire_cam_proc"
        assert result["source"] == "camera_0.capture.frame_out"
        assert result["target"] == "processor_0.color_mask.frame_in"
        assert result["source_process"] == "camera_0"
        assert result["target_process"] == "processor_0"
        assert result["transport"] == "router"

    def test_build_wire_setup_applies_defaults(self, simple_wire: WireConfig) -> None:
        """build_wire_setup вызывает with_defaults() — shm_name авто-генерируется."""
        result = build_wire_setup(simple_wire)
        shm = result["shm_config"]

        # shm_name должен быть заполнен через with_defaults()
        assert shm["shm_name"] == "shm_camera_0_processor_0"
        # owner_process должен стать source_process
        assert shm["owner_process"] == "camera_0"

    def test_build_wire_setup_shm_config_structure(self, simple_wire: WireConfig) -> None:
        """shm_config в результате содержит все обязательные ключи."""
        result = build_wire_setup(simple_wire)
        shm = result["shm_config"]

        assert "shm_name" in shm
        assert "buffer_slots" in shm
        assert "owner_process" in shm
        assert "strategy" in shm
        assert shm["buffer_slots"] == 4
        assert shm["strategy"] == "direct"

    def test_build_wire_setup_preserves_explicit_shm(self) -> None:
        """build_wire_setup сохраняет явно заданный shm_name."""
        wire = WireConfig(
            wire_key="w",
            source="proc_a.plug.out",
            target="proc_b.plug.in",
            shm_config=ShmConfig(shm_name="my_custom_shm", buffer_slots=8),
        )
        result = build_wire_setup(wire)
        assert result["shm_config"]["shm_name"] == "my_custom_shm"
        assert result["shm_config"]["buffer_slots"] == 8

    def test_build_wire_teardown(self) -> None:
        """build_wire_teardown формирует dict с wire_key и процессами."""
        result = build_wire_teardown("wire_cam_proc", "camera_0", "processor_0")

        assert result["cmd"] == "wire.teardown"
        assert result["wire_key"] == "wire_cam_proc"
        assert result["source_process"] == "camera_0"
        assert result["target_process"] == "processor_0"


# --- Тест реестра ---


class TestSystemCommandsRegistry:

    def test_system_commands_registry(self) -> None:
        """SYSTEM_COMMANDS содержит все 7 команд."""
        expected_keys = {
            "process.start",
            "process.stop",
            "process.restart",
            "process.hot_add",
            "process.hot_remove",
            "wire.setup",
            "wire.teardown",
        }
        assert set(SYSTEM_COMMANDS.keys()) == expected_keys

    def test_system_commands_descriptions_nonempty(self) -> None:
        """Все описания в SYSTEM_COMMANDS непустые."""
        for cmd, description in SYSTEM_COMMANDS.items():
            assert description, f"Пустое описание для команды '{cmd}'"

    def test_system_commands_builders_match_registry(self) -> None:
        """cmd-значения из builders соответствуют ключам SYSTEM_COMMANDS."""
        # Проверяем что значения cmd совпадают с ключами реестра
        assert build_process_start("p")["cmd"] in SYSTEM_COMMANDS
        assert build_process_stop("p")["cmd"] in SYSTEM_COMMANDS
        assert build_process_restart("p")["cmd"] in SYSTEM_COMMANDS
        assert build_hot_add_process("p", "plugin")["cmd"] in SYSTEM_COMMANDS
        assert build_hot_remove_process("p")["cmd"] in SYSTEM_COMMANDS
        assert build_wire_teardown("w", "a", "b")["cmd"] in SYSTEM_COMMANDS

    def test_wire_setup_cmd_in_registry(self, simple_wire: WireConfig) -> None:
        """cmd из build_wire_setup есть в SYSTEM_COMMANDS."""
        result = build_wire_setup(simple_wire)
        assert result["cmd"] in SYSTEM_COMMANDS
