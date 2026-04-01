"""Тесты ErrorManagerConfig и expand_error_manager_config."""

from ..configs.error_manager_config import ErrorManagerConfig
from ..core.error_config_assembly import expand_error_manager_config


class TestExpandErrorManagerConfig:
    """Сборка runtime-dict — единое место (см. core/error_config_assembly)."""

    def test_expand_dict_has_required_keys(self) -> None:
        """После expand есть ключи для LoggerManager и три severity-канала."""
        cfg = ErrorManagerConfig()
        d = expand_error_manager_config(cfg.model_dump())

        assert "app_name" in d
        assert d["app_name"] == "errors"
        assert "default_level" in d
        assert d["default_level"] == "WARNING"
        assert "channels" in d
        assert "errors_file" in d["channels"]
        assert "critical_file" in d["channels"]
        assert d["channels"]["errors_file"]["file_path"] == "logs/errors.log"
        assert d["channels"]["critical_file"]["file_path"] == "logs/critical.log"

    def test_include_stacktrace_preserved(self) -> None:
        cfg = ErrorManagerConfig(include_stacktrace=False)
        d = expand_error_manager_config(cfg.model_dump())
        assert d["include_stacktrace"] is False

    def test_custom_paths(self) -> None:
        cfg = ErrorManagerConfig(
            app_name="my_errors",
            error_file_path="var/log/errors.log",
        )
        d = expand_error_manager_config(cfg.model_dump())
        assert d["app_name"] == "my_errors"
        assert d["channels"]["errors_file"]["file_path"] == "var/log/errors.log"


class TestErrorManagerConfig:
    """Плоская схема без кастомного build()."""

    def test_model_dump_roundtrip(self) -> None:
        cfg = ErrorManagerConfig()
        dumped = cfg.model_dump()
        assert dumped["manager_name"] == "ErrorManager"
        assert isinstance(dumped["channels"], dict)
