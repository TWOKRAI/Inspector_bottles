# multiprocess_prototype_v3/tests/unit/test_settings_register.py
"""Unit-тесты регистра `settings` в create_registers() (Phase 0, Task 0.4)."""

from __future__ import annotations

import pytest

from multiprocess_prototype_v3.registers import (
    CAMERA_REGISTER,
    PROCESSOR_REGISTER,
    RENDERER_REGISTER,
    SETTINGS_REGISTER,
    AppSettingsRegisters,
    create_registers,
)


@pytest.fixture()
def registers_and_map():
    return create_registers()


class TestCreate:
    def test_settings_register_present(self, registers_and_map) -> None:
        rm, _ = registers_and_map
        assert SETTINGS_REGISTER in rm.register_names()

    def test_settings_is_app_settings_instance(self, registers_and_map) -> None:
        rm, _ = registers_and_map
        reg = rm.get_register(SETTINGS_REGISTER)
        assert isinstance(reg, AppSettingsRegisters)

    def test_full_register_set(self, registers_and_map) -> None:
        rm, _ = registers_and_map
        assert set(rm.register_names()) == {
            CAMERA_REGISTER,
            PROCESSOR_REGISTER,
            RENDERER_REGISTER,
            SETTINGS_REGISTER,
        }


class TestDefaults:
    def test_settings_starts_with_schema_defaults(self, registers_and_map) -> None:
        rm, _ = registers_and_map
        reg = rm.get_register(SETTINGS_REGISTER)
        assert reg.camera_count == 1
        assert reg.ring_buffer_size == 3
        assert reg.shm_budget_mb == 512
        assert reg.workers_per_processor == 2


class TestDump:
    def test_model_dump_all_includes_settings(self, registers_and_map) -> None:
        rm, _ = registers_and_map
        dump = rm.model_dump_all()
        assert SETTINGS_REGISTER in dump
        assert "camera_count" in dump[SETTINGS_REGISTER]
        assert "shm_budget_mb" in dump[SETTINGS_REGISTER]


class TestValidateAll:
    def test_model_validate_all_updates_settings_fields(self, registers_and_map) -> None:
        rm, _ = registers_and_map
        rm.model_validate_all(
            {
                SETTINGS_REGISTER: {
                    **rm.get_register(SETTINGS_REGISTER).model_dump(),
                    "camera_count": 4,
                    "ring_buffer_size": 2,
                }
            }
        )
        reg = rm.get_register(SETTINGS_REGISTER)
        assert reg.camera_count == 4
        assert reg.ring_buffer_size == 2


class TestConnectionMap:
    def test_settings_absent_from_connection_map_phase0(self, registers_and_map) -> None:
        """Phase 0: settings — frontend-only регистр, у него нет process_targets.

        В Phase 3+ появится RegisterDispatchMeta с конкретными процессами
        (camera/processor/renderer получают settings).
        """
        _, cmap = registers_and_map
        assert SETTINGS_REGISTER not in cmap
