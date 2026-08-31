# -*- coding: utf-8 -*-
"""Задача 1.6 (С-2) — поиск по стору для человека.

Данные в ``observability.db`` были, а ходить по ним нечем: страница по
kind/severity — это лента, а разбор начинается со слова. Внешней инфраструктуры
(Loki/ELK) не заводится: таблица уже здесь, у SQLite есть FTS5.

Три группы свойств, и каждая — про свой класс дефекта:

* **поиск находит и сужается** — иначе это лента с лишней кнопкой;
* **индекс не переживает свои строки** — иначе теневая таблица растёт вечно
  после ретеншена, то есть инцидент 645 МБ, повторённый в тени;
* **«искать нечем» и «не нашлось» различимы** — пустой список на сломанный
  запрос читается как «записей нет», и это худший из трёх исходов.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from ..observability.observability_store import (
    ObservabilitySearchError,
    ObservabilityStore,
)


def _rec(**kw: Any) -> Dict[str, Any]:
    base = {
        "kind": "log",
        "module": "capture",
        "process": "camera_0",
        "ts": 1000.0,
        "severity": "info",
        "message": "запись",
    }
    base.update(kw)
    return base


@pytest.fixture
def store(tmp_path):
    st = ObservabilityStore(str(tmp_path / "obs.db"))
    try:
        yield st
    finally:
        st.close()


@pytest.fixture
def filled(store):
    store.append_records(
        [
            _rec(ts=100.0, message="hikvision камера подключена"),
            _rec(ts=200.0, module="seg", process="seg", severity="warning", message="маска пустая"),
            _rec(ts=300.0, kind="error", severity="error", message="hikvision таймаут кадра"),
        ]
    )
    return store


def _messages(rows: List[Dict[str, Any]]) -> List[str]:
    return [r["message"] for r in rows]


class TestSearchFindsAndNarrows:
    def test_a_word_from_the_message_finds_its_records(self, filled):
        assert sorted(_messages(filled.search("hikvision"))) == [
            "hikvision камера подключена",
            "hikvision таймаут кадра",
        ]

    def test_a_word_no_record_carries_finds_nothing(self, filled):
        """Пара к предыдущему: без неё «находит» доказывалось бы и поиском,
        который возвращает всё подряд."""
        assert filled.search("трактор") == []

    def test_the_source_name_is_searchable_too(self, filled):
        """Разбор начинается либо со слова, либо с имени источника."""
        assert _messages(filled.search("seg")) == ["маска пустая"]

    def test_a_prefix_query_works(self, filled):
        assert len(filled.search("hik*")) == 2

    def test_a_filter_narrows_the_search_the_same_way_it_narrows_the_feed(self, filled):
        """Один набор фильтров на ленту и на поиск.

        Разойдись они — «фильтр по процессу сузил ленту, но не сузил поиск»
        читалось бы как дефект поиска, а не как две копии одного набора.
        """
        assert _messages(filled.search("hikvision", kind="error")) == ["hikvision таймаут кадра"]
        assert filled.search("hikvision", process="seg") == []
        assert _messages(filled.search("hikvision", since=250.0)) == ["hikvision таймаут кадра"]
        assert _messages(filled.search("hikvision", until=150.0)) == ["hikvision камера подключена"]
        assert _messages(filled.search("hikvision", severity_in=["ERROR"])) == ["hikvision таймаут кадра"]

    def test_the_feed_gained_the_same_new_filters(self, filled):
        """Обратная половина того же свойства: process/since/until есть и у ленты."""
        assert _messages(filled.list_records(process="seg")) == ["маска пустая"]
        assert _messages(filled.list_records(since=250.0)) == ["hikvision таймаут кадра"]

    def test_a_found_row_has_the_same_shape_as_a_feed_row(self, filled):
        """Панель показывает найденное тем же виджетом, что и ленту."""
        found = filled.search("hikvision", kind="error")[0]
        listed = filled.list_records(kind="error")[0]
        assert found == listed

    def test_newest_first_by_default(self, filled):
        assert _messages(filled.search("hikvision")) == [
            "hikvision таймаут кадра",
            "hikvision камера подключена",
        ]


class TestOperatorPastesAFragment:
    """То, что человек ВСТАВЛЯЕТ из сообщения, обязано искаться.

    Найдено живым прогоном 2026-08-10, не тестами: голый FTS5 отвергал почти
    любой кусок реального сообщения — ``кадр,`` → «syntax error near ","»,
    ``12:30`` → «no such column: 12», ``camera-0`` → «no such column: 0».
    Отказ был назван, но оператору от него толку ноль: разбор начинается со
    слова, а слово он вставляет, а не изобретает.
    """

    @pytest.fixture
    def pasted(self, store):
        store.append_records(
            [
                _rec(ts=100.0, process="camera-0", message="кадр 12:30 потерян, ROI=1/2"),
                # Процесс у второй записи ДРУГОЙ намеренно: дефолтный
                # ``camera_0`` токенизируется в [camera, 0] ровно как вставленный
                # ``camera-0``, и запрос честно нашёл бы обе — соседняя запись
                # маскировала бы разбор запроса совпадением токенов.
                _rec(ts=200.0, module="seg", process="seg", message="маска пустая"),
            ]
        )
        return store

    @pytest.mark.parametrize(
        "pasted_fragment",
        ["кадр,", "12:30", "ROI=1/2", "camera-0", "потерян.", "кадр 12:30", "  кадр  "],
    )
    def test_a_fragment_pasted_from_a_message_is_found(self, pasted, pasted_fragment):
        assert _messages(pasted.search(pasted_fragment)) == ["кадр 12:30 потерян, ROI=1/2"]

    def test_a_fragment_that_is_not_in_any_record_still_finds_nothing(self, pasted):
        """Пара к предыдущему: разбор запроса не превращает поиск во «всё подряд»."""
        assert pasted.search("вертолёт, 99:99") == []

    def test_deliberate_syntax_is_NOT_quoted_away(self, pasted):
        """Power-синтаксис включается явно и обязан работать по-прежнему.

        Числа взяты там, где кандидаты РАСХОДЯТСЯ: при слепом закавычивании
        ``кадр OR маска`` стало бы поиском трёх слов подряд и дало бы 0, а
        ``мас*`` — поиском буквального «мас*» и дало бы 0.
        """
        assert len(pasted.search("кадр OR маска")) == 2
        assert _messages(pasted.search("мас*")) == ["маска пустая"]
        assert _messages(pasted.search('"маска пустая"')) == ["маска пустая"]
        assert pasted.search('"пустая маска"') == [], "кавычки обязаны остаться ФРАЗОЙ, а не набором слов"

    def test_a_query_without_a_single_word_is_a_named_refusal(self, pasted):
        """``,`` и ``---`` — не «не нашлось», а «искать нечем»: третий случай той же пары."""
        for junk in (",", "---", ". , ;"):
            with pytest.raises(ObservabilitySearchError) as exc:
                pasted.search(junk)
            assert "нет ни одного слова" in str(exc.value)


class TestIndexNeverOutlivesItsRows:
    """Индекс обязан забывать удалённые строки — иначе место занято вечно.

    Ретеншен (Ф5.2) заведён ровно потому, что безлимитная таблица — это инцидент
    645 МБ в SQLite. Индекс, не подчинённый ретеншену, повторил бы его в тени.

    **Судится ПРЯМОЙ MATCH по индексу, а не счётчик строк.** Первая редакция
    сверяла ``COUNT(*) FROM records_fts`` с ``count()`` — и инъекция «delete-триггер
    выключен» дала НОЛЬ красных: у external-content таблицы этот ``COUNT`` читает
    саму ``records``, то есть равен ей по построению. Наружу остаток индекса не
    протекает (соединение с ``records`` его отфильтрует), поэтому и через
    :meth:`search` он невидим — виден только так.
    """

    def test_the_index_knows_the_word_while_the_row_lives(self, filled):
        """Опорная половина пары: до удаления слово в индексе ЕСТЬ.

        Без неё «после удаления не находится» доказывалось бы и индексом,
        который не знает слова никогда.
        """
        assert len(filled.index_rowids("камера")) == 1

    def test_purge_by_rows_drops_the_word_from_the_index(self, filled):
        filled.purge(max_rows=1)

        assert filled.count() == 1
        assert filled.index_rowids("камера") == [], "индекс пережил срезанную ретеншеном строку"
        assert _messages(filled.search("hikvision")) == ["hikvision таймаут кадра"]

    def test_purge_by_age_drops_the_word_from_the_index(self, filled):
        filled.purge(max_age_sec=50.0, now=250.0)

        assert filled.index_rowids("камера") == [], "срезанная по возрасту строка осталась в индексе"
        assert filled.search("камера") == []

    def test_clear_empties_the_index(self, filled):
        filled.clear()

        assert filled.count() == 0
        assert filled.index_rowids("hikvision") == [], "clear оставил индекс населённым"

    def test_no_update_ever_touches_an_indexed_column(self):
        """UPDATE-триггера нет — значит правка ИНДЕКСИРУЕМОЙ колонки разошлась бы молча.

        Первая редакция этого стража требовала, чтобы стор вообще не знал
        ``UPDATE``, и **упала на первом же прогоне**: правка есть — миграция
        ``severity_number`` для унаследованных строк. Права оказалась инъекция,
        а не посылка: свойство, на котором держатся два триггера вместо трёх, —
        не «строки не правятся», а «правки не касаются ``message``/``module``/
        ``process``». Его и сторожим; расширять индекс новой колонкой — законно,
        но тогда придётся либо не править её, либо завести третий триггер.
        """
        import inspect
        import re

        from ..observability import observability_store as module

        source = inspect.getsource(module)
        indexed = ("message", "module", "process")
        offenders: list[str] = []
        for block in re.findall(r"UPDATE\s+records\s+SET\s+(.*?)(?:\bWHERE\b|\"\"\")", source, re.IGNORECASE | re.S):
            for column in indexed:
                if re.search(rf"\b{column}\s*=", block, re.IGNORECASE):
                    offenders.append(f"{column} в UPDATE: {block.strip()[:60]}…")

        assert not offenders, (
            f"UPDATE правит индексируемую колонку ({offenders}) — индекс FTS5 об этом не узнает: "
            "нужен третий триггер (AFTER UPDATE) либо отказ от external content"
        )

    def test_the_guard_above_can_actually_fire(self):
        """Молчащий детектор ничего не доказывает — показываем его красным.

        Тот же разбор, что и в стороже, но на заведомо нарушающем тексте: без
        этого «нарушителей нет» могло бы значить «разбор ничего не находит».
        """
        import re

        offending = 'self._conn.execute("""\n UPDATE records SET message = \'x\'\n WHERE id = 1\n""")'
        blocks = re.findall(r"UPDATE\s+records\s+SET\s+(.*?)(?:\bWHERE\b|\"\"\")", offending, re.IGNORECASE | re.S)

        assert blocks, "разбор не нашёл UPDATE даже в нарушающем тексте"
        assert any(re.search(r"\bmessage\s*=", b, re.IGNORECASE) for b in blocks)


class TestUnsearchableIsNotEmpty:
    """«Искать нечем» и «не нашлось» — разные ответы. Худший исход — их спутать."""

    def test_a_broken_query_is_a_named_refusal_not_an_empty_page(self, filled):
        with pytest.raises(ObservabilitySearchError) as exc:
            filled.search('"незакрытая кавычка')

        assert "не понят" in str(exc.value)

    def test_an_empty_query_is_refused_too(self, filled):
        with pytest.raises(ObservabilitySearchError):
            filled.search("   ")

    def test_the_store_says_whether_search_is_possible_before_the_first_query(self, filled):
        """Панель решает, показывать ли строку поиска, ДО запроса."""
        assert filled.search_available is True
        assert filled.search_unavailable_reason is None

    def test_without_fts_the_reason_is_named_and_the_feed_still_works(self, filled):
        """Сборка SQLite без FTS5 — законное состояние, а не отказ стора.

        Состояние воспроизводится тем же полем, которым его помечает
        :meth:`_init_fts`; проверяется, что отказ ИМЕНОВАН и что чтение истории
        от этого не страдает.
        """
        filled._fts_reason = "полнотекстовый индекс недоступен в этой сборке SQLite: no such module: fts5"

        assert filled.search_available is False
        with pytest.raises(ObservabilitySearchError) as exc:
            filled.search("hikvision")
        assert "недоступен" in str(exc.value)
        assert len(filled.list_records()) == 3, "лента перестала читаться из-за отсутствия поиска"


class TestLegacyFileGetsItsIndex:
    """Унаследованный файл: триггеры ловят только новые строки, старые — backfill."""

    def test_rows_written_before_the_index_become_searchable_after_reopen(self, tmp_path):
        from ..observability import observability_store as module

        path = str(tmp_path / "legacy.db")
        st = ObservabilityStore(path)
        # Снести индекс и откатить версию схемы — файл «до 1.6», но со строками.
        st._conn.execute("DROP TRIGGER IF EXISTS records_fts_ai")
        st._conn.execute("DROP TRIGGER IF EXISTS records_fts_ad")
        st._conn.execute(f"DROP TABLE IF EXISTS {module._FTS_TABLE}")
        st._conn.execute("PRAGMA user_version = 1")
        st._conn.commit()
        st.append_records([_rec(message="унаследованная запись про hikvision")])
        st.close()

        reopened = ObservabilityStore(path)
        try:
            assert reopened.index_rowids("унаследованная"), "backfill не построил индекс по старым строкам"
            assert len(reopened.search("унаследованная")) == 1
        finally:
            reopened.close()

    def test_backfill_does_not_repeat_on_every_open(self, tmp_path):
        """Гейт `user_version`: перестроение — однократно за жизнь файла.

        Проверяется не таймером (он на Windows грубее самой операции), а тем,
        что версия схемы поднята: именно она и есть однократность.
        """
        from ..observability import observability_store as module

        path = str(tmp_path / "fresh.db")
        st = ObservabilityStore(path)
        version = int(st._conn.execute("PRAGMA user_version").fetchone()[0])
        st.close()

        assert version >= module._FTS_SCHEMA_VERSION

    def test_the_auto_vacuum_migration_still_runs_on_a_legacy_file(self, tmp_path):
        """Порядок миграций: индекс НЕ имеет права проскочить вперёд auto_vacuum.

        Обе гейтятся ОДНИМ ``user_version``. Поставь 1.6 свою версию 2 раньше — и
        миграция D3 увидела бы ``2 >= 1`` и пропустила себя молча на файле, который
        как раз и надо было пересобрать.

        **Файл строится дореформенным порядком PRAGMA** (``journal_mode=WAL``
        раньше ``auto_vacuum``), из-за которого SQLite молча игнорирует режим и
        оставляет ``auto_vacuum = 0``. Первая редакция теста бралa свежий файл и
        лишь сбрасывала ``user_version``: режим там уже был 2, поэтому проверка
        «стало 2» проходила и при переставленных миграциях — инъекция M-5 дала
        **ноль красных**, и права была она, а не тест. Барьер должен
        воспроизводить состояние, а не его номер.
        """
        import sqlite3

        path = str(tmp_path / "legacy_vacuum.db")
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")  # ПЕРВЫМ — и auto_vacuum ниже не применится
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        conn.execute(
            "CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, "
            "process TEXT, module TEXT NOT NULL, ts REAL NOT NULL, severity TEXT, "
            "severity_number INTEGER, message TEXT, extra TEXT)"
        )
        conn.commit()
        mode_before = int(conn.execute("PRAGMA auto_vacuum").fetchone()[0])
        conn.close()
        assert mode_before == 0, "не удалось построить дореформенный файл — тест не воспроизводит состояние"

        reopened = ObservabilityStore(path)
        try:
            mode_after = int(reopened._conn.execute("PRAGMA auto_vacuum").fetchone()[0])
            version = int(reopened._conn.execute("PRAGMA user_version").fetchone()[0])
        finally:
            reopened.close()

        assert mode_after == 2, f"auto_vacuum потерян: было {mode_before}, стало {mode_after}"
        assert version == 2, "версия схемы не доросла до индекса — backfill повторится на каждом открытии"
