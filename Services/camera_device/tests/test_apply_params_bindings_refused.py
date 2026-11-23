# -*- coding: utf-8 -*-
"""Task 4c, Б2 (слепой тест REDS 8): ``apply_params`` при исключении вендорского ``bindings()`` отвечает отказом.

Контракт 1.8: отказ команды — ответ, исключение наружу не идёт. Подкласс плагина камеры бросает
``RuntimeError("boom")`` из ``bindings()`` только после ``boot()`` (иначе падает ``configure``).
Вызов ПРЯМОЙ: ``plugin.cmd_apply_params(...)``; через ``cm.handle_command`` исключение глотает диспетчер
(``{"status": "error", "reason": "Dispatch failed: boom"}``), и тест краснел бы по другой причине.
Ожидаемые значения — литералы из REDS. Вызов, который может зависнуть, идёт в daemon-потоке с дедлайном.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device.interface import Binding
from Services.camera_device.plugin_base import CameraDevicePlugin

pytestmark = pytest.mark.timeout(60)

_THIS = "Services.camera_device.tests.test_apply_params_bindings_refused"
_JOIN_S = 30.0


class _BrokenBindingsPlugin(CameraDevicePlugin):
    """Камера, у которой ``bindings()`` падает, когда тест взвёл ``explode`` (после ``boot()``)."""

    explode = False

    def bindings(self) -> dict[str, Binding]:
        if self.explode:
            raise RuntimeError("boom")
        return super().bindings()


def _in_daemon(fn: Callable[[], Any], deadline_s: float = _JOIN_S) -> Any:
    box: dict[str, Any] = {}

    def go() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["exc"] = exc

    th = threading.Thread(target=go, daemon=True, name="apply-params-scenario")
    th.start()
    th.join(deadline_s)
    assert not th.is_alive(), f"сценарий завис дольше {deadline_s} с"
    if "exc" in box:
        raise box["exc"]
    return box.get("result")


def _call_with_broken_bindings() -> tuple[Any, float, float, list[dict]]:
    """boot -> взвести ``explode`` -> прямой ``cmd_apply_params``.

    Возврат: (ответ | исключение, ``exposure_time`` до, после, ``services.logs``).
    """
    services = MockProcessServices(name="cam_apply_refused")
    wm = WorkerManager("cam_apply_refused_wm")
    services.worker_manager = wm
    orch = PluginOrchestrator(services=services)
    pdef = {
        "plugin_class": f"{_THIS}._BrokenBindingsPlugin",
        "plugin_name": "camera_device",
        "driver": "fake",
        "camera_id": 0,
        "device_select": "first",
    }
    orch.load_and_configure_managers([pdef])
    orch.boot()
    try:
        plugin = orch.plugins[0]
        before = plugin._reg.exposure_time
        plugin.explode = True
        try:
            outcome: Any = plugin.cmd_apply_params({"params": {"exposure_time": 5000.0}})
        except Exception as exc:  # noqa: BLE001 — контракт нарушен: исключение вернём тесту как значение
            outcome = exc
        after = plugin._reg.exposure_time
        return outcome, before, after, list(services.logs)
    finally:
        try:
            orch.shutdown()
        finally:
            wm.stop_all_workers(2.0)


@pytest.fixture
def scenario() -> tuple[Any, float, float, list[dict]]:
    return _in_daemon(_call_with_broken_bindings)


def test_apply_params_does_not_raise_when_bindings_fails(scenario) -> None:
    outcome, _, _, _ = scenario
    assert not isinstance(outcome, BaseException), repr(outcome)


def test_apply_params_replies_refusal_with_error_type_when_bindings_fails(scenario) -> None:
    outcome, _, _, _ = scenario
    assert not isinstance(outcome, BaseException), repr(outcome)
    assert outcome["success"] is False
    assert outcome["error"] == "RuntimeError"
    assert not outcome.get("applied"), outcome


def test_apply_params_logs_exactly_one_error_when_bindings_fails(scenario) -> None:
    outcome, _, _, logs = scenario
    assert not isinstance(outcome, BaseException), repr(outcome)
    errors = [rec for rec in logs if rec["level"] == "ERROR" and "bindings() отказал" in str(rec["msg"])]
    assert len(errors) == 1, [(rec["level"], rec["msg"]) for rec in logs if rec["level"] == "ERROR"]


def test_apply_params_leaves_register_untouched_when_bindings_fails(scenario) -> None:
    outcome, before, after, _ = scenario
    assert not isinstance(outcome, BaseException), repr(outcome)
    assert before == 10000.0
    assert after == 10000.0
