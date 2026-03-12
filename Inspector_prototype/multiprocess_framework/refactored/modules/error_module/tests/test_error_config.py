"""Тесты ErrorManagerConfig."""

import pytest

from ..config.error_config import ErrorManagerConfig


class TestErrorManagerConfig:
    """Тесты ErrorManagerConfig."""

    def test_build_returns_tuple(self) -> None:
        """build() возвращает (name, dict)."""
        config = ErrorManagerConfig()
        name, d = config.build()

        assert name == "ErrorManager"
        assert isinstance(d, dict)

    def test_build_dict_has_required_keys(self) -> None:
        """config_dict содержит ключи для LogConfig.

        default_level=WARNING: ErrorManager ловит WARNING, ERROR, CRITICAL.
        Три severity-канала: critical_file, errors_file, warnings_file.
        """
        config = ErrorManagerConfig()
        _, d = config.build()

        assert "app_name" in d
        assert d["app_name"] == "errors"
        assert "default_level" in d
        assert d["default_level"] == "WARNING"
        assert "channels" in d
        assert "errors_file" in d["channels"]
        assert "critical_file" in d["channels"]
        assert d["channels"]["errors_file"]["file_path"] == "logs/errors.log"
        assert d["channels"]["critical_file"]["file_path"] == "logs/critical.log"

    def test_build_include_stacktrace(self) -> None:
        """include_stacktrace в config_dict."""
        config = ErrorManagerConfig(include_stacktrace=False)
        _, d = config.build()

        assert d["include_stacktrace"] is False

    def test_custom_values(self) -> None:
        """Кастомные значения в build()."""
        config = ErrorManagerConfig(
            app_name="my_errors",
            error_file_path="var/log/errors.log",
        )
        name, d = config.build()

        assert d["app_name"] == "my_errors"
        assert d["channels"]["errors_file"]["file_path"] == "var/log/errors.log"
