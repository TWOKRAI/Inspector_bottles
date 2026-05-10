# multiprocess_prototype/tests/unit/test_settings_profile_manager.py
"""Unit-тесты `SettingsProfileManager` — list/get/save/switch + SHM budget (Phase 0, Task 0.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from multiprocess_prototype.frontend.managers import (
    DEFAULT_PROFILE_ID,
    SettingsProfileManager,
    SettingsProfileManagerProtocol,
    ShmBudgetError,
    default_profile_snapshot,
    validate_shm_budget,
)
from multiprocess_prototype.registers.constants import SETTINGS_REGISTER
from multiprocess_prototype.registers.settings import AppSettingsRegisters


class FakeRegistersBridge:
    """Мок RegistersManager: фиксирует последний вызов model_validate_all."""

    def __init__(self) -> None:
        self.last_applied: dict[str, Any] | None = None
        self.apply_count: int = 0

    def model_validate_all(self, data: dict[str, Any], strict: bool = False) -> None:
        self.last_applied = data
        self.apply_count += 1


@pytest.fixture()
def tmp_yaml(tmp_path: Path) -> str:
    return str(tmp_path / "settings_profiles.yaml")


@pytest.fixture()
def manager(tmp_yaml: str) -> SettingsProfileManager:
    return SettingsProfileManager(data_path=tmp_yaml)


@pytest.fixture()
def bridge() -> FakeRegistersBridge:
    return FakeRegistersBridge()


class TestProtocolConformance:
    def test_manager_implements_protocol(self, manager: SettingsProfileManager) -> None:
        assert isinstance(manager, SettingsProfileManagerProtocol)


class TestListAndGet:
    def test_empty_manager_lists_nothing(self, manager: SettingsProfileManager) -> None:
        assert manager.list_profiles() == []

    def test_get_missing_returns_none(self, manager: SettingsProfileManager) -> None:
        assert manager.get_profile_snapshot("unknown") is None


class TestSaveAndRoundTrip:
    def test_save_then_get_returns_deepcopy(self, manager: SettingsProfileManager) -> None:
        snap = default_profile_snapshot()
        assert manager.save_profile_snapshot("prod", snap) is True
        got = manager.get_profile_snapshot("prod")
        assert got == snap
        got["camera_count"] = 99
        assert manager.get_profile_snapshot("prod")["camera_count"] == snap["camera_count"]

    def test_save_invalid_snapshot_raises(self, manager: SettingsProfileManager) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            manager.save_profile_snapshot("bad", {"camera_count": -5})

    def test_yaml_round_trip_via_reload(self, tmp_yaml: str) -> None:
        mgr1 = SettingsProfileManager(data_path=tmp_yaml)
        mgr1.save_profile_snapshot(
            "fast",
            {**default_profile_snapshot(), "camera_count": 4, "ring_buffer_size": 2},
        )
        mgr2 = SettingsProfileManager(data_path=tmp_yaml)
        assert "fast" in mgr2.list_profiles()
        assert mgr2.get_profile_snapshot("fast")["camera_count"] == 4


class TestSwitchProfile:
    def test_switch_nonexistent_returns_false(
        self, manager: SettingsProfileManager, bridge: FakeRegistersBridge
    ) -> None:
        assert manager.switch_profile("missing", bridge) is False
        assert bridge.apply_count == 0

    def test_switch_existing_applies_to_bridge(
        self, manager: SettingsProfileManager, bridge: FakeRegistersBridge
    ) -> None:
        manager.save_profile_snapshot(
            "fast",
            {**default_profile_snapshot(), "camera_count": 4, "ring_buffer_size": 2},
        )
        assert manager.switch_profile("fast", bridge) is True
        assert bridge.apply_count == 1
        assert bridge.last_applied is not None
        assert SETTINGS_REGISTER in bridge.last_applied
        applied = bridge.last_applied[SETTINGS_REGISTER]
        assert applied["camera_count"] == 4
        assert applied["ring_buffer_size"] == 2
        assert manager.get_current_profile_id() == "fast"


class TestShmBudget:
    def test_validate_ok_for_default(self) -> None:
        validate_shm_budget(AppSettingsRegisters())

    def test_validate_ok_for_4_cam_ring3(self) -> None:
        profile = AppSettingsRegisters(camera_count=4, ring_buffer_size=3, shm_budget_mb=512)
        validate_shm_budget(profile)

    def test_validate_fails_for_8_cam_tight_budget(self) -> None:
        profile = AppSettingsRegisters(camera_count=8, ring_buffer_size=3, shm_budget_mb=100)
        with pytest.raises(ShmBudgetError) as exc_info:
            validate_shm_budget(profile)
        assert exc_info.value.camera_count == 8
        assert exc_info.value.ring_buffer_size == 3
        assert exc_info.value.budget_mb == 100
        assert exc_info.value.required_mb > 100

    def test_switch_overbudget_raises_error(
        self, manager: SettingsProfileManager, bridge: FakeRegistersBridge
    ) -> None:
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
            manager.switch_profile("overbudget", bridge)
        assert bridge.apply_count == 0


class TestEnsureDefault:
    def test_ensure_creates_default_on_empty(
        self, manager: SettingsProfileManager, bridge: FakeRegistersBridge
    ) -> None:
        assert manager.list_profiles() == []
        manager.ensure_default_profile(bridge)
        assert DEFAULT_PROFILE_ID in manager.list_profiles()
        assert bridge.apply_count == 1
        assert bridge.last_applied is not None
        assert bridge.last_applied[SETTINGS_REGISTER]["camera_count"] == 1

    def test_ensure_idempotent(
        self, manager: SettingsProfileManager, bridge: FakeRegistersBridge
    ) -> None:
        manager.save_profile_snapshot(
            DEFAULT_PROFILE_ID,
            {**default_profile_snapshot(), "camera_count": 7},
        )
        manager.ensure_default_profile(bridge)
        assert manager.get_profile_snapshot(DEFAULT_PROFILE_ID)["camera_count"] == 7


class TestSetCurrent:
    def test_set_current_missing_profile_returns_false(
        self, manager: SettingsProfileManager
    ) -> None:
        assert manager.set_current_profile_id("missing") is False

    def test_set_current_persists(self, tmp_yaml: str) -> None:
        mgr1 = SettingsProfileManager(data_path=tmp_yaml)
        mgr1.save_profile_snapshot("alpha", default_profile_snapshot())
        mgr1.save_profile_snapshot("beta", default_profile_snapshot())
        assert mgr1.set_current_profile_id("beta") is True
        mgr2 = SettingsProfileManager(data_path=tmp_yaml)
        assert mgr2.get_current_profile_id() == "beta"
