# -*- coding: utf-8 -*-
"""Тесты level routing, fallback, track_error и log() override (DEBUG/INFO)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerManagerConfig,
)

from ..core.error_manager import ErrorManager


def _file_ch(
    path: str,
    *,
    fmt: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
) -> dict:
    return {
        "type": "file",
        "enabled": True,
        "file_path": path,
        "format": fmt,
        "max_size": 10 * 1024 * 1024,
        "backup_count": 5,
    }


def _logger_config_for_routing(
    tmp_path,
    *,
    enable_batching: bool = False,
    include_critical: bool = True,
    include_warnings: bool = True,
    default_level: str = "WARNING",
) -> LoggerManagerConfig:
    """LoggerManagerConfig без expand_error_manager_config — для сценариев без critical/warnings."""
    channels: dict = {
        "errors_file": _file_ch(str(tmp_path / "errors.log")),
    }
    if include_critical:
        channels["critical_file"] = _file_ch(
            str(tmp_path / "critical.log"),
            fmt="%(asctime)s [CRITICAL] %(name)s: %(message)s",
        )
    if include_warnings:
        channels["warnings_file"] = _file_ch(
            str(tmp_path / "warnings.log"),
            fmt="%(asctime)s [WARNING] %(name)s: %(message)s",
        )
    return LoggerManagerConfig.model_validate(
        {
            "app_name": "err_route_test",
            "default_level": default_level,
            "enable_batching": enable_batching,
            "batch_size": 50,
            "batch_interval": 0.5,
            "channels": channels,
            "scopes": {
                "SYSTEM": {
                    "enabled": True,
                    "min_level": "DEBUG",
                    "channels": list(channels.keys()),
                },
                "BUSINESS": {
                    "enabled": True,
                    "min_level": "DEBUG",
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


class TestLevelRouting:
    def test_level_routes_after_initialize(self, tmp_path) -> None:
        em = ErrorManager(config=_logger_config_for_routing(tmp_path))
        em.initialize()
        try:
            routes = em.get_stats()["level_routes"]
            assert routes.get("CRITICAL") == "critical_file"
            assert routes.get("ERROR") == "errors_file"
            assert routes.get("WARNING") == "warnings_file"
        finally:
            em.shutdown()

    def test_critical_routes_to_critical_file(self, tmp_path) -> None:
        em = ErrorManager(config=_logger_config_for_routing(tmp_path))
        em.initialize()
        try:
            before = em.stats["messages_processed"]
            em.critical("severity critical")
            assert em.stats["messages_processed"] > before
        finally:
            em.shutdown()

    def test_error_routes_to_errors_file(self, tmp_path) -> None:
        em = ErrorManager(config=_logger_config_for_routing(tmp_path))
        em.initialize()
        try:
            before = em.stats["messages_processed"]
            em.error("severity error")
            assert em.stats["messages_processed"] > before
        finally:
            em.shutdown()

    def test_warning_routes_to_warnings_file(self, tmp_path) -> None:
        em = ErrorManager(config=_logger_config_for_routing(tmp_path))
        em.initialize()
        try:
            before = em.stats["messages_processed"]
            em.warning("severity warning")
            assert em.stats["messages_processed"] > before
        finally:
            em.shutdown()

    def test_fallback_critical_to_errors_file_when_no_critical_channel(self, tmp_path) -> None:
        em = ErrorManager(
            config=_logger_config_for_routing(tmp_path, include_critical=False)
        )
        em.initialize()
        try:
            routes = em.get_stats()["level_routes"]
            assert routes.get("CRITICAL") == "errors_file"
            assert "critical_file" not in routes.values()
        finally:
            em.shutdown()

    def test_fallback_warning_to_errors_file_when_no_warnings_channel(self, tmp_path) -> None:
        em = ErrorManager(
            config=_logger_config_for_routing(tmp_path, include_warnings=False)
        )
        em.initialize()
        try:
            routes = em.get_stats()["level_routes"]
            assert routes.get("WARNING") == "errors_file"
            assert "warnings_file" not in routes.values()
        finally:
            em.shutdown()


class TestLogOverride:
    def test_debug_goes_to_parent_log(self, tmp_path) -> None:
        em = ErrorManager(
            config=_logger_config_for_routing(tmp_path, default_level="DEBUG")
        )
        em.initialize()
        try:
            em.debug("dbg")
        finally:
            em.shutdown()

    def test_info_goes_to_parent_log(self, tmp_path) -> None:
        em = ErrorManager(
            config=_logger_config_for_routing(tmp_path, default_level="DEBUG")
        )
        em.initialize()
        try:
            em.info("inf")
        finally:
            em.shutdown()

    def test_messages_processed_counts_correctly(self, tmp_path) -> None:
        em = ErrorManager(config=_logger_config_for_routing(tmp_path))
        em.initialize()
        try:
            em.error("e1")
            em.warning("w1")
            em.critical("c1")
            assert em.stats["messages_processed"] >= 3
        finally:
            em.shutdown()


class TestTrackError:
    def test_track_error_calls_log_exception(self, tmp_path) -> None:
        em = ErrorManager(config=_logger_config_for_routing(tmp_path))
        em.initialize()
        try:
            err = RuntimeError("boom")
            with patch.object(em, "log_exception") as mock_le:
                em.track_error(
                    err,
                    context={"message": "ctx msg", "module": "test_mod"},
                )
            mock_le.assert_called_once()
            call_kw = mock_le.call_args.kwargs
            assert call_kw.get("message") == "ctx msg"
            assert call_kw.get("module") == "test_mod"
        finally:
            em.shutdown()

    def test_track_error_with_empty_context(self, tmp_path) -> None:
        em = ErrorManager(config=_logger_config_for_routing(tmp_path))
        em.initialize()
        try:
            err = ValueError("x")
            with patch.object(em, "log_exception") as mock_le:
                em.track_error(err, context=None)
            mock_le.assert_called_once()
        finally:
            em.shutdown()

    def test_track_error_with_dict_message(self, tmp_path) -> None:
        em = ErrorManager(config=_logger_config_for_routing(tmp_path))
        em.initialize()
        try:
            err = ValueError("x")
            with patch.object(em, "log_exception") as mock_le:
                em.track_error(err, context={"message": {"key": "val"}, "module": "m"})
            mock_le.assert_called_once()
            assert isinstance(mock_le.call_args.kwargs.get("message"), str)
        finally:
            em.shutdown()
