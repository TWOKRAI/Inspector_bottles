# -*- coding: utf-8 -*-
"""Уровень записи «stop summary:» у ``ProcessManagerProcess._publish_stop_summary``.

Независимый тест по контракту (тестер писал, не видя тела метода). Контракт:

* для каждого имени из ``stop_results`` берётся ``registry.exit_report(name)`` ->
  ``{"released": int, "buffered_dropped": int, "reported": bool}``;
* публикуется РОВНО ОДНА запись лога PM, текст начинается с ``stop summary:``,
  структурный контекст ``stop_summary`` -> ``{child: {released, buffered_dropped, reported}}``
  по КАЖДОМУ ребёнку;
* уровень WARNING, если хоть у одного ребёнка ``released > 0`` ИЛИ ``buffered_dropped > 0``
  ИЛИ ``reported == False`` (нули + ``reported=False`` = «не знаю» — тоже WARNING);
  иначе INFO;
* метод не бросает наружу.

Граница наблюдения. Собран НАСТОЯЩИЙ путь записи: ``ObservableMixin`` PM -> настоящий
``LoggerManager`` -> приёмник ``memory``. Читается словарь записи, дошедший до приёмника,
поле ``level`` — буквальные ``"WARNING"`` / ``"INFO"``. Мок ``_log_warning`` был бы шпионом
на имя метода: он остался бы зелёным, если бы уровень выбирали через ``_log(level=...)`` или
через ``_log_error``, а ровно уровень и есть защищаемое свойство. Подставные тут только PM без
своего ``__init__`` (иначе поднимаются процессы/очереди) и реестр (одна функция ``exit_report``).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from multiprocess_framework.modules.base_manager.mixins.observable_mixin import ObservableMixin
from multiprocess_framework.modules.logger_module.configs import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

from ..process.process_manager_process import ProcessManagerProcess

CLEAN = {"released": 0, "buffered_dropped": 0, "reported": True}
UNKNOWN = {"released": 0, "buffered_dropped": 0, "reported": False}
RELEASED = {"released": 3, "buffered_dropped": 0, "reported": True}
DROPPED = {"released": 0, "buffered_dropped": 2, "reported": True}


class _FakeRegistry:
    """Только ``exit_report``: единственное, что метод берёт у реестра по контракту."""

    def __init__(self, reports: dict[str, dict]) -> None:
        self._reports = reports

    def exit_report(self, name: str) -> dict:
        return dict(self._reports[name])


class _Harness:
    def __init__(self, pm: ProcessManagerProcess, logger: LoggerManager) -> None:
        self.pm = pm
        self._logger = logger

    def publish(self, reports: dict[str, dict]) -> list[dict]:
        """Один вызов метода; вернуть ВСЕ записи, дошедшие до приёмника за него."""
        self.pm._process_registry = _FakeRegistry(reports)
        before = len(self.records())
        self.pm._publish_stop_summary({name: True for name in reports})
        return self.records()[before:]

    def records(self) -> list[dict]:
        return self._logger._channel_registry.get("mem").tail()


@pytest.fixture
def harness(tmp_path):
    logger = LoggerManager(
        config=LoggerManagerConfig(
            app_name="stopsev",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={"mem": LoggerChannelSchema(type="memory", capacity=100)},
            scopes={
                "SYSTEM": LoggerScopeSchema(channels=["mem"]),
                "BUSINESS": LoggerScopeSchema(channels=["mem"]),
            },
        )
    )
    with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
        pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
    pm.name = "ProcessManager"
    ObservableMixin.__init__(pm, managers={"logger": logger})
    try:
        yield _Harness(pm, logger)
    finally:
        logger.shutdown()


def _one(records: list[dict]) -> dict:
    assert len(records) == 1, f"ожидалась ровно одна запись, получено {len(records)}: {records!r}"
    return records[0]


# --------------------------------------------------------------------------- INFO


@pytest.mark.parametrize("children", [1, 2, 5])
def test_all_clean_children_publish_at_info(harness, children):
    reports = {f"c{i}": CLEAN for i in range(children)}

    record = _one(harness.publish(reports))

    assert record["level"] == "INFO"


# ------------------------------------------------------------------------ WARNING


def test_single_child_reported_false_with_zeros_is_warning(harness):
    """Литерал CTO: нули + reported=False — «не знаю», а не «чисто»."""
    record = _one(harness.publish({"a": UNKNOWN}))

    assert record["level"] == "WARNING"


def test_single_child_released_positive_is_warning(harness):
    record = _one(harness.publish({"a": RELEASED}))

    assert record["level"] == "WARNING"


def test_single_child_buffered_dropped_positive_is_warning(harness):
    record = _one(harness.publish({"a": DROPPED}))

    assert record["level"] == "WARNING"


@pytest.mark.parametrize("position", ["first", "middle", "last"])
@pytest.mark.parametrize("bad", [UNKNOWN, RELEASED, DROPPED], ids=["unknown", "released", "dropped"])
def test_one_bad_among_clean_children_is_warning(harness, bad, position):
    """Один плохой среди чистых поднимает всю сводку; порядок ребёнка не важен."""
    reports = {"c0": CLEAN, "c1": CLEAN, "c2": CLEAN}
    reports[{"first": "c0", "middle": "c1", "last": "c2"}[position]] = bad

    record = _one(harness.publish(reports))

    assert record["level"] == "WARNING"


def test_several_bad_children_of_different_kinds_is_warning(harness):
    record = _one(harness.publish({"a": UNKNOWN, "b": RELEASED, "c": DROPPED, "d": CLEAN}))

    assert record["level"] == "WARNING"


def test_released_and_dropped_together_is_warning(harness):
    record = _one(harness.publish({"a": {"released": 1, "buffered_dropped": 1, "reported": True}}))

    assert record["level"] == "WARNING"


def test_boundary_of_one_is_already_warning(harness):
    """Граница «> 0»: единица уже WARNING, ноль (при reported=True) — ещё INFO."""
    at_one_released = _one(harness.publish({"a": {"released": 1, "buffered_dropped": 0, "reported": True}}))
    at_one_dropped = _one(harness.publish({"a": {"released": 0, "buffered_dropped": 1, "reported": True}}))
    at_zero = _one(harness.publish({"a": {"released": 0, "buffered_dropped": 0, "reported": True}}))

    assert (at_one_released["level"], at_one_dropped["level"], at_zero["level"]) == ("WARNING", "WARNING", "INFO")


# ----------------------------------------------------------- форма записи / контекст


def test_exactly_one_record_per_call_for_every_severity(harness):
    counts = [
        len(harness.publish({"a": CLEAN, "b": CLEAN})),
        len(harness.publish({"a": CLEAN, "b": UNKNOWN})),
        len(harness.publish({"a": RELEASED, "b": DROPPED})),
    ]

    assert counts == [1, 1, 1]


def test_message_starts_with_stop_summary_for_both_severities(harness):
    info = _one(harness.publish({"a": CLEAN}))
    warning = _one(harness.publish({"a": UNKNOWN}))

    assert info["message"].startswith("stop summary:")
    assert warning["message"].startswith("stop summary:")


def test_context_carries_every_child_with_its_exact_report(harness):
    reports = {"cam": CLEAN, "plc": UNKNOWN, "gui": RELEASED, "db": DROPPED}

    record = _one(harness.publish(reports))

    assert record["extra"]["stop_summary"] == {
        "cam": {"released": 0, "buffered_dropped": 0, "reported": True},
        "plc": {"released": 0, "buffered_dropped": 0, "reported": False},
        "gui": {"released": 3, "buffered_dropped": 0, "reported": True},
        "db": {"released": 0, "buffered_dropped": 2, "reported": True},
    }


def test_context_is_present_at_info_level_too(harness):
    """Контекст не привязан к WARNING: чистая сводка тоже несёт всех детей."""
    record = _one(harness.publish({"a": CLEAN, "b": CLEAN}))

    assert record["extra"]["stop_summary"] == {
        "a": {"released": 0, "buffered_dropped": 0, "reported": True},
        "b": {"released": 0, "buffered_dropped": 0, "reported": True},
    }


def test_record_is_attributed_to_the_pm_module(harness):
    record = _one(harness.publish({"a": CLEAN}))

    assert record["module"] == "ProcessManager"


# --------------------------------------------------------------------- не бросает


def test_a_raising_exit_report_does_not_escape(harness):
    """Метод зовётся из shutdown(), где отказ недопустим (контракт: не бросает наружу)."""

    class _Exploding:
        def exit_report(self, name: str) -> dict:
            raise RuntimeError("слот разделяемой памяти недоступен")

    harness.pm._process_registry = _Exploding()

    harness.pm._publish_stop_summary({"a": True, "b": False})  # не должно бросить
