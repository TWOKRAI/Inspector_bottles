# multiprocess_prototype/tests/unit/test_app_settings_schema.py
"""Unit-тесты `AppSettingsRegisters` — схема профиля настроек (Phase 0, Task 0.1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from multiprocess_prototype.registers.settings import AppSettingsRegisters


class TestDefaults:
    def test_default_instance_creates(self) -> None:
        reg = AppSettingsRegisters()
        assert reg.camera_count == 1
        assert reg.ring_buffer_size == 3
        assert reg.shm_budget_mb == 512
        assert reg.workers_per_processor == 2
        assert reg.display_count == 2
        assert reg.camera_source_type == "simulator"


class TestRoundTrip:
    def test_dump_then_validate_preserves_values(self) -> None:
        original = AppSettingsRegisters(
            camera_count=4,
            ring_buffer_size=2,
            shm_budget_mb=256,
            workers_per_processor=4,
            display_count=0,
            camera_source_type="hikvision",
        )
        restored = AppSettingsRegisters.model_validate(original.model_dump())
        assert restored == original


class TestValidation:
    def test_camera_count_below_min_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AppSettingsRegisters(camera_count=0)

    def test_camera_count_above_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AppSettingsRegisters(camera_count=17)

    def test_ring_buffer_below_min_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AppSettingsRegisters(ring_buffer_size=1)

    def test_shm_budget_above_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AppSettingsRegisters(shm_budget_mb=10_000)

    def test_camera_source_type_rejects_unknown(self) -> None:
        with pytest.raises(ValidationError):
            AppSettingsRegisters(camera_source_type="unknown")


class TestRegistry:
    def test_registered_in_default_registry(self) -> None:
        from multiprocess_framework.modules.data_schema_module import get_default_registry

        registry = get_default_registry()
        assert registry.has_schema("AppSettingsRegistersV3")
        assert "AppSettingsRegistersV3" in registry.list_schemas()
