# -*- coding: utf-8 -*-
"""Авторские hazard-тесты hint'а ``telemetry_readmodel_empty`` (Ф2 Task 2.8).

Что может сломаться именно в ЭТОМ механизме, given как он построен: условие
читает ``snapshot["count"]`` — размер ВСЕГО read-model (все трекаемые суффиксы,
``DEFAULT_TRACKED_SUFFIXES``: fps/latency_ms/uptime/effective_hz/cycle_duration_ms),
а не размер локальной проекции ``telemetry.fps`` (та строится тем же циклом чуть
выше, отдельным словарём). Разница молчит на всех трёх сценах приёмки — там либо
ничего не накоплено, либо накоплена ровно fps-метрика, и «read-model пуст» с
«fps-срез пуст» на этих сценах совпадают побитово. Опасность: будущая правка,
«упрощающая» условие до ``not res["telemetry"]["fps"]`` (читается как то же самое,
раз оба словаря обычно пустеют вместе), тихо сломала бы систему, где read-model
уже накопил ДРУГУЮ метрику (не fps) — сводка снова начала бы врать про пустой
read-model, хотя он таковым не является.
"""

from __future__ import annotations

from backend_ctl.driver import BackendDriver
from backend_ctl.tests.test_overview import _fake_backend, _feed_state, _healthy_responses


def _telemetry_hints(res):
    return [a for a in res["anomalies"] if a.get("kind") == "telemetry_readmodel_empty"]


class TestReadmodelEmptinessIsWholeModelNotFpsView:
    def test_nonfps_metric_keeps_readmodel_non_empty_hint_silent(self, monkeypatch) -> None:
        """Read-model накопил ``effective_hz`` (не fps), подписки НЕТ — hint обязан молчать.

        Держит: условие смотрит на ``snapshot["count"]`` (весь read-model), а не на
        ``telemetry.fps`` (локальную проекцию по суффиксу). ``fps`` в ответе при этом
        пуст — если бы условие читало пустоту ИМЕННО ``fps``-среза, тест покраснел бы
        (hint появился бы поверх непустого read-model).
        """
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=_healthy_responses())
        _feed_state(d, "processes.cam.workers.w1.effective_hz", 42.0)  # трекаемый суффикс, НЕ fps

        snap = d.telemetry_snapshot()
        assert snap["ingest_active"] is False, "сцена: подписки не было — только прямой feed read-model"
        assert snap["count"] == 1, "сцена сломана: read-model обязан накопить ровно одну метрику"

        res = d.system_overview()
        assert res["telemetry"]["fps"] == {}, "сцена: fps-срез пуст — метрика была не fps"
        assert _telemetry_hints(res) == [], (
            "read-model НЕ пуст (effective_hz накоплен) — hint обязан молчать, даже если fps-срез пуст"
        )
