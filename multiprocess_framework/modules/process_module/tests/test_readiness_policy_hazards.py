# -*- coding: utf-8 -*-
"""Task 2.9 (system-run-state) — hazards автора: оркестратор + политика готовности узла на часах ``orch._clock``.

Слепые приёмочные тесты — ``test_readiness_policy.py``; здесь то, что ломается на стыке оркестратора и памяти
политики: упавший хук, повторный ``boot()``, память на плагин, лог негодного ключа, подкласс ``str`` из рецепта,
подпись push 3.3 в окне удержания и связь предела разрыва наблюдения с периодом снимка.

Часы — ``orch._clock = lambda: now[0]`` (реального времени и ``sleep`` нет), ``hold_s = 2.0``, шаг часов <= 2,0 с.
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_framework.modules.process_module.core.process_module import _READINESS_SNAPSHOT_PERIOD_SEC
from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.health.readiness_policy import (
    NEVER_CLEAN,
    ReadinessPolicy,
    apply_policy,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, PluginState, ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

_THIS = "multiprocess_framework.modules.process_module.tests.test_readiness_policy_hazards"
_PROC = "rph_proc"
_HOLD = {"hold_s": 2.0}


class _Plain(ProcessModulePlugin):
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items):
        return items


class RphToggle(_Plain):
    """Режим читается живым классовым состоянием: ``clean`` / ``failure`` / ``oos`` / ``raise`` / ``bad``."""

    name = "rph_toggle"
    mode = "clean"

    def readiness(self, ctx: PluginContext) -> list[dict]:
        if RphToggle.mode == "raise":
            raise RuntimeError("boom")
        if RphToggle.mode == "bad":
            return "bad"  # type: ignore[return-value]  # неверная форма хука
        if RphToggle.mode == "failure":
            return [{"severity": "failure", "reason": "x"}]
        if RphToggle.mode == "oos":
            return [{"severity": "out_of_spec", "reason": "x"}]
        return []


class RphSecond(_Plain):
    """Второй плагин процесса: свой режим, своя память политики."""

    name = "rph_second"
    mode = "failure"

    def readiness(self, ctx: PluginContext) -> list[dict]:
        if RphSecond.mode == "failure":
            return [{"severity": "failure", "reason": "x"}]
        return []


@pytest.fixture(autouse=True)
def _reset_modes():
    RphToggle.mode = "clean"
    RphSecond.mode = "failure"
    yield
    RphToggle.mode = "clean"
    RphSecond.mode = "failure"


def _booted(*classes: type, readiness: Any) -> tuple[PluginOrchestrator, MockProcessServices, list[float]]:
    """Настоящий оркестратор + поднятые плагины; ``readiness`` — плоский ключ в определении КАЖДОГО плагина."""
    return _booted_defs(
        [{"plugin_class": f"{_THIS}.{c.__name__}", "plugin_name": c.name, "readiness": readiness} for c in classes]
    )


def _booted_defs(definitions: list[dict]) -> tuple[PluginOrchestrator, MockProcessServices, list[float]]:
    """То же, что ``_booted``, но определения плагинов заданы целиком (вложенный ``config``, одинаковые имена)."""
    services = MockProcessServices(name=_PROC)
    services._current_process_status = "running"
    orch = PluginOrchestrator(services=services)
    now = [0.0]
    orch._clock = lambda: now[0]
    orch.load_and_configure_managers(definitions)
    orch.boot()
    return orch, services, now


def _snap(orch: PluginOrchestrator, now: list[float], at: float) -> dict:
    now[0] = at
    return orch.readiness_snapshot()


def _severity_of(snap: dict, plugin: str) -> str:
    found = [r["severity"] for r in snap["reasons"] if r["node"] == f"{_PROC}.{plugin}"]
    assert len(found) == 1, snap["reasons"]
    return found[0]


def _make_clean_for_hold(orch: PluginOrchestrator, now: list[float]) -> None:
    assert _snap(orch, now, 0.0)["reasons"] == []
    assert _snap(orch, now, 2.0)["reasons"] == []


def test_hook_failure_resets_memory() -> None:
    """Хук упал при 2.5: память -> NEVER_CLEAN, свой failure при 3.0 не удерживается (был бы out_of_spec)."""
    orch, _, now = _booted(RphToggle, readiness=_HOLD)
    _make_clean_for_hold(orch, now)

    RphToggle.mode = "raise"
    assert _severity_of(_snap(orch, now, 2.5), "rph_toggle") == "failure"
    RphToggle.mode = "failure"
    assert _severity_of(_snap(orch, now, 3.0), "rph_toggle") == "failure"


def test_invalid_policy_logged_once() -> None:
    """Негодный ключ: 10 снимков — ровно одна ERROR «политика readiness негодна» (кэш по ``key in dict``)."""
    RphToggle.mode = "oos"
    orch, services, now = _booted(RphToggle, readiness={"hold": 2.0})
    for i in range(10):
        _snap(orch, now, i * 0.5)
    errors = [e for e in services.logs if e["level"] == "ERROR" and "политика readiness негодна" in e["msg"]]
    assert len(errors) == 1, services.logs


def test_reboot_resets_cache_and_memory() -> None:
    """Повторный ``boot()`` обнуляет память: узел снова «ни разу не чист», потеря не удерживается."""
    orch, _, now = _booted(RphToggle, readiness=_HOLD)
    _make_clean_for_hold(orch, now)

    orch.boot()
    # Допущение теста: повторный boot() поднимает уже работавший плагин в RUNNING; иначе тест ничего не проверяет.
    assert orch._plugins[0].state is PluginState.RUNNING

    RphToggle.mode = "failure"
    assert _severity_of(_snap(orch, now, 2.5), "rph_toggle") == "failure"


def test_memory_is_per_plugin() -> None:
    """Два плагина: память у каждого своя; B (всегда failure) не удерживается, A после чистоты — да."""
    orch, _, now = _booted(RphToggle, RphSecond, readiness=_HOLD)
    RphToggle.mode = "clean"
    for at in (0.0, 2.0):
        snap = _snap(orch, now, at)
        assert _severity_of(snap, "rph_second") == "failure"
        assert [r for r in snap["reasons"] if r["node"] == f"{_PROC}.rph_toggle"] == []

    RphToggle.mode = "failure"
    snap = _snap(orch, now, 2.5)
    assert _severity_of(snap, "rph_toggle") == "out_of_spec"
    assert _severity_of(snap, "rph_second") == "failure"


def test_str_subclass_in_recipe_is_normalized() -> None:
    """Ключи/значения ``severity`` — подкласс ``str``: наружу уходит встроенный ``str`` с нужным значением."""

    class S(str):
        pass

    RphToggle.mode = "oos"
    raw = {"severity": {S("out_of_spec"): S("check_function")}}
    orch, _, now = _booted(RphToggle, readiness=raw)
    snap = _snap(orch, now, 0.0)
    (reason,) = snap["reasons"]
    assert reason["severity"] == "check_function"
    assert type(reason["severity"]) is str


def test_hold_window_keeps_push_signature() -> None:
    """Окно удержания: потеря = ``out_of_spec`` без failure/check_function (подпись push 3.3 неизменна), ready True."""
    orch, _, now = _booted(RphToggle, readiness=_HOLD)
    _make_clean_for_hold(orch, now)

    RphToggle.mode = "failure"
    snap = _snap(orch, now, 2.5)
    assert _severity_of(snap, "rph_toggle") == "out_of_spec"
    assert snap["ready"] is True
    assert not [r for r in snap["reasons"] if r["severity"] in ("failure", "check_function")]

    snap = _snap(orch, now, 4.5)
    assert _severity_of(snap, "rph_toggle") == "failure"
    assert snap["ready"] is False


def test_gap_limit_covers_snapshot_period() -> None:
    """Предел разрыва наблюдения не меньше трёх тактов снимка: рост периода без правки предела ловится здесь."""
    from multiprocess_framework.modules.process_module.health.readiness_policy import OBSERVATION_GAP_MAX_S

    assert OBSERVATION_GAP_MAX_S >= 3 * _READINESS_SNAPSHOT_PERIOD_SEC


def test_bad_shape_resets_memory() -> None:
    """Хук вернул неверную форму при 2.5: память -> NEVER_CLEAN, свой failure при 3.0 не удерживается."""
    orch, _, now = _booted(RphToggle, readiness=_HOLD)
    _make_clean_for_hold(orch, now)

    RphToggle.mode = "bad"
    assert _severity_of(_snap(orch, now, 2.5), "rph_toggle") == "failure"
    RphToggle.mode = "failure"
    assert _severity_of(_snap(orch, now, 3.0), "rph_toggle") == "failure"


def test_expired_window_is_not_rearmed() -> None:
    """Окно истекло (4.5), потеря длится: история чистоты обнулена, failure не прячется снова (хвост до 8.0)."""
    F, O = [("failure", "x")], [("out_of_spec", "x")]  # noqa: E741
    memory = NEVER_CLEAN
    outs = []
    steps = [(0.0, []), (2.0, []), (2.5, F), (4.0, F), (4.5, F), (5.0, F), (5.5, F), (8.0, F)]
    for at, items in steps:
        out, memory = apply_policy(items, ReadinessPolicy(hold_s=2.0), memory, at)
        outs.append(out)
    assert outs == [[], [], O, O, F, F, F, F]


def test_remap_then_hold_uses_remapped_severity() -> None:
    """Сначала ремап, потом удержание: failure->maintenance не блокирует, check_function удерживается."""
    policy = ReadinessPolicy(hold_s=2.0, remap=(("failure", "maintenance"),))
    items = [("failure", "a"), ("check_function", "b")]
    memory = NEVER_CLEAN
    outs = []
    for at, step in [(0.0, []), (2.0, []), (2.5, items), (4.5, items)]:
        out, memory = apply_policy(step, policy, memory, at)
        outs.append(out)
    assert outs[2] == [("maintenance", "a"), ("out_of_spec", "b")]
    assert outs[3] == [("maintenance", "a"), ("check_function", "b")]


def test_hold_arms_at_exact_hold_boundary() -> None:
    """Чист ровно ``hold_s`` (0.0 -> 2.0): потеря на границе уже удерживается (``>=``)."""
    policy = ReadinessPolicy(hold_s=2.0)
    _, memory = apply_policy([], policy, NEVER_CLEAN, 0.0)
    out, _ = apply_policy([("failure", "x")], policy, memory, 2.0)
    assert out == [("out_of_spec", "x")]


def test_gap_exactly_at_limit_is_still_observation() -> None:
    """Разрыв ровно 2.5 с (2.0 -> 4.5) ещё наблюдение: чистота с 0.0 не сброшена, потеря удержана (``>``, не ``>=``)."""
    memory = NEVER_CLEAN
    outs = []
    for at, items in [(0.0, []), (2.0, []), (4.5, [("failure", "x")])]:
        out, memory = apply_policy(items, ReadinessPolicy(hold_s=2.0), memory, at)
        outs.append(out)
    assert outs[-1] == [("out_of_spec", "x")]


def test_same_name_plugins_keep_separate_memory() -> None:
    """Два плагина с одним ``name`` и разным конфигом (hold 2.0 и 5.0): память и политика по ``id``, не по имени."""
    cls = f"{_THIS}.RphToggle"
    orch, _, now = _booted_defs(
        [
            {"plugin_class": cls, "plugin_name": "rph_toggle", "readiness": {"hold_s": 2.0}},
            {"plugin_class": cls, "plugin_name": "rph_toggle", "readiness": {"hold_s": 5.0}},
        ]
    )
    _make_clean_for_hold(orch, now)

    RphToggle.mode = "failure"
    snap = _snap(orch, now, 2.5)
    assert [r["severity"] for r in snap["reasons"]] == ["out_of_spec", "failure"]


def test_nested_config_readiness_key_is_applied() -> None:
    """Вложенная форма ``config: {readiness: ...}`` (рецепт после GUI): годный ключ держит, негодный — config."""
    cls = f"{_THIS}.RphToggle"
    orch, _, now = _booted_defs(
        [{"plugin_class": cls, "plugin_name": "rph_toggle", "config": {"readiness": {"hold_s": 2.0}}}]
    )
    _make_clean_for_hold(orch, now)
    RphToggle.mode = "failure"
    assert _severity_of(_snap(orch, now, 2.5), "rph_toggle") == "out_of_spec"

    orch, services, now = _booted_defs(
        [{"plugin_class": cls, "plugin_name": "rph_toggle", "config": {"readiness": {"hold": 2.0}}}]
    )
    snap = _snap(orch, now, 0.0)
    assert [(r["severity"], r["source"]) for r in snap["reasons"]] == [("failure", "config"), ("failure", "readiness")]
    assert len([e for e in services.logs if "политика readiness негодна" in e["msg"]]) == 1
