# -*- coding: utf-8 -*-
"""Хазард-тесты АВТОРА к Task 3.1 — то, что видно только изнутри механизма.

Это **дополнение** к слепому приёмочному набору
(``test_task_3_1_store_and_dedup.py``, ``test_task_3_1_number_record.py``,
``backend_ctl/tests/test_task_3_1_history_series.py``), а не его замена.
Тестер писал от контракта К1–К8 и реализации не видел; здесь — ровно обратное:
опасности, которые видны из ТОГО, КАК механизм построен, и невидимы из того,
что он обещает.

======================================================================
Что может сломаться именно в ЭТОМ механизме, учитывая как он построен
======================================================================

**1. Лестница ``user_version`` — три ступени, и перепрыгнуть можно молча.**
``_migrate_auto_vacuum`` (1), ``_init_fts`` (2) и ``_migrate_backfill_metric``
(3) гейтятся ОДНИМ числом, и каждая пропускает себя, увидев число не меньше
своего. ``_init_fts`` возвращается РАНЬШЕ своего ``PRAGMA user_version = 2``,
если в сборке SQLite нет FTS5 (законное состояние, оно так и задумано). Поставь
третья ступень своё число безусловно — файл, однажды открытый сборкой без FTS5,
НАВСЕГДА потерял бы полнотекстовый индекс по прежним строкам: следующая, уже
полноценная сборка увидела бы ``3 >= 2`` и пропустила бы backfill. Отказа при
этом нет нигде — поиск просто не находит того, что было записано до.

**2. ``NULL`` в колонке ``metric`` — законный КОНЕЦ, а не «ещё не посчитали».**
Засыпка ``severity_number`` (Ф3.6) опустошала своё множество за один проход:
значение получала каждая строка. Здесь у агрегата окна, лога и ошибки ``metric``
остаётся ``NULL`` навсегда, поэтому голое ``WHERE metric IS NULL`` не
опустошается НИКОГДА и переписывало бы NULL поверх NULL у всей ленты при каждом
старте процесса. Свойство, которое надо сторожить, — «на здоровом файле второй
проход не меняет НИ ОДНОЙ строки», и меряется оно числом изменений, а не
отсутствием жалоб.

**3. Гейт на данных обязан чинить падение ПОСЕРЕДИНЕ.** DDL в legacy-режиме
sqlite3 коммитится сразу, ``UPDATE`` едет в транзакции. Файл «колонка есть,
значения NULL, версия уже поднята» — достижимое состояние, и засыпка обязана его
исправить, а не счесть выполненной.

**4. Разбор JSON внутри миграции роняет ОТКРЫТИЕ стора.** ``json_extract`` на
непарсимом ``extra`` не отдаёт NULL, а бросает ``OperationalError``. Одна битая
строка (ручная правка файла, обрыв записи) закрыла бы доступ ко всей истории.

**5. Новый маркер ``origin`` стоит РЯДОМ со старым и мог бы съесть соседа.**
Правил теперь два, и они разной природы: ``error_manager`` — «берёт ровно один
tap», ``stats_snapshot`` — «не берёт ни один». Проверка на второй стоит ПЕРВОЙ и
безусловна; ошибка здесь глотала бы записи с любым третьим значением ``origin``.

**6. Идентичность метрики строится из ЧУЖИХ строк.** ``writer``/``metric``
приезжают с провода и бывают пустыми. Прежний код собирал текст записи
конкатенацией и на пустом имени давал ``"capture."`` — как ИМЯ РЯДА это мусор,
который при этом не равен ``NULL`` и потому попадает в срез.

**7. Файл читают ДВА кода с разными правами.** Стор открывает на запись и
мигрирует; ``backend_ctl.history_query`` открывает read-only и мигрировать не
вправе. Значит колонки ``metric`` в файле может не быть — и «фильтр не сузил»
здесь получается не из ошибки, а из штатного расхождения версий.

**8. Файл общий на процессы.** Миграцию на одном пути запускают несколько
писателей одновременно; ``PRAGMA table_info`` + ``ALTER TABLE`` — не атомарная
пара.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List

import pytest

from ..observability import (
    KIND_OBSERVATION,
    KIND_STATS,
    NUMBER_SEVERITY,
    ORIGIN_ERROR_MANAGER,
    ORIGIN_FIELD,
    ORIGIN_STATS_SNAPSHOT,
    ObservabilityStore,
    StoreTapChannel,
    hub_record_to_display,
    number_metric_identity,
)
from ..observability.observability_store import _FTS_SCHEMA_VERSION, _METRIC_SCHEMA_VERSION


def _observation(writer: str, metric: str, value: Any, ts: float) -> Dict[str, Any]:
    return {
        "kind": KIND_OBSERVATION,
        "module": "capture_proc",
        "ts": ts,
        "writer": writer,
        "metric": metric,
        "value": value,
    }


def _aggregate(ts: float) -> Dict[str, Any]:
    return {
        "kind": KIND_STATS,
        "module": "seg",
        "ts": ts,
        "aggregate": True,
        "metrics": [{"name": "fps", "type": "gauge", "tags": {}, "value": 30}],
        "total_count": 1,
        "window_ts": ts,
    }


def _log(message: str, ts: float) -> Dict[str, Any]:
    return {"kind": "log", "module": "worker_module", "ts": ts, "severity": "info", "message": message, "context": {}}


class TestVersionLadderHasNoShortcut:
    """Хазард 1: третья ступень не берётся со второй, если вторая не была взята."""

    def test_metric_migration_does_not_lock_out_the_fts_backfill(self, tmp_path, monkeypatch) -> None:
        """Файл, открытый сборкой БЕЗ FTS5, обязан получить индекс на следующей — с FTS5.

        Воспроизведение сборки без FTS5 — подменой ``_init_fts`` на ту же
        реакцию, что у настоящего кода в этом случае (запомнить причину и
        вернуться, НЕ трогая ``user_version``). Подменяется метод, а не сам
        sqlite: собрать интерпретатор без FTS5 здесь не из чего, а поведение
        ветки описано в самом ``_init_fts`` и воспроизводится дословно.

        Сломается: если засыпка ``metric`` поставит версию 3 безусловно — тогда
        на втором открытии ``_init_fts`` увидит ``3 >= 2``, пропустит rebuild, и
        поиск по слову из СТАРОЙ строки не найдёт ничего. Отказа при этом не
        будет нигде.
        """
        db_path = str(tmp_path / "no_fts_first.db")

        def _fts_unavailable(self) -> None:
            self._fts_reason = "имитация сборки SQLite без FTS5"

        monkeypatch.setattr(ObservabilityStore, "_init_fts", _fts_unavailable)
        crippled = ObservabilityStore(db_path)
        crippled.append_records([_log(message="ancient marker word", ts=1.0)])
        version_without_fts = int(crippled._conn.execute("PRAGMA user_version").fetchone()[0])
        crippled.close()

        assert version_without_fts < _METRIC_SCHEMA_VERSION, (
            f"версия перепрыгнула ступень: {version_without_fts} при непройденном FTS "
            f"({_FTS_SCHEMA_VERSION}) — следующая сборка пропустит backfill индекса"
        )

        monkeypatch.undo()
        healthy = ObservabilityStore(db_path)
        try:
            assert healthy.search_available, healthy.search_unavailable_reason
            found = healthy.search("ancient")
            assert len(found) == 1, (
                f"полнотекстовый индекс не построен по строкам, записанным до появления FTS5: {found!r}"
            )
            assert int(healthy._conn.execute("PRAGMA user_version").fetchone()[0]) == _METRIC_SCHEMA_VERSION
        finally:
            healthy.close()


class TestBackfillIsANoOpOnAHealthyFile:
    """Хазард 2: ``NULL`` — законный конец, и второй проход не имеет права его трогать."""

    def test_second_pass_changes_zero_rows(self, tmp_path) -> None:
        """Свойство меряется ЧИСЛОМ изменённых строк, а не отсутствием жалоб.

        ``total_changes`` — накопленный счётчик соединения; его прирост за вызов
        и есть «сколько строк переписала засыпка». На здоровом файле он обязан
        быть нулём: агрегат, лог и ошибка законно несут ``NULL``, и переписывание
        NULL поверх NULL — это грязные страницы на каждом старте процесса плюс
        риск задеть индексируемую колонку следующей правкой.

        Сломается: если убрать из ``WHERE`` вторую половину («и оно вычислимо») —
        прирост станет равен числу строк с NULL, то есть почти всей ленте.
        """
        store = ObservabilityStore(str(tmp_path / "healthy.db"))
        try:
            store.append_records(
                [
                    _observation("capture", "drops", 1, 1.0),
                    _aggregate(2.0),
                    _log(message="ordinary", ts=3.0),
                ]
            )
            before = store._conn.total_changes
            store._migrate_backfill_metric()
            delta = store._conn.total_changes - before
            assert delta == 0, (
                f"засыпка переписала {delta} строк на здоровом файле — она будет делать это при "
                "КАЖДОМ открытии процесса; NULL у агрегата/лога/ошибки законен и трогать его нечем"
            )
            # Контроль достижимости: сам счётчик не сломан и растёт на реальной записи.
            store.append_records([_log(message="one more", ts=4.0)])
            assert store._conn.total_changes > before, "total_changes не растёт даже на INSERT — мера слепа"
        finally:
            store.close()


class TestBackfillRepairsACrashInTheMiddle:
    """Хазард 3: «колонка есть, значения NULL, версия поднята» — достижимое состояние."""

    def test_column_present_but_empty_and_version_already_advanced_is_still_filled(self, tmp_path) -> None:
        """Гейт держится на ДАННЫХ, а не на «колонку только что добавили».

        Воспроизведение состояния — ровно то, что оставляет падение между
        ``ALTER`` (коммитится сразу в legacy-режиме) и ``UPDATE`` (едет в
        транзакции): колонка есть, значения NULL, версия схемы уже 3.

        Сломается: если засыпку загейтить фактом добавления колонки или версией
        схемы — строка останется без имени НАВСЕГДА, и ``where metric=…`` молча
        не найдёт дореформенную историю. Ровно этот дефект уже был воспроизведён
        на ``severity_number`` (ревью Ф3).
        """
        db_path = str(tmp_path / "half_migrated.db")
        seeded = ObservabilityStore(db_path)
        seeded.append_records([_observation("capture", "drops", 5, 1.0)])
        seeded.close()

        raw = sqlite3.connect(db_path)
        raw.execute("UPDATE records SET metric = NULL")
        raw.execute(f"PRAGMA user_version = {_METRIC_SCHEMA_VERSION}")
        raw.commit()
        emptied = raw.execute("SELECT COUNT(*) FROM records WHERE metric IS NULL").fetchone()[0]
        raw.close()
        assert emptied == 1, "фикстура сама не собралась — состояние «после падения» не построено"

        repaired = ObservabilityStore(db_path)
        try:
            row = repaired._conn.execute("SELECT metric FROM records").fetchone()
            assert row["metric"] == "capture.drops", (
                f"засыпка не починила файл, оставшийся после падения между ALTER и UPDATE: {row['metric']!r}"
            )
        finally:
            repaired.close()


class TestCorruptExtraDoesNotBlockTheStore:
    """Хазард 4: ``json_extract`` на битом тексте бросает, а не отдаёт NULL."""

    def test_a_row_with_unparsable_extra_still_lets_the_store_open(self, tmp_path) -> None:
        """Одна битая строка не имеет права закрыть доступ ко всей истории.

        Сломается: если снять ``json_valid(extra) = 0 OR`` из условия засыпки —
        ``ObservabilityStore(...)`` поднимет ``sqlite3.OperationalError``
        («malformed JSON») прямо в конструкторе, то есть история станет
        недоступна целиком из-за одной записи.
        """
        db_path = str(tmp_path / "corrupt_extra.db")
        seeded = ObservabilityStore(db_path)
        seeded.append_records([_observation("capture", "drops", 1, 1.0), _aggregate(2.0)])
        seeded.close()

        raw = sqlite3.connect(db_path)
        raw.execute("UPDATE records SET extra = ?, metric = NULL WHERE kind = 'stats'", ("{это не json",))
        raw.commit()
        raw.close()

        reopened = ObservabilityStore(db_path)
        try:
            rows = {r["kind"]: r for r in reopened.list_records()}
            assert rows["observation"]["metric"] == "capture.drops", "здоровая строка не засыпалась"
            # Битая строка остаётся ВИДИМОЙ недостачей: имени у неё нет, потому
            # что прочитать её конверт нечем, — а не потому, что имени не было.
            assert rows["stats"]["metric"] is None
        finally:
            reopened.close()


class TestMetricIdentityOnEmptyEdges:
    """Хазард 6: writer/metric приезжают с провода и бывают пустыми."""

    @pytest.mark.parametrize(
        "writer,name,expected",
        [
            ("capture", "drops", "capture.drops"),
            ("", "fps", "fps"),  # метрика самого процесса — писателя нет
            ("capture", "", None),  # НЕ "capture." — как имя ряда это мусор
            ("", "", None),
            ("  capture  ", "  drops  ", "capture.drops"),  # пробелы провода не создают второй ряд
        ],
    )
    def test_identity_never_produces_a_dangling_dot(self, writer, name, expected) -> None:
        """``"capture."`` не равно ``NULL`` и потому попало бы в срез по имени.

        Сломается: если вернуться к конкатенации ``f"{writer}.{metric}"`` — на
        пустом имени появится ряд с именем ``"capture."``, а на пустом писателе —
        ``".fps"``; оба неотличимы в SQL от настоящего имени.
        """
        assert number_metric_identity(writer, name) == expected

    def test_display_message_and_metric_column_come_from_one_string(self) -> None:
        """Два потребителя одного правила обязаны получить ОДНО значение.

        Сломается: если ``message`` снова начнут строить отдельной
        конкатенацией — на записи с пустым именем текст станет ``"capture."``, а
        колонка останется ``None``, и строка, читаемая как ``capture.``, не
        найдётся фильтром по метрике.
        """
        display = hub_record_to_display(_observation("capture", "", 1, 1.0))
        assert display["metric"] is None
        assert display["message"] == "", f"текст записи разошёлся с колонкой: {display['message']!r}"


class TestNewOriginMarkerDoesNotEatItsNeighbours:
    """Хазард 5: правил ``origin`` теперь два, и они разной природы."""

    def _line(self, origin: Any) -> Dict[str, Any]:
        extra = {} if origin is None else {ORIGIN_FIELD: origin}
        return {"level": "INFO", "module": "m", "timestamp": 1.0, "message": "line", "extra": extra}

    def test_a_third_origin_value_is_still_written_and_lifted_to_the_row(self, tmp_path) -> None:
        """Неизвестный маркер — не повод пропустить запись.

        Сломается: если проверку на ``stats_snapshot`` написать как «есть
        origin → пропустить» — исчезли бы все записи ``health.report`` и любых
        будущих плоскостей, а голос об этом не прозвучал бы нигде.
        """
        store = ObservabilityStore(str(tmp_path / "third.db"))
        tap = StoreTapChannel(store)
        try:
            result = tap.write(self._line("some_future_plane"))
            assert result.get("status") == "success"
            assert "skipped_origin" not in result, f"чужой маркер прочитан как наш: {result}"
            tap.flush(timeout=2.0)  # Task 3.3: дожать очередь перед чтением своих же строк
            rows = store.list_records()
            assert len(rows) == 1, f"запись с ТРЕТЬИМ значением origin потерялась: {rows}"
            assert rows[0]["extra"]["context"] == {ORIGIN_FIELD: "some_future_plane"}
        finally:
            store.close()

    def test_error_manager_rule_stays_conditional_while_the_new_one_is_not(self, tmp_path) -> None:
        """Две развилки, четыре исхода — все четыре в одном тесте.

        Иначе «новое правило безусловно» и «старое правило условно» проверялись
        бы порознь и разошлись бы молча: реализация, сделавшая БЕЗУСЛОВНЫМИ оба,
        прошла бы половину проверок.
        """
        store = ObservabilityStore(str(tmp_path / "both.db"))
        try:
            owner = StoreTapChannel(store, name="owner", owns_error_plane=True)
            outsider = StoreTapChannel(store, name="outsider", owns_error_plane=False)

            owner.write(self._line(ORIGIN_ERROR_MANAGER))  # владелец плоскости ошибок ПИШЕТ
            outsider.write(self._line(ORIGIN_ERROR_MANAGER))  # остальные пропускают
            owner.write(self._line(ORIGIN_STATS_SNAPSHOT))  # снапшот не берёт НИКТО,
            outsider.write(self._line(ORIGIN_STATS_SNAPSHOT))  # включая владельца

            # Дожать ОБА tap'а (Task 3.3): «ровно одна строка» ниже — утверждение
            # и о наличии, и об отсутствии; с неслитыми очередями оно вакуумно.
            owner.flush(timeout=2.0)
            outsider.flush(timeout=2.0)

            assert store.count() == 1, (
                f"ожидалась РОВНО одна строка (запись плоскости ошибок у её владельца), "
                f"фактически {store.count()} — правила origin разъехались"
            )
            assert store.list_records()[0]["extra"]["context"][ORIGIN_FIELD] == ORIGIN_ERROR_MANAGER
        finally:
            store.close()


class TestReopenKeepsTheColumnAndTheIndex:
    """Хазард 3/8, бытовая половина: повторное открытие ничего не теряет."""

    def test_column_index_and_writing_survive_a_reopen(self, tmp_path) -> None:
        db_path = str(tmp_path / "reopen.db")
        first = ObservabilityStore(db_path)
        first.append_records([_observation("capture", "drops", 1, 1.0)])
        first.close()

        second = ObservabilityStore(db_path)
        try:
            second.append_records([_observation("capture", "drops", 2, 2.0)])
            rows = second.list_records(metric="capture.drops")
            assert len(rows) == 2, f"после переоткрытия ряд неполон: {rows}"
            indexes = {r[0] for r in second._conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            assert "idx_records_metric_ts" in indexes, sorted(indexes)
        finally:
            second.close()


class TestConcurrentMigrationOnASharedFile:
    """Хазард 8: файл стора общий на процессы, миграцию запускают все сразу."""

    def test_eight_simultaneous_opens_do_not_raise(self, tmp_path) -> None:
        """``PRAGMA table_info`` + ``ALTER TABLE`` — не атомарная пара.

        Стор — «один писатель на процесс», но процессов восемь и файл у них
        один, поэтому старт стенда открывает его восемь раз почти одновременно.
        Проверяется НЕ производительность, а отсутствие ``duplicate column
        name``/``database is locked`` у любого из открывающих: упавший
        конструктор — это процесс без истории, молча.

        Барьер, а не «просто восемь потоков»: без него планировщик почти
        наверняка развёл бы открытия по времени, и тест сторожил бы очередь, а
        не гонку.
        """
        db_path = str(tmp_path / "shared.db")
        ObservabilityStore(db_path).close()  # файл существует, дальше — только миграции

        workers = 8
        barrier = threading.Barrier(workers)
        failures: List[BaseException] = []

        def _open_and_close() -> None:
            try:
                barrier.wait(timeout=10.0)
                store = ObservabilityStore(db_path)
                store.append_records([_observation("capture", "drops", 1, 1.0)])
                store.close()
            except BaseException as exc:  # noqa: BLE001 — собираем ЛЮБОЙ отказ, он и есть предмет
                failures.append(exc)

        threads = [threading.Thread(target=_open_and_close, daemon=True) for _ in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30.0)
            assert not t.is_alive(), "открытие стора зависло — это хуже отказа, его прячет таймаут"

        assert not failures, f"одновременное открытие общего файла дало отказы: {[repr(e) for e in failures]}"


class TestNumberSeverityIsOneWordNotThree:
    """Смежная страховка: одно слово по ОБЕИМ дорогам записи, live и history."""

    def test_live_display_and_stored_row_agree(self, tmp_path) -> None:
        """Форма живого хвоста и форма истории обязаны совпадать ПО ПОСТРОЕНИЮ.

        Сломается: если ``severity`` начнут считать в сторе отдельно от
        нормализатора — вкладка и история разойдутся, и фильтр заработает на
        половине данных.
        """
        record = _observation("capture", "drops", 1, 1.0)
        store = ObservabilityStore(str(tmp_path / "agree.db"))
        try:
            store.append_records([record])
            row = store.list_records()[0]
            display = hub_record_to_display(record)
            assert display["severity"] == row["severity"] == NUMBER_SEVERITY
            assert display["metric"] == row["metric"] == "capture.drops"
        finally:
            store.close()


# ===========================================================================
# Хазард 7 — сторона читателя: history_query открывает файл read-only и
# мигрировать его не вправе.
# ===========================================================================


class TestHistoryQueryOnAFileWithoutTheColumn:
    """Замена удалённому ``TestK7MetricNotYetSupported`` — отказ остался, основание другое."""

    @staticmethod
    def _legacy_db(tmp_path) -> str:
        """Файл ДО Task 3.1: колонки ``metric`` нет вовсе (сырой SQL — стор её завёл бы)."""
        db_path = str(tmp_path / "pre_task_31.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, "
            "process TEXT, module TEXT NOT NULL, ts REAL NOT NULL, severity TEXT, "
            "severity_number INTEGER, message TEXT, extra TEXT)"
        )
        # ``ts`` — СЕЙЧАС, а не 1.0: окно ``since=-600`` считается от часов
        # драйвера, и запись из эпохи в него не попадает. Первая редакция
        # фикстуры давала пустую ленту и выглядела как поломка инструмента.
        conn.execute(
            "INSERT INTO records (kind, process, module, ts, severity, severity_number, message, extra) "
            "VALUES ('log','p','m',?,'info',9,'old line',?)",
            (time.time(), json.dumps({})),
        )
        conn.commit()
        conn.close()
        return db_path

    @staticmethod
    def _driver(db_path: str):
        from backend_ctl.driver import BackendDriver

        drv = BackendDriver()
        drv.send_command = lambda *a, **kw: {  # type: ignore[assignment]
            "success": True,
            "process": "ProcessManager",
            "history": {"enabled": True, "db_path": db_path},
        }
        return drv

    def test_metric_filter_refuses_by_name_instead_of_dumping_everything(self, tmp_path) -> None:
        """«Фильтровать нечем» и «фильтр не сузил» — разные ответы, худший исход спутать их.

        Сломается: если ``metric`` уйдёт в общий список колонок ``SELECT`` без
        проверки файла — вместо названного отказа приедет ``no such column:
        metric``, обвиняющий файл в баге драйвера; а если фильтр просто
        проигнорировать — приедет ВЕСЬ стор под видом среза по метрике.
        """
        db_path = self._legacy_db(tmp_path)
        result = self._driver(db_path).history_query(metric="capture.drops", since=-600)
        assert result.get("success") is False, f"срез по метрике на файле без колонки обязан отказать: {result}"
        error = str(result.get("error", ""))
        assert "metric" in error, f"отказ не называет ПРИЧИНУ: {error!r}"
        # Сравнение по имени файла, а не по полному пути: в тексте отказа путь
        # стоит под ``!r``, и на Windows его обратные слэши там удвоены —
        # первая редакция этой проверки падала ИМЕННО на экранировании, а не
        # на отсутствии адреса.
        assert os.path.basename(db_path) in error, f"отказ не называет АДРЕС (какой файл): {error!r}"
        assert not result.get("rows"), f"отказ обязан быть БЕЗ строк, а не тихим дампом: {result.get('rows')}"

    def test_the_rest_of_the_tool_still_works_on_such_a_file(self, tmp_path) -> None:
        """Контроль достижимости к предыдущему: отказ УЗКИЙ, а не «инструмент лёг».

        Без этой пары «отказ по metric» был бы неотличим от «history_query на
        старом файле не работает вовсе» — а лента, поиск и прочие фильтры к
        колонке ``metric`` отношения не имеют.
        """
        db_path = self._legacy_db(tmp_path)
        result = self._driver(db_path).history_query(since=-600)
        assert result.get("success") is True, f"лента на файле без колонки metric сломалась: {result}"
        assert [r["message"] for r in result["rows"]] == ["old line"]
        assert result["rows"][0]["metric"] is None, "строка обязана нести ключ metric со значением None"


class TestSeriesShapeHazards:
    """Хазард ряда: что считается точкой, а что — пропуском."""

    @staticmethod
    def _rows(values: List[Any]) -> List[Dict[str, Any]]:
        return [{"id": i, "ts": float(i), "extra": {"value": v}} for i, v in enumerate(values, start=1)]

    def test_string_number_and_bool_are_skipped_not_coerced(self) -> None:
        """``"5"`` и ``True`` — НЕ точки ряда, и пропуск назван числом.

        Строка ``"5"`` выглядит числом и приводится ``float()`` без ошибки —
        именно поэтому проверка написана через ``isinstance``, а не через
        ``try: float(...)``: молчаливое приведение нарисовало бы тренд из
        текстовых значений, у которых в сторе может лежать что угодно.
        ``bool`` в Python подкласс ``int``, и уровень-флаг ``connected=True``
        стал бы ``1.0``.

        Сломается: если условие заменить на ``try: float(value)`` — оба входа
        попадут в ряд, и ``series_skipped`` станет нулём при живых пропусках.
        """
        from backend_ctl.driver import _history_series

        points, skipped = _history_series(self._rows([1.0, "5", True, None, 2.0]))
        assert [p[1] for p in points] == [1.0, 2.0], points
        assert skipped == 3, f"пропуски обязаны быть СОСЧИТАНЫ, получено {skipped}"

    def test_points_are_ordered_by_ts_not_by_row_order(self) -> None:
        """Ряд читают как временной — порядок задаёт ``ts``, а не порядок строк.

        Сломается: если ряд собирать разворотом списка (``rows[::-1]``) — при
        доливке старых записей батчем (``id`` и ``ts`` расходятся) точки поедут
        в порядке ПРИХОДА В СТОР, и график покажет ломаную назад во времени.
        """
        from backend_ctl.driver import _history_series

        rows = [
            {"id": 3, "ts": 30.0, "extra": {"value": 3.0}},
            {"id": 1, "ts": 10.0, "extra": {"value": 1.0}},
            {"id": 2, "ts": 20.0, "extra": {"value": 2.0}},
        ]
        points, skipped = _history_series(rows)
        assert points == [[10.0, 1.0], [20.0, 2.0], [30.0, 3.0]]
        assert skipped == 0

    def test_empty_series_still_names_its_skips(self) -> None:
        """Ноль точек при ненулевых пропусках — это ОТВЕТ, а не молчание.

        «Ряда нет, потому что строк не было» и «ряд пуст, потому что ни одна из
        четырёх строк не дала числа» — разные факты, и различает их только
        число.
        """
        from backend_ctl.driver import _history_series

        points, skipped = _history_series(self._rows([None, "x", {}, []]))
        assert points == []
        assert skipped == 4


class TestGoldenPathOnRealObjects:
    """К1/К2 на НАСТОЯЩЕЙ проводке — не на фейковом логгере.

    Приёмочный тест тестера («канал передаёт origin в performance») смотрит на
    ФЕЙКОВЫЙ логгер и потому доказывает форму вызова, а не доставку: переименуй
    кто-нибудь поле в ``LogRecord.extra`` — тест остался бы зелёным, а дубль
    вернулся бы в стор. Здесь собраны живые ``LoggerManager`` + ``StoreTapChannel``
    + ``ObservabilityStore`` + оба канала статистики, и один снапшот проезжает
    ОБЕ дороги разом.
    """

    def test_one_snapshot_gives_one_stats_row_and_no_duplicate_log_row(self, tmp_path) -> None:
        """К2 дословно, с обязательным контролем: ноль дублей ПРИ непустом kind=stats.

        Сломается: если ``LogStatsChannel`` перестанет ставить маркер, если
        kwargs логгера перестанут доезжать до ``LogRecord.extra``, или если tap
        станет читать маркер не оттуда — дубль вернётся, и ``kind=log`` со
        строкой снапшота станет равен единице.
        """
        from ...logger_module.configs.logger_manager_config import LoggerChannelSchema, LoggerManagerConfig
        from ...logger_module.configs.logger_manager_config import LoggerScopeSchema
        from ...logger_module.core.log_config import LogLevel
        from ...logger_module.core.logger_manager import LoggerManager
        from ...statistics_module.channels.hub_stats_channel import HubStatsChannel
        from ...statistics_module.channels.log_stats_channel import LogStatsChannel
        from ..observability import ObservabilityHub

        config = LoggerManagerConfig(
            app_name="t31_golden",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={
                "perf_file": LoggerChannelSchema(
                    name="perf_file", type="file", enabled=True, file_path="performance.log", rotate=False
                )
            },
            default_level="DEBUG",
            scopes={
                scope: LoggerScopeSchema(channels=["perf_file"]) for scope in ("SYSTEM", "BUSINESS", "PERFORMANCE")
            },
        )
        logger = LoggerManager(manager_name="T31Logger", config=config)
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        try:
            logger.add_tap(StoreTapChannel(store, process="camera_0"), min_level=LogLevel.INFO, name="store_tap")

            hub = ObservabilityHub("statistics_module")
            snapshot = {
                "metrics": [{"name": "fps", "type": "gauge", "tags": {}, "value": 30.0}],
                "total_count": 1,
                "timestamp": 5.0,
            }
            # Обе дороги ОДНОГО снапшота, как на живом процессе: структурная
            # (hub → drain → стор) и человеческая (performance.log).
            assert HubStatsChannel(hub).write(snapshot)["status"] == "success"
            assert LogStatsChannel(logger).write(snapshot)["status"] == "success"
            logger.flush()

            inserted = store.append_records(hub.drain_stats())
            assert inserted == 1, "фикстура сама не собралась: снапшот не доехал структурной дорогой"

            # Task 3.3: снять tap = дожать его очередь (``remove_tap`` зовёт
            # ``close()`` канала). Сам объект tap'а отсюда недостижим — он
            # живёт внутри менеджера, — и это ровно та дорога, которой обязан
            # ходить останов в проде.
            assert logger.remove_tap("store_tap") is True

            stats_rows = store.count(kind="stats")
            snapshot_logs = [
                r for r in store.list_records(kind="log", limit=100) if str(r["message"]).startswith("metrics snapshot")
            ]
            assert stats_rows == 1, "контроль: kind=stats обязан быть НЕПУСТ, иначе ноль дублей не значит ничего"
            assert snapshot_logs == [], (
                f"человеческая копия снапшота доехала в стор второй дорогой: "
                f"{[r['message'][:60] for r in snapshot_logs]}"
            )
            # Файл для человека при этом никуда не делся — резать надо было
            # только вторую дорогу в стор, а не саму строку.
            perf = (tmp_path / "performance.log").read_text(encoding="utf-8", errors="replace")
            assert "metrics snapshot" in perf, "строка снапшота исчезла и из performance.log — срезано лишнее"
        finally:
            store.close()
            logger.shutdown()
