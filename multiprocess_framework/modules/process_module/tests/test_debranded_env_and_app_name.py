# -*- coding: utf-8 -*-
"""Де-брендинг env-ручек и имени приложения в конфиге менеджеров (D4).

До D4 три ручки из восьми имели каноничное имя ``MULTIPROCESS_*`` (Ф5.11), а пять
жили ТОЛЬКО под продуктовым префиксом. Плюс два читателя были асимметричны:
``process_launch_config`` знал только легаси-имя, а ``observability_reload`` и
``observability_store`` читали пару в обратном порядке — легаси перекрывал канон.

Проверяется поимённо, ручка за ручкой: суммарное «хотя бы одно каноничное имя
работает» пережило бы потерю любой отдельной.

Сама таблица пар живёт в ``app_module`` и проверяется ``app_module/tests/
test_env_aliases.py``: framework-модули не вправе импортировать ``app_module``
(граничный контракт ``test_no_other_framework_module_imports_app_module``).
Здесь — только ЧИТАТЕЛИ ручек, которые живут в этом слое.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.base_manager.utils import DEFAULT_APP_NAME
from multiprocess_framework.modules.process_module.configs.managers_config import (
    ManagersConfig,
    managers_from_log_dir,
)


class TestHealthEnvReadsBothNames:
    """``health/state.py`` — пять из восьми ручек жили только под легаси-именем."""

    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch):
        for name in ("HEALTH_LOG_ONLY", "HEALTH_BREAKER_THRESHOLD", "HEALTH_BREAKER_COOLDOWN"):
            monkeypatch.delenv(f"MULTIPROCESS_{name}", raising=False)
            monkeypatch.delenv(f"INSPECTOR_{name}", raising=False)
        yield

    @pytest.mark.parametrize("env_key", ["MULTIPROCESS_HEALTH_LOG_ONLY", "INSPECTOR_HEALTH_LOG_ONLY"])
    def test_log_only_switch_honours_both_names(self, monkeypatch, env_key):
        from multiprocess_framework.modules.process_module.health import state as health_state

        assert health_state._env_log_only() is False
        monkeypatch.setenv(env_key, "1")
        assert health_state._env_log_only() is True, f"ручка {env_key} не читается"

    def test_canonical_log_only_wins_over_legacy(self, monkeypatch):
        from multiprocess_framework.modules.process_module.health import state as health_state

        monkeypatch.setenv("MULTIPROCESS_HEALTH_LOG_ONLY", "0")
        monkeypatch.setenv("INSPECTOR_HEALTH_LOG_ONLY", "1")
        assert health_state._env_log_only() is False, "легаси перекрыл каноничную ручку"


class TestFrameTraceEnvReadsBothNames:
    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch):
        monkeypatch.delenv("MULTIPROCESS_FRAME_TRACE", raising=False)
        monkeypatch.delenv("INSPECTOR_FRAME_TRACE", raising=False)
        yield

    @pytest.mark.parametrize("env_key", ["MULTIPROCESS_FRAME_TRACE", "INSPECTOR_FRAME_TRACE"])
    def test_both_names_enable_trace(self, monkeypatch, env_key):
        from multiprocess_framework.modules.process_module.generic import frame_trace

        assert frame_trace._env_frame_trace_on() is False
        monkeypatch.setenv(env_key, "1")
        assert frame_trace._env_frame_trace_on() is True, f"ручка {env_key} не читается"

    def test_canonical_off_wins_over_legacy_on(self, monkeypatch):
        from multiprocess_framework.modules.process_module.generic import frame_trace

        monkeypatch.setenv("MULTIPROCESS_FRAME_TRACE", "0")
        monkeypatch.setenv("INSPECTOR_FRAME_TRACE", "1")
        assert frame_trace._env_frame_trace_on() is False


class TestLogDirReaderSymmetry:
    """``process_launch_config`` читал ТОЛЬКО легаси-имя — тихий увод каталога логов."""

    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch):
        monkeypatch.delenv("MULTIPROCESS_LOG_DIR", raising=False)
        monkeypatch.delenv("INSPECTOR_LOG_DIR", raising=False)
        yield

    @pytest.mark.parametrize("env_key", ["MULTIPROCESS_LOG_DIR", "INSPECTOR_LOG_DIR"])
    def test_launch_config_default_reads_both(self, monkeypatch, tmp_path, env_key):
        from multiprocess_framework.modules.process_module.configs import process_launch_config

        monkeypatch.setenv(env_key, str(tmp_path))
        cfg = process_launch_config.ProcessLaunchConfig(process_name="p")
        assert cfg._resolve_log_dir() == str(tmp_path), f"ручка {env_key} не доехала до log_dir"

    @pytest.mark.parametrize("env_key", ["MULTIPROCESS_LOG_DIR", "INSPECTOR_LOG_DIR"])
    def test_observability_reload_reads_both(self, monkeypatch, tmp_path, env_key):
        from multiprocess_framework.modules.process_module.managers import observability_reload

        monkeypatch.setenv(env_key, str(tmp_path))
        assert observability_reload.resolve_base_log_dir() == str(tmp_path)

    def test_observability_reload_prefers_canonical(self, monkeypatch, tmp_path):
        from multiprocess_framework.modules.process_module.managers import observability_reload

        canonical = tmp_path / "canon"
        monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(canonical))
        monkeypatch.setenv("INSPECTOR_LOG_DIR", str(tmp_path / "legacy"))
        assert observability_reload.resolve_base_log_dir() == str(canonical)


class TestAppNameIsNotHardcoded:
    """``app_name`` логгера — из composition root, не константа фреймворка."""

    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch):
        monkeypatch.delenv("MPF_APP_NAME", raising=False)
        monkeypatch.delenv("MULTIPROCESS_LOG_LEVEL", raising=False)
        monkeypatch.delenv("INSPECTOR_LOG_LEVEL", raising=False)
        yield

    def test_default_managers_config_is_neutral(self):
        """Дефолт схемы не содержит имени продукта."""
        assert ManagersConfig().logger.app_name == DEFAULT_APP_NAME

    def test_env_app_name_reaches_logger_section(self, monkeypatch):
        monkeypatch.setenv("MPF_APP_NAME", "AcmeApp")
        assert ManagersConfig().logger.app_name == "AcmeApp"

    def test_managers_from_log_dir_neutral_by_default(self, tmp_path):
        cfg = managers_from_log_dir(str(tmp_path))
        assert cfg.logger.app_name == DEFAULT_APP_NAME
        assert "inspector" not in cfg.logger.app_name.lower()

    def test_managers_from_log_dir_takes_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MPF_APP_NAME", "AcmeApp")
        assert managers_from_log_dir(str(tmp_path)).logger.app_name == "AcmeApp"

    def test_explicit_argument_wins_over_env(self, monkeypatch, tmp_path):
        """Composition root вправе передать имя явно, минуя env."""
        monkeypatch.setenv("MPF_APP_NAME", "FromEnv")
        cfg = managers_from_log_dir(str(tmp_path), app_name="FromArg")
        assert cfg.logger.app_name == "FromArg"

    @pytest.mark.parametrize("env_key", ["MULTIPROCESS_LOG_LEVEL", "INSPECTOR_LOG_LEVEL"])
    def test_log_level_env_reads_both_names(self, monkeypatch, tmp_path, env_key):
        monkeypatch.setenv(env_key, "debug")
        assert managers_from_log_dir(str(tmp_path)).logger.default_level == "DEBUG"

    def test_log_level_canonical_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MULTIPROCESS_LOG_LEVEL", "WARNING")
        monkeypatch.setenv("INSPECTOR_LOG_LEVEL", "DEBUG")
        assert managers_from_log_dir(str(tmp_path)).logger.default_level == "WARNING"
