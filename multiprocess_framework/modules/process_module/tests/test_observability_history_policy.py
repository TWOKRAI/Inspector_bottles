# -*- coding: utf-8 -*-
"""Ф5.2: политика истории — порог записи и пределы ретеншена.

Проверяется по одному свойству на тест:

  * дефолт порога — INFO, а не ERROR: с ERROR вкладка «Логи» пуста ПО ПОСТРОЕНИЮ,
    и это была находка Б-8;
  * значения берутся из секции ``observability.history`` слоями конфига;
  * мусор в значении не молчит — падает на дефолт и говорит вслух;
  * ноль как предел проходит, но объявляется громко: молчаливая безлимитность и
    была исходным состоянием;
  * уборка идёт не чаще интервала и не роняет такт при отказе БД.
"""

from __future__ import annotations

from typing import Any, Dict

from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    DEFAULT_HISTORY_LEVEL,
    DEFAULT_HISTORY_MAX_AGE_SEC,
    DEFAULT_HISTORY_MAX_ROWS,
    DEFAULT_HISTORY_PURGE_INTERVAL_SEC,
    resolve_history_policy,
    sweep_observability_history,
)


class _Svc:
    """Процесс с секцией наблюдаемости и журналом предупреждений."""

    def __init__(self, history: Any = None) -> None:
        self.name = "camera_0"
        self.warnings: list = []
        self._history = history
        self._observability_store = None
        self._observability_history_policy = None

    def get_config(self, key, default=None):
        if key == "observability_app":
            return {"history": self._history} if self._history is not None else {}
        return default

    def _log_warning(self, message, module=None) -> None:
        self.warnings.append(str(message))

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...


class _Store:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list = []
        self._fail = fail

    def purge(self, *, max_rows=None, max_age_sec=None, now=None) -> Dict[str, int]:
        self.calls.append((max_rows, max_age_sec))
        if self._fail:
            raise RuntimeError("БД закрыта")
        return {"by_age": 0, "by_rows": 0, "remaining": 0}


class TestDefaults:
    def test_default_level_is_info_so_the_logs_tab_is_not_empty_by_construction(self) -> None:
        """Литерал, а не ссылка на константу: число проверяется отдельно ниже."""
        assert resolve_history_policy(_Svc())["level"] == "INFO"

    def test_defaults_come_from_the_named_constants(self) -> None:
        policy = resolve_history_policy(_Svc())

        assert policy["max_rows"] == DEFAULT_HISTORY_MAX_ROWS
        assert policy["max_age_sec"] == DEFAULT_HISTORY_MAX_AGE_SEC
        assert policy["purge_interval_sec"] == DEFAULT_HISTORY_PURGE_INTERVAL_SEC
        assert DEFAULT_HISTORY_LEVEL == "INFO"


class TestFromConfig:
    def test_section_values_win(self) -> None:
        svc = _Svc({"level": "warning", "max_rows": 50, "max_age_sec": 60, "purge_interval_sec": 5})

        policy = resolve_history_policy(svc)

        assert policy == {"level": "WARNING", "max_rows": 50, "max_age_sec": 60.0, "purge_interval_sec": 5.0}
        assert svc.warnings == [], "нормальная секция не имеет права шуметь"

    def test_unknown_level_falls_back_loudly(self) -> None:
        svc = _Svc({"level": "ОРУЩИЙ"})

        assert resolve_history_policy(svc)["level"] == "INFO"
        assert any("level" in w for w in svc.warnings), "опечатка в уровне прошла молча"

    def test_garbage_number_falls_back_loudly(self) -> None:
        svc = _Svc({"max_rows": "много"})

        assert resolve_history_policy(svc)["max_rows"] == DEFAULT_HISTORY_MAX_ROWS
        assert any("max_rows" in w for w in svc.warnings), "мусор в пределе прошёл молча"

    def test_zero_is_an_accepted_but_announced_refusal_of_the_limit(self) -> None:
        """Ноль = «предела нет». Это решение оператора — но не тихое."""
        svc = _Svc({"max_rows": 0})

        assert resolve_history_policy(svc)["max_rows"] == 0
        assert any("предел СНЯТ" in w for w in svc.warnings)

    def test_section_of_the_wrong_type_does_not_kill_the_process(self) -> None:
        svc = _Svc("не словарь")

        assert resolve_history_policy(svc)["level"] == "INFO"
        assert any("не словарь" in w for w in svc.warnings)


class TestSweep:
    def test_no_store_means_no_sweep(self) -> None:
        assert sweep_observability_history(_Svc()) is None

    def test_policy_limits_reach_the_store(self) -> None:
        svc = _Svc()
        svc._observability_store = _Store()
        svc._observability_history_policy = {"max_rows": 7, "max_age_sec": 42.0, "purge_interval_sec": 100.0}

        sweep_observability_history(svc, now=1000.0)

        assert svc._observability_store.calls == [(7, 42.0)]

    def test_second_tick_inside_the_interval_is_skipped(self) -> None:
        svc = _Svc()
        svc._observability_store = _Store()
        svc._observability_history_policy = {"max_rows": 7, "max_age_sec": 42.0, "purge_interval_sec": 100.0}

        sweep_observability_history(svc, now=1000.0)
        assert sweep_observability_history(svc, now=1050.0) is None
        sweep_observability_history(svc, now=1100.0)

        assert len(svc._observability_store.calls) == 2, "интервал не соблюдён"

    def test_db_failure_does_not_kill_the_tick_and_does_not_stay_silent(self) -> None:
        svc = _Svc()
        svc._observability_store = _Store(fail=True)
        svc._observability_history_policy = {"max_rows": 7, "max_age_sec": 42.0, "purge_interval_sec": 100.0}

        assert sweep_observability_history(svc, now=1000.0) is None
        assert any("уборка истории" in w for w in svc.warnings)

    def test_failed_sweep_does_not_retry_every_tick(self) -> None:
        """Срок ставится ДО уборки: отказ БД не превращается в нагрузку на неё же."""
        svc = _Svc()
        svc._observability_store = _Store(fail=True)
        svc._observability_history_policy = {"max_rows": 7, "max_age_sec": 42.0, "purge_interval_sec": 100.0}

        sweep_observability_history(svc, now=1000.0)
        sweep_observability_history(svc, now=1010.0)

        assert len(svc._observability_store.calls) == 1
