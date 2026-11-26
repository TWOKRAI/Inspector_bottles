# -*- coding: utf-8 -*-
"""Task 2.2e (system-run-state) — слепой акцептанс ``inbox_watch``, написан до реализации (REDS 1–7).

Контракт: груз ждёт в очереди, а прогресс стоит ``inbox_stall_s`` подряд -> одна причина ``out_of_spec``.
Все ожидаемые значения — литералы спецификации, из кода под тестом ничего не берётся.

Импорт ``inbox_watch`` — внутри тестов: пока модуля нет, собираются все семь тестов и каждый падает сам.
Время — подставные часы (``clock=``), реального ожидания нет.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from multiprocess_framework.modules.process_manager_module.monitor.process_monitor import normalize_leaf
from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.health.schema import READINESS_REASONS_MAX
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

#: Причина «приём стоит».
R = {"node": "recog", "severity": "out_of_spec", "reason": "recog: кадры не принимаются", "source": "inbox"}
#: Причина «обработка стоит».
E = {"node": "recog", "severity": "out_of_spec", "reason": "recog: обработка стоит", "source": "pipeline"}
#: Причина плагина-заглушки (тест 7).
P = {"node": "recog.stub", "severity": "out_of_spec", "reason": "p", "source": "readiness"}

_BAD_KEY_TEXT = "inbox_stall_s негоден: ждали число 1.0–600.0 с или 0 — предупреждение выключено"

Poll = Callable[[float, bool, int | None, int | None], list]


def _iw() -> Any:
    import multiprocess_framework.modules.process_module.generic.inbox_watch as iw

    return iw


def _watch(text: str = "recog: кадры не принимаются", source: str = "inbox") -> Poll:
    """Новый ``InboxWatch`` со сроком 15 с на подставных часах; возвращает опрос ``(t, running, progress, depth)``."""
    iw = _iw()
    now = [0.0]
    watch = iw.InboxWatch("recog", text, source, 15.0, clock=lambda: now[0])

    def poll(t: float, running: bool, progress: int | None, depth: int | None) -> list:
        now[0] = t
        return watch.observe(running, progress, depth)

    return poll


def _times(first: float, last: float) -> list[float]:
    """Моменты ``first…last`` включительно с шагом 0,5 с."""
    return [first + 0.5 * i for i in range(int((last - first) * 2) + 1)]


def _span(poll: Poll, first: float, last: float, running: bool, progress: int | None, depth: int | None) -> list:
    """Опрос на отрезке с постоянными входами: список пар ``(t, ответ)``."""
    return [(t, poll(t, running, progress, depth)) for t in _times(first, last)]


def _assert_silent(answers: list) -> None:
    assert [(t, out) for t, out in answers if out != []] == []


def _assert_only_last_fires(answers: list) -> None:
    _assert_silent(answers[:-1])
    last_t, last_out = answers[-1]
    assert last_out == [R], f"t={last_t}"


# --------------------------------------------------------------------------- #
# 1. Разбор ключа
# --------------------------------------------------------------------------- #


def test_parse_stall_s() -> None:
    iw = _iw()

    assert iw.INBOX_STALL_KEY == "inbox_stall_s"
    for raw in (None, 0, 0.0):
        assert iw.parse_stall_s(raw) == (None, None), repr(raw)
    assert iw.parse_stall_s(15) == (15.0, None)
    assert iw.parse_stall_s(1.0) == (1.0, None)
    assert iw.parse_stall_s(600.0) == (600.0, None)
    bad = (0.5, 600.5, -1, True, "abc", float("nan"), float("inf"), 10**400, [15])
    for index, raw in enumerate(bad):
        # index вместо repr(raw): repr(10**400) в сообщении нечитаем
        value, error = iw.parse_stall_s(raw)
        assert (value, error) == (None, _BAD_KEY_TEXT), f"негодное значение №{index}"
        for echoed in ("abc", "nan", "600.5"):
            assert echoed not in error, f"негодное значение №{index}: в тексте {echoed!r}"


# --------------------------------------------------------------------------- #
# 2–6. Сторож
# --------------------------------------------------------------------------- #


def test_silent_when_not_running_or_unknown() -> None:
    _assert_silent(_span(_watch(), 1000.0, 1100.0, False, 100, 5))
    _assert_silent(_span(_watch(), 1000.0, 1030.0, True, None, 5))
    _assert_silent(_span(_watch(), 1000.0, 1030.0, True, 100, None))


def test_fires_after_stall_and_holds() -> None:
    poll = _watch()

    _assert_silent(_span(poll, 1000.0, 1014.5, True, 100, 5))
    assert poll(1015.0, True, 100, 5) == [R]
    for t, out in _span(poll, 1015.5, 1030.0, True, 100, 5):
        assert out == [R], f"t={t}"


def test_healthy_slow_idle_and_long_batch_are_silent() -> None:
    # (а) медленный, но живой потребитель: +1 в 1000.0, 1010.0, …, 1100.0
    poll = _watch()
    steps = [1000.0 + 10.0 * i for i in range(11)]
    _assert_silent([(t, poll(t, True, 100 + sum(s <= t for s in steps), 50)) for t in _times(1000.0, 1100.0)])

    # (б) простой с пустой очередью; срок считается от появления груза
    poll = _watch()
    _assert_silent(_span(poll, 1000.0, 1100.0, True, 100, 0))
    _assert_silent(_span(poll, 1100.5, 1115.0, True, 100, 1))
    assert poll(1115.5, True, 100, 1) == [R]

    # (в) длинная коллекция: +1 в 1000.0, 1014.5, 1029.0, …, 1101.5
    poll = _watch()
    steps = [1000.0 + 14.5 * i for i in range(8)]
    assert steps[-1] == 1101.5
    _assert_silent([(t, poll(t, True, 100 + sum(s <= t for s in steps), 2)) for t in _times(1000.0, 1101.5)])


def test_clears_and_restarts() -> None:
    # (а) прогресс, пустая очередь и выход из running снимают причину и начинают срок заново
    a = _watch()
    _assert_only_last_fires(_span(a, 1000.0, 1015.0, True, 100, 5))
    assert a(1015.5, True, 101, 5) == []
    _assert_only_last_fires(_span(a, 1016.0, 1030.5, True, 101, 5))
    assert a(1031.0, True, 101, 0) == []
    assert a(1031.5, False, 101, 5) == []
    _assert_only_last_fires(_span(a, 1100.0, 1115.0, True, 101, 5))

    # (б) выход из running до срабатывания обнуляет накопленный срок
    b = _watch()
    _assert_silent(_span(b, 1000.0, 1010.0, True, 100, 5))
    assert b(1010.5, False, 100, 5) == []
    _assert_silent(_span(b, 1011.0, 1025.5, True, 100, 5))
    assert b(1026.0, True, 100, 5) == [R]


def test_reason_literals_are_fresh_copies() -> None:
    # опрос с 1001.0, поэтому первая причина приходится ровно на 1016.0
    poll = _watch()
    _assert_silent(_span(poll, 1001.0, 1015.5, True, 100, 5))
    out = poll(1016.0, True, 100, 5)
    assert out == [R]
    out[0]["reason"] = "x"
    assert poll(1016.5, True, 100, 5) == [R]

    pipeline = _watch("recog: обработка стоит", "pipeline")
    _assert_silent(_span(pipeline, 1001.0, 1015.5, True, 100, 5))
    assert pipeline(1016.0, True, 100, 5) == [E]


# --------------------------------------------------------------------------- #
# 7. Оркестратор: причины процесса — первыми
# --------------------------------------------------------------------------- #


class StubPlugin(ProcessModulePlugin):
    """Плагин с одной постоянной причиной ``out_of_spec``."""

    name = "stub"
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items: list[dict]) -> list[dict]:
        return items

    def readiness(self, ctx: PluginContext) -> list[dict]:
        return [{"severity": "out_of_spec", "reason": "p"}]


def test_orchestrator_puts_process_reasons_first() -> None:
    services = MockProcessServices(name="recog")
    orch = PluginOrchestrator(services=services)
    orch.load_and_configure_managers(
        [
            {"plugin_class": "Plugins.processing.center_crop.plugin.CenterCropPlugin", "plugin_name": "center_crop"},
            {"plugin_class": f"{__name__}.StubPlugin", "plugin_name": "stub"},
        ]
    )
    orch.boot()
    try:
        assert [p.name for p in orch.plugins] == ["center_crop", "stub"]

        # (а) без причин процесса — только причина плагина
        assert orch.readiness_snapshot(announced=True)["reasons"] == [P]

        # (б) причина процесса стоит перед причинами плагинов и не блокирует готовность
        snap = orch.readiness_snapshot(announced=True, extra_reasons=[dict(R)])
        assert len(snap["reasons"]) == 2, snap["reasons"]
        assert snap["reasons"][0] == R
        assert snap["reasons"][1] == P
        assert snap["ready"] is True

        # (в) 40 причин: список обрезан, лист остаётся годным для PM
        snap = orch.readiness_snapshot(announced=True, extra_reasons=[dict(R) for _ in range(40)])
        assert READINESS_REASONS_MAX == 32
        assert len(snap["reasons"]) <= READINESS_REASONS_MAX
        assert snap["reasons"][0] == R
        assert normalize_leaf("recog", snap)["ready"] is True
    finally:
        orch.shutdown()
