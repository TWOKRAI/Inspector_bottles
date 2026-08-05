# -*- coding: utf-8 -*-
"""Ф3.6 — миграция стора под словарь OTel: число важности и отметка приёма.

Проверяются четыре свойства, каждое ломается отдельно:

1. **старый файл читается** — колонок нет, падать нельзя (стор истории это та
   поверхность, куда идут разбираться, когда сломалось);
2. **старые строки засыпаются**, а не остаются NULL: пороговый запрос строки с
   NULL не вернёт, то есть вся доreформенная история молча исчезла бы из ответа
   «покажи всё от WARNING и выше»;
3. **порог считается по числу**, а не перечислением уровней руками;
4. **форма live == форма history** — иначе вкладка знала бы два формата, а
   фильтр работал бы на половине данных.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.channel_routing_module.levels import SEVERITY_NUMBERS
from multiprocess_framework.modules.channel_routing_module.observability.observability_store import (
    ObservabilityStore,
)
from multiprocess_framework.modules.channel_routing_module.observability.record_display import (
    hub_record_to_display,
    log_record_to_display,
    severity_number_for,
)


def _legacy_db(path: str, rows: List[Dict[str, Any]]) -> None:
    """Создать файл СТАРОЙ схемы (до Ф3.6) и набить его строками."""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE records (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            kind     TEXT NOT NULL,
            process  TEXT,
            module   TEXT NOT NULL,
            ts       REAL NOT NULL,
            severity TEXT,
            message  TEXT,
            extra    TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO records (kind, process, module, ts, severity, message, extra) "
        "VALUES (:kind, :process, :module, :ts, :severity, :message, :extra)",
        rows,
    )
    conn.commit()
    conn.close()


def _row(kind: str, severity: str, message: str = "x") -> Dict[str, Any]:
    return {
        "kind": kind,
        "process": "camera_0",
        "module": "m",
        "ts": 1.0,
        "severity": severity,
        "message": message,
        "extra": "{}",
    }


class TestLegacyFileSurvives:
    def test_old_db_opens_and_reads(self, tmp_path: Any) -> None:
        db = str(tmp_path / "old.db")
        _legacy_db(db, [_row("log", "info", "древняя запись")])

        store = ObservabilityStore(db)
        try:
            records = store.list_records()
            assert len(records) == 1
            assert records[0]["message"] == "древняя запись"
        finally:
            store.close()

    def test_migration_is_idempotent(self, tmp_path: Any) -> None:
        db = str(tmp_path / "old.db")
        _legacy_db(db, [_row("log", "info")])
        for _ in range(3):
            store = ObservabilityStore(db)
            store.close()
        store = ObservabilityStore(db)
        try:
            assert store.count() == 1, "повторная миграция размножила или потеряла строки"
        finally:
            store.close()


class TestBackfillDoesNotLoseHistory:
    def test_old_rows_get_numbers_from_their_text(self, tmp_path: Any) -> None:
        db = str(tmp_path / "old.db")
        _legacy_db(
            db,
            [
                _row("log", "debug"),
                _row("log", "info"),
                _row("error", "warning"),
                _row("error", "error"),
                _row("error", "critical"),
                _row("stats", "gauge"),
            ],
        )

        store = ObservabilityStore(db)
        try:
            numbers = [r["severity_number"] for r in store.list_records(newest_first=False)]
            assert numbers == [5, 9, 13, 17, 21, 0], f"засыпка разошлась с таблицей: {numbers}"
        finally:
            store.close()

    def test_threshold_query_sees_pre_migration_history(self, tmp_path: Any) -> None:
        """Главная пара задачи: без засыпки этот запрос вернул бы ПУСТО.

        Строки с ``severity_number IS NULL`` порогу не удовлетворяют, и вся
        история до миграции исчезла бы из ответа молча.
        """
        db = str(tmp_path / "old.db")
        _legacy_db(db, [_row("log", "info", "тихо"), _row("error", "error", "беда")])

        store = ObservabilityStore(db)
        try:
            found = store.list_records(min_severity=SEVERITY_NUMBERS["WARNING"])
            assert [r["message"] for r in found] == ["беда"]
        finally:
            store.close()

    def test_backfill_matches_the_live_table(self, tmp_path: Any) -> None:
        """SQL-выражение засыпки — ВТОРОЕ место, где живут числа.

        Тест сверяет его с единственной таблицей слоя: разойдись они, старые и
        новые записи одного уровня получили бы разные числа, и порог отвечал бы
        по-разному на одну и ту же историю.
        """
        db = str(tmp_path / "old.db")
        _legacy_db(db, [_row("log", name.lower()) for name in SEVERITY_NUMBERS])

        store = ObservabilityStore(db)
        try:
            got = [r["severity_number"] for r in store.list_records(newest_first=False)]
            assert got == list(SEVERITY_NUMBERS.values())
        finally:
            store.close()


class TestThresholdOnFreshRecords:
    def test_min_severity_filters_by_number(self, tmp_path: Any) -> None:
        store = ObservabilityStore(str(tmp_path / "new.db"))
        try:
            store.append_records(
                [
                    {"kind": "log", "module": "m", "ts": 1.0, "severity": "info", "message": "тихо"},
                    {"kind": "log", "module": "m", "ts": 2.0, "severity": "warning", "message": "внимание"},
                    {"kind": "log", "module": "m", "ts": 3.0, "severity": "error", "message": "беда"},
                ]
            )
            found = store.list_records(min_severity=13, newest_first=False)
            assert [r["message"] for r in found] == ["внимание", "беда"]
        finally:
            store.close()

    def test_stats_rows_never_answer_a_severity_threshold(self, tmp_path: Any) -> None:
        """У метрики оси важности нет — порог по уровню её задевать не вправе."""
        store = ObservabilityStore(str(tmp_path / "new.db"))
        try:
            store.append_records(
                [
                    {"kind": "stats", "module": "m", "ts": 1.0, "metric": "fps", "metric_type": "gauge", "value": 30},
                    {"kind": "log", "module": "m", "ts": 2.0, "severity": "error", "message": "беда"},
                ]
            )
            found = store.list_records(min_severity=5)
            assert [r["message"] for r in found] == ["беда"]
        finally:
            store.close()

    def test_observed_stamp_survives_the_round_trip(self, tmp_path: Any) -> None:
        """Задержка доставки восстановима на истории — ради этого колонка и есть."""
        store = ObservabilityStore(str(tmp_path / "new.db"))
        try:
            store.append_records(
                [
                    {
                        "kind": "log",
                        "module": "m",
                        "ts": 100.0,
                        "severity": "info",
                        "message": "x",
                        "observed_ts": 108.5,
                    }
                ]
            )
            record = store.list_records()[0]
            assert record["observed_ts"] == 108.5
            assert record["observed_ts"] - record["ts"] == pytest.approx(8.5)
        finally:
            store.close()

    def test_record_without_stamp_reads_as_absent_not_zero(self, tmp_path: Any) -> None:
        """``None``, а не ``0``: ноль здесь читался бы как «принято в 1970»."""
        store = ObservabilityStore(str(tmp_path / "new.db"))
        try:
            store.append_records([{"kind": "log", "module": "m", "ts": 1.0, "severity": "info", "message": "x"}])
            assert store.list_records()[0]["observed_ts"] is None
        finally:
            store.close()


class TestLiveAndHistoryShareTheShape:
    """Инвариант ``record_display``: панель обязана знать ОДИН формат."""

    def test_both_normalizers_produce_the_number(self) -> None:
        hub = hub_record_to_display({"kind": "log", "module": "m", "ts": 1.0, "severity": "error"})
        tap = log_record_to_display({"timestamp": 1.0, "level": "ERROR", "message": "x", "module": "m"})
        assert hub["severity_number"] == 17
        assert tap["severity_number"] == 17

    def test_history_row_has_the_same_keys_as_live(self, tmp_path: Any) -> None:
        live = hub_record_to_display({"kind": "log", "module": "m", "ts": 1.0, "severity": "info", "message": "x"})
        store = ObservabilityStore(str(tmp_path / "new.db"))
        try:
            store.append_records([{"kind": "log", "module": "m", "ts": 1.0, "severity": "info", "message": "x"}])
            history = store.list_records()[0]
        finally:
            store.close()

        # У истории законно есть свои поля (``id``, отметка приёма может быть
        # пустой); проверяется, что ключи ЖИВОЙ формы не потерялись.
        assert set(live).issubset(set(history)), f"история потеряла ключи: {set(live) - set(history)}"
        # Одного включения мало: снеси поле из ОБЕИХ форм — и подмножество
        # по-прежнему верно, а фильтра нет ни там, ни там (слом-инъекция N-6).
        assert "severity_number" in live and "severity_number" in history

    def test_stats_number_comes_from_kind_not_from_failed_ranking(self) -> None:
        """Метрика и опечатка в уровне обязаны быть различимы.

        Обе не ранжируются, но у метрики ЗАКОННО нет оси важности, а у лога это
        дефект. Число берётся по ``kind`` — иначе оба стали бы нулём и вопрос
        «а это метрика или сломанный уровень?» остался бы без ответа.
        """
        # Вход подобран так, чтобы ветка по `kind` была НАБЛЮДАЕМА: на "gauge"
        # обе дороги дают 0 (метрика не ранжируется), и тест на таком входе
        # вакуумен — слом-инъекция это и показала. Наблюдаема разница только
        # на строке, которая КАК УРОВЕНЬ ранжируется, а как metric_type им не
        # является.
        assert severity_number_for("stats", "error") == 0, (
            "у плоскости статистики нет оси важности — число берётся по kind, "
            "а не ранжированием содержимого колонки severity"
        )
        assert severity_number_for("stats", "gauge") == 0
        assert severity_number_for("log", "ОПЕЧАТКА") == 0
        assert severity_number_for("log", "warning") == 13


class TestPartialMigrationWindow:
    """Падение между ALTER'ом и UPDATE-засыпкой не должно терять историю навсегда.

    Найдено ревью Ф3 (2026-08-05) репродукцией: sqlite3 в legacy-режиме коммитит
    DDL сразу (ALTER — вне транзакции), а засыпка ехала в транзакции до
    ``commit()``. Падение в этом окне оставляло файл в состоянии «колонка есть,
    числа NULL», и гейт ``if added:`` при следующем открытии больше НИКОГДА не
    засыпал: ``added=False`` — дореформенная история молча выпадала из
    порогового запроса. Ровно та тихая потеря, которую миграция запрещает.
    """

    def test_crash_after_alter_still_backfills_on_next_open(self, tmp_path: Any) -> None:
        db = str(tmp_path / "old.db")
        _legacy_db(db, [_row("log", "error", "беда"), _row("log", "warning"), _row("stats", "gauge")])
        # Состояние диска после падения: колонка добавлена (DDL закоммичен),
        # засыпки не было (UPDATE потерян вместе с транзакцией).
        conn = sqlite3.connect(db)
        conn.execute("ALTER TABLE records ADD COLUMN severity_number INTEGER")
        conn.commit()
        conn.close()

        store = ObservabilityStore(db)
        try:
            hits = [r["message"] for r in store.list_records(min_severity=SEVERITY_NUMBERS["WARNING"])]
            assert "беда" in hits, "история после частичной миграции молча выпала из порогового запроса"
            assert len(hits) == 2, hits
        finally:
            store.close()
