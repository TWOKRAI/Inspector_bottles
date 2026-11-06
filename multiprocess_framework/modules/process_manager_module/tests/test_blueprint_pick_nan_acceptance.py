"""C-79: ложное WARNING «typed-поле перекрывает extras», когда значения равны по NaN.

Слепые приёмочные тесты. Контракт: рецепт задаёт и typed-поле ``ProcessConfig``, и одноимённый
ключ в ``extras`` — при расхождении пишется WARNING «typed-поле перекрывает extras»; при совпадении
значений WARNING нет. NaN совпадает с NaN на верхнем уровне и на любой глубине ``dict``/``list``/
``tuple``. Всё остальное сравнение — как раньше.

Захват WARNING — патч ``StdLoggerFacade.warning`` (образец: ``process_module/tests/
test_blueprint_extras.py::TestConflictWarning``), ``caplog`` здесь не годится.
NaN берутся как РАЗНЫЕ объекты (``float("nan")``): ``math.nan`` — один объект, он маскирует дефект
в контейнерах (сравнение по идентичности внутри ``==`` контейнеров).
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.logger_module.adapters.std_facade import StdLoggerFacade
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


# (ключ, фабрика typed(n1, n2), фабрика extras(n1, n2)); n1 и n2 — разные объекты NaN,
# кроме случая «-same», где в обе стороны уходит один и тот же n1.
_NAN_CASES = [
    pytest.param("stop_window_s", lambda n1, n2: n1, lambda n1, n2: n2, id="stop_window_s-distinct"),
    pytest.param("stop_window_s", lambda n1, n2: n1, lambda n1, n2: n1, id="stop_window_s-same"),
    pytest.param("source_target_fps", lambda n1, n2: n1, lambda n1, n2: n2, id="source_target_fps"),
    pytest.param(
        "collector",
        lambda n1, n2: {"mode": "x", "w": n1},
        lambda n1, n2: {"mode": "x", "w": n2},
        id="collector-nested",
    ),
    pytest.param(
        "io_peek",
        lambda n1, n2: {"a": [n1]},
        lambda n1, n2: {"a": [n2]},
        id="io_peek-in-list",
    ),
    pytest.param("stop_window_s", lambda n1, n2: [n1], lambda n1, n2: [n2], id="stop_window_s-in-list"),
]


@pytest.mark.parametrize(("key", "typed", "extra"), _NAN_CASES)
def test_nan_in_both_no_conflict_warning(warnings_captured, key, typed, extra):
    n1 = float("nan")
    n2 = float("nan")
    cfg = _build(**{key: typed(n1, n2)}, extras={key: extra(n1, n2)})

    cfg.as_generic_config()

    conflicts = _conflicts(warnings_captured)
    assert len(conflicts) == 0, f"NaN == NaN: WARNING о перекрытии не нужен, а их {len(conflicts)}: {conflicts}"


def test_real_conflict_warning_text(warnings_captured):
    cfg = _build(chain_targets=["typed"], extras={"chain_targets": ["extras"]})

    cfg.as_generic_config()

    conflicts = _conflicts(warnings_captured)
    assert len(conflicts) == 1, conflicts
    assert conflicts[0] == (
        "ProcessConfig[pc]: typed-поле 'chain_targets'=['typed'] перекрывает "
        "extras['chain_targets']=['extras'] (typed-приоритет)."
    )


def test_nan_against_number_is_conflict(warnings_captured):
    cfg = _build(source_target_fps=30.0, extras={"source_target_fps": float("nan")})

    cfg.as_generic_config()

    conflicts = _conflicts(warnings_captured)
    assert len(conflicts) == 1, conflicts
    assert conflicts[0] == (
        "ProcessConfig[pc]: typed-поле 'source_target_fps'=30.0 перекрывает "
        "extras['source_target_fps']=nan (typed-приоритет)."
    )


def test_nan_typed_against_number_extras_is_conflict(warnings_captured):
    cfg = _build(stop_window_s=float("nan"), extras={"stop_window_s": 30.0})

    cfg.as_generic_config()

    assert len(_conflicts(warnings_captured)) == 1, warnings_captured


def test_list_against_tuple_stays_conflict(warnings_captured):
    cfg = _build(chain_targets=["a"], extras={"chain_targets": ("a",)})

    cfg.as_generic_config()

    assert len(_conflicts(warnings_captured)) == 1, warnings_captured


@pytest.mark.parametrize(
    ("key", "typed", "extra"),
    [
        pytest.param("source_target_fps", 30.0, 30.0, id="float-float"),
        pytest.param("io_peek", {"a": 1}, {"a": 1.0}, id="dict-int-float"),
        pytest.param("stop_window_s", 1, True, id="int-bool"),
        pytest.param("chain_targets", ["a"], ["a"], id="list-list"),
    ],
)
def test_equal_values_no_warning(warnings_captured, key, typed, extra):
    cfg = _build(**{key: typed}, extras={key: extra})

    cfg.as_generic_config()

    assert len(_conflicts(warnings_captured)) == 0, warnings_captured


def test_typed_value_wins(warnings_captured):
    cfg = _build(source_target_fps=30.0, extras={"source_target_fps": 40.0})

    generic = cfg.as_generic_config()

    assert generic.source_target_fps == 30.0
    assert len(_conflicts(warnings_captured)) == 1, warnings_captured
