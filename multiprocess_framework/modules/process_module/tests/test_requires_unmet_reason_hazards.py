# -*- coding: utf-8 -*-
"""Task 1.6 (system-run-state) — hazard-тесты причины «REQUIRES не удовлетворены» (автор реализации).

Дополняют слепые ``test_requires_unmet_reason.py``: параллельные снимки против ``boot()``, защёлка
``announced``, порядок нескольких пропущенных плагинов, потолок длины, повторный ``boot()``
(в т.ч. REQUIRES, ставшие выполненными), соседи с выполненными REQUIRES.

Ожидаемые значения — литералы; блокирующих вызовов нет, потоки — daemon с дедлайном ``join``.
"""

from __future__ import annotations

import threading

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

_THIS = "multiprocess_framework.modules.process_module.tests.test_requires_unmet_reason_hazards"
_PROC = "rh_proc"
_PREFIX = "REQUIRES не удовлетворены:"
_DEADLINE_S = 10.0


class _Plain(ProcessModulePlugin):
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items):
        return items


class RhHealthy(_Plain):
    name = "rh_healthy"
    REQUIRES = ("manager:services", "service:name")


class RhNeedsA(_Plain):
    name = "rh_needs_a"
    REQUIRES = ("manager:rh_missing_a",)


class RhNeedsB(_Plain):
    name = "rh_needs_b"
    REQUIRES = ("manager:rh_missing_b",)


class RhNeedsC(_Plain):
    name = "rh_needs_c"
    REQUIRES = ("manager:rh_missing_c",)


class RhNeedsLate(_Plain):
    """Нужен ``services.rh_late``, которого в первом ``boot()`` ещё нет."""

    name = "rh_needs_late"
    REQUIRES = ("service:rh_late",)


class RhNeedsMany(_Plain):
    """30 недостающих менеджеров: полный текст заведомо длиннее потолка в 200 символов."""

    name = "rh_needs_many"
    REQUIRES = tuple(f"manager:rh_missing_manager_{i:02d}" for i in range(30))


def _orch(*classes: type, announced: bool = True) -> tuple[PluginOrchestrator, MockProcessServices]:
    services = MockProcessServices(name=_PROC)
    if announced:
        services._current_process_status = "running"
    orch = PluginOrchestrator(services=services)
    orch.load_and_configure_managers(
        [{"plugin_class": f"{_THIS}.{c.__name__}", "plugin_name": c.name} for c in classes]
    )
    return orch, services


def _requires_nodes(snap: dict) -> list[str]:
    return [r["node"] for r in snap["reasons"] if r["reason"].startswith(_PREFIX)]


def test_parallel_snapshots_against_repeated_boot_are_consistent() -> None:
    """Снимки из нескольких потоков во время повторных ``boot()``: без исключений, причина 0 или 1, не дубль."""
    orch, _ = _orch(RhNeedsA)
    orch.boot()
    errors: list[BaseException] = []
    bad: list[list[str]] = []
    stop = threading.Event()

    def snapshots() -> None:
        try:
            while not stop.is_set():
                nodes = _requires_nodes(orch.readiness_snapshot())
                if nodes not in ([], [f"{_PROC}.rh_needs_a"]):
                    bad.append(nodes)
        except BaseException as exc:  # noqa: BLE001 — любое исключение снимка = провал теста
            errors.append(exc)

    readers = [threading.Thread(target=snapshots, daemon=True) for _ in range(4)]
    for t in readers:
        t.start()

    def boots() -> None:
        try:
            for _ in range(300):
                orch.boot()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    booter = threading.Thread(target=boots, daemon=True)
    booter.start()
    booter.join(_DEADLINE_S)
    stop.set()
    for t in readers:
        t.join(_DEADLINE_S)

    assert not booter.is_alive() and not any(t.is_alive() for t in readers), "поток завис"
    assert errors == [], errors
    assert bad == [], bad[:3]
    assert _requires_nodes(orch.readiness_snapshot()) == [f"{_PROC}.rh_needs_a"]


def test_requires_reason_does_not_touch_announced_latch() -> None:
    """Причина REQUIRES не меняет защёлку процесса: статус носителя прежний, ``announced`` решает только вызывающий."""
    orch, services = _orch(RhNeedsA)
    orch.boot()

    snap_latched = orch.readiness_snapshot()
    snap_explicit_false = orch.readiness_snapshot(announced=False)

    assert services._current_process_status == "running"
    assert snap_latched["ready"] is False and snap_explicit_false["ready"] is False
    assert _requires_nodes(snap_latched) == [f"{_PROC}.rh_needs_a"]
    # без объявления готовности причина REQUIRES всё равно видна (а не прячется за «не объявил»)
    assert _requires_nodes(snap_explicit_false) == [f"{_PROC}.rh_needs_a"]
    # снятие причины (shutdown) возвращает готовность при той же защёлке: причина не «залипла» в ней
    orch.shutdown()
    assert orch.readiness_snapshot(announced=True)["ready"] is True


def test_several_skipped_plugins_give_several_reasons_in_stable_order() -> None:
    """Три пропущенных плагина: три причины в порядке рецепта, одинаковом во всех снимках."""
    orch, _ = _orch(RhNeedsB, RhHealthy, RhNeedsA, RhNeedsC)
    orch.boot()

    expected = [f"{_PROC}.rh_needs_b", f"{_PROC}.rh_needs_a", f"{_PROC}.rh_needs_c"]
    for _ in range(3):
        assert _requires_nodes(orch.readiness_snapshot()) == expected


def test_long_requires_reason_is_capped_at_200_chars() -> None:
    """30 недостающих REQUIRES: текст причины ровно обрезан до потолка 200, префикс на месте."""
    orch, _ = _orch(RhNeedsMany)
    orch.boot()

    reasons = orch.readiness_snapshot()["reasons"]

    assert len(reasons) == 1, reasons
    assert reasons[0]["reason"].startswith(_PREFIX), reasons
    assert len(reasons[0]["reason"]) == 200, len(reasons[0]["reason"])


def test_repeated_boot_does_not_accumulate_and_drops_satisfied() -> None:
    """Повторный ``boot()``: без дублей; плагин, чьи REQUIRES стали выполненными, снимается с причин."""
    orch, services = _orch(RhNeedsA, RhNeedsLate)
    orch.boot()
    orch.boot()
    orch.boot()

    assert _requires_nodes(orch.readiness_snapshot()) == [f"{_PROC}.rh_needs_a", f"{_PROC}.rh_needs_late"]

    services.rh_late = object()  # теперь service:rh_late есть
    orch.boot()

    assert _requires_nodes(orch.readiness_snapshot()) == [f"{_PROC}.rh_needs_a"]
    assert [p.name for p in orch.plugins] == ["rh_needs_late"]


def test_neighbour_with_satisfied_requires_works_as_before() -> None:
    """Плагин с выполненными REQUIRES рядом с пропущенным: running, свои причины пусты, ``process`` работает."""
    orch, _ = _orch(RhNeedsA, RhHealthy)
    orch.boot()

    healthy = [p for p in orch.plugins if p.name == "rh_healthy"]
    assert len(healthy) == 1 and healthy[0].state.value == "running"
    assert [p.name for p in orch.plugins] == ["rh_healthy"]  # пропущенный в _plugins не попадает
    assert healthy[0].process([{"k": 1}]) == [{"k": 1}]
    reasons = orch.readiness_snapshot()["reasons"]
    assert [r["node"] for r in reasons] == [f"{_PROC}.rh_needs_a"], reasons
