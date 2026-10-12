"""Авторские hazard-тесты Task 1.1: формула ``stop_budget`` и её четыре читателя.

Каждый тест называет строку, которую сторожит. Приёмка (слепая) — в
``test_stop_budget_child_stop_acceptance.py``; здесь — то, что может сломаться в
миграции читателей: PM, реестр, спавнер.
"""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ..core.process_registry import ProcessRegistry
from ..core.stop_budget import stop_budget
from ..launcher.spawner import ProcessSpawner
from ..process.process_manager_process import ProcessManagerProcess

_BUDGET_5 = {"work_s": 3.0, "infra_s": 1.0, "pm_graceful_s": 5.0, "pm_total_s": 7.0, "outer_s": 8.5}


class _RecLogger:
    """PM-подобный логгер: запись предупреждений."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def _log_info(self, msg: str) -> None:
        pass

    def _log_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def _log_error(self, msg: str) -> None:
        self.errors.append(msg)


# ---------------------------------------------------------------------------
# stop_budget: текст ошибки
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("value", "exc", "type_name"), [(-2.5, ValueError, "float"), ("x", TypeError, "str")])
def test_error_text_names_parameter_and_type(value: Any, exc: type, type_name: str) -> None:
    """Сторожит: f-строки ``_graceful_s`` — параметр и тип названы, значение нет."""
    with pytest.raises(exc) as ei:
        stop_budget(value)
    text = str(ei.value)
    assert "shutdown_timeout" in text
    assert type_name in text


def test_int_argument_gives_floats() -> None:
    """Сторожит: ``float(...)`` в ``_graceful_s`` — int 2 даёт те же числа, что 2.0."""
    r = stop_budget(2)
    assert r == pytest.approx({"work_s": 1.2, "infra_s": 0.4, "pm_graceful_s": 2.0, "pm_total_s": 4.0, "outer_s": 5.5})
    assert all(isinstance(v, float) for v in r.values())


# ---------------------------------------------------------------------------
# PM: два чтения shutdown_timeout
# ---------------------------------------------------------------------------


def _bare_pm(shutdown_timeout: Any) -> ProcessManagerProcess:
    with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
        pm = ProcessManagerProcess()
    pm.get_config = lambda key, default=None: {"shutdown_timeout": shutdown_timeout}.get(key, default)
    pm._process_registry = MagicMock()
    return pm


@pytest.mark.parametrize("value", [None, 0])
def test_pm_stop_process_all_passes_default_for_none_and_zero(value: Any) -> None:
    """Сторожит: ``stop_budget(self.get_config(SHUTDOWN_TIMEOUT_KEY))["pm_graceful_s"]`` в
    ``stop_process(None)``: ``None`` и ``0`` — 5.0, как прежнее ``or 5.0``."""
    pm = _bare_pm(value)
    assert pm.stop_process(None) is True
    pm._process_registry.stop_all.assert_called_once_with(timeout=5.0, mark_reader_gone=True)


@pytest.mark.parametrize("value", [None, 0])
def test_pm_stop_children_once_passes_default_for_none_and_zero(value: Any) -> None:
    """Сторожит: то же чтение в ``_stop_children_once`` (путь shutdown)."""
    pm = _bare_pm(value)
    pm._process_monitor = MagicMock()
    pm._process_registry.stop_all.return_value = {}
    try:
        pm._stop_children_once()
    except Exception:  # noqa: BLE001 — хвост метода (сводка) на голом PM не важен
        pass
    assert pm._process_registry.stop_all.call_args.kwargs["timeout"] == 5.0


# ---------------------------------------------------------------------------
# Реестр: child_stop_budget и приведение timeout
# ---------------------------------------------------------------------------


def _child_config(registry: ProcessRegistry, name: str, config: dict) -> dict:
    proc = registry.create_and_register(name, "os.getpid", config, "normal")
    assert proc is not None
    return proc._args[3]["config"]


def test_child_config_explicit_stop_budget_wins() -> None:
    """Сторожит: ``setdefault`` (не присваивание) в ``_create_process``; словарь реестра не тронут."""
    budget = dict(_BUDGET_5)
    registry = ProcessRegistry(logger=None, child_stop_budget=budget)
    cfg = _child_config(registry, "R", {"stop_budget": {"work_s": 9.0}})
    assert cfg["stop_budget"] == {"work_s": 9.0}
    assert _child_config(registry, "S", {})["stop_budget"] == _BUDGET_5
    assert budget == _BUDGET_5


def test_registry_keeps_own_copy_of_budget() -> None:
    """Сторожит: ``dict(child_stop_budget)`` в ``__init__`` — правка словаря вызывающим не течёт."""
    budget = dict(_BUDGET_5)
    registry = ProcessRegistry(logger=None, child_stop_budget=budget)
    budget["work_s"] = 42.0
    assert _child_config(registry, "R", {})["stop_budget"] == _BUDGET_5


@pytest.mark.parametrize(
    ("value", "expected", "warns"),
    [
        (2.5, 2.5, False),
        (0, 0.0, False),
        (-1.0, 0.0, False),
        (math.inf, 5.0, True),
        (math.nan, 5.0, True),
        (None, 5.0, True),
        (True, 5.0, True),
        ("3", 5.0, True),
    ],
)
def test_registry_timeout_coercion(value: Any, expected: float, warns: bool) -> None:
    """Сторожит: ``_stop_timeout_s`` — путь стопа не бросает; ``inf`` не даёт немедленный terminate."""
    logger = _RecLogger()
    registry = ProcessRegistry(logger=logger)
    assert registry._stop_timeout_s(value) == expected
    assert bool(logger.warnings) is warns


def test_stop_many_with_bad_timeout_does_not_raise() -> None:
    """Сторожит: новых исключений на пути стопа нет (``stop_process_timeout`` идёт мимо ``stop_budget``)."""
    registry = ProcessRegistry(logger=_RecLogger())
    assert registry.stop_many(["ghost"], timeout=math.nan) == {"ghost": True}
    assert registry.stop_one("ghost", timeout="bad") is True  # type: ignore[arg-type]


class _TermProc:
    """Живой дублёр процесса: умирает от ``terminate()``; ``stop_event`` не слушает."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.pid = 1
        self._alive = True
        self.terminated = 0

    def is_alive(self) -> bool:
        return self._alive

    def terminate(self) -> None:
        self.terminated += 1
        self._alive = False

    def kill(self) -> None:
        self._alive = False


@pytest.mark.parametrize("bad", [math.nan, None, "x", math.inf, True])
def test_stop_many_bad_timeout_reaches_scope_without_raising(bad: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Сторожит: вызов ``self._stop_timeout_s(timeout)`` в ``_stop_many`` — до ``open_scope`` доходит
    приведённый срок. Сырой NaN/None/строка/inf в ``open_scope`` дал бы ``ValueError``/``TypeError``
    посреди стопа. Имя живое: путь идёт через область, а не ранний возврат «призрака».
    Умолчание реестра уменьшено патчем, чтобы не ждать 5 с; проверяется поведение, а не время."""
    import time

    from ..core import process_registry as reg_mod

    monkeypatch.setattr(reg_mod, "DEFAULT_SHUTDOWN_TIMEOUT_S", 0.1)
    logger = _RecLogger()
    registry = ProcessRegistry(logger=logger)
    proc = _TermProc("Q")
    registry.add_process(proc)
    t0 = time.monotonic()
    assert registry.stop_many(["Q"], timeout=bad) == {"Q": True}
    assert time.monotonic() - t0 < 3.0
    assert proc.terminated == 1  # эскалация прошла: graceful-срок умолчания, затем terminate
    assert any("взято умолчание" in w for w in logger.warnings)


# ---------------------------------------------------------------------------
# Спавнер: stop(timeout) из обработчика сигнала не бросает
# ---------------------------------------------------------------------------


def _stopped_join(spawner: ProcessSpawner, **kw: Any) -> float:
    proc = MagicMock()
    proc.is_alive.side_effect = [True, False, False]
    spawner._process = proc
    spawner.stop(**kw)
    return proc.join.call_args.kwargs["timeout"]


@pytest.mark.parametrize("bad", [0, -1.0, math.nan, math.inf, True, "x"])
def test_spawner_bad_explicit_timeout_uses_default(bad: Any) -> None:
    """Сторожит: ``_stop_graceful_s`` — плохой явный ``timeout`` даёт умолчание (8.5), не исключение.

    ``stop(timeout=0)`` до 1.1 давал внешний бюджет 3.5 с — меньше внутреннего бюджета PM."""
    assert _stopped_join(ProcessSpawner(stop_timeout=5.0), timeout=bad) == pytest.approx(8.5)


def test_spawner_bad_orchestrator_shutdown_timeout_does_not_raise() -> None:
    """Сторожит: ``except (TypeError, ValueError)`` вокруг чтения конфига оркестратора."""
    spawner = ProcessSpawner(stop_timeout=5.0, orchestrator_config={"shutdown_timeout": -3.0})
    assert _stopped_join(spawner) == pytest.approx(8.5)


def test_spawner_has_no_second_formula() -> None:
    """Сторожит: удаление ``outer_stop_budget`` и ``_pm_graceful_budget`` (вторая копия формулы)."""
    import importlib

    mod = importlib.import_module(ProcessSpawner.__module__)
    assert not hasattr(mod, "outer_stop_budget")
    assert not hasattr(ProcessSpawner, "_pm_graceful_budget")
