# multiprocess_prototype/tests/unit/test_frontend_config_settings_path.py
"""Unit-тесты FrontendConfig.settings_profiles_path (Phase 0, Task 0.5).

Пропускается в CI без PySide6 (FrontendConfig → MainWindowConfig → widgets.header).
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="FrontendConfig зависит от PySide6 через widgets.header")

from multiprocess_prototype.frontend.configs.frontend_config import (  # noqa: E402
    FrontendConfig,
    build_frontend_config,
)


class TestFrontendConfigField:
    def test_defaults_none(self) -> None:
        cfg = FrontendConfig()
        assert cfg.settings_profiles_path is None

    def test_build_dict_includes_settings_profiles_path(self) -> None:
        result = build_frontend_config({"settings_profiles_path": "/tmp/custom.yaml"})
        assert result["settings_profiles_path"] == "/tmp/custom.yaml"

    def test_build_dict_defaults_to_none_when_absent(self) -> None:
        result = build_frontend_config({})
        assert "settings_profiles_path" in result
        assert result["settings_profiles_path"] is None
