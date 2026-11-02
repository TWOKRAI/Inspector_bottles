"""C-79 (hazard автора): ``_pick`` не даёт ложного WARNING о конфликте typed/extras при NaN.

H1 YAML и граница процессов, H2 разная форма, H3 глубина, H4 тождество, H8 текст WARNING
(i — рецепт с NaN в ``stop_window_s``, ii — WARNING реестра PM о негодном окне).

Захват WARNING — патч ``StdLoggerFacade.warning`` (образец: ``process_module/tests/
test_blueprint_extras.py::TestConflictWarning``): ``caplog`` здесь не годится. «Разные объекты NaN» —
только ``float("nan")``; ``math.nan`` один на модуль и маскирует дефект в контейнерах.
"""

from __future__ import annotations

import math
import pickle

import numpy as np
import pytest
import yaml

from multiprocess_framework.modules.logger_module.adapters.std_facade import StdLoggerFacade
from multiprocess_framework.modules.process_manager_module.core.process_registry import ProcessRegistry
from multiprocess_framework.modules.process_manager_module.topology.blueprint import ProcessConfig


@pytest.fixture
def warnings_captured(monkeypatch) -> list[str]:
    msgs: list[str] = []
    monkeypatch.setattr(StdLoggerFacade, "warning", lambda self, msg, *a, **kw: msgs.append(str(msg)))
    return msgs


def _conflicts(msgs: list[str]) -> list[str]:
    return [m for m in msgs if "перекрывает" in m]


def _build(**typed_and_extras) -> ProcessConfig:
    extras = typed_and_extras.pop("extras")
    return ProcessConfig(process_name="pc", process_class="m.C", extras=extras, **typed_and_extras)


_COLLECTOR_YAML = """
process_name: pc
process_class: m.C
collector: {mode: x, w: .nan}
extras:
  collector: {mode: x, w: .nan}
"""

_STOP_WINDOW_YAML = """
process_name: pc
process_class: m.C
stop_window_s: .nan
extras:
  stop_window_s: .nan
"""


def _through_pickle(d: dict) -> dict:
    """Рецепт после границы процессов: pickle не разделяет объекты float."""
    return pickle.loads(pickle.dumps(d))


# --- H1: YAML-рецепт с NaN внутри collector, как есть и после pickle -----------------------------------------


@pytest.mark.parametrize("via_pickle", [False, True], ids=["as-is", "after-pickle"])
def test_h1_yaml_collector_nan_no_conflict(warnings_captured, via_pickle):
    d = yaml.safe_load(_COLLECTOR_YAML)
    if via_pickle:
        d = _through_pickle(d)
    ProcessConfig(**d).as_generic_config()
    assert _conflicts(warnings_captured) == []


# --- H2: разная форма — конфликт остаётся, усечения zip нет --------------------------------------------------


def test_h2_dicts_with_different_keys_conflict(warnings_captured):
    cfg = _build(collector={"mode": "x", "w": float("nan")}, extras={"collector": {"mode": "x", "v": float("nan")}})
    cfg.as_generic_config()
    assert len(_conflicts(warnings_captured)) == 1


def test_h2_lists_of_different_length_conflict(warnings_captured):
    cfg = _build(stop_window_s=[float("nan")], extras={"stop_window_s": [float("nan"), float("nan")]})
    cfg.as_generic_config()
    assert len(_conflicts(warnings_captured)) == 1


def test_h2_extra_dict_key_conflict(warnings_captured):
    cfg = _build(
        io_peek={"a": [float("nan")]},
        extras={"io_peek": {"a": [float("nan")], "b": 1}},
    )
    cfg.as_generic_config()
    assert len(_conflicts(warnings_captured)) == 1


# --- H3: глубина ---------------------------------------------------------------------------------------------


def test_h3_nan_at_depth_three_no_conflict(warnings_captured):
    cfg = _build(
        io_peek={"a": [{"b": float("nan")}]},
        extras={"io_peek": {"a": [{"b": float("nan")}]}},
    )
    cfg.as_generic_config()
    assert _conflicts(warnings_captured) == []


def test_h3_nan_against_number_at_depth_three_conflict(warnings_captured):
    cfg = _build(
        io_peek={"a": [{"b": float("nan")}]},
        extras={"io_peek": {"a": [{"b": 1.0}]}},
    )
    cfg.as_generic_config()
    assert len(_conflicts(warnings_captured)) == 1


def test_h3_tuple_with_nan_from_distinct_objects_no_conflict(warnings_captured):
    cfg = _build(stop_window_s=(float("nan"),), extras={"stop_window_s": (float("nan"),)})
    cfg.as_generic_config()
    assert _conflicts(warnings_captured) == []


# --- H4: тождество — один и тот же объект не роняет сравнение ------------------------------------------------


def test_h4_same_numpy_array_does_not_raise(warnings_captured):
    arr = np.array([1.0, 2.0, 3.0])
    cfg = _build(collector={"mode": "x", "arr": arr}, extras={"collector": {"mode": "x", "arr": arr}})
    cfg.as_generic_config()
    assert _conflicts(warnings_captured) == []


def test_h4_self_referencing_dict_does_not_raise(warnings_captured):
    s: dict = {"mode": "x"}
    s["self"] = s
    cfg = _build(collector=s, extras={"collector": s})
    cfg.as_generic_config()
    assert _conflicts(warnings_captured) == []


# --- H8 (i): рецепт с NaN в stop_window_s — нет ложного WARNING, ключ дошёл до результата -------------------


@pytest.mark.parametrize("via_pickle", [False, True], ids=["as-is", "after-pickle"])
def test_h8_recipe_nan_stop_window_no_conflict_and_key_reaches_result(warnings_captured, via_pickle):
    d = yaml.safe_load(_STOP_WINDOW_YAML)
    if via_pickle:
        d = _through_pickle(d)
    result = ProcessConfig(**d).as_generic_config()
    assert _conflicts(warnings_captured) == []
    assert isinstance(result.stop_window_s, float)
    assert math.isnan(result.stop_window_s)


# --- H8 (ii): реестр PM сам пишет ОДИН WARNING о негодном окне ------------------------------------------------


class _WarnStub:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def _log_warning(self, message: str, *a, **kw) -> None:
        self.warnings.append(message)


def test_h8_registry_warns_once_about_nan_window():
    stub = _WarnStub()
    registry = ProcessRegistry(logger=stub)
    result = registry._register_stop_window("bad_w", {"stop_window_s": float("nan")})
    assert result is None
    assert len(stub.warnings) == 1
    assert "stop_window_s процесса 'bad_w' негоден" in stub.warnings[0]
