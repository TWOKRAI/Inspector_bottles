# -*- coding: utf-8 -*-
"""Task 1.2 (system-run-state) — слепые приёмочные тесты хука ``readiness()`` и снимка готовности процесса.

Контракт — DESIGN пп.1-3 ``plans/2026-10-27_system-run-state/tasks/1.2.md``:
  * ``ProcessModulePlugin.readiness(self, ctx) -> list[dict]`` — умолчание ``[]``;
    элемент ``{"severity": "failure|check_function|out_of_spec|maintenance", "reason": str}``;
  * ``PluginOrchestrator.readiness_snapshot() -> dict`` —
    ``{"ready": bool, "reasons": [...], "paused": bool, "at": float}``,
    у причины ``node = "<процесс>.<плагин>"``, ``source = "readiness"``;
  * исключение ``readiness()`` -> ``failure`` «readiness() упал: <ТипИсключения>» БЕЗ текста исключения
    (текст — в ``log_error``);
  * плагин вне ``{RUNNING, PAUSED}`` (``IDLE`` после упавшего ``configure``, ``READY`` после упавшего ``start``) ->
    ``failure`` «плагин не поднят (<состояние>)»;
  * ``ready`` = нет ``failure`` и нет ``check_function`` И процесс объявил готовность; ``out_of_spec`` не блокирует.

Решения тестера (``# ASSUMPTION``), вынесены в отчёт «ВОПРОС ЛИДУ»:
  * снимок берётся прямым вызовом ``readiness_snapshot()`` БЕЗ аргументов; «процесс объявил
    готовность» тест обеспечивает атрибутом носителя ``_current_process_status = "running"`` (как его ставит
    ``ProcessModule.run()``, ``process_module.py:1406``);
  * ``<состояние>`` в причине «плагин не поднят» — значение состояния (``"idle"``/``"ready"``), как в существующих логах
    оркестратора; регистр и точная скобочная форма в тесте не зажаты.

Ожидаемые значения — литералы. Блокирующих вызовов нет (оркестратор синхронный, настоящие плагины без потоков).
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

_THIS = "multiprocess_framework.modules.process_module.tests.test_readiness_hook"
_PROC = "rh_proc"


class _Plain(ProcessModulePlugin):
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items):
        return items


class RhHealthy(_Plain):
    name = "rh_healthy"


class RhToggle(_Plain):
    """Здоров, пока ``failing`` ложно; затем объявляет сбой (читается живым состоянием плагина)."""

    name = "rh_toggle"
    failing = False

    def readiness(self, ctx: PluginContext) -> list[dict]:
        if RhToggle.failing:
            return [{"severity": "failure", "reason": "камера не отвечает"}]
        return []


class RhRaising(_Plain):
    name = "rh_raising"

    def readiness(self, ctx: PluginContext) -> list[dict]:
        raise RuntimeError("секрет-путь /etc/secret.key")


class RhOutOfSpec(_Plain):
    name = "rh_outofspec"

    def readiness(self, ctx: PluginContext) -> list[dict]:
        return [{"severity": "out_of_spec", "reason": "переподключение камеры"}]


class RhConfigureBroken(_Plain):
    name = "rh_cfg_broken"

    def configure(self, ctx: PluginContext) -> None:
        raise RuntimeError("configure упал")


class RhStartBroken(_Plain):
    name = "rh_start_broken"

    def start(self, ctx: PluginContext) -> None:
        raise RuntimeError("start упал")


def _booted(*classes: type) -> tuple[PluginOrchestrator, MockProcessServices]:
    """Настоящий оркестратор + загруженные и поднятые (``boot()``) плагины; процесс «объявил готовность»."""
    services = MockProcessServices(name=_PROC)
    # ASSUMPTION: «процесс объявил готовность» оркестратор берёт из статуса носителя (``ProcessModule.run()`` ставит его
    # в ``running`` прямо перед ``_announce_ready``).
    services._current_process_status = "running"
    orch = PluginOrchestrator(services=services)
    orch.load_and_configure_managers(
        [{"plugin_class": f"{_THIS}.{c.__name__}", "plugin_name": c.name} for c in classes]
    )
    orch.boot()
    return orch, services


def _reason(node_plugin: str, severity: str, reason: str) -> dict[str, Any]:
    return {"node": f"{_PROC}.{node_plugin}", "severity": severity, "reason": reason, "source": "readiness"}


def test_default_readiness_is_empty() -> None:
    """Плагин, не переопределивший ``readiness()``, ничего не объявляет: ``[]`` (именно list)."""
    plugin = RhHealthy()
    got = plugin.readiness(PluginContext(services=MockProcessServices(name=_PROC)))
    assert got == []
    assert isinstance(got, list)


def test_failure_reason_makes_process_not_ready() -> None:
    """Здоровый плагин: ``ready`` истинно, причин нет; тот же плагин объявил ``failure``: ``ready`` ложно + причина."""
    RhToggle.failing = False
    orch, _ = _booted(RhHealthy, RhToggle)

    healthy = orch.readiness_snapshot()
    assert healthy["ready"] is True, healthy
    assert healthy["reasons"] == [], healthy
    assert isinstance(healthy["at"], float)

    RhToggle.failing = True
    try:
        failed = orch.readiness_snapshot()
    finally:
        RhToggle.failing = False
    assert failed["ready"] is False, failed
    assert failed["reasons"] == [_reason("rh_toggle", "failure", "камера не отвечает")], failed


def test_raising_readiness_becomes_failure_reason_without_exception_text() -> None:
    """``readiness()`` бросил -> ``failure`` «readiness() упал: RuntimeError»; текст исключения — в ``log_error``."""
    orch, services = _booted(RhHealthy, RhRaising)

    snap = orch.readiness_snapshot()

    assert snap["ready"] is False, snap
    assert snap["reasons"] == [_reason("rh_raising", "failure", "readiness() упал: RuntimeError")], snap
    assert "секрет-путь" not in repr(snap), (
        "текст исключения утёк в снимок (путь/значение входа не должны ехать наружу)"
    )
    errors = [rec["msg"] for rec in services.logs if rec["level"] == "ERROR"]
    assert any("секрет-путь /etc/secret.key" in msg for msg in errors), errors


def test_out_of_spec_does_not_block_ready() -> None:
    """``out_of_spec`` попадает в причины, но ``ready`` остаётся истинным (не блокирует START)."""
    orch, _ = _booted(RhHealthy, RhOutOfSpec)

    snap = orch.readiness_snapshot()

    assert snap["reasons"] == [_reason("rh_outofspec", "out_of_spec", "переподключение камеры")], snap
    assert snap["ready"] is True, snap


def test_plugin_not_running_is_failure_reason() -> None:
    """Плагин в ``IDLE`` (упал ``configure``) и в ``READY`` (упал ``start``): ``failure`` «плагин не поднят»."""
    orch, _ = _booted(RhHealthy, RhConfigureBroken, RhStartBroken)
    states = {p.name: p.state.value for p in orch.plugins}
    assert states == {"rh_healthy": "running", "rh_cfg_broken": "idle", "rh_start_broken": "ready"}, states

    snap = orch.readiness_snapshot()

    assert snap["ready"] is False, snap
    by_node = {r["node"]: r for r in snap["reasons"]}
    assert sorted(by_node) == [f"{_PROC}.rh_cfg_broken", f"{_PROC}.rh_start_broken"], snap["reasons"]
    assert len(snap["reasons"]) == 2, snap["reasons"]
    for plugin_name, state in (("rh_cfg_broken", "idle"), ("rh_start_broken", "ready")):
        reason = by_node[f"{_PROC}.{plugin_name}"]
        assert reason["severity"] == "failure", reason
        assert reason["source"] == "readiness", reason
        # ASSUMPTION: «плагин не поднят (<состояние>)», состояние — значение (idle/ready); регистр не зажат.
        assert reason["reason"].startswith("плагин не поднят ("), reason
        assert state in reason["reason"].lower(), reason
