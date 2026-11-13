# -*- coding: utf-8 -*-
"""Task 1.6 (system-run-state) — слепые тесты: невыполненные ``REQUIRES`` видны в снимке готовности.

Требование (из брифа, реализации нет): плагин, у которого ``check_requires`` даёт непустой список (сегодня
``PluginOrchestrator.boot()`` молча пропускает его с ``log_error``), должен давать в
``readiness_snapshot()`` причину ``severity="failure"``, ``reason`` начинается с «REQUIRES не удовлетворены:» и
перечисляет недостающее; ``ready`` ложно (процесс объявил готовность). Плагин с выполненными REQUIRES лишней причины
не даёт; процесс/оркестратор не падает, соседи работают как раньше; повторный снимок не плодит дублей;
после ``shutdown()`` причина пропадает.

Решения тестера (``# ASSUMPTION``, подробности в отчёте):
  * ``node`` причины = ``<процесс>.<имя плагина>``, ``source`` = ``"readiness"`` (как у остальных причин снимка);
  * «процесс объявил готовность» = ``services._current_process_status = "running"`` (как в test_readiness_hook.py);
  * перечисление недостающего — подстроки литералов ``manager:<attr>`` / ``service:<name>`` (формат ``check_requires``),
    порядок и разделитель не зажаты; весь ``reason`` короче лимита 200 символов (подстроки не должны обрезаться);
  * попадает ли пропущенный плагин в ``orch.plugins`` — НЕ проверяется (контракт не говорит).

Ожидаемые значения — литералы. Блокирующих вызовов нет (оркестратор синхронный).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

_THIS = "multiprocess_framework.modules.process_module.tests.test_requires_unmet_reason"
_PROC = "ru_proc"
_PREFIX = "REQUIRES не удовлетворены:"


class _Plain(ProcessModulePlugin):
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items):
        return items


class RuHealthy(_Plain):
    name = "ru_healthy"


class RuNeedsTwo(_Plain):
    """Два недостающих требования: менеджера и сервиса, которых у носителя нет."""

    name = "ru_needs_two"
    REQUIRES = ("manager:ru_no_such_manager", "service:ru_no_such_service")


class RuNeedsOne(_Plain):
    name = "ru_needs_one"
    REQUIRES = ("manager:ru_other_missing",)


class RuSatisfied(_Plain):
    """REQUIRES выполнены: ``ctx.services`` и ``services.name`` у носителя есть."""

    name = "ru_satisfied"
    REQUIRES = ("manager:services", "service:name")


class RuFailing(_Plain):
    """Здоровый по REQUIRES, но сам объявляет ``failure`` через ``readiness()``."""

    name = "ru_failing"

    def readiness(self, ctx: PluginContext) -> list[dict]:
        return [{"severity": "failure", "reason": "камера не отвечает"}]


def _booted(*classes: type) -> tuple[PluginOrchestrator, MockProcessServices]:
    """Настоящий оркестратор + ``boot()``; процесс «объявил готовность»."""
    services = MockProcessServices(name=_PROC)
    # ASSUMPTION: «процесс объявил готовность» оркестратор берёт из статуса носителя.
    services._current_process_status = "running"
    orch = PluginOrchestrator(services=services)
    orch.load_and_configure_managers(
        [{"plugin_class": f"{_THIS}.{c.__name__}", "plugin_name": c.name} for c in classes]
    )
    orch.boot()
    return orch, services


def _requires_reasons(snap: dict) -> list[dict]:
    return [r for r in snap["reasons"] if "REQUIRES" in r["reason"]]


def test_unmet_requires_gives_failure_reason_and_blocks_ready() -> None:
    """Невыполненные REQUIRES: ровно одна причина ``failure`` с префиксом и перечислением; ``ready`` ложно."""
    orch, _ = _booted(RuHealthy, RuNeedsTwo)

    snap = orch.readiness_snapshot()

    assert snap["ready"] is False, snap
    assert len(snap["reasons"]) == 1, snap["reasons"]
    reason = snap["reasons"][0]
    assert reason["node"] == f"{_PROC}.ru_needs_two", reason
    assert reason["severity"] == "failure", reason
    assert reason["source"] == "readiness", reason
    assert reason["reason"].startswith(_PREFIX), reason
    assert "manager:ru_no_such_manager" in reason["reason"], reason
    assert "service:ru_no_such_service" in reason["reason"], reason
    assert len(reason["reason"]) <= 200, reason


def test_satisfied_requires_adds_no_reason() -> None:
    """Охранный (зелёный и до реализации): плагин с выполненными REQUIRES не даёт причины, ``ready`` истинно."""
    orch, _ = _booted(RuSatisfied)
    assert [p.state.value for p in orch.plugins] == ["running"]

    snap = orch.readiness_snapshot()

    assert snap["reasons"] == [], snap
    assert snap["ready"] is True, snap


def test_unmet_requires_does_not_break_neighbours() -> None:
    """Два плагина с невыполненными REQUIRES + плагин с собственным ``failure`` + здоровый: у каждого своя причина."""
    orch, services = _booted(RuHealthy, RuNeedsTwo, RuFailing, RuNeedsOne)

    snap = orch.readiness_snapshot()  # не бросает

    assert snap["ready"] is False, snap
    by_node = {r["node"]: r for r in snap["reasons"]}
    assert sorted(by_node) == [f"{_PROC}.ru_failing", f"{_PROC}.ru_needs_one", f"{_PROC}.ru_needs_two"], snap["reasons"]
    assert len(snap["reasons"]) == 3, snap["reasons"]
    assert by_node[f"{_PROC}.ru_failing"]["reason"] == "камера не отвечает", snap["reasons"]
    assert by_node[f"{_PROC}.ru_needs_one"]["reason"].startswith(_PREFIX), snap["reasons"]
    assert "manager:ru_other_missing" in by_node[f"{_PROC}.ru_needs_one"]["reason"], snap["reasons"]
    assert by_node[f"{_PROC}.ru_needs_two"]["reason"].startswith(_PREFIX), snap["reasons"]
    # соседи по-прежнему подняты и работают
    states = {p.name: p.state.value for p in orch.plugins if p.name in ("ru_healthy", "ru_failing")}
    assert states == {"ru_healthy": "running", "ru_failing": "running"}, states
    assert services._current_process_status == "running"


def test_repeated_snapshot_does_not_duplicate_requires_reason() -> None:
    """Три снимка подряд: в каждом ровно одна причина REQUIRES (не копится от вызова к вызову)."""
    orch, _ = _booted(RuHealthy, RuNeedsTwo)

    counts = [len(_requires_reasons(orch.readiness_snapshot())) for _ in range(3)]

    assert counts == [1, 1, 1], counts


def test_requires_reason_disappears_after_shutdown() -> None:
    """До ``shutdown()`` причина есть (иначе тест ничего не доказывает); после — её нет."""
    orch, _ = _booted(RuHealthy, RuNeedsTwo)
    before = orch.readiness_snapshot()
    assert len(_requires_reasons(before)) == 1, before

    orch.shutdown()

    after = orch.readiness_snapshot()
    assert _requires_reasons(after) == [], after
    assert all(r["node"] != f"{_PROC}.ru_needs_two" for r in after["reasons"]), after
