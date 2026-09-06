# -*- coding: utf-8 -*-
"""Независимая приёмка Task 3.1 плана ``observability-closure`` — К1, К2, К4, К5, К6, К7.

**RED-набор, написан ДО реализации.** Тестер работал в отдельном git worktree
(``.claude/worktrees/f3-t31``) на коммите ``610698c0`` — ДО правки Task 3.1,
не видел diff/реализацию, не читал ``_impl/`` (директории с таким именем в
этом дереве нет). Источник критериев — раздел «### Task 3.1» в
``plans/observability-closure/phase-3-store-and-signal.md`` (контракт К1–К8 +
«пять исправлений спеки»), а НЕ сегодняшнее поведение кода. Все объекты, через
которые тесты бьют по контракту (``StoreTapChannel``, ``ObservabilityHub``,
``HubStatsChannel``, ``ObservabilityStore``, ``hub_record_to_display``,
``LogStatsChannel``), — РЕАЛЬНЫЕ, уже существующие классы; ничего из них не
придумано. Единственные ДОГАДКИ отмечены в докстринге конкретного теста и
сведены в отчёте тестера к минимуму — по аналогии с уже существующим кодом
того же файла (см. ``TestProcessColumn.test_migration_adds_process_column_to_legacy_db``
в ``test_observability_store.py`` — тот же приём для колонки ``process``).

======================================================================
Что здесь НЕ проверяется (сознательно, не забыто)
======================================================================

* Живые 30-минутный/8-процессный замеры (строк/КиБ в час, горизонт при
  ``max_rows=200000``) — у тестера нет доступа к запущенному backend'у;
  автономные тесты ниже проверяют МЕХАНИЗМ на маленьком N, не темп.
* «Три диалекта числа сходятся к ``NumberRecord``» и «адаптеры удаляются» —
  интеграционное утверждение про ``StatsManager``/``ObservationManager``,
  проверено отдельно в ``test_task_3_1_number_record.py`` (К3) на уровне
  схемы; здесь не повторяется.
* Косметическая находка К6 («докстринг ``_init_fts`` ссылается на
  несуществующий ``test_the_store_never_updates_a_row``, поправить на
  ``test_no_update_ever_touches_an_indexed_column``») — это правка ОДНОЙ
  строки докстринга, не поведение; тестировать нечего, автору — поправить
  заодно.
"""

from __future__ import annotations


import pytest

from multiprocess_framework.modules.channel_routing_module.observability import (
    KIND_OBSERVATION,
    KIND_STATS,
    ORIGIN_ERROR_MANAGER,
    STATS_AGGREGATE_KEY,
    ObservabilityHub,
    ObservabilityStore,
    StoreTapChannel,
    hub_record_to_display,
)
from multiprocess_framework.modules.statistics_module.channels.hub_stats_channel import HubStatsChannel

#: К1: литерал контракта — значение маркера ``origin`` для строки-снапшота метрик.
#: Дан ПРЯМО текстом задачи («а ``origin=stats_snapshot``»), не выведен из кода.
ORIGIN_STATS_SNAPSHOT = "stats_snapshot"

#: Зачин строки снапшота — литерал из ``LogStatsChannel._format_snapshot``
#: (``head = f"metrics snapshot (ts={ts:.0f}, count={total}): "``), уже
#: существующий сегодня код; используется как признак «это та самая строка».
SNAPSHOT_MESSAGE_PREFIX = "metrics snapshot"


# ===========================================================================
# К1 — снапшот доезжает до стора РОВНО одной дорогой (store-tap не берёт
# origin=stats_snapshot, независимо от того, кто ВЛАДЕЕТ плоскостью ошибок).
# ===========================================================================


class TestK1StoreTapSkipsStatsSnapshotOrigin:
    def test_marked_record_writes_no_row_while_unmarked_control_does(self, tmp_path) -> None:
        """Основное свойство К1, с контролем достижимости в ТОМ ЖЕ тесте.

        Без контроля «ноль строк» неотличим от «tap вообще ничего не пишет»
        (см. память tester'а: утверждение об отсутствии требует парной
        проверки достижимости). Control — запись БЕЗ маркера, той же формы,
        через ТОТ ЖЕ tap: она обязана лечь в стор нормально.

        Сломается: если store-tap продолжит принимать snapshot-строки (К1 не
        реализован) — итоговый ``store.count()`` будет 2, а не 1.
        """
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        tap = StoreTapChannel(store)

        control = {
            "level": "INFO",
            "module": "worker_module",
            "timestamp": 1.0,
            "message": "ordinary log line",
            "extra": {},
        }
        marked = {
            "level": "INFO",
            "module": "log_stats",
            "timestamp": 2.0,
            "message": f"{SNAPSHOT_MESSAGE_PREFIX} (ts=2, count=3): [...]",
            "extra": {"origin": ORIGIN_STATS_SNAPSHOT},
        }

        result_control = tap.write(control)
        result_marked = tap.write(marked)

        assert result_control.get("status") == "success", f"контроль сам не записался: {result_control}"
        tap.flush(timeout=2.0)  # Task 3.3: без дожатия «ноль строк» ниже вакуумен
        assert store.count() == 1, (
            f"ожидалась РОВНО одна строка (контроль); snapshot-строка обязана быть пропущена "
            f"tap'ом, а не записана — фактически строк: {store.count()}, ответ на marked: {result_marked}"
        )
        store.close()

    def test_skip_is_reported_as_a_named_success_not_a_silent_write(self, tmp_path) -> None:
        """К1: «Пропуск возвращается как ``success`` (``{"skipped_origin": ...}``)».

        Ключ ``skipped_origin`` — ДОГАДКА тестера по аналогии с уже
        существующим в этом же классе литералом ``{"deduplicated": True}``
        (путь ``ORIGIN_ERROR_MANAGER``, см. ``store_tap.py``); план называет
        КЛЮЧ буквально в кавычках, поэтому проверяется только его ПРИСУТСТВИЕ,
        не конкретное значение (план значение не называет — стоит ``...``).
        """
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        tap = StoreTapChannel(store)
        marked = {
            "level": "INFO",
            "module": "log_stats",
            "timestamp": 1.0,
            "message": f"{SNAPSHOT_MESSAGE_PREFIX} (ts=1, count=1): [...]",
            "extra": {"origin": ORIGIN_STATS_SNAPSHOT},
        }
        result = tap.write(marked)
        assert result.get("status") == "success", f"пропуск обязан отвечать success, получено {result}"
        assert "skipped_origin" in result, (
            f"ответ пропуска обязан называть, ЧТО пропущено (ключ 'skipped_origin', по аналогии с "
            f"'deduplicated' у пути error_manager) — доступные ключи: {sorted(result.keys())}"
        )
        store.close()

    def test_rule_is_unconditional_not_gated_by_owns_error_plane(self, tmp_path) -> None:
        """К1: «правило другое, и копировать прежнее нельзя» — «не берёт НИ ОДИН tap».

        У ``ORIGIN_ERROR_MANAGER`` пропуск условен: ``owns_error_plane=True``
        строку БЕРЁТ (он и есть владелец плоскости ошибок). Реализация,
        скопировавшая эту же развилку для ``stats_snapshot`` (наиболее
        вероятная ошибка «взял старое правило по образцу»), пропускала бы
        snapshot-строку только у НЕ-владельца и писала бы её у tap'а с
        ``owns_error_plane=True``. Этот тест ставит tap ИМЕННО в роль
        владельца плоскости ошибок и требует пропуска и здесь — отличает
        «скопировали правило error_manager» от «сделали общее правило».
        """
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        tap_owner = StoreTapChannel(store, owns_error_plane=True)
        marked = {
            "level": "INFO",
            "module": "log_stats",
            "timestamp": 1.0,
            "message": f"{SNAPSHOT_MESSAGE_PREFIX} (ts=1, count=1): [...]",
            "extra": {"origin": ORIGIN_STATS_SNAPSHOT},
        }
        tap_owner.write(marked)
        tap_owner.flush(timeout=2.0)  # Task 3.3: без дожатия «ноль строк» ниже вакуумен
        assert store.count() == 0, (
            "tap с owns_error_plane=True тоже обязан пропустить stats_snapshot — правило "
            "не завязано на владение плоскостью ошибок (К1: 'не берёт НИ ОДИН tap')"
        )
        store.close()

    def test_origin_error_manager_marker_is_unaffected_by_this_task(self, tmp_path) -> None:
        """Контроль-регрессия: старое правило (``error_manager``, условный пропуск) не тронуто.

        Не часть К1 сама по себе (это поведение уже существует и зелено
        сегодня) — здесь как страховка: если реализация Task 3.1 случайно
        обобщит правило так, что ``error_manager`` тоже станет
        безусловным/сломанным, этот тест это увидит.
        """
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        tap_non_owner = StoreTapChannel(store, owns_error_plane=False)
        marked_error = {
            "level": "ERROR",
            "module": "error_manager",
            "timestamp": 1.0,
            "message": "boom",
            "extra": {"origin": ORIGIN_ERROR_MANAGER},
        }
        result = tap_non_owner.write(marked_error)
        assert result.get("deduplicated") is True
        tap_non_owner.flush(timeout=2.0)  # Task 3.3: без дожатия «ноль строк» ниже вакуумен
        assert store.count() == 0
        store.close()


class TestLogStatsChannelTagsSnapshotLineWithOrigin:
    """К1, сторона ЭМИТЕНТА: ``LogStatsChannel`` обязан САМ проставить маркер.

    Фейковый ``logger_manager`` — единственный способ увидеть, что именно
    канал передаёт в ``performance()``, не поднимая настоящий LoggerCore/tap
    (это уже проверяется классом выше, на РЕАЛЬНОМ ``StoreTapChannel``).
    """

    class _CapturingLogger:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def performance(self, level, message, module: str = "main", **extra) -> None:
            self.calls.append({"level": level, "message": message, "module": module, "extra": extra})

    def test_write_passes_origin_stats_snapshot_to_performance_call(self) -> None:
        """Сломается: если ``LogStatsChannel.write`` не передаёт ``origin`` в ``extra``
        вызова ``performance(...)`` — сегодня канал зовёт ``performance(level, msg,
        module=LOG_SOURCE)`` без единого дополнительного kwarg (проверено чтением
        ``log_stats_channel.py``), поэтому ``extra`` пуст и тест красный.
        """
        from multiprocess_framework.modules.statistics_module.channels.log_stats_channel import LogStatsChannel

        logger = self._CapturingLogger()
        channel = LogStatsChannel(logger)
        result = channel.write(
            {"metrics": [{"name": "fps", "type": "gauge", "tags": {}, "value": 30}], "total_count": 1, "timestamp": 5.0}
        )

        assert result.get("status") == "success", f"канал сам отказал: {result}"
        assert logger.calls, "LogStatsChannel не вызвал performance() вовсе"
        call_extra = logger.calls[0]["extra"]
        assert call_extra.get("origin") == ORIGIN_STATS_SNAPSHOT, (
            f"performance() обязан получить origin='{ORIGIN_STATS_SNAPSHOT}' в extra — получено {call_extra!r}"
        )


# ===========================================================================
# К2 — проверяемо СНАРУЖИ числом, с обязательным контролем (пара из самого К2).
# ===========================================================================


class TestK2CountsProveDedupWithControl:
    def test_n_flushes_give_n_stats_rows_and_zero_duplicate_log_rows(self, tmp_path) -> None:
        """К2 дословно: ``COUNT(kind='log' AND message LIKE 'metrics snapshot%') == 0``
        ПРИ ``COUNT(kind='stats') > 0`` — обе половины в одном тесте, иначе
        ноль дублей неотличим от «снапшотов не было вовсе» (правило самого К2).

        Дорога hub→stats (шаги 1-6) — РЕАЛЬНАЯ, уже существующая с задачи 2.1
        (``HubStatsChannel``/``ObservabilityHub.emit_stats_record``); эта
        половина сегодня уже проходит САМА ПО СЕБЕ — новое здесь только
        дедуп log-стороны (вторая половина assert'а).
        """
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        hub = ObservabilityHub("statistics_module")
        hub_channel = HubStatsChannel(hub)
        tap = StoreTapChannel(store)

        n = 3
        for i in range(n):
            hub_channel.write(
                {
                    "metrics": [{"name": "fps", "type": "gauge", "tags": {}, "value": 30.0 + i}],
                    "total_count": 1,
                    "timestamp": float(i),
                }
            )
            tap.write(
                {
                    "level": "INFO",
                    "module": "log_stats",
                    "timestamp": float(i),
                    "message": f"{SNAPSHOT_MESSAGE_PREFIX} (ts={i}, count=1): [...]",
                    "extra": {"origin": ORIGIN_STATS_SNAPSHOT},
                }
            )

        inserted = store.append_records(hub.drain_stats())
        assert inserted == n, f"фикстура сама не собралась: дренаж hub'а дал {inserted}, ожидалось {n}"
        tap.flush(timeout=2.0)  # Task 3.3: без дожатия «ноль строк» ниже вакуумен

        stats_count = store.count(kind="stats")
        log_rows = store.list_records(kind="log", limit=1000)
        duplicate_snapshot_logs = [r for r in log_rows if str(r["message"]).startswith(SNAPSHOT_MESSAGE_PREFIX)]

        assert stats_count > 0, "контроль: kind=stats обязан быть НЕПУСТ, иначе 'ноль дублей' ничего не доказывает"
        assert stats_count == n, f"COUNT(kind='stats') обязан быть равен числу флешей {n}, получено {stats_count}"
        assert duplicate_snapshot_logs == [], (
            f"COUNT(kind='log' AND message LIKE 'metrics snapshot%') обязан быть 0, "
            f"найдено {len(duplicate_snapshot_logs)}: {[r['message'] for r in duplicate_snapshot_logs]}"
        )
        store.close()


# ===========================================================================
# К4 — колонка metric: заполнена там, где строка ЕСТЬ одно число, NULL иначе.
# ===========================================================================


def _observation_record(*, writer: str, metric: str, value, ts: float, module: str = "capture_process") -> dict:
    """Hub-запись kind=observation — форма envelope + payload (см. ``ObservabilityHub.emit_observation_record``)."""
    return {"kind": KIND_OBSERVATION, "module": module, "ts": ts, "writer": writer, "metric": metric, "value": value}


def _single_stats_record(*, metric: str, value, ts: float, metric_type: str = "gauge", module: str = "seg") -> dict:
    """Hub-запись kind=stats, ОДИНОЧНАЯ метрика (без STATS_AGGREGATE_KEY)."""
    return {
        "kind": KIND_STATS,
        "module": module,
        "ts": ts,
        "metric": metric,
        "value": value,
        "metric_type": metric_type,
        "tags": {},
    }


def _aggregate_stats_record(*, ts: float, module: str = "seg") -> dict:
    """Hub-запись kind=stats, АГРЕГАТ окна (STATS_AGGREGATE_KEY=True, много метрик, без единого имени)."""
    return {
        "kind": KIND_STATS,
        "module": module,
        "ts": ts,
        STATS_AGGREGATE_KEY: True,
        "metrics": [
            {"name": "fps", "type": "gauge", "tags": {}, "value": 30},
            {"name": "drops", "type": "counter", "tags": {}, "count": 2},
        ],
        "total_count": 2,
        "window_ts": ts,
    }


def _log_record(*, message: str, ts: float, module: str = "worker_module") -> dict:
    return {"kind": "log", "module": module, "ts": ts, "severity": "info", "message": message, "context": {}}


def _error_record(*, message: str, ts: float, module: str = "worker_module") -> dict:
    return {
        "kind": "error",
        "module": module,
        "ts": ts,
        "severity": "error",
        "error_type": "ValueError",
        "message": message,
        "traceback": "tb",
        "context": {},
    }


class TestK4MetricColumnPopulation:
    """ДОГАДКА, названная явно: ``list_records(...)`` возвращает ключ ``"metric"``
    в строке результата — план не называет это буквально, но существующий
    прецедент (``process``/``severity_number``, добавленные прежними
    миграциями) уже проходит ИМЕННО этот путь: колонка появляется в схеме И
    в возвращаемом ``dict`` строки ``list_records``. Единственная НЕ-угаданная
    (SQL-уровня, без Python API) проверка — EXPLAIN-тест индекса ниже.
    """

    def test_observation_record_gets_writer_dot_metric_identity(self, tmp_path) -> None:
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        store.append_records([_observation_record(writer="capture", metric="drops", value=3, ts=1.0)])
        rows = store.list_records(kind="observation")
        assert len(rows) == 1, "фикстура сама не записалась"
        assert rows[0].get("metric") == "capture.drops", (
            f"kind=observation обязан дать metric='<writer>.<metric>'='capture.drops', "
            f"получено {rows[0].get('metric')!r} (ключи строки: {sorted(rows[0].keys())})"
        )
        store.close()

    def test_single_stats_record_gets_bare_metric_name(self, tmp_path) -> None:
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        store.append_records([_single_stats_record(metric="fps", value=30, ts=1.0)])
        rows = store.list_records(kind="stats")
        assert len(rows) == 1
        assert rows[0].get("metric") == "fps", (
            f"одиночная kind=stats обязана дать metric='fps', получено {rows[0].get('metric')!r}"
        )
        store.close()

    @pytest.mark.parametrize(
        "builder,label",
        [
            (lambda: _aggregate_stats_record(ts=1.0), "aggregate"),
            (lambda: _log_record(message="m", ts=1.0), "log"),
            (lambda: _error_record(message="e", ts=1.0), "error"),
        ],
    )
    def test_aggregate_log_and_error_rows_have_null_metric(self, tmp_path, builder, label) -> None:
        """К4: «агрегат, log, error → NULL» — три категории, одно правило, один тест-параметр каждая.

        **Якорь существования ОБЯЗАТЕЛЕН перед проверкой None** (см. память
        tester'а: negative-wording-assertion-needs-an-existence-anchor /
        unconnected-driver-reads-as-a-clean-zero). Без ``assert "metric" in
        rows[0]`` этот тест был бы ВАКУУМНО зелёным уже сегодня: ключа
        ``"metric"`` в возвращаемом dict нет вовсе (колонки не существует), и
        ``dict.get("metric")`` даёт ``None`` по умолчанию отсутствующего
        ключа — неотличимо от «ключ есть и хранит NULL». Поймано прогоном:
        первая редакция без этой строки была зелёной ДО реализации Task 3.1.
        """
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        store.append_records([builder()])
        rows = store.list_records()
        assert len(rows) == 1, f"фикстура {label} сама не записалась"
        assert "metric" in rows[0], (
            f"{label}: строка обязана нести КЛЮЧ 'metric' (со значением None) — ключ отсутствует "
            f"вовсе, доступные ключи: {sorted(rows[0].keys())}"
        )
        assert rows[0]["metric"] is None, f"{label}-строка обязана иметь metric=NULL, получено {rows[0]['metric']!r}"
        store.close()

    def test_filter_by_metric_returns_only_matching_rows(self, tmp_path) -> None:
        """Догадка (отдельно от предыдущей): ``list_records`` принимает kwarg ``metric=``.

        Показана из акцептанс-критерия буквально («select … where
        metric='capture.drops' возвращает ряд»); если реализация выберет
        другое имя параметра, здесь будет ``TypeError: unexpected keyword
        argument`` вместо содержательного расхождения — это ОТДЕЛЬНАЯ догадка
        от «строка несёт ключ metric» (предыдущие тесты), и падение здесь не
        значит, что тот, другой контракт тоже не выполнен.
        """
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        store.append_records(
            [
                _observation_record(writer="capture", metric="drops", value=1, ts=1.0),
                _observation_record(writer="capture", metric="frame_count", value=2, ts=2.0),
            ]
        )
        rows = store.list_records(metric="capture.drops")
        got = [r.get("metric") for r in rows]
        assert got == ["capture.drops"], f"фильтр metric обязан вернуть РОВНО capture.drops, получено {got}"
        store.close()

    def test_index_on_metric_and_ts_is_used_by_the_query_planner(self, tmp_path) -> None:
        """К4: «Индекс (metric, ts)» — проверено НА УРОВНЕ SQL (EXPLAIN QUERY PLAN),
        без единого предположения об именах Python-методов.

        Сегодня колонки ``metric`` нет вовсе — сам запрос не компилируется, и
        ``sqlite3.OperationalError: no such column: metric`` пробивает тест
        (НЕ обёрнуто в ``pytest.raises`` — иначе тест был бы зелёным уже
        сегодня, инверсия полярности; см. память tester'а). После реализации
        строка плана обязана называть использование индекса, а не полный
        скан таблицы.
        """
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        plan_rows = store._conn.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM records WHERE metric = ? ORDER BY ts", ("capture.drops",)
        ).fetchall()
        plan_text = " ".join(str(tuple(r)) for r in plan_rows).upper()
        # Сторожим ИМЯ индекса, а не слова «USING INDEX» — правка ведущего (2026-09-05).
        # Первая редакция требовала подстроку «USING INDEX» и краснела на ЛУЧШЕМ плане:
        # `SELECT id … WHERE metric=? ORDER BY ts` покрывается индексом целиком (rowid
        # лежит в самом индексе), и SQLite пишет «USING COVERING INDEX». Проверено
        # рядом: тот же запрос с `SELECT *` даёт обычное «USING INDEX». То есть литерал
        # различал не «индекс работает или нет», а форму списка колонок.
        # Имя индекса — проверка строго СИЛЬНЕЕ: план по таблице его не содержит вовсе.
        assert "IDX_RECORDS_METRIC_TS" in plan_text, (
            f"план запроса по metric не использует индекс (metric, ts): {plan_text}"
        )
        store.close()


# ===========================================================================
# К5 + К6 + К7(частично) — миграция унаследованного файла: metric заполняется
# backfill'ом, а message/severity СТАРЫХ строк не переписываются (bundle —
# см. докстринг теста, почему они в одном тесте, а не порознь).
# ===========================================================================


class TestK5MigrationBackfillsLegacyFileWithoutCorruptingOldRows:
    def test_legacy_db_gets_metric_backfilled_while_message_and_old_severity_survive(self, tmp_path) -> None:
        """Почему ТРИ проверки в ОДНОМ тесте, а не в трёх.

        К5 (backfill даёт ``metric``) и К6/К7 («backfill не трогает message/
        severity старых строк») по отдельности стали бы ВАКУУМНО зелёными
        сегодня: миграции ``metric`` не существует вовсе, значит ничего и не
        может её испортить — «message не изменился» тривиально верно, когда
        НИКАКОЙ код вообще не запускался. Связав их в одном тесте, я делаю
        первую (реально красную) проверку ВЕДУЩЕЙ: тест красный сегодня по
        существу (`metric` не читается), а вторая/третья проверки становятся
        содержательными только когда первая начнёт проходить — как «assert
        services.logs» перед проверкой словесной формулировки (см. память
        tester'а: negative-wording-assertion-needs-an-existence-anchor).

        **Строка-агрегат заводится СЫРЫМ SQL, и это правка ведущего (2026-09-05).**
        Первая редакция строила её сегодняшним ``ObservabilityStore`` — приёмом,
        который здесь не работает и не мог: после Task 3.1 тот же писатель кладёт
        в ``severity`` слово ``number`` (К7 распространён на агрегат), поэтому
        фикстура физически не способна произвести строку СТАРОЙ формы, а тест
        требовал от неё ``snapshot``. Тест краснел не на дефекте миграции, а на
        собственной невозможности. Свойство при этом настоящее и стоит того,
        чтобы его сторожили: засыпка не имеет права переписать ``severity`` уже
        записанных строк. Значит старую форму надо ВПИСАТЬ, а не воспроизвести
        сегодняшним кодом — ровно как это делает соседний
        `test_migration_adds_process_column_to_legacy_db` для схемы до 5.21.
        """
        db_path = str(tmp_path / "legacy.db")
        legacy = ObservabilityStore(db_path)
        legacy.append_records([_log_record(message="legacy log line — do not touch", ts=3.0)])
        # ВСЕ дореформенные строки вписываются СЫРЫМ SQL, с ``metric`` пустым —
        # вторая правка ведущего (2026-09-05), найденная СОБСТВЕННОЙ матрицей
        # инъекций, а не чтением. Заплата «засыпка не выполняется вовсе» убила
        # ровно ОДИН тест — hazard-тест автора, — а этот приёмочный остался
        # зелёным: строку наблюдения писал сегодняшний ``append_records``, и
        # ``metric`` ей проставлял нормализатор ПРИ ВСТАВКЕ. Засыпке нечего было
        # делать, и «backfill засыпал легаси-строку» было верно вхолостую.
        # Легаси-строка обязана прийти в файл БЕЗ имени — иначе тест сторожит
        # не миграцию, а нормализатор, который проверяют соседние тесты.
        legacy._conn.executemany(
            "INSERT INTO records (kind, process, module, ts, severity, severity_number, message, extra, metric) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, ?, NULL)",
            [
                # Наблюдение: имя вычислимо из message — засыпка ОБЯЗАНА его поставить.
                ("observation", "camera_0", "camera_0", 1.0, "level", "capture.drops", '{"value": 9}'),
                # Агрегат: severity='snapshot' — слово, которого сегодняшний
                # нормализатор уже не производит; имя невычислимо, останется NULL.
                (
                    "stats",
                    "seg",
                    "seg",
                    2.0,
                    "snapshot",
                    "metrics snapshot (count=1): fps",
                    '{"aggregate": true, "metrics": [{"name": "fps", "type": "gauge", "tags": {}, "value": 30}]}',
                ),
            ],
        )
        legacy._conn.commit()
        legacy.close()

        # «Новый процесс» открывает тот же файл — по этому открытию и мигрирует схема.
        reopened = ObservabilityStore(db_path)

        # К5 (ведущая проверка, красная сегодня): колонки metric нет — OperationalError
        # пробивает тест НЕ обёрнутым (иначе инверсия полярности).
        row = reopened._conn.execute("SELECT metric FROM records WHERE kind = 'observation'").fetchone()
        assert row["metric"] == "capture.drops", (
            f"backfill обязан вычислить metric='capture.drops', получено {row['metric']!r}"
        )

        # К6/К7 (содержательны только после того, как строка выше стала зелёной):
        # старые message/severity — БЕЗ ИЗМЕНЕНИЙ, литерал в литерал.
        aggregate_row = reopened.list_records(kind="stats")[0]
        assert aggregate_row["severity"] == "snapshot", (
            f"backfill НЕ имеет права переписать severity старой агрегатной строки — "
            f"было 'snapshot', стало {aggregate_row['severity']!r}"
        )
        # К4 на дороге ЗАСЫПКИ, а не только на дороге вставки (правка ведущего:
        # заплата «агрегат получает имя» убивала ровно один тест — тот, что
        # смотрит на нормализатор; засыпку в этой точке не сторожил никто).
        assert aggregate_row["metric"] is None, (
            f"у агрегата единственного имени нет — засыпка обязана оставить NULL, получено {aggregate_row['metric']!r}"
        )
        log_row = reopened.list_records(kind="log")[0]
        assert log_row["message"] == "legacy log line — do not touch", (
            f"backfill НЕ имеет права коснуться message — было 'legacy log line — do not touch', "
            f"стало {log_row['message']!r}"
        )
        reopened.close()

    def test_user_version_advances_past_the_metric_migration(self, tmp_path) -> None:
        """К5: «user_version +1» — миграция аддитивна и версионирована, а не безусловна
        на каждом открытии (иначе backfill гонялся бы на каждом старте процесса).

        Сегодня версия схемы — 2 (``_FTS_SCHEMA_VERSION``, задача 1.6, дословно
        прочитано в ``observability_store.py``). Это ЧИСЛО — литерал из
        сегодняшнего кода, а не переменная: если Task 3.1 введёт версию 3,
        строка ниже покраснеет РОВНО по этой причине, а не вычислит сама себя
        из будущей реализации (см. память tester'а: литерал, а не выражение
        из предмета).
        """
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        version = int(store._conn.execute("PRAGMA user_version").fetchone()[0])
        assert version > 2, (
            f"после Task 3.1 user_version обязан вырасти сверх сегодняшних 2 "
            f"(FTS-миграция задачи 1.6) — фактически {version}"
        )
        store.close()


# ===========================================================================
# К7 — severity числовой записи: ОДНО значение (NUMBER_SEVERITY = "number").
# ===========================================================================


class TestK7NumberSeverityIsUnified:
    @pytest.mark.parametrize(
        "record,label",
        [
            (lambda: _single_stats_record(metric="fps", value=30, ts=1.0, metric_type="gauge"), "single-stats(gauge)"),
            (lambda: _aggregate_stats_record(ts=2.0), "aggregate-stats"),
            (lambda: _observation_record(writer="capture", metric="drops", value=1, ts=3.0), "observation"),
        ],
    )
    def test_severity_is_the_literal_number_for_every_numeric_shape(self, record, label) -> None:
        """К7: «под ``NumberRecord`` форма одна, поэтому и значение одно: ``NUMBER_SEVERITY = "number"``».

        Использует ТОЛЬКО уже существующую функцию ``hub_record_to_display`` —
        ноль угаданных символов. Сегодня даёт 'gauge'/'snapshot'/'level'
        соответственно (прочитано в ``record_display.py``) — ни одно не
        равно 'number', тест красный по всем трём параметрам.
        """
        display = hub_record_to_display(record())
        assert display["severity"] == "number", (
            f"{label}: severity обязан стать литералом 'number', получено {display['severity']!r}"
        )

    @pytest.mark.parametrize(
        "record,label",
        [
            (lambda: _single_stats_record(metric="fps", value=30, ts=1.0), "single-stats"),
            (lambda: _aggregate_stats_record(ts=2.0), "aggregate-stats"),
            (lambda: _observation_record(writer="capture", metric="drops", value=1, ts=3.0), "observation"),
        ],
    )
    def test_severity_number_stays_unspecified_for_every_numeric_shape(self, record, label) -> None:
        """Смежный инвариант К7 (``severity_number == UNSPECIFIED``) — уже верен СЕГОДНЯ
        для всех трёх форм (``severity_number_for`` отдаёт UNSPECIFIED по kind
        ``stats``/``observation`` независимо от строки severity — прочитано в
        ``record_display.py``). Держится здесь как страховка от регресса, а
        не как новое красное свойство Task 3.1 — назван честно в отчёте.
        """
        display = hub_record_to_display(record())
        assert display["severity_number"] == 0, f"{label}: severity_number обязан остаться UNSPECIFIED(0)"


class TestGetattrAstGuardOnRecordDisplay:
    """Acceptance criteria (не К1-К8, отдельным пунктом): «Ни одного getattr по форме
    числовой записи в record_display.py (AST-страж)».

    **Единственный санкционированный зелёный тест в этом наборе** — контракт
    сам называет его зелёным вхолостую сегодня: нормализатор ходит по
    ``dict.get``, ``getattr`` в файле нет ни одного (проверено ``grep``'ом
    перед написанием). Это запрет на РЕГРЕСС, который может внести именно
    рефактор Task 3.1 (dataclass/Pydantic-модель вместо dict на входе
    нормализатора соблазнила бы написать ``record.name`` через ``getattr``),
    а не доказательство какого-либо сегодняшнего свойства.
    """

    def test_record_display_module_contains_no_getattr_calls(self) -> None:
        import ast
        import inspect

        from multiprocess_framework.modules.channel_routing_module.observability import record_display as module

        source = inspect.getsource(module)
        tree = ast.parse(source)
        offenders = [
            node.func.id if isinstance(node.func, ast.Name) else "getattr"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
        ]
        assert offenders == [], (
            f"record_display.py обязан ходить по dict.get, не по getattr — найдено {len(offenders)} вызовов"
        )

    def test_the_guard_above_can_actually_fire(self) -> None:
        """Молчащий детектор ничего не доказывает (см. память tester'а) — показываю
        его красным на заведомо нарушающем тексте, тем же разбором AST."""
        import ast

        offending_source = "def f(record):\n    return getattr(record, 'name', '')\n"
        tree = ast.parse(offending_source)
        offenders = [
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
        ]
        assert offenders, "разбор не нашёл getattr даже в нарушающем тексте — страж сам сломан"
