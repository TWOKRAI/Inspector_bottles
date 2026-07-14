# -*- coding: utf-8 -*-
"""Ф7 G.3 M7b: unit-тесты env_truthy/env_flag (общий парсер булевых env-флагов).

Выделены как отдельный контракт (ревью Ф7 G.2 F9): все флаги фазы (FW_SHM_SEQLOCK,
FW_SHM_OWNER_INCARNATION, FW_SHM_HANDLE_CACHE, FW_SHM_PREFIX_CLEANUP, ...) разбираются
ОДНИМ парсером — эти тесты фиксируют его контракт независимо от конкретных имён флагов.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.config_module.tools.env import env_flag, env_truthy

_ENV_NAME = "FW_TEST_ENV_FLAG_G3M7B"


class TestEnvTruthy:
    """env_truthy: canonical truthy-литералы (регистронезависимо, после strip)."""

    @pytest.mark.parametrize(
        "value",
        ["1", "true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON", " 1 ", " true ", "\tyes\n"],
    )
    def test_truthy_values(self, value):
        assert env_truthy(value) is True

    @pytest.mark.parametrize(
        "value",
        [None, "", "   ", "0", "false", "False", "no", "No", "off", "Off", "garbage", "2", "yesno"],
    )
    def test_falsy_values(self, value):
        assert env_truthy(value) is False


class TestEnvFlag:
    """env_flag: приоритет env (в т.ч. явное выключение) над default; default при отсутствии."""

    def test_not_set_returns_default_false(self, monkeypatch):
        monkeypatch.delenv(_ENV_NAME, raising=False)
        assert env_flag(_ENV_NAME, default=False) is False

    def test_not_set_returns_default_true(self, monkeypatch):
        monkeypatch.delenv(_ENV_NAME, raising=False)
        assert env_flag(_ENV_NAME, default=True) is True

    def test_empty_string_returns_default(self, monkeypatch):
        monkeypatch.setenv(_ENV_NAME, "")
        assert env_flag(_ENV_NAME, default=True) is True
        assert env_flag(_ENV_NAME, default=False) is False

    def test_explicit_zero_overrides_default_true(self, monkeypatch):
        """ "0" — явное выключение, перекрывает default=True (не просто "не задано")."""
        monkeypatch.setenv(_ENV_NAME, "0")
        assert env_flag(_ENV_NAME, default=True) is False

    def test_explicit_one_returns_true(self, monkeypatch):
        monkeypatch.setenv(_ENV_NAME, "1")
        assert env_flag(_ENV_NAME, default=False) is True

    def test_off_overrides_default_true(self, monkeypatch):
        monkeypatch.setenv(_ENV_NAME, "off")
        assert env_flag(_ENV_NAME, default=True) is False

    def test_garbage_value_falls_back_to_falsy(self, monkeypatch):
        monkeypatch.setenv(_ENV_NAME, "garbage")
        assert env_flag(_ENV_NAME, default=True) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
