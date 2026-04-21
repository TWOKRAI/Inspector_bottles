# multiprocess_prototype_v3/tests/unit/test_frontend_integration_settings.py
"""Unit-тесты FrontendAppContext.settings_profile_manager (Phase 0, Task 0.5).

FrontendConfig.settings_profiles_path — в `test_frontend_config_settings_path.py`
(требует PyQt5 из-за транзитивного импорта).
"""

from __future__ import annotations

from multiprocess_prototype_v3.frontend.app_context import FrontendAppContext
from multiprocess_prototype_v3.frontend.managers import (
    SettingsProfileManager,
    SettingsProfileManagerProtocol,
)


class TestAppContextField:
    def test_default_settings_profile_manager_none(self) -> None:
        ctx = FrontendAppContext(
            config={},
            registers_manager=None,
            camera_callbacks_map={},
            camera_type="simulator",
        )
        assert ctx.settings_profile_manager is None

    def test_accepts_manager_conforming_to_protocol(self, tmp_path) -> None:
        mgr = SettingsProfileManager(data_path=str(tmp_path / "profiles.yaml"))
        ctx = FrontendAppContext(
            config={},
            registers_manager=None,
            camera_callbacks_map={},
            camera_type="simulator",
            settings_profile_manager=mgr,
        )
        assert ctx.settings_profile_manager is mgr
        assert isinstance(ctx.settings_profile_manager, SettingsProfileManagerProtocol)

    def test_get_settings_profiles_path_from_config(self) -> None:
        ctx = FrontendAppContext(
            config={"settings_profiles_path": "/tmp/x.yaml"},
            registers_manager=None,
            camera_callbacks_map={},
            camera_type="simulator",
        )
        assert ctx.get_settings_profiles_path() == "/tmp/x.yaml"

    def test_get_settings_profiles_path_absent_returns_none(self) -> None:
        ctx = FrontendAppContext(
            config={},
            registers_manager=None,
            camera_callbacks_map={},
            camera_type="simulator",
        )
        assert ctx.get_settings_profiles_path() is None
