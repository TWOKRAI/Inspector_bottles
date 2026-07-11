"""Тесты реестра step-миграций (migrations.migration / registered_steps / run_chain).

ADR-RCP-003 (C2). Покрытие:
- декоратор регистрирует шаг под (doc_type, from_, to), различая одноимённые
  шаги разных doc_type (namespace, дубль D6);
- run_chain прогоняет цепочку шагов v → v+1 → ... → target;
- property-тесты round-trip: идемпотентность (from_version == to_version — no-op)
  и сохранение неизвестных ключей сквозь цепочку шагов.

Хайпотезис недоступен в окружении (.venv без hypothesis, пакеты не ставим —
правило владельца) — property-тесты написаны вручную широкой параметризацией.
"""

from __future__ import annotations

import copy

import pytest

from multiprocess_framework.modules.recipe.migrations import (
    migration,
    registered_steps,
    run_chain,
)

# --------------------------------------------------------------------------
# Синтетические шаги под изолированные test-doc_type — не пересекаются с
# реальными doc_type домена (recipe.config_snapshot / recipe.file_format),
# чтобы тесты не зависели от состояния глобального реестра, засеянного
# импортом прикладных модулей.
# --------------------------------------------------------------------------


def _int_or_zero(value: object) -> int:
    # Синтетический шаг работает с произвольными dict-сэмплами (в т.ч. "a": None) —
    # нечисловое значение "a" считаем отсутствующим (0), как обычный migration-шаг
    # трактовал бы неожиданный legacy-тип поля.
    return value if isinstance(value, int) else 0


@migration("test.chain_a", from_=1, to=2)
def _step_a_1_to_2(data: dict) -> dict:
    result = dict(data)
    result["a"] = _int_or_zero(result.get("a")) + 1
    return result


@migration("test.chain_a", from_=2, to=3)
def _step_a_2_to_3(data: dict) -> dict:
    result = dict(data)
    result["a"] = _int_or_zero(result.get("a")) + 10
    return result


def test_migration_decorator_registers_step() -> None:
    # given декоратор @migration зарегистрировал шаг под test.chain_a
    steps = registered_steps("test.chain_a")
    # then оба шага на месте под своими (from_, to)
    assert steps[(1, 2)] is _step_a_1_to_2
    assert steps[(2, 3)] is _step_a_2_to_3


def test_migration_decorator_returns_function_unchanged() -> None:
    # given декоратор — прозрачен для прямого вызова функции
    assert _step_a_1_to_2({"a": 0}) == {"a": 1}


def test_registered_steps_empty_for_unknown_doc_type() -> None:
    assert registered_steps("test.does_not_exist") == {}


def test_two_same_named_steps_different_doc_type_do_not_collide() -> None:
    # given два шага с одинаковым python-именем функции под РАЗНЫМИ doc_type
    @migration("test.ns_one", from_=1, to=2)
    def v1_to_v2(data: dict) -> dict:  # noqa: N802 — имитация одноимённого шага
        result = dict(data)
        result["marker"] = "ns_one"
        return result

    @migration("test.ns_two", from_=1, to=2)
    def v1_to_v2(data: dict) -> dict:  # noqa: N802,F811 — другой doc_type, не конфликт
        result = dict(data)
        result["marker"] = "ns_two"
        return result

    # then реестр различает их по doc_type (namespace в ключе)
    assert registered_steps("test.ns_one")[(1, 2)]({}) == {"marker": "ns_one"}
    assert registered_steps("test.ns_two")[(1, 2)]({}) == {"marker": "ns_two"}


def test_migration_rejects_from_gte_to() -> None:
    with pytest.raises(ValueError):

        @migration("test.invalid", from_=2, to=2)
        def _step(data: dict) -> dict:
            return data


def test_migration_rejects_empty_doc_type() -> None:
    with pytest.raises(ValueError):

        @migration("", from_=1, to=2)
        def _step(data: dict) -> dict:
            return data


# --------------------------------------------------------------------------
# run_chain — цепочечный раннер
# --------------------------------------------------------------------------


def test_run_chain_applies_steps_in_order() -> None:
    # given data на версии 1, цель — версия 3 (два шага: +1, затем +10)
    result = run_chain("test.chain_a", {"a": 0}, from_version=1, to_version=3)
    assert result == {"a": 11}


def test_run_chain_single_step() -> None:
    result = run_chain("test.chain_a", {"a": 0}, from_version=1, to_version=2)
    assert result == {"a": 1}


def test_run_chain_missing_step_raises() -> None:
    with pytest.raises(RuntimeError):
        run_chain("test.chain_a", {"a": 0}, from_version=1, to_version=99)


def test_run_chain_from_greater_than_to_raises() -> None:
    with pytest.raises(ValueError):
        run_chain("test.chain_a", {"a": 0}, from_version=3, to_version=1)


# --------------------------------------------------------------------------
# Property: идемпотентность (повторный прогон уже мигрированных данных — no-op)
# --------------------------------------------------------------------------

_IDEMPOTENCE_SAMPLES: list[dict] = [
    {},
    {"a": 1},
    {"a": 1, "b": {"nested": True}},
    {"unknown_key": "value", "list_field": [1, 2, 3]},
    {"a": None, "b": 0, "c": False, "d": ""},
    {"deep": {"deeper": {"deepest": [1, {"x": "y"}]}}},
]


@pytest.mark.parametrize("sample", _IDEMPOTENCE_SAMPLES)
def test_run_chain_no_op_when_from_equals_to(sample: dict) -> None:
    # given from_version == to_version (данные уже на целевой версии)
    # then run_chain — no-op: тот же объект, без изменений (широкая параметризация
    # вместо Hypothesis — пакет недоступен в окружении, ставить запрещено)
    result = run_chain("test.chain_a", sample, from_version=2, to_version=2)
    assert result is sample
    assert result == sample


@pytest.mark.parametrize("sample", _IDEMPOTENCE_SAMPLES)
def test_run_chain_applied_twice_from_target_version_is_stable(sample: dict) -> None:
    # given данные мигрированы один раз до целевой версии
    once = run_chain("test.chain_a", copy.deepcopy(sample), from_version=1, to_version=3)
    # then повторный прогон "уже на целевой версии" (from == to == текущая) — no-op
    twice = run_chain("test.chain_a", once, from_version=3, to_version=3)
    assert twice == once


# --------------------------------------------------------------------------
# Property: неизвестные ключи проходят миграцию нетронутыми
# --------------------------------------------------------------------------

_UNKNOWN_KEY_SAMPLES: list[dict] = [
    {"junk": "keep-me"},
    {"junk": {"nested": [1, 2, 3]}},
    {"junk": None},
    {"junk": 0},
    {"junk": [], "other_junk": {}},
]


@pytest.mark.parametrize("sample", _UNKNOWN_KEY_SAMPLES)
def test_run_chain_preserves_unknown_keys(sample: dict) -> None:
    # given шаги chain_a трогают только ключ "a"; произвольный "junk" им неизвестен
    data = {"a": 0, **sample}
    result = run_chain("test.chain_a", data, from_version=1, to_version=3)
    # then junk-ключи дошли до конца цепочки нетронутыми
    for key, value in sample.items():
        assert result[key] == value
    assert result["a"] == 11
