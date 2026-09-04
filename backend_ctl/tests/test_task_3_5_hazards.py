# -*- coding: utf-8 -*-
"""Task 3.5 — hazard-тесты АВТОРА для ``BackendDriver.history_query``.

НЕ дубль ``test_task_3_5_history_query.py`` (тот — приёмка К1-К8 от независимого
тестера по критериям, вслепую). Здесь — то, что видно только ИЗНУТРИ конструкции:
что ИМЕННО может сломаться в ЭТОЙ реализации (read-only sqlite3-соединение поверх
WAL-файла, который пишет другой процесс/поток; JSON в TEXT-колонке; часы читателя
вместо часов писателя; ручная сборка WHERE из имён фильтров).

Каждый тест — докстрока «что ломается, если это свойство снять» ПЕРЕД кодом
(правило проекта: ценность рождается при написании докстроки, не только в прогоне).

Комментарии и докстроки — по-русски (правило проекта).
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

import pytest

import backend_ctl.driver as driver_module
from backend_ctl.driver import BackendDriver

from multiprocess_framework.modules.channel_routing_module.observability import ObservabilityStore


class _FakeSendCommand:
    """Тот же фейк-приём, что в приёмочном файле — history_query зовёт ровно один readback."""

    def __init__(self, response: Dict[str, Any]) -> None:
        self._response = response
        self.calls: List[tuple] = []

    def __call__(self, target: str, command: str, args: Optional[dict] = None, *, timeout: Optional[float] = None):
        self.calls.append((target, command, args, timeout))
        return dict(self._response)


def _driver_for(db_path: str, *, process: str = "ProcessManager") -> BackendDriver:
    drv = BackendDriver()
    drv.send_command = _FakeSendCommand(  # type: ignore[assignment]
        {"success": True, "process": process, "history": {"enabled": True, "db_path": db_path}}
    )
    return drv


def _seed(tmp_path, records: List[Dict[str, Any]]) -> str:
    db_path = str(tmp_path / "hazard.db")
    store = ObservabilityStore(db_path=db_path)
    inserted = store.append_records(records)
    assert inserted == len(records), "фикстура сама не записалась — тест будет врать"
    return db_path, store


def _log_record(message: str, *, ts: Optional[float] = None, module: str = "m", process: str = "p") -> Dict[str, Any]:
    return {
        "kind": "log",
        "module": module,
        "process": process,
        "ts": time.time() if ts is None else ts,
        "severity": "info",
        "message": message,
        "context": {},
    }


# ===========================================================================
# Хазард 1 — WAL: писатель ЖИВ и продолжает писать в момент чтения.
# ===========================================================================


class TestWalConcurrentWriter:
    """Что ломается, если это свойство снять: read-only соединение открывалось бы
    поверх ОБЫЧНОГО (rw, без mode=ro) файла БД — тогда конкурентная запись живого
    писателя рано или поздно даёт ``database is locked`` на читателе, потому что
    два rw-соединения конкурируют за журнал. WAL + read-only читают ПОСЛЕДНИЙ
    ЗАКОММИЧЕННЫЙ снимок без блокировки писателя — это и есть контракт К3,
    испытанный здесь ЖИВЬЁМ (писатель не закрывается между двумя вызовами), а не
    только продекларированный."""

    def test_reader_sees_committed_rows_while_writer_stays_open(self, tmp_path) -> None:
        db_path, store = _seed(tmp_path, [_log_record("до открытия писателя")])
        try:
            drv = _driver_for(db_path)
            first = drv.history_query(limit=10)
            assert first["success"] is True
            assert [r["message"] for r in first["rows"]] == ["до открытия писателя"]

            # Писатель НЕ закрыт — то же самое соединение продолжает писать,
            # имитируя другой процесс, живущий рядом с читателем в этот же момент.
            store.append_records([_log_record("после открытия писателя, до второго чтения")])

            second = drv.history_query(limit=10)
            assert second["success"] is True
            messages = [r["message"] for r in second["rows"]]
            assert "после открытия писателя, до второго чтения" in messages, (
                f"read-only соединение не увидело закоммиченную запись живого писателя: {messages}"
            )
        finally:
            store.close()

    def test_reader_does_not_corrupt_or_lock_out_the_live_writer(self, tmp_path) -> None:
        """Обратная сторона: read-only чтение НЕ мешает писателю продолжать писать
        (если бы наше соединение держало эксклюзивную блокировку, следующий
        ``append_records`` писателя завис бы на ``busy_timeout`` или потерял строки)."""
        db_path, store = _seed(tmp_path, [_log_record("исходная")])
        try:
            drv = _driver_for(db_path)
            drv.history_query(limit=10)  # открыть-прочитать-закрыть read-only соединение
            inserted = store.append_records([_log_record("после чтения")])
            assert inserted == 1, f"писатель потерял запись после read-only чтения рядом: dropped={store.dropped}"
            assert store.dropped == 0
        finally:
            store.close()


# ===========================================================================
# Хазард 2 — соединение обязано закрыться, включая путь с исключением.
# ===========================================================================


class _ClosingConnection:
    """Прозрачная обёртка над РЕАЛЬНЫМ sqlite3-соединением — форвардит всё, кроме
    ``close()``, который дополнительно отмечается в ``closed`` (снаружи проверяемо).
    """

    def __init__(self, real: sqlite3.Connection) -> None:
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "closed", False)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._real, name, value)

    def close(self) -> None:
        object.__setattr__(self, "closed", True)
        self._real.close()


class TestConnectionAlwaysCloses:
    """Что ломается, если это свойство снять: history_query зовётся агентом
    повторно (разные фильтры, поисковые уточнения) — каждый неудачный вызов без
    закрытия оставлял бы читающий handle открытым на файл БД. На Windows это
    рано или поздно мешает писателю/ретеншену/VACUUM'у (файл занят читателем),
    а сам процесс агента копит открытые дескрипторы без предела. ``finally:
    conn.close()`` в history_query обязан сработать ДАЖЕ когда сам запрос упал
    исключением, которое history_query не ловит (не входит в его словарь именованных
    отказов) — это и проверяется здесь принудительным взломом внутренней функции."""

    def test_connection_closes_even_when_the_query_raises_unexpectedly(self, tmp_path, monkeypatch) -> None:
        db_path, store = _seed(tmp_path, [_log_record("что угодно")])
        store.close()

        tracker: Dict[str, Any] = {}
        real_connect = sqlite3.connect

        def _spy_connect(*args: Any, **kwargs: Any) -> Any:
            wrapped = _ClosingConnection(real_connect(*args, **kwargs))
            tracker["conn"] = wrapped
            return wrapped

        monkeypatch.setattr(sqlite3, "connect", _spy_connect)

        def _boom(*_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("сбой середины запроса — НЕ входит в словарь именованных отказов history_query")

        # Взлом ИЗНУТРИ (не публичный контракт К1-К8, поэтому — hazard, а не приёмка):
        # чтение без text идёт через _history_list_rows.
        monkeypatch.setattr(driver_module, "_history_list_rows", _boom)

        drv = _driver_for(db_path)
        with pytest.raises(RuntimeError, match="сбой середины запроса"):
            drv.history_query()

        assert "conn" in tracker, "sqlite3.connect ни разу не был позван — тест не проверил то, что думает"
        assert tracker["conn"].closed is True, (
            "соединение НЕ закрылось при незапланированном исключении внутри запроса — "
            "read-only handle остался висеть на файле"
        )


# ===========================================================================
# Хазард 3 — extra: битый JSON в одной строке не должен ронять весь ответ.
# ===========================================================================


class TestCorruptedExtraJson:
    """Что ломается, если это свойство снять: колонка ``extra`` — TEXT с JSON,
    её никто, кроме ``ObservabilityStore``, не пишет НАПРЯМУЮ — но обрыв записи
    посреди flush (crash питания, диск переполнен на середине INSERT — WAL это
    смягчает, но не гарантирует от ручной порчи файла сторонним инструментом)
    способен оставить нечитаемый JSON в этой колонке одной строки. Если
    ``json.loads`` кинет некэтченый ``ValueError`` наружу, ОДНА повреждённая
    строка убивает ВЕСЬ ответ history_query — агент теряет доступ к истории
    целиком из-за одной старой записи, вместо того чтобы просто не понять её extra."""

    def test_one_corrupted_row_does_not_break_the_whole_response(self, tmp_path) -> None:
        db_path, store = _seed(
            tmp_path,
            [
                _log_record("здоровая запись 1", ts=100.0),
                _log_record("запись с битым extra", ts=200.0),
                _log_record("здоровая запись 2", ts=300.0),
            ],
        )
        store.close()

        # Порча ПОСЛЕ закрытия store — напрямую, как обрыв файла сторонним инструментом
        # (не через API стора: тот никогда не пишет невалидный JSON сам).
        raw = sqlite3.connect(db_path)
        try:
            raw.execute("UPDATE records SET extra = ? WHERE message = ?", ("{не json:::", "запись с битым extra"))
            raw.commit()
        finally:
            raw.close()

        drv = _driver_for(db_path)
        result = drv.history_query(limit=10)
        assert result["success"] is True, f"одна повреждённая строка уронила весь ответ: {result}"
        by_message = {r["message"]: r for r in result["rows"]}
        assert set(by_message) == {"здоровая запись 1", "запись с битым extra", "здоровая запись 2"}, (
            "повреждённая строка исчезла из ответа целиком вместо того, чтобы прийти с пометкой"
        )

        healthy = by_message["здоровая запись 1"]
        assert isinstance(healthy["extra"], dict) and healthy["extra"] == {"context": {}}

        broken = by_message["запись с битым extra"]
        assert isinstance(broken["extra"], dict), f"extra повреждённой строки не dict: {broken['extra']!r}"
        assert "{не json:::" in json.dumps(broken["extra"], ensure_ascii=False), (
            f"повреждённый текст исчез молча вместо явной пометки: {broken['extra']!r}"
        )


# ===========================================================================
# Хазард 4 — часы ЧИТАТЕЛЯ, не часы ПИСАТЕЛЯ: since/until относительны к driver'у.
# ===========================================================================


class TestClockIsTheReadersNotTheWriters:
    """Что ломается, если это свойство снять (точнее: что уже сломано ПО КОНСТРУКЦИИ
    и должно быть названо, а не спрятано): К5 резолвит отрицательные since/until
    через ``time.time()`` МАШИНЫ ДРАЙВЕРА, а строки несут ``ts`` часов ПРОЦЕССА-
    ЭМИТЕНТА. Из этого следует конкретная дыра: запись с ``ts`` в БУДУЩЕМ (сбой
    NTP писателя, разъехавшиеся часы контейнера) проходит ЛЮБОЙ фильтр
    ``since=-N`` НАВСЕГДА — потому что ``ts >= now-N`` тривиально истинно для
    любого будущего ``ts``. Окно «последние 10 минут» в этом случае перестаёт
    быть окном: скошенная в будущее запись остаётся в нём сколько угодно долго."""

    def test_a_future_skewed_timestamp_never_leaves_the_recent_window(self, tmp_path) -> None:
        far_future = time.time() + 10_000  # писатель с часами, ушедшими на ~2.8 часа вперёд
        db_path, store = _seed(
            tmp_path,
            [
                _log_record("нормальная запись", ts=time.time()),
                _log_record("скошенная в будущее запись", ts=far_future),
            ],
        )
        store.close()

        drv = _driver_for(db_path)
        result = drv.history_query(since=-60, limit=10)  # «последняя минута»
        assert result["success"] is True
        messages = [r["message"] for r in result["rows"]]
        assert "скошенная в будущее запись" in messages, (
            "документируемая дыра не воспроизвелась — если это когда-нибудь перестанет быть "
            "так, докстрока history_query про часы читателя устарела и должна быть переписана"
        )


# ===========================================================================
# Хазард 5 — severity=[] это «не фильтровать», а не «показать пусто» (решение застраховано).
# ===========================================================================


class TestEmptySeverityListMeansNoFilter:
    """Что ломается, если это свойство снять (то есть если решение когда-нибудь
    молча поменяют на противоположное): агент, программно строящий фильтр
    (``severity=[s for s in candidates if ...]``), в вырожденном случае пустого
    списка получил бы ПОЛНОСТЬЮ ПУСТОЙ ответ вместо «фильтр не применён» — и
    прочитал бы это как «истории нет вовсе», хотя причина — в форме вызова.
    Тест закрепляет выбор явно, а не оставляет его свойством `if severity_in:`,
    которое можно перепутать с обратным на следующей правке."""

    def test_empty_severity_list_returns_everything_not_nothing(self, tmp_path) -> None:
        db_path, store = _seed(
            tmp_path,
            [_log_record("раз", ts=1.0), _log_record("два", ts=2.0)],
        )
        store.close()
        drv = _driver_for(db_path)
        result = drv.history_query(severity=[], limit=10)
        assert result["success"] is True
        assert {r["message"] for r in result["rows"]} == {"раз", "два"}, (
            f"severity=[] срезал выдачу вместо того, чтобы не фильтровать: {result['rows']}"
        )


# ===========================================================================
# Хазард 6 — имена фильтров идут ?-плейсхолдерами, инъекция не пробивает.
# ===========================================================================


class TestFilterValuesAreParameterizedNotInterpolated:
    """Что ломается, если это свойство снять: WHERE собирается из СТРОК фильтров
    вручную (``_history_where_clauses``) — если бы значение (не имя колонки, а
    именно ЗНАЧЕНИЕ фильтра) хоть раз попало в SQL склейкой, а не через ``?``,
    операторский/агентский ввод с кавычкой или ``;`` ломал бы запрос синтаксически
    либо — в горшем случае — исполнял чужой SQL. Инъекция здесь ЦЕЛится в
    ЗНАЧЕНИЕ (``process=...``), не в имя параметра — имена параметров и так
    фиксированы сигнатурой Python и инъекции не подвержены."""

    def test_a_sql_metacharacter_in_a_filter_value_is_inert(self, tmp_path) -> None:
        db_path, store = _seed(
            tmp_path,
            [_log_record("цель", process="victim", ts=1.0)],
        )
        store.close()
        drv = _driver_for(db_path)

        payload = "victim'; DROP TABLE records; --"
        result = drv.history_query(process=payload, limit=10)
        assert result["success"] is True, f"инъекция сломала запрос синтаксически: {result}"
        assert result["rows"] == [], "заведомо несуществующий process нашёл строки — фильтр не сузил"

        # Таблица жива и данные на месте — ни один осколок инъекции не исполнился.
        survivor = drv.history_query(process="victim", limit=10)
        assert survivor["success"] is True
        assert [r["message"] for r in survivor["rows"]] == ["цель"], (
            f"таблица records повреждена инъекцией или потеряла строки: {survivor}"
        )


# ===========================================================================
# Хазард 7 — поиск (FTS) недоступен: именованный отказ, а НЕ падение всего инструмента;
# лента (без text) при этом работает независимо от состояния FTS-индекса.
# ===========================================================================


class TestSearchUnavailableIsIsolatedFromPlainListing:
    """Что ломается, если это свойство снять: ``history_query`` не инстанцирует
    ``ObservabilityStore`` и не знает заранее (кэшированным флагом), жив ли FTS5 —
    отсутствие тени `records_fts` обязано превращаться в НАЗВАННЫЙ отказ ИМЕННО у
    вызова с ``text=``, а НЕ ронять обычную ленту (``kind``/``severity``/… без
    ``text``), которая с этой таблицей вообще не имеет дела. Смешение этих двух
    путей означало бы, что поломка поиска на одной сборке sqlite3 делает
    недоступной ВСЮ историю, а не только полнотекстовый поиск по ней."""

    def test_dropping_the_fts_shadow_table_fails_search_but_not_plain_listing(self, tmp_path) -> None:
        db_path, store = _seed(tmp_path, [_log_record("crash при старте камеры", ts=1.0)])
        store.close()

        # Имитация «поиск недоступен в этой сборке sqlite3» — теневая таблица снесена
        # напрямую, в обход API стора (который её сам не удаляет никогда).
        raw = sqlite3.connect(db_path)
        try:
            raw.execute("DROP TABLE IF EXISTS records_fts")
            raw.commit()
        finally:
            raw.close()

        drv = _driver_for(db_path)

        searched = drv.history_query(text="crash")
        assert searched.get("success") is False, f"поиск без индекса обязан быть НАЗВАННЫМ отказом: {searched}"
        assert not searched.get("rows"), "отказ поиска пришёл вместе со строками — конверт противоречив"

        listed = drv.history_query(limit=10)
        assert listed["success"] is True, f"обычная лента упала из-за отсутствия FTS-таблицы: {listed}"
        assert [r["message"] for r in listed["rows"]] == ["crash при старте камеры"]


# ===========================================================================
# Хазард 8 (Н-3 добора ревью 2026-09-04) — отрицательный limit не должен снимать предел.
# ===========================================================================


class TestNegativeLimitDoesNotUnboundTheQuery:
    """Что ломается, если это свойство снять: SQLite читает ``LIMIT -1`` как «без
    предела» — схема объявляла ``limit`` целым числом без нижней границы, то есть
    значение агенту доступно. На сторе у потолка ретенции (200 000 строк) ответ на
    ``history_query(limit=-1)`` разросся бы до сотен мегабайт в памяти driver'а
    вместо страницы. ``effective_limit`` обязан клэмпиться к ``>= 1`` ДО того, как
    число попадёт в SQL, а не только описываться как опасное в docstring/схеме."""

    def test_negative_limit_returns_at_most_one_row(self, tmp_path) -> None:
        db_path, store = _seed(
            tmp_path,
            [_log_record("раз", ts=1.0), _log_record("два", ts=2.0), _log_record("три", ts=3.0)],
        )
        store.close()
        drv = _driver_for(db_path)
        result = drv.history_query(limit=-1)
        assert result["success"] is True
        assert len(result["rows"]) == 1, (
            f"limit=-1 отдал {len(result['rows'])} строк из 3 вместо клэмпа к 1 (SQLite читает "
            f"LIMIT<=0 как «без предела»): {result['rows']}"
        )

    def test_zero_limit_also_returns_at_most_one_row(self, tmp_path) -> None:
        """Тот же класс ``LIMIT<=0`` — не только строго отрицательный вход."""
        db_path, store = _seed(
            tmp_path,
            [_log_record("раз", ts=1.0), _log_record("два", ts=2.0)],
        )
        store.close()
        drv = _driver_for(db_path)
        result = drv.history_query(limit=0)
        assert result["success"] is True
        assert len(result["rows"]) == 1, f"limit=0 отдал {len(result['rows'])} строк вместо клэмпа к 1"


# ===========================================================================
# Хазард 9 (Н-4 добора ревью 2026-09-04) — sqlite3.DatabaseError не пробивает метод
# необработанным исключением; readback с db_path не-строкой — тоже названный отказ.
# ===========================================================================


class TestUnanticipatedDbFailuresAreNamedNotRaised:
    """Что ломается, если это свойство снять: ``sqlite3.DatabaseError`` («file is
    not a database») — РОДИТЕЛЬ ``sqlite3.OperationalError`` в иерархии исключений
    sqlite3 (``Error → DatabaseError → OperationalError``), не потомок. Узкий
    ``except sqlite3.OperationalError`` его не ловит: history_query падает
    необработанным исключением наружу вместо ``{"success": False, "error": ...}`` —
    для инструмента, объявленного read-only и «безопасным» в MCP-реестре, чужое
    исключение снаружи функции — это дефект того же класса, что непойманный отказ
    IPC. Второй сценарий — readback вернул ``db_path`` не строкой (баг на стороне
    процесса/протокола): ``_history_readonly_uri`` тогда падает ``AttributeError``
    (у int/list/dict нет ``.replace``), тоже необработанным."""

    def test_a_non_sqlite_file_is_a_named_refusal_not_an_exception(self, tmp_path) -> None:
        not_a_db = tmp_path / "not_a_database.txt"
        not_a_db.write_text("это обычный текстовый файл, не sqlite", encoding="utf-8")

        drv = _driver_for(str(not_a_db))
        result = drv.history_query()  # не должно бросить исключение наружу теста
        assert result.get("success") is False, f"не-sqlite файл обязан быть НАЗВАННЫМ отказом: {result}"
        assert "not_a_database" in str(result.get("error", "")), f"ошибка не называет путь: {result}"

    def test_a_non_sqlite_file_is_a_named_refusal_on_the_text_search_branch_too(self, tmp_path) -> None:
        """Тот же дефект жил в ДВУХ ветках (ревью Н-4): без ``text=`` и с ``text=`` —
        у поиска свой ``except``, и widening одной ветки не чинит другую."""
        not_a_db = tmp_path / "not_a_database_search.txt"
        not_a_db.write_text("тоже не sqlite", encoding="utf-8")

        drv = _driver_for(str(not_a_db))
        result = drv.history_query(text="crash")
        assert result.get("success") is False, f"не-sqlite файл на ветке поиска обязан быть отказом: {result}"

    @pytest.mark.parametrize("bad_db_path", [123, ["a", "b"], {"x": 1}])
    def test_non_string_db_path_from_readback_is_a_named_refusal(self, bad_db_path) -> None:
        drv = BackendDriver()
        drv.send_command = _FakeSendCommand(  # type: ignore[assignment]
            {"success": True, "process": "ProcessManager", "history": {"enabled": True, "db_path": bad_db_path}}
        )
        result = drv.history_query()
        assert result.get("success") is False, (
            f"нестроковый history.db_path={bad_db_path!r} обязан быть НАЗВАННЫМ отказом, "
            f"а не AttributeError из _history_readonly_uri: {result}"
        )
        assert "db_path" in str(result.get("error", "")).lower()


# ===========================================================================
# Хазард 9 — баг ДРАЙВЕРА не переодевается в отказ о ФАЙЛЕ (Q1 ревью, итерация 2).
# ===========================================================================


class TestOurOwnBugIsNotDisguisedAsAFileProblem:
    """Что ломается, если это свойство снять: `except sqlite3.Error` шире узкого
    `OperationalError` на семь классов, и один из них значим — `ProgrammingError`
    («Incorrect number of bindings supplied») приходит от рассогласования SQL и
    списка параметров, то есть от НАШЕЙ правки, а не от входа и не от файла.

    Под общей шапкой он читался бы как «чтение истории по '<путь>' провалилось»
    и отправил бы чинить файл, которым всё в порядке. Атрибуция причины — часть
    диагностики, а не косметика текста: неверный адрес переживает сам баг.

    Ловится ОБЕ ветки: у ленты и у поиска свои `except`, и вылечить одну, оставив
    другую, здесь уже случалось (ревью Н-4).
    """

    @staticmethod
    def _break_the_bindings(monkeypatch) -> None:
        """Заплата: лишнее условие БЕЗ парного параметра — ровно баг драйвера."""
        original = driver_module._history_where_clauses

        def broken(**kwargs):
            clauses, params = original(**kwargs)
            prefix = kwargs.get("prefix", "")
            clauses.append(f"{prefix}kind = ?")  # параметр НЕ добавлен — рассогласование
            return clauses, params

        monkeypatch.setattr(driver_module, "_history_where_clauses", broken)

    def test_a_binding_mismatch_on_the_listing_branch_is_not_reported_as_a_file_failure(
        self, tmp_path, monkeypatch
    ) -> None:
        db_path, store = _seed(tmp_path, [_log_record("обычная строка")])
        store.close()
        self._break_the_bindings(monkeypatch)

        drv = _driver_for(db_path)
        with pytest.raises(sqlite3.ProgrammingError):
            drv.history_query(kind="log")

    def test_a_binding_mismatch_on_the_search_branch_is_not_reported_as_a_file_failure(
        self, tmp_path, monkeypatch
    ) -> None:
        db_path, store = _seed(tmp_path, [_log_record("crash случился")])
        store.close()
        self._break_the_bindings(monkeypatch)

        drv = _driver_for(db_path)
        with pytest.raises(sqlite3.ProgrammingError):
            drv.history_query(text="crash")

    def test_a_broken_file_is_still_a_named_refusal_on_both_branches(self, tmp_path) -> None:
        """Парная проверка достижимости: сузив except, легко заодно перестать ловить
        и НАСТОЯЩИЕ отказы файла. Контроль — без заплаты оба входа названы, а не подняты."""
        not_a_db = tmp_path / "still_not_a_database.txt"
        not_a_db.write_text("не sqlite", encoding="utf-8")

        drv = _driver_for(str(not_a_db))
        assert drv.history_query().get("success") is False
        assert drv.history_query(text="crash").get("success") is False
