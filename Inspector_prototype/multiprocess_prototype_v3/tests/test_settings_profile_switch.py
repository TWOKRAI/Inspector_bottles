# multiprocess_prototype_v3/tests/test_settings_profile_switch.py
"""L2 integration smoke-test: YAML → SettingsProfileManager.switch_profile → RegistersManager.

Phase 0, Task 0.6. Критерий приёмки фазы:
"Профиль из YAML → переключается → RegistersManager отражает значения."

Сценарии:
A — базовый switch: "fast" с camera_count=4, ring_buffer_size=2 применяется.
B — несуществующий профиль: возвращает False, регистры не изменились.
C — превышение SHM-бюджета: ShmBudgetError до применения.
D — round-trip YAML: save → reload новый менеджер → данные идентичны.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from multiprocess_prototype_v3.frontend.managers import (
    DEFAULT_PROFILE_ID,
    SettingsProfileManager,
    ShmBudgetError,
    default_profile_snapshot,
)
from multiprocess_prototype_v3.registers import (
    SETTINGS_REGISTER,
    create_registers,
)


@pytest.fixture()
def registers():
    rm, _ = create_registers()
    return rm


@pytest.fixture()
def yaml_path(tmp_path: Path) -> str:
    return str(tmp_path / "settings_profiles.yaml")


class TestScenarioA_BasicSwitch:
    def test_switch_to_fast_applies_fields_to_registers(
        self, registers, yaml_path: str
    ) -> None:
        manager = SettingsProfileManager(data_path=yaml_path)
        manager.ensure_default_profile(registers)

        manager.save_profile_snapshot(
            "fast",
            {**default_profile_snapshot(), "camera_count": 4, "ring_buffer_size": 2},
        )
        assert manager.switch_profile("fast", registers) is True

        reg = registers.get_register(SETTINGS_REGISTER)
        assert reg.camera_count == 4
        assert reg.ring_buffer_size == 2
        assert manager.get_current_profile_id() == "fast"


class TestScenarioB_MissingProfile:
    def test_switch_missing_returns_false_and_preserves_state(
        self, registers, yaml_path: str
    ) -> None:
        manager = SettingsProfileManager(data_path=yaml_path)
        manager.ensure_default_profile(registers)
        before = registers.get_register(SETTINGS_REGISTER).camera_count

        assert manager.switch_profile("nonexistent", registers) is False
        assert registers.get_register(SETTINGS_REGISTER).camera_count == before


class TestScenarioC_OverBudget:
    def test_switch_overbudget_raises_error_and_keeps_registers(
        self, registers, yaml_path: str
    ) -> None:
        manager = SettingsProfileManager(data_path=yaml_path)
        manager.ensure_default_profile(registers)
        before = registers.get_register(SETTINGS_REGISTER).camera_count

        manager.save_profile_snapshot(
            "overbudget",
            {
                **default_profile_snapshot(),
                "camera_count": 8,
                "ring_buffer_size": 3,
                "shm_budget_mb": 64,
            },
        )
        with pytest.raises(ShmBudgetError):
            manager.switch_profile("overbudget", registers)
        assert registers.get_register(SETTINGS_REGISTER).camera_count == before


class TestScenarioD_YamlRoundTrip:
    def test_save_reload_in_new_manager_preserves_profile(
        self, registers, yaml_path: str
    ) -> None:
        manager1 = SettingsProfileManager(data_path=yaml_path)
        manager1.ensure_default_profile(registers)
        manager1.save_profile_snapshot(
            "prod",
            {
                **default_profile_snapshot(),
                "camera_count": 3,
                "workers_per_processor": 4,
                "display_count": 4,
            },
        )
        manager1.set_current_profile_id("prod")

        # Новый менеджер с тем же путём — читает YAML с диска.
        manager2 = SettingsProfileManager(data_path=yaml_path)
        assert set(manager2.list_profiles()) == {DEFAULT_PROFILE_ID, "prod"}
        assert manager2.get_current_profile_id() == "prod"

        prod = manager2.get_profile_snapshot("prod")
        assert prod is not None
        assert prod["camera_count"] == 3
        assert prod["workers_per_processor"] == 4
        assert prod["display_count"] == 4

        # И его switch_profile применяется к свежему RegistersManager.
        fresh_rm, _ = create_registers()
        assert manager2.switch_profile("prod", fresh_rm) is True
        reg = fresh_rm.get_register(SETTINGS_REGISTER)
        assert reg.camera_count == 3
        assert reg.workers_per_processor == 4
        assert reg.display_count == 4
