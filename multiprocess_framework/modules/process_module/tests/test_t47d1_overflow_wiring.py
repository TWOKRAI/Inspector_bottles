# -*- coding: utf-8 -*-
"""Task 4.7d-1 — слепые приёмочные тесты проводки ``overflow`` в ``_init_data_pipeline``.

Источник: plans/transport-single-policy/task-4.7.md, acceptance 4.7d-1 (пункт про
``receiver.overflow`` / ``executor.overflow``).

Шов (допущение лида: «самый узкий реальный»): настоящий ``GenericProcess._init_data_pipeline``,
вызванный на заглушке процесса (``object.__new__``) с настоящим ``PluginOrchestrator`` и
настоящим processing-плагином — тот же приём, что в
``test_plugin_levels_defect_quartet_hazards.py::_wire_data_pipeline``. DataReceiver и
PipelineExecutor строятся настоящие (без подмен); воркеры — ``MockWorkerManager``
(потоки не стартуют, ничего не блокируется).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices


class PassthroughProcessing(ProcessModulePlugin):
    """Целый processing-плагин: его наличие заставляет проводку собрать DataReceiver и PipelineExecutor."""

    name = "t47d1_passthrough"
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items: list[dict]) -> list[dict]:
        return items


_PLUGIN_PATH = "multiprocess_framework.modules.process_module.tests.test_t47d1_overflow_wiring.PassthroughProcessing"


def _wired_process(app_cfg: dict):
    services = MockProcessServices(name="t47d1_proc")
    orch = PluginOrchestrator(services=services)
    orch.load_and_configure_managers([{"plugin_class": _PLUGIN_PATH, "plugin_name": "t47d1_passthrough"}])
    orch.boot()

    proc = object.__new__(GenericProcess)
    proc.name = "t47d1_proc"
    proc._orchestrator = orch
    proc.worker_manager = services.worker_manager
    proc.router_manager = None
    proc.memory_manager = None
    cfg = {"chain_targets": ["out"], **app_cfg}
    proc.get_config = lambda key, default=None: cfg if key == "config" else default
    proc.send_message = lambda target, msg: None
    proc.receive_message = lambda *a, **k: None
    proc._log_info = lambda *a, **k: None
    proc._log_error = lambda *a, **k: None
    proc._log_debug = lambda *a, **k: None
    proc._init_data_pipeline()
    # якорь существования: проводка реально собрала обе половины data-плоскости
    assert proc._data_receiver is not None
    assert proc._pipeline_executor is not None
    return proc


def test_receiver_overflow_is_every_when_recipe_says_every():
    assert _wired_process({"overflow": "every"})._data_receiver.overflow == "every"


def test_executor_overflow_is_every_when_recipe_says_every():
    assert _wired_process({"overflow": "every"})._pipeline_executor.overflow == "every"


def test_receiver_overflow_is_latest_without_key():
    assert _wired_process({})._data_receiver.overflow == "latest"


def test_executor_overflow_is_latest_without_key():
    assert _wired_process({})._pipeline_executor.overflow == "latest"
