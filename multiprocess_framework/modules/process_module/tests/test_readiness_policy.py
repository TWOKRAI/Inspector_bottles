# -*- coding: utf-8 -*-
"""Task 2.9 (system-run-state) — слепые приёмочные тесты политики готовности узла.

Ключ ``readiness: {hold_s, severity}`` в определении плагина. Чистая часть: модуль
``health.readiness_policy`` (``ReadinessPolicy``, ``NEVER_CLEAN``, ``parse_policy``, ``apply_policy``);
оркестраторная часть: ``PluginOrchestrator.readiness_snapshot()``.

Ожидаемые значения — литералы. Реального времени и ``sleep`` нет: удержание проверяется чистыми тестами с
внешними часами. Импорт нового модуля — внутри тестов (на базе иначе упал бы весь файл).
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

_THIS = "multiprocess_framework.modules.process_module.tests.test_readiness_policy"
_PROC = "rp_proc"

F = [("failure", "x")]
O = [("out_of_spec", "x")]  # noqa: E741

_CONFIG_REASON = "политика readiness в рецепте негодна"


class _Plain(ProcessModulePlugin):
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items):
        return items


class RpOos(_Plain):
    name = "rp_oos"

    def readiness(self, ctx: PluginContext) -> list[dict]:
        return [{"severity": "out_of_spec", "reason": "b"}]


class RpTwo(_Plain):
    name = "rp_two"

    def readiness(self, ctx: PluginContext) -> list[dict]:
        return [{"severity": "failure", "reason": "a"}, {"severity": "out_of_spec", "reason": "b"}]


class RpRaise(_Plain):
    name = "rp_raise"

    def readiness(self, ctx: PluginContext) -> list[dict]:
        raise RuntimeError("boom")


class RpBad(_Plain):
    name = "rp_bad"

    def readiness(self, ctx: PluginContext):
        return "bad"


_MISSING = object()


def _snapshot(cls: type, raw: Any = _MISSING) -> dict:
    """Свежий оркестратор с одним плагином (``raw`` — плоский ключ ``readiness``, если задан) -> снимок готовности."""
    services = MockProcessServices(name=_PROC)
    services._current_process_status = "running"
    orch = PluginOrchestrator(services=services)
    definition: dict[str, Any] = {"plugin_class": f"{_THIS}.{cls.__name__}", "plugin_name": cls.name}
    if raw is not _MISSING:
        definition["readiness"] = raw
    orch.load_and_configure_managers([definition])
    orch.boot()
    return orch.readiness_snapshot()


def _item(plugin: str, severity: str, reason: str, source: str = "readiness") -> dict[str, Any]:
    return {"node": f"{_PROC}.{plugin}", "severity": severity, "reason": reason, "source": source}


def _run(policy: Any, steps: list[tuple[float, list[tuple[str, str]]]]) -> list[list[tuple[str, str]]]:
    from multiprocess_framework.modules.process_module.health.readiness_policy import NEVER_CLEAN, apply_policy

    memory = NEVER_CLEAN
    outs = []
    for now, items in steps:
        out, memory = apply_policy(items, policy, memory, now)
        outs.append(out)
    return outs


def _policy(hold_s: float = 2.0):
    from multiprocess_framework.modules.process_module.health.readiness_policy import ReadinessPolicy

    return ReadinessPolicy(hold_s=hold_s)


def test_boot_loss_is_not_held() -> None:
    """Узел ни разу не был чистым: потеря на первом вызове показывается своей степенью."""
    assert _run(_policy(), [(0.0, F)]) == [F]


def test_loss_after_clean_hold_is_held_until_expiry() -> None:
    """Чист 2.0 с, потеря при 2.5: out_of_spec до 4.5 (hold 2.0 от первой потери), затем своя степень."""
    steps = [(0.0, []), (2.0, []), (2.5, F), (4.0, F), (4.5, F)]
    assert _run(_policy(), steps) == [[], [], O, O, F]


def test_blink_shorter_than_hold_is_not_hidden() -> None:
    """Возврат в чистое закрывает окно; следующая потеря удерживается, только если снова было чисто hold_s."""
    a = [(0.0, []), (2.0, []), (2.5, F), (3.0, []), (3.5, F)]
    assert _run(_policy(), a) == [[], [], O, [], F]

    b = [(0.0, []), (2.0, []), (2.5, F), (3.0, []), (3.5, []), (4.5, []), (5.5, []), (6.0, F)]
    assert _run(_policy(), b) == [[], [], O, [], [], [], [], O]


def test_severity_remap_keeps_text_and_order() -> None:
    """``severity`` переназначает степень; текст и порядок причин не меняются."""
    from multiprocess_framework.modules.process_module.health.readiness_policy import (
        NEVER_CLEAN,
        apply_policy,
        parse_policy,
    )

    items = [
        ("out_of_spec", "модель не загружена: кадры идут без распознавания"),
        ("failure", "a"),
        ("maintenance", "m"),
    ]
    out = apply_policy(items, parse_policy({"severity": {"out_of_spec": "check_function"}}), NEVER_CLEAN, 0.0)[0]
    assert out == [
        ("check_function", "модель не загружена: кадры идут без распознавания"),
        ("failure", "a"),
        ("maintenance", "m"),
    ]


@pytest.mark.timeout(60)
def test_framework_reasons_bypass_policy() -> None:
    """Причины фреймворка («упал», «неверная форма») политику не проходят, даже при ремапе failure."""
    raw = {"severity": {"failure": "out_of_spec"}}

    snap = _snapshot(RpRaise, raw)
    assert snap["reasons"] == [_item("rp_raise", "failure", "readiness() упал: RuntimeError")]
    assert snap["ready"] is False

    snap = _snapshot(RpBad, raw)
    assert snap["reasons"] == [_item("rp_bad", "failure", "readiness() вернул неверную форму")]
    assert snap["ready"] is False


@pytest.mark.timeout(60)
def test_invalid_policy_fails_closed_with_config_reason() -> None:
    """Негодный ключ: первой идёт failure/config «политика негодна», затем свои причины без изменений."""
    bad_raws = [
        5,
        {"hold_s": -1},
        {"hold_s": True},
        {"hold_s": "2"},
        {"hold_s": None},
        {"hold_s": 10.5},
        {"hold_s": float("nan")},
        {"hold_s": float("inf")},
        {"hold_s": 10**400},
        {"hold": 2.0},
        {"severity": ["x"]},
        {"severity": {"out_of_spec": "blocker"}},
        {"severity": {"blocker": "failure"}},
    ]
    for raw in bad_raws:
        snap = _snapshot(RpOos, raw)
        assert snap["reasons"] == [
            _item("rp_oos", "failure", _CONFIG_REASON, source="config"),
            _item("rp_oos", "out_of_spec", "b"),
        ], raw
        assert snap["ready"] is False, raw

    from multiprocess_framework.modules.process_module.health.readiness_policy import parse_policy

    for raw in bad_raws:
        assert isinstance(parse_policy(raw), str), raw


@pytest.mark.timeout(60)
def test_valid_policies_add_no_config_reason() -> None:
    """Годные ключи (умолчания, границы) не добавляют причину config; out_of_spec не блокирует."""
    good_raws = [None, {}, {"hold_s": 0}, {"hold_s": 10.0}, {"severity": {}}]
    for raw in good_raws:
        snap = _snapshot(RpOos, raw)
        assert snap["reasons"] == [_item("rp_oos", "out_of_spec", "b")], raw
        assert snap["ready"] is True, raw

    from multiprocess_framework.modules.process_module.health.readiness_policy import (
        ReadinessPolicy,
        parse_policy,
    )

    for raw in good_raws:
        assert isinstance(parse_policy(raw), ReadinessPolicy), raw


@pytest.mark.timeout(60)
def test_default_policy_equals_no_key() -> None:
    """Умолчания (``{hold_s: 0.0, severity: {}}``, ``{}``, ``None``) ведут себя как без ключа и не удерживают."""
    expected = [_item("rp_two", "failure", "a"), _item("rp_two", "out_of_spec", "b")]
    assert _snapshot(RpTwo, {"hold_s": 0.0, "severity": {}})["reasons"] == expected
    assert _snapshot(RpTwo)["reasons"] == expected

    from multiprocess_framework.modules.process_module.health.readiness_policy import parse_policy

    steps = [(0.0, []), (2.0, []), (2.5, F)]
    assert _run(parse_policy({}), steps) == [[], [], F]
    assert _run(parse_policy(None), steps) == [[], [], F]


def test_observation_gap_resets_clean_history() -> None:
    """Пауза между вызовами больше 2,5 с обнуляет историю чистоты; пауза в 2,0 с — нет."""
    # (а) пауза 3.0 с между 2.0 и 5.0: чистота обнулена, потеря не удерживается
    a = [(0.0, []), (2.0, []), (5.0, F)]
    assert _run(_policy(), a)[-1] == F

    # (б) паузы по 2.0 с не обнуляют: чист с 0.0 до 4.0, потеря удерживается
    b = [(0.0, []), (2.0, []), (4.0, []), (4.5, F)]
    assert _run(_policy(), b)[-1] == O

    # (в) hold 5.0: 11 чистых вызовов 0.0..5.0, потеря удержана; пауза 3.0 с (6.0 -> 9.0) обнуляет историю
    c: list[tuple[float, list[tuple[str, str]]]] = [(i * 0.5, []) for i in range(11)]
    c += [(5.5, F), (6.0, F), (9.0, F)]
    outs = _run(_policy(hold_s=5.0), c)
    assert outs[11] == O and outs[12] == O
    assert outs[-1] == F


@pytest.mark.timeout(60)
def test_remapped_check_function_blocks_ready() -> None:
    """Ремап out_of_spec -> check_function делает узел блокирующим: ``ready`` ложно."""
    snap = _snapshot(RpOos)
    assert snap["reasons"] == [_item("rp_oos", "out_of_spec", "b")]
    assert snap["ready"] is True

    snap = _snapshot(RpOos, {"severity": {"out_of_spec": "check_function"}})
    assert snap["reasons"] == [_item("rp_oos", "check_function", "b")]
    assert snap["ready"] is False
