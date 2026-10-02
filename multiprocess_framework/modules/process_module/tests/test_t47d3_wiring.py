# -*- coding: utf-8 -*-
"""Task 4.7d-3 — слепые приёмочные тесты проводки ``overflow`` в ``FrameShmMiddleware`` процесса.

Источник: plans/transport-single-policy/task-4.7.md, acceptance 4.7d-3 (пункт про ``GenericProcess`` с
``overflow: every`` и ключи ``get_shm_stats``).

Шов — тот же, что в ``test_t47d1_overflow_wiring.py``: настоящий ``GenericProcess._init_data_pipeline``,
вызванный на заглушке процесса (``object.__new__``) с настоящим ``PluginOrchestrator`` и processing-плагином;
отличие — вместо ``router_manager=None`` стоит НАСТОЯЩИЙ ``RouterManager``: ``_init_data_pipeline`` регистрирует
в нём ``FrameShmMiddleware`` (``register_frame_middleware``), и именно из него читаются middleware процесса и
``get_shm_stats()``. Никаких подмен ``FrameShmMiddleware``; воркеры — ``MockWorkerManager`` (потоки не стартуют).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager


class PassthroughProcessing(ProcessModulePlugin):
    """Целый processing-плагин: его наличие заставляет проводку собрать приём/исполнитель и middleware."""

    name = "t47d3_passthrough"
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items: list[dict]) -> list[dict]:
        return items


_PLUGIN_PATH = "multiprocess_framework.modules.process_module.tests.test_t47d3_wiring.PassthroughProcessing"


def _wired(app_cfg: dict):
    """(процесс, его router, FrameShmMiddleware процесса) после настоящей ``_init_data_pipeline``."""
    services = MockProcessServices(name="t47d3_proc")
    orch = PluginOrchestrator(services=services)
    orch.load_and_configure_managers([{"plugin_class": _PLUGIN_PATH, "plugin_name": "t47d3_passthrough"}])
    orch.boot()

    router = RouterManager(manager_name="t47d3_proc_router")
    proc = object.__new__(GenericProcess)
    proc.name = "t47d3_proc"
    proc._orchestrator = orch
    proc.worker_manager = services.worker_manager
    proc.router_manager = router
    proc.memory_manager = None
    cfg = {"chain_targets": ["out"], **app_cfg}
    proc.get_config = lambda key, default=None: cfg if key == "config" else default
    proc.send_message = lambda target, msg: None
    proc.receive_message = lambda *a, **k: None
    proc._log_info = lambda *a, **k: None
    proc._log_error = lambda *a, **k: None
    proc._log_debug = lambda *a, **k: None
    proc._init_data_pipeline()

    # якорь существования: проводка реально собрала data-плоскость и зарегистрировала ОДИН middleware
    assert proc._data_receiver is not None
    assert len(router._frame_middlewares) == 1, "стенд неисправен: middleware процесса не зарегистрирован"
    return proc, router, router._frame_middlewares[0]


def test_shm_middleware_overflow_is_every_when_recipe_says_every():
    _, _, mw = _wired({"overflow": "every"})
    assert mw.overflow == "every"


def test_shm_middleware_overflow_is_latest_when_recipe_says_latest():
    _, _, mw = _wired({"overflow": "latest"})
    assert mw.overflow == "latest"


def test_shm_middleware_overflow_is_latest_without_key():
    _, _, mw = _wired({})
    assert mw.overflow == "latest"


def test_shm_stats_under_every_has_door_drops_and_not_inspected_door():
    _, router, _ = _wired({"overflow": "every"})

    stats = router.get_shm_stats()

    assert stats["door_drops"] == 0
    assert stats["not_inspected_door"] == 0


def test_shm_stats_under_latest_has_door_drops_but_no_not_inspected_door():
    _, router, _ = _wired({})

    stats = router.get_shm_stats()

    assert stats["door_drops"] == 0
    assert "not_inspected_door" not in stats
