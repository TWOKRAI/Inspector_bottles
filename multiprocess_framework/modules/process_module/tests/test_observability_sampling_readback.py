# -*- coding: utf-8 -*-
"""Задача 4.4 — включённый дроссель подтверждается вердиктом, а не верится на слово.

План: plans/observability-roadmap.md, задача 4.4 (С-8).

Зачем. Живой прогон (``backend_ctl/probes/probe_4_4_sampler_live.py``) показал:
дроссель на работающем процессе включается и душит шторм (2000 → 8), но команда
``config.reload`` отвечает ``verdict: "unverifiable"`` — путей ``logger.sampling_*``
в readback не было вовсе. То есть оператор включал единственную защиту эмитента от
шторма и не мог подтвердить, что она включилась: механизм, включение которого
нельзя проверить, по закону этого проекта не существует.

Тест водит НАСТОЯЩИЙ ``LoggerManager`` через ``observability_effective`` и
настоящий ``observability_verified``: обвязка на подставных снимках доказала бы
обвязку, а сломался бы ровно стык — как это уже было с секцией ``stats``, чья
ветка readback'а не исполнялась ни разу.
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_framework.modules.logger_module.configs import LoggerManagerConfig
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    observability_effective,
    observability_verified,
)


def _manager(tmp_path, **sampling: Any) -> LoggerManager:
    return LoggerManager(
        config=LoggerManagerConfig(
            app_name="s44",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            **sampling,
        )
    )


@pytest.fixture()
def logger(tmp_path) -> Any:
    manager = _manager(
        tmp_path,
        sampling_first_n=5,
        sampling_every_mth=500,
        sampling_burst_reset_sec=7.5,
    )
    yield manager
    manager.shutdown()


class TestReadbackCarriesTheKnob:
    """Секция ``logger`` несёт четыре действующих значения дросселя."""

    def test_all_four_paths_are_present(self, logger: Any) -> None:
        section = observability_effective(logger=logger)["logger"]

        assert section["sampling_first_n"] == 5
        assert section["sampling_every_mth"] == 500
        assert section["sampling_burst_reset_sec"] == 7.5
        assert section["sampling_max_level"] == "DEBUG"

    def test_disabled_sampler_is_an_answer_not_a_gap(self, tmp_path) -> None:
        """Выключенный дроссель отдаёт 0, а не отсутствие ключа.

        «Ключа нет» и «дроссель выключен» — разные факты: по первому оператор
        полез бы искать поломку readback'а вместо того, чтобы включить ручку.
        """
        manager = _manager(tmp_path)
        try:
            section = observability_effective(logger=manager)["logger"]
        finally:
            manager.shutdown()

        assert section["sampling_first_n"] == 0

    def test_ceiling_is_shown_as_it_acts_not_as_requested(self, tmp_path) -> None:
        """Просили CRITICAL — readback говорит WARNING, потому что действует WARNING.

        Ошибки не сэмплируются никогда, потолок обрезан кодом. Readback, который
        повторил бы запрос, показал бы оператору границу, которой нет ни на одной
        записи, — и «ERROR подавлены» пришлось бы проверять глазами по файлу.
        """
        manager = _manager(tmp_path, sampling_first_n=1, sampling_max_level="CRITICAL")
        try:
            section = observability_effective(logger=manager)["logger"]
        finally:
            manager.shutdown()

        assert section["sampling_max_level"] == "WARNING"


class TestVerdictOnTheKnob:
    """Вердикт живой команды: подтверждено / расхождение названо."""

    def test_turning_the_knob_on_is_confirmed(self, logger: Any) -> None:
        effective = observability_effective(logger=logger)

        result = observability_verified({"sampling_first_n": 5, "sampling_every_mth": 500}, effective)

        assert result["verdict"] == "confirmed", f"вердикт {result}"
        assert result["checked"] == 2
        assert result["unverifiable"] == []

    def test_knob_that_did_not_reach_the_sampler_is_failed_and_named(self, logger: Any) -> None:
        """Вторая половина пары.

        Без неё первый тест зелен и у реализации «readback повторяет запрос»:
        сторожил бы наличие ключей, а не суждение о них.
        """
        effective = observability_effective(logger=logger)

        result = observability_verified({"sampling_first_n": 42}, effective)

        assert result["verdict"] == "failed"
        assert result["mismatches"] == [{"key": "logger.sampling_first_n", "expected": 42, "actual": 5}]

    def test_ceiling_above_errors_is_reported_as_a_mismatch(self, tmp_path) -> None:
        """Запрос ``CRITICAL`` — законный отказ, названный поимённо, а не тихий успех."""
        manager = _manager(tmp_path, sampling_first_n=1, sampling_max_level="CRITICAL")
        try:
            effective = observability_effective(logger=manager)
        finally:
            manager.shutdown()

        result = observability_verified({"sampling_first_n": 1, "sampling_max_level": "CRITICAL"}, effective)

        assert result["verdict"] == "failed"
        assert result["mismatches"] == [
            {"key": "logger.sampling_max_level", "expected": "CRITICAL", "actual": "WARNING"}
        ]
