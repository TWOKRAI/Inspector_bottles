# -*- coding: utf-8 -*-
"""Интеграционные тесты записи в файлы (enable_batching=False, прямой write)."""

from __future__ import annotations

from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerManagerConfig,
)

from ..core.error_manager import ErrorManager


def _integration_config(tmp_path, errors_name: str = "errors.log") -> LoggerManagerConfig:
    err_path = tmp_path / errors_name
    return LoggerManagerConfig.model_validate(
        {
            "app_name": "err_integration",
            "default_level": "WARNING",
            "enable_batching": False,
            "batch_size": 50,
            "batch_interval": 0.5,
            "channels": {
                "critical_file": {
                    "type": "file",
                    "enabled": True,
                    "file_path": str(tmp_path / "critical.log"),
                    "format": "%(asctime)s [CRITICAL] %(name)s: %(message)s",
                    "max_size": 10 * 1024 * 1024,
                    "backup_count": 5,
                },
                "errors_file": {
                    "type": "file",
                    "enabled": True,
                    "file_path": str(err_path),
                    "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    "max_size": 10 * 1024 * 1024,
                    "backup_count": 5,
                },
                "warnings_file": {
                    "type": "file",
                    "enabled": True,
                    "file_path": str(tmp_path / "warnings.log"),
                    "format": "%(asctime)s [WARNING] %(name)s: %(message)s",
                    "max_size": 5 * 1024 * 1024,
                    "backup_count": 3,
                },
            },
            "scopes": {
                "SYSTEM": {
                    "enabled": True,
                    "min_level": "WARNING",
                    "channels": ["errors_file", "critical_file", "warnings_file"],
                },
                "BUSINESS": {
                    "enabled": True,
                    "min_level": "INFO",
                    "channels": ["errors_file"],
                },
                "DEBUG": {
                    "enabled": True,
                    "min_level": "DEBUG",
                    "channels": ["errors_file"],
                },
            },
        }
    )


class TestErrorIntegration:
    def test_error_writes_to_file(self, tmp_path) -> None:
        error_log = tmp_path / "errors.log"
        em = ErrorManager(config=_integration_config(tmp_path))
        em.initialize()
        try:
            msg = "integration test error"
            em.error(msg)
        finally:
            em.shutdown()

        assert error_log.exists()
        content = error_log.read_text(encoding="utf-8", errors="replace")
        assert msg in content

    def test_log_exception_writes_traceback_to_file(self, tmp_path) -> None:
        error_log = tmp_path / "errors.log"
        em = ErrorManager(config=_integration_config(tmp_path))
        em.initialize()
        try:
            try:
                raise RuntimeError("integration exc")
            except RuntimeError as exc:
                em.log_exception(exc, message="wrapped", include_stacktrace=True)
        finally:
            em.shutdown()

        assert error_log.exists()
        content = error_log.read_text(encoding="utf-8", errors="replace")
        assert "wrapped" in content or "RuntimeError" in content
        assert "Traceback" in content
