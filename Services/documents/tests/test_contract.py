# -*- coding: utf-8 -*-
"""Контрактные тесты плоскости документов — читаются как документация.

Каждая строка Pre/Post из ``interfaces.py`` имеет здесь хотя бы один тест: положительный
или отрицательный. Реализация не подменяется фейком — стенд собран на настоящем
sqlite-адаптере, потому что половина контракта (индексы, DELETE по времени, round-trip
JSON) существует только в БД, а на дубле доказывала бы дубль.
"""

from __future__ import annotations

import pytest

from Services.documents import KIND_AUDIT, KIND_VERDICT, DocumentStore, IDocumentSink, IDocumentStore
from Services.sql.adapters.sqlite import SQLiteSyncAdapter
from Services.sql.configs import SQLManagerConfig


def _adapter(tmp_path, name: str = "docs.db") -> SQLiteSyncAdapter:
    """Адаптер на ФАЙЛОВОЙ sqlite, не in-memory.

    ``BaseSyncAdapter.execute``/``query`` берут НОВОЕ соединение на каждый вызов
    (``with self._engine.connect()``), а у sqlite каждое соединение к ``:memory:`` —
    отдельная база. На in-memory стенд молча терял бы всё между вызовами и проверял
    бы пустоту.
    """
    adapter = SQLiteSyncAdapter(SQLManagerConfig(url=f"sqlite:///{tmp_path / name}", dialect="sqlite"))
    adapter.setup()
    return adapter


@pytest.fixture()
def store(tmp_path) -> DocumentStore:
    """Стор на sqlite, срок хранения: аудит 10с, вердикт не задан."""
    return DocumentStore(_adapter(tmp_path), retention_sec={KIND_AUDIT: 10.0}, clock=lambda: 1000.0)


def _audit(ts: float, summary: str = "session_set log_level=DEBUG") -> dict:
    return {
        "kind": KIND_AUDIT,
        "ts": ts,
        "source": "camera_0",
        "summary": summary,
        "origin": "command:config.reload",
        "ok": True,
    }


def _verdict(ts: float, part: str = "N-1", confidence: float = 0.91) -> dict:
    return {
        "kind": KIND_VERDICT,
        "ts": ts,
        "source": "line_a",
        "summary": f"{part}: брак",
        "part_id": part,
        "confidence": confidence,
    }


class TestSinkContract:
    def test_appended_document_becomes_queryable(self, store: DocumentStore) -> None:
        # given документ аудита
        # when он записан
        assert store.append(_audit(ts=100.0)) is True

        # then он доступен чтением, и payload доехал целиком
        found = store.query(kind=KIND_AUDIT)
        assert len(found) == 1
        assert found[0]["summary"] == "session_set log_level=DEBUG"
        assert found[0]["origin"] == "command:config.reload"
        assert found[0]["ok"] is True

    def test_document_without_kind_is_refused_and_counted(self, store: DocumentStore) -> None:
        # Pre: kind — непустая строка. Нарушение → False, и отказ посчитан.
        assert store.append({"ts": 100.0, "summary": "без рода"}) is False
        assert store.append({"kind": "", "ts": 100.0}) is False
        assert store.dropped == 2
        assert store.count() == 0

    def test_document_without_ts_is_refused(self, store: DocumentStore) -> None:
        assert store.append({"kind": KIND_AUDIT, "summary": "без времени"}) is False
        assert store.count() == 0

    def test_storage_failure_does_not_escape_to_the_writer(self, store: DocumentStore) -> None:
        """Post: исключение наружу не выходит — аудит зовётся из пути смены конфигурации.

        Ломаем соединение под стором: писатель обязан получить False, а не исключение.
        """
        store._adapter.dispose()

        assert store.append(_audit(ts=100.0)) is False
        assert store.dropped == 1

    def test_two_identical_appends_yield_two_documents(self, store: DocumentStore) -> None:
        # Invariant: идемпотентности НЕТ — документ это событие, а не состояние.
        store.append(_audit(ts=100.0))
        store.append(_audit(ts=100.0))

        assert store.count(kind=KIND_AUDIT) == 2


class TestQueryContract:
    def test_result_is_newest_first(self, store: DocumentStore) -> None:
        for ts in (100.0, 300.0, 200.0):
            store.append(_audit(ts=ts, summary=f"at-{int(ts)}"))

        got = [d["ts"] for d in store.query()]

        assert got == [300.0, 200.0, 100.0]

    def test_filters_combine_with_and_not_or(self, store: DocumentStore) -> None:
        # given два рода в пересекающихся периодах
        store.append(_audit(ts=100.0))
        store.append(_verdict(ts=100.0))
        store.append(_verdict(ts=500.0))

        # when спрошены вердикты ДО 200
        got = store.query(kind=KIND_VERDICT, until=200.0)

        # then ровно один: род И период, а не род ИЛИ период
        assert len(got) == 1
        assert got[0]["ts"] == 100.0
        assert got[0]["kind"] == KIND_VERDICT

    def test_since_and_until_are_inclusive_bounds(self, store: DocumentStore) -> None:
        for ts in (100.0, 200.0, 300.0):
            store.append(_audit(ts=ts))

        got = [d["ts"] for d in store.query(since=100.0, until=300.0)]

        assert got == [300.0, 200.0, 100.0]

    def test_limit_bounds_the_page(self, store: DocumentStore) -> None:
        for ts in (100.0, 200.0, 300.0):
            store.append(_audit(ts=ts))

        assert [d["ts"] for d in store.query(limit=2)] == [300.0, 200.0]
        assert [d["ts"] for d in store.query(limit=2, offset=2)] == [100.0]

    def test_non_positive_limit_is_a_precondition_violation(self, store: DocumentStore) -> None:
        with pytest.raises(ValueError):
            store.query(limit=0)
        with pytest.raises(ValueError):
            store.query(offset=-1)


class TestRetentionContract:
    def test_expired_documents_of_a_kind_with_ttl_are_purged(self, store: DocumentStore) -> None:
        # given часы стоят на 1000, срок аудита 10с
        store.append(_audit(ts=985.0))  # возраст 15с — протух
        store.append(_audit(ts=995.0))  # возраст 5с — жив

        removed = store.purge_expired()

        assert removed == 1
        assert [d["ts"] for d in store.query(kind=KIND_AUDIT)] == [995.0]

    def test_kind_without_declared_ttl_is_never_purged(self, store: DocumentStore) -> None:
        """Post: молчание конфига — не разрешение потерять документ о качестве."""
        store.append(_verdict(ts=0.0))  # возраст 1000с, срока для вердиктов нет

        removed = store.purge_expired()

        assert removed == 0
        assert store.count(kind=KIND_VERDICT) == 1

    def test_zero_ttl_is_read_as_unset_not_as_delete_everything(self, tmp_path) -> None:
        """Опечатка в конфиге (ttl=0) не имеет права стереть плоскость."""
        s = DocumentStore(_adapter(tmp_path, "zero.db"), retention_sec={KIND_VERDICT: 0.0}, clock=lambda: 1000.0)
        s.append(_verdict(ts=0.0))

        assert s.purge_expired() == 0
        assert s.count(kind=KIND_VERDICT) == 1

    def test_purge_accepts_an_explicit_moment(self, store: DocumentStore) -> None:
        store.append(_audit(ts=100.0))

        assert store.purge_expired(now=105.0) == 0, "возраст 5с < срока 10с"
        assert store.purge_expired(now=200.0) == 1


class TestProtocolConformance:
    def test_store_satisfies_both_protocols(self, store: DocumentStore) -> None:
        """Фреймворк видит только IDocumentSink — проверяем, что этого достаточно."""
        assert isinstance(store, IDocumentSink)
        assert isinstance(store, IDocumentStore)


class TestPayloadRoundTrip:
    def test_large_payload_is_truncated_with_a_visible_marker(self, store: DocumentStore) -> None:
        """Усечение обязано быть ЗАМЕТНЫМ: молча обрезанный документ врёт полнотой."""
        store.append({**_audit(ts=100.0), "blob": "x" * 20000})

        got = store.query()[0]

        assert got["_truncated"] is True
        assert got["_original_len"] > 8192

    def test_corrupted_payload_does_not_lose_the_whole_page(self, store: DocumentStore) -> None:
        store.append(_audit(ts=100.0))
        store._adapter.execute('UPDATE "documents" SET "payload_json" = :bad', {"bad": "{не json"})

        got = store.query()

        assert len(got) == 1, "страница не должна пропадать из-за одной битой строки"
        assert got[0]["_payload_error"] == "invalid_json"
        assert got[0]["summary"] == "session_set log_level=DEBUG", "колонки читаются мимо payload"
