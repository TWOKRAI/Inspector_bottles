# -*- coding: utf-8 -*-
"""Ф8.7 — вердикт как ВТОРОЙ род в той же плоскости.

Пока клиент один, «плоскость документов» неотличима от «аудит пишет в свою таблицу».
Здесь проверяется ровно то, что делает её механизмом:

1. **Срок берётся из СВОЕЙ строки** ``retention_sec``. Аудит и вердикт живут в одной
   таблице, и уборка обязана различать их по роду, а не по времени попадания.
2. **Чистка логов вердикт не трогает.** Это свойство РАСПОЛОЖЕНИЯ, а не везения:
   файл БД лежит вне каталога логов, куда смотрит ``enforce_log_retention``. Пара к
   утверждению — тот же файл, положенный ВНУТРЬ каталога логов, тем же вызовом
   удаляется. Без пары «ротация не тронула» держалось бы и на выключенной ротации.

Файловая БД, не in-memory: ``BaseSyncAdapter`` берёт новое соединение на каждый вызов,
и ``:memory:`` не переживает между ними. Каждый сток закрывается явно — на Windows
неотпущенный файл БД роняет уборку ``tmp_path`` не там, где ошибся тест.
"""

from __future__ import annotations

import time
from pathlib import Path

from multiprocess_framework.modules.logger_module.channels.log_channel import (
    enforce_log_retention,
)
from Services.documents import KIND_AUDIT, KIND_VERDICT, make_document_sink

_DAY = 86400.0
#: Сроки из живого конфига прототипа (``backend/config/system.yaml``): год у аудита,
#: десять лет у вердикта. Числа взяты оттуда, а не выдуманы под тест: совпадение
#: констант с дефолтом проверяет дефолт, а не ручку.
RETENTION = {KIND_AUDIT: 31536000.0, KIND_VERDICT: 315360000.0}


def _sink(tmp_path: Path, name: str = "documents.db"):
    return make_document_sink({"db_path": str(tmp_path / name), "retention_sec": RETENTION})


def _put(sink, kind: str, age_days: float, now: float) -> None:
    sink.append({"kind": kind, "ts": now - age_days * _DAY, "summary": f"{kind} возрастом {age_days} сут"})


class TestRetentionComesFromTheKindsOwnRow:
    def test_expired_audit_leaves_while_the_verdict_of_the_same_age_stays(self, tmp_path: Path) -> None:
        """Одинаковый возраст, разная судьба — значит решает род, а не время."""
        now = time.time()
        sink = _sink(tmp_path)
        try:
            _put(sink, KIND_AUDIT, 400, now)  # старше года
            _put(sink, KIND_VERDICT, 400, now)  # моложе десяти лет

            removed = sink.purge_expired(now)

            assert removed == 1
            assert sink.count(KIND_AUDIT) == 0
            assert sink.count(KIND_VERDICT) == 1
        finally:
            sink.close()

    def test_a_verdict_older_than_its_own_term_does_leave(self, tmp_path: Path) -> None:
        """Пара: вердикт не бессмертен, у него просто СВОЙ срок. Без этого плеча
        предыдущий тест был бы зелен и при «verdict никогда не удалять»."""
        now = time.time()
        sink = _sink(tmp_path)
        try:
            _put(sink, KIND_VERDICT, 4000, now)  # старше десяти лет

            assert sink.purge_expired(now) == 1
            assert sink.count(KIND_VERDICT) == 0
        finally:
            sink.close()


class TestLogRetentionDoesNotReachTheVerdict:
    def test_sweep_of_the_log_directory_leaves_the_document_database_alone(self, tmp_path: Path) -> None:
        """Каталог логов метётся, вердикт остаётся читаемым."""
        logs = tmp_path / "logs"
        logs.mkdir()
        old_log = logs / "messages.log"
        old_log.write_text("старая диагностика", encoding="utf-8")
        aged = time.time() - 30 * _DAY
        import os

        os.utime(old_log, (aged, aged))

        data = tmp_path / "data"
        data.mkdir()
        sink = make_document_sink({"db_path": str(data / "documents.db"), "retention_sec": RETENTION})
        try:
            sink.append({"kind": KIND_VERDICT, "ts": aged, "summary": "отбраковка #1"})
            db_file = data / "documents.db"
            os.utime(db_file, (aged, aged))

            result = enforce_log_retention(logs, retention_days=7, retention_total_mb=1)

            assert result["deleted"] == 1, "детектор жив: старый лог уборка забрала"
            assert not old_log.exists()
            assert db_file.exists()
            assert len(sink.query(kind=KIND_VERDICT)) == 1, "вердикт читается после чистки логов"
        finally:
            sink.close()

    def test_the_same_file_inside_the_log_directory_would_be_deleted(self, tmp_path: Path) -> None:
        """Пара, называющая источник защиты: она в РАСПОЛОЖЕНИИ файла.

        Положи БД в каталог логов — и та же уборка тем же вызовом её удалит. Значит
        ``DEFAULT_DB_PATH`` вне каталога логов — не косметика, а само свойство.
        """
        import os

        logs = tmp_path / "logs"
        logs.mkdir()
        sink = make_document_sink({"db_path": str(logs / "documents.db"), "retention_sec": RETENTION})
        aged = time.time() - 30 * _DAY
        sink.append({"kind": KIND_VERDICT, "ts": aged, "summary": "отбраковка #1"})
        sink.close()  # Windows: под открытым хэндлером файл не удалить

        db_file = logs / "documents.db"
        os.utime(db_file, (aged, aged))

        enforce_log_retention(logs, retention_days=7)

        assert not db_file.exists(), "внутри каталога логов документ прожил бы срок логов"
