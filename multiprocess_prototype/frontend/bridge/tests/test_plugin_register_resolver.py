# -*- coding: utf-8 -*-
"""Тесты resolve_plugin_register (Этап 2 pipeline-live-control, Task 2.1)."""

from __future__ import annotations

from multiprocess_prototype.frontend.bridge.plugin_register_resolver import resolve_plugin_register


def _topo() -> dict:
    """Топология: multi-plugin процесс + 1:1 процесс + процесс без плагинов."""
    return {
        "processes": [
            {
                "process_name": "vision",
                "plugins": [
                    {"plugin_name": "camera"},
                    {"plugin_name": "blur"},
                    {"plugin_name": "detector"},
                ],
            },
            {"process_name": "renderer", "plugins": [{"plugin_name": "renderer"}]},
            {"process_name": "empty", "plugins": []},
        ]
    }


def test_resolves_first_plugin():
    assert resolve_plugin_register(_topo(), "vision", 0) == "camera"


def test_resolves_second_plugin_multi():
    # Ключевой кейс Этапа 2: правка второго плагина бьёт в ЕГО регистр.
    assert resolve_plugin_register(_topo(), "vision", 1) == "blur"
    assert resolve_plugin_register(_topo(), "vision", 2) == "detector"


def test_resolves_one_to_one_process():
    assert resolve_plugin_register(_topo(), "renderer", 0) == "renderer"


def test_index_out_of_range_returns_none():
    assert resolve_plugin_register(_topo(), "vision", 5) is None


def test_process_with_no_plugins_returns_none():
    assert resolve_plugin_register(_topo(), "empty", 0) is None


def test_unknown_process_returns_none():
    assert resolve_plugin_register(_topo(), "ghost", 0) is None


def test_empty_topology_returns_none():
    assert resolve_plugin_register({}, "vision", 0) is None


def test_empty_plugin_name_returns_none():
    topo = {"processes": [{"process_name": "p", "plugins": [{"plugin_name": ""}]}]}
    assert resolve_plugin_register(topo, "p", 0) is None
