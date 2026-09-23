# -*- coding: utf-8 -*-
"""RED-приёмка Task 3.5 (часть B, плагины) — «робот забрал — объект исчезает»,
сторона ``Plugins/sim/robot_host``, §5 контракта лида.

Независимый tester, worktree на коммите контракта лида (``ea2761e7``, до реализации).
Контракт — ТОЛЬКО секция «Контракт лида 3.5 (2026-09-23, до тестера)» в
``plans/line-sim/phase-3-object-engine.md``, §5. ``_on_job_done`` сегодня НЕ существует
на ``SimRobotHostPlugin`` (символа нет) -- ожидаемый провал ``AttributeError``.

**Интерпретация тестера (отклонение от буквы DESIGN, см. отчёт):** DESIGN допускает провести
завершённое задание через реальный ``RobotSimCore``/регистры/тик ИЛИ дёрнуть колбэк напрямую.
§1 (``RobotSimCore(on_job_done=...)``) -- Services-сторона, вне области этого файла (другой
тестер, ``OUT OF SCOPE`` этого брифа) и СЕГОДНЯ не поддерживает колбэк вовсе -- провести
задание через реальный ``SimRobotServer``/pymodbus невозможно, не задев §1. Поэтому здесь
``plugin._on_job_done(event)`` дёргается НАПРЯМУЮ с синтетическим ``JobDone``-словарём --
это ровно то место контракта §5, которое проверяется: «на завершение задания плагин шлёт
DeviceHubClient(...).send_fire_and_forget(...)», независимо от того, ЧТО вызвало колбэк.
``DeviceHubClient`` подменяется по имени в модуле плагина (сегодня модуль его вообще не
импортирует -- ``monkeypatch.setattr(..., raising=False)``, чтобы падение было в
содержательной точке -- вызове ``_on_job_done`` -- а не на самом ``setattr``).
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import Plugins.sim.robot_host.plugin as robot_plugin_module
import Plugins.sim.scene_source.plugin as scene_plugin_module
from Plugins.sim.robot_host.plugin import SimRobotHostPlugin

pytestmark = pytest.mark.timeout(30)

_JOB_EVENT = {"index": 1, "x_mm": 12.5, "y_mm": -3.0, "ecap": 106016, "t": 123.456}


def _make_configured_plugin(scene_process: str | None = None) -> tuple[SimRobotHostPlugin, MagicMock]:
    ctx = MagicMock()
    cfg = {"host": "127.0.0.1", "port": 0, "unit_id": 2, "auto_start": False}
    if scene_process is not None:
        cfg["scene_process"] = scene_process
    ctx.config = cfg
    ctx.health = MagicMock()
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    return plugin, ctx


class _FakeDeviceHubClient:
    """Подмена ``DeviceHubClient`` -- фиксирует конструктор и вызов ``send_fire_and_forget``."""

    calls: list[dict] = []

    def __init__(self, ctx, target_process: str = "devices") -> None:
        self._ctx = ctx
        self.target_process = target_process

    def send_fire_and_forget(self, command: str, args: dict | None = None) -> bool:
        type(self).calls.append({"target_process": self.target_process, "command": command, "args": args})
        return True


class _RaisingDeviceHubClient(_FakeDeviceHubClient):
    def send_fire_and_forget(self, command: str, args: dict | None = None) -> bool:
        raise RuntimeError("boom -- клиент шины бросает")


class _FalseDeviceHubClient(_FakeDeviceHubClient):
    def send_fire_and_forget(self, command: str, args: dict | None = None) -> bool:
        return False


# --------------------------------------------------------------------------- #
# B8 -- завершённое задание уходит в scene_process (дефолт/из конфига)       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "scene_process,expected_target",
    [(None, "camera"), ("camera2", "camera2")],
    ids=["default", "configured"],
)
def test_completed_job_forwarded_to_scene_process(monkeypatch, scene_process, expected_target):
    plugin, ctx = _make_configured_plugin(scene_process)
    _FakeDeviceHubClient.calls = []
    monkeypatch.setattr(robot_plugin_module, "DeviceHubClient", _FakeDeviceHubClient, raising=False)

    plugin._on_job_done(dict(_JOB_EVENT))

    assert len(_FakeDeviceHubClient.calls) == 1
    call = _FakeDeviceHubClient.calls[0]
    assert call["target_process"] == expected_target
    assert call["command"] == "scene.job_done"
    assert call["args"] == _JOB_EVENT
    ctx.health.report_error.assert_not_called()


# --------------------------------------------------------------------------- #
# B9 -- клиент падает или возвращает False -- никогда не пробрасывается,     #
#       репортится через ctx.health с throttle=30.0                          #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "fake_client_cls",
    [_RaisingDeviceHubClient, _FalseDeviceHubClient],
    ids=["raises", "returns_false"],
)
def test_client_failure_reported_not_raised(monkeypatch, fake_client_cls):
    plugin, ctx = _make_configured_plugin()
    monkeypatch.setattr(robot_plugin_module, "DeviceHubClient", fake_client_cls, raising=False)

    plugin._on_job_done(dict(_JOB_EVENT))  # не должен бросить -- иначе тест упадёт исключением

    assert ctx.health.report_error.call_count == 1
    call = ctx.health.report_error.call_args
    assert isinstance(call.args[0], Exception), "первый позиционный аргумент -- объект исключения"
    assert call.kwargs.get("throttle") == 30.0


# --------------------------------------------------------------------------- #
# B10 -- плагины друг друга не импортируют (может быть GREEN уже сегодня)    #
# --------------------------------------------------------------------------- #


def _imported_modules(py_path: Path) -> set[str]:
    """Имена модулей из реальных ``import``/``from ... import`` (AST, не текстовый греп —
    докстринги вроде "паблишер -- Plugins.sim.robot_host" не должны считаться импортом)."""
    tree = ast.parse(py_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_plugins_do_not_import_each_other():
    scene_path = Path(scene_plugin_module.__file__)
    robot_path = Path(robot_plugin_module.__file__)

    scene_imports = _imported_modules(scene_path)
    robot_imports = _imported_modules(robot_path)

    assert not any("robot_host" in name for name in scene_imports), (
        f"scene_source не должен импортировать robot_host: {scene_imports}"
    )
    assert not any("scene_source" in name for name in robot_imports), (
        f"robot_host не должен импортировать scene_source: {robot_imports}"
    )
