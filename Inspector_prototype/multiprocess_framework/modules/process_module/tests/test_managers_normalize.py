# -*- coding: utf-8 -*-
"""Тесты normalize_managers_view и согласованности с ProcessConfigHandler."""

import pytest

from ..configs.managers_normalize import normalize_managers_view
from ..configs.process_config_handler import ProcessConfigHandler


class TestNormalizeManagersView:
    def test_legacy_top_level_managers(self):
        cfg = {"managers": {"logger": {"level": "DEBUG"}}}
        assert normalize_managers_view(cfg)["logger"]["level"] == "DEBUG"

    def test_nested_config_managers(self):
        cfg = {
            "class": "x.Process",
            "config": {
                "managers": {
                    "console": {"enabled": True, "interactive": False},
                }
            },
        }
        m = normalize_managers_view(cfg)
        assert m["console"]["enabled"] is True
        assert m["console"]["interactive"] is False

    def test_flat_sections_in_config_without_managers_key(self):
        cfg = {
            "config": {
                "console": {"enabled": True, "title": "T"},
                "logger": {"default_level": "INFO"},
            }
        }
        m = normalize_managers_view(cfg)
        assert m["console"]["title"] == "T"
        assert m["logger"]["default_level"] == "INFO"

    def test_flat_top_level_sections(self):
        cfg = {"console": {"enabled": False}, "logger": {"default_level": "WARNING"}}
        m = normalize_managers_view(cfg)
        assert m["console"]["enabled"] is False
        assert m["logger"]["default_level"] == "WARNING"


def test_console_process_config_build_and_process_helper():
    from multiprocess_framework.modules.console_module.configs import ConsoleProcessConfig
    from multiprocess_framework.modules.data_schema_module import process as proc_fn

    name, proc_dict = proc_fn(ConsoleProcessConfig())
    assert name == "console_app"
    # process_class в ConsoleProcessConfig не задан (пользователь указывает его сам),
    # поэтому "class" = "" по контракту ProcessLaunchConfig
    assert isinstance(proc_dict["class"], str)
    assert "managers" in proc_dict["config"]
    assert proc_dict["config"]["managers"]["console"]["interactive"] is True


class TestProcessConfigHandlerNormalize:
    def test_handler_nested_config_managers(self):
        h = ProcessConfigHandler(
            "p1",
            config={
                "class": "x.Y",
                "config": {
                    "managers": {
                        "router": {"duplicate_messages_to_logger": True},
                    }
                },
            },
        )
        m = h.get_managers_config()
        assert m["router"]["duplicate_messages_to_logger"] is True

    def test_handler_flat_console_in_config(self):
        h = ProcessConfigHandler(
            "p1",
            config={"config": {"console": {"enabled": True, "interactive": True}}},
        )
        m = h.get_managers_config()
        assert m["console"]["enabled"] is True
