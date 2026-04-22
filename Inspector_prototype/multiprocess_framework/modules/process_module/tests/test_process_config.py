# -*- coding: utf-8 -*-
"""Тесты для ProcessConfigHandler — get_config/update_config."""

import pytest
from unittest.mock import Mock

from ..configs.process_config_handler import ProcessConfigHandler


def make_mock_shared_resources_with_data(custom_data=None):
    """Мок shared_resources с ProcessData."""
    sr = Mock()
    process_data = Mock()
    process_data.config = None
    process_data.custom = custom_data or {}
    sr.get_process_data = Mock(return_value=process_data)
    return sr


class TestProcessConfigHandlerNoSharedResources:
    def test_create_without_shared_resources(self):
        handler = ProcessConfigHandler("proc1", config={"key": "value"})
        assert handler.process_name == "proc1"

    def test_get_returns_local_config(self):
        handler = ProcessConfigHandler("proc1", config={"key": "value"})
        assert handler.get("key") == "value"

    def test_get_missing_key_returns_default(self):
        handler = ProcessConfigHandler("proc1", config={})
        assert handler.get("missing", "default") == "default"

    def test_get_managers_config_empty(self):
        handler = ProcessConfigHandler("proc1", config={})
        result = handler.get_managers_config()
        assert isinstance(result, dict)

    def test_get_managers_config_from_local(self):
        handler = ProcessConfigHandler(
            "proc1",
            config={"managers": {"logger": {"level": "DEBUG"}}},
        )
        result = handler.get_managers_config()
        assert result.get("logger", {}).get("level") == "DEBUG"

    def test_get_manager_config(self):
        handler = ProcessConfigHandler(
            "proc1",
            config={"managers": {"worker": {"max_workers": 4}}},
        )
        result = handler.get_manager_config("worker")
        assert result.get("max_workers") == 4

    def test_get_manager_config_missing(self):
        handler = ProcessConfigHandler("proc1", config={})
        result = handler.get_manager_config("nonexistent")
        assert result == {}


class TestProcessConfigHandlerWithSharedResources:
    def test_get_config_from_process_data_custom(self):
        sr = make_mock_shared_resources_with_data(
            custom_data={
                "process_config": {"debug": True},
                "component_managers_config": {"logger": {"level": "INFO"}},
            }
        )
        handler = ProcessConfigHandler("proc1", shared_resources=sr)
        managers = handler.get_managers_config()
        assert managers.get("logger", {}).get("level") == "INFO"

    def test_get_process_data_none_falls_back(self):
        sr = Mock()
        sr.get_process_data = Mock(return_value=None)
        handler = ProcessConfigHandler("proc1", shared_resources=sr, config={"key": "fallback"})
        assert handler.get("key") == "fallback"


class TestProcessConfigHandlerUpdate:
    def test_update_config_updates_local(self):
        handler = ProcessConfigHandler("proc1", config={"key": "old"})
        handler.update_config({"key": "new"})
        assert handler.get("key") == "new"

    def test_update_config_returns_true(self):
        handler = ProcessConfigHandler("proc1", config={})
        result = handler.update_config({"new_key": "value"})
        assert result is True
