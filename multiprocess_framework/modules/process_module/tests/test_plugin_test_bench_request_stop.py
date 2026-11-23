# -*- coding: utf-8 -*-
"""T5.3e.5f: ``PluginTestBench`` создаётся и умеет звать хук ``request_stop`` (C-60).

До правки стенд не создавался вовсе: конструктор звал ``PluginContext`` с
несуществующими именами аргументов (``process_name=``, ``process=``) и падал
``TypeError``. Здесь — приёмка починки и нового шага ``request_stop()``.
Литералы ожидаемых значений — в тестах, не из кода.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    PluginState,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.plugin_test_bench import PluginTestBench


class _CountingPlugin(ProcessModulePlugin):
    """Плагин-счётчик: считает вызовы хука ``request_stop``."""

    name = "counting_plugin"

    def __init__(self) -> None:
        super().__init__()
        self.request_stop_calls = 0

    def configure(self, ctx: PluginContext) -> None:
        pass

    def request_stop(self, ctx: PluginContext) -> None:
        self.request_stop_calls += 1


def test_bench_constructs() -> None:
    bench = PluginTestBench(_CountingPlugin)

    bench.configure()

    assert bench.state == PluginState.READY
    assert bench.ctx.process_name == "test_process"


def test_bench_request_stop_calls_hook_once() -> None:
    bench = PluginTestBench(_CountingPlugin)
    bench.configure().start()
    state_before: Any = bench.state

    result = bench.request_stop()

    assert result is bench
    assert bench.plugin.request_stop_calls == 1
    assert state_before == PluginState.RUNNING
    assert bench.state == PluginState.RUNNING


def test_bench_request_stop_skips_idle() -> None:
    bench = PluginTestBench(_CountingPlugin)

    bench.request_stop()

    assert bench.plugin.request_stop_calls == 0
    assert bench.state == PluginState.IDLE
