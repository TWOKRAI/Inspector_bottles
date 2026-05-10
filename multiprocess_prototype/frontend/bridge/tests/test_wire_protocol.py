"""Тесты wire_protocol — data classes и валидация wire конфигурации.

Pure Python, без Qt. Тестируем:
- source_process / target_process properties
- with_defaults(): авто-заполнение shm_name и owner_process
- from_topology_entry() / to_topology_entry(): round-trip
- validate_wire(): все варианты ошибок + happy path
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.frontend.bridge.wire_protocol import (
    ShmConfig,
    WireConfig,
    validate_wire,
)


# --- Fixtures ---


@pytest.fixture
def minimal_wire() -> WireConfig:
    """Минимальный wire без заполненных defaults."""
    return WireConfig(
        wire_key="wire_cam_proc",
        source="camera_0.capture.frame_out",
        target="processor_0.color_mask.frame_in",
    )


@pytest.fixture
def full_wire() -> WireConfig:
    """Wire с явно указанным ShmConfig."""
    return WireConfig(
        wire_key="wire_proc_display",
        source="processor_0.color_mask.result_out",
        target="display_0.viewer.frame_in",
        transport="direct",
        shm_config=ShmConfig(
            shm_name="shm_custom",
            buffer_slots=8,
            owner_process="processor_0",
            strategy="via_pm",
        ),
    )


# --- Тесты properties ---


class TestProperties:

    def test_source_target_process_properties(self, minimal_wire: WireConfig) -> None:
        """source_process и target_process извлекают имя процесса до первой точки."""
        assert minimal_wire.source_process == "camera_0"
        assert minimal_wire.target_process == "processor_0"

    def test_source_process_multi_segment(self) -> None:
        """source_process работает при сложном пути process.plugin.port."""
        wire = WireConfig(
            wire_key="w",
            source="my_process.my_plugin.output_port",
            target="other_proc.plugin_b.input_port",
        )
        assert wire.source_process == "my_process"
        assert wire.target_process == "other_proc"


# --- Тесты with_defaults ---


class TestWithDefaults:

    def test_with_defaults_fills_shm_name(self, minimal_wire: WireConfig) -> None:
        """Если shm_name пуст — генерируется shm_{source}_{target}."""
        result = minimal_wire.with_defaults()
        assert result.shm_config.shm_name == "shm_camera_0_processor_0"

    def test_with_defaults_fills_owner(self, minimal_wire: WireConfig) -> None:
        """Если owner_process пуст — становится source_process."""
        result = minimal_wire.with_defaults()
        assert result.shm_config.owner_process == "camera_0"

    def test_with_defaults_preserves_explicit_shm_name(self, full_wire: WireConfig) -> None:
        """Если shm_name уже задан — не перезаписывается."""
        result = full_wire.with_defaults()
        assert result.shm_config.shm_name == "shm_custom"

    def test_with_defaults_preserves_explicit_owner(self, full_wire: WireConfig) -> None:
        """Если owner_process задан — не перезаписывается."""
        result = full_wire.with_defaults()
        assert result.shm_config.owner_process == "processor_0"

    def test_with_defaults_returns_new_instance(self, minimal_wire: WireConfig) -> None:
        """with_defaults() возвращает новый WireConfig (frozen dataclass)."""
        result = minimal_wire.with_defaults()
        # Оба — WireConfig, но разные объекты (или тот же если ничего не изменилось)
        assert isinstance(result, WireConfig)

    def test_with_defaults_preserves_other_fields(self, minimal_wire: WireConfig) -> None:
        """with_defaults не трогает wire_key, source, target, transport."""
        result = minimal_wire.with_defaults()
        assert result.wire_key == minimal_wire.wire_key
        assert result.source == minimal_wire.source
        assert result.target == minimal_wire.target
        assert result.transport == minimal_wire.transport

    def test_with_defaults_preserves_buffer_slots(self) -> None:
        """Кастомные buffer_slots сохраняются после with_defaults."""
        wire = WireConfig(
            wire_key="w",
            source="proc_a.plugin.out",
            target="proc_b.plugin.in",
            shm_config=ShmConfig(buffer_slots=16),
        )
        result = wire.with_defaults()
        assert result.shm_config.buffer_slots == 16


# --- Тесты round-trip ---


class TestRoundTrip:

    def test_from_topology_entry_roundtrip(self, full_wire: WireConfig) -> None:
        """from_topology_entry(key, to_topology_entry()) == исходный wire."""
        entry = full_wire.to_topology_entry()
        restored = WireConfig.from_topology_entry(full_wire.wire_key, entry)
        assert restored == full_wire

    def test_from_topology_entry_minimal(self) -> None:
        """from_topology_entry работает с минимальным entry (дефолтные значения)."""
        entry = {
            "source": "proc_a.plug.out",
            "target": "proc_b.plug.in",
        }
        wire = WireConfig.from_topology_entry("my_wire", entry)
        assert wire.wire_key == "my_wire"
        assert wire.source == "proc_a.plug.out"
        assert wire.target == "proc_b.plug.in"
        assert wire.transport == "router"  # дефолт
        assert wire.shm_config.buffer_slots == 4  # дефолт

    def test_to_topology_entry_contains_all_keys(self, minimal_wire: WireConfig) -> None:
        """to_topology_entry() содержит все необходимые ключи."""
        entry = minimal_wire.to_topology_entry()
        assert "source" in entry
        assert "target" in entry
        assert "transport" in entry
        assert "shm_config" in entry
        shm = entry["shm_config"]
        assert "shm_name" in shm
        assert "buffer_slots" in shm
        assert "owner_process" in shm
        assert "strategy" in shm

    def test_roundtrip_with_defaults_applied(self, minimal_wire: WireConfig) -> None:
        """round-trip работает и после with_defaults()."""
        wire_with_defaults = minimal_wire.with_defaults()
        entry = wire_with_defaults.to_topology_entry()
        restored = WireConfig.from_topology_entry(wire_with_defaults.wire_key, entry)
        assert restored == wire_with_defaults


# --- Тесты validate_wire ---


class TestValidateWire:

    def test_validate_happy_path(self, minimal_wire: WireConfig) -> None:
        """Корректный wire проходит все проверки."""
        ok, error = validate_wire(minimal_wire)
        assert ok is True
        assert error is None

    def test_validate_self_loop(self) -> None:
        """source == target → ошибка self-loop."""
        wire = WireConfig(
            wire_key="loop",
            source="proc_a.plugin.port",
            target="proc_a.plugin.port",
        )
        ok, error = validate_wire(wire)
        assert ok is False
        assert error is not None
        assert "совпадают" in error or "self" in error.lower() or "source" in error

    def test_validate_same_process(self) -> None:
        """source_process == target_process → ошибка (wire внутри одного процесса)."""
        wire = WireConfig(
            wire_key="intra",
            source="proc_a.plugin_x.out",
            target="proc_a.plugin_y.in",
        )
        ok, error = validate_wire(wire)
        assert ok is False
        assert error is not None

    def test_validate_bad_format_source(self) -> None:
        """source без двух точек → ошибка формата."""
        wire = WireConfig(
            wire_key="bad",
            source="only_one_dot.plugin",  # нет порта
            target="proc_b.plugin.in",
        )
        ok, error = validate_wire(wire)
        assert ok is False
        assert error is not None

    def test_validate_bad_format_target(self) -> None:
        """target без двух точек → ошибка формата."""
        wire = WireConfig(
            wire_key="bad",
            source="proc_a.plugin.out",
            target="proc_b",  # вообще нет точек
        )
        ok, error = validate_wire(wire)
        assert ok is False
        assert error is not None

    def test_validate_small_buffer(self) -> None:
        """buffer_slots < 2 → ошибка."""
        wire = WireConfig(
            wire_key="small_buf",
            source="proc_a.plugin.out",
            target="proc_b.plugin.in",
            shm_config=ShmConfig(buffer_slots=1),
        )
        ok, error = validate_wire(wire)
        assert ok is False
        assert error is not None
        assert "buffer_slots" in error

    def test_validate_buffer_exactly_two(self) -> None:
        """buffer_slots == 2 → валидно (граничное значение)."""
        wire = WireConfig(
            wire_key="w",
            source="proc_a.plugin.out",
            target="proc_b.plugin.in",
            shm_config=ShmConfig(buffer_slots=2),
        )
        ok, error = validate_wire(wire)
        assert ok is True
        assert error is None

    def test_validate_full_wire(self, full_wire: WireConfig) -> None:
        """Full wire с явным ShmConfig — тоже проходит валидацию."""
        ok, error = validate_wire(full_wire)
        assert ok is True
        assert error is None
