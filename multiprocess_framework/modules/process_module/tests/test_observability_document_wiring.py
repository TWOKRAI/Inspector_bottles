# -*- coding: utf-8 -*-
"""Независимые тесты сшивки стока документов в процесс (Ф8.5, приёмка B+C).

Пишутся ТОЛЬКО по приёмочным критериям задачи — ``wire_document_sink``/
``unwire_document_sink``/``sweep_process_documents`` из
``multiprocess_framework.modules.process_module.managers.observability_wiring`` — БЕЗ
чтения исходника этого модуля и без чтения
``multiprocess_framework/modules/process_module/core/process_module.py``. Модели
поведения взяты из приёмки и из соседних, не запрещённых к чтению файлов пакета
(``configs/observability_layers.py`` — как секция ``observability_app`` доезжает до
``svc.get_config``, ``tests/test_observability_layers.py`` — форма фейкового ``svc``).

Фейковый ``svc`` — плоский словарь конфига (форма оркестратора: ``get_config(key)``
отдаёт значение напрямую, без вложенности ``config.``) плюс запись предупреждений в
список вместо реального логгера.
"""

from __future__ import annotations

import os
import time

import pytest

from multiprocess_framework.modules.process_module.configs.observability_layers import (
    process_observability_layers,
)
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    sweep_process_documents,
    unwire_document_sink,
    wire_document_sink,
)

# Framework -> Services — обратный импорт запрещён (правило слоёв 9,
# .sentrux/rules.toml). Фабрика адресуется СТРОКОЙ "модуль:атрибут" (ровно как её
# принимает observability.documents.factory в проде), а род документа берём литералом
# — это тот же "audit", что Services.documents.interfaces.KIND_AUDIT, без импорта пакета.
FACTORY = "Services.documents.wiring:make_document_sink"
KIND_AUDIT = "audit"


class FlatSvc:
    """Минимальный дублёр процесса: плоский конфиг + запись WARNING в список."""

    def __init__(self, data: dict) -> None:
        self._d = data
        self.warnings: list = []

    def get_config(self, key, default=None):
        node = self._d
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def _log_warning(self, message, *args, **kwargs) -> None:
        self.warnings.append(message)


def _svc_with_documents_section(section: dict) -> FlatSvc:
    """``svc``, у которого секция ``observability.documents`` едет тем же путём, что и
    весь ``observability`` (ключ ``observability_app``, см. ``read_process_config``)."""
    return FlatSvc({"observability_app": {"documents": section}})


class TestWireDeliversAuditToTheDocumentPlane:
    def test_configured_factory_makes_audit_land_in_the_db(self, tmp_path) -> None:
        db_path = tmp_path / "docs.db"
        svc = _svc_with_documents_section({"factory": FACTORY, "config": {"db_path": str(db_path)}})

        store = wire_document_sink(svc)
        try:
            layers = process_observability_layers(svc)
            layers.audit.record("set", origin="command:config.reload", key="log_level", value="DEBUG")

            # Читаем ПОСТОРОННИМ путём (не через объект, вернувшийся из wire) — доказываем
            # факт в самой БД, а не то, что стор помнит про свою последнюю запись.
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            try:
                rows = conn.execute('SELECT "kind", "summary" FROM "documents"').fetchall()
            finally:
                conn.close()
            assert rows == [("audit", "set log_level")]
        finally:
            close = getattr(store, "close", None)
            if callable(close):
                close()


class TestWireIsANoOpWithoutFactory:
    def test_missing_key_raises_nothing_and_wires_nothing(self) -> None:
        svc = FlatSvc({})

        result = wire_document_sink(svc)  # не должно бросать

        assert result is None
        layers = process_observability_layers(svc)
        assert layers.audit.sink is None
        # Запись аудита по-прежнему работает как раньше — просто без плоскости документов.
        entry = layers.audit.record("set", origin="watcher:app", key="log_level")
        assert entry["ok"] is True
        assert "document_failed" not in entry

    def test_empty_factory_string_is_treated_as_absent(self) -> None:
        svc = _svc_with_documents_section({"factory": "", "config": {}})

        result = wire_document_sink(svc)

        assert result is None
        assert process_observability_layers(svc).audit.sink is None


class TestFactoryFailureIsLoudButDoesNotCrashTheProcess:
    def test_broken_import_path_logs_a_warning_naming_the_key(self) -> None:
        svc = _svc_with_documents_section({"factory": "no_such_module.x:make", "config": {}})

        result = wire_document_sink(svc)  # не должно бросать

        assert result is None
        assert process_observability_layers(svc).audit.sink is None
        assert svc.warnings, "молчание тут — дефект: отказ фабрики обязан быть виден"
        assert any("observability.documents" in str(w) for w in svc.warnings)

    def test_factory_object_without_append_also_warns_instead_of_crashing(self) -> None:
        """Фабрика импортировалась, но её результат не удовлетворяет ``IDocumentSink``."""
        svc = _svc_with_documents_section({"factory": "builtins:dict", "config": {}})

        result = wire_document_sink(svc)

        assert result is None
        assert process_observability_layers(svc).audit.sink is None
        assert any("observability.documents" in str(w) for w in svc.warnings)


class TestUnwireDetachesTheSink:
    def test_after_unwire_audit_no_longer_reaches_the_db(self, tmp_path) -> None:
        """После ``unwire`` дальнейший ``append`` не должен долетать до БД.

        Читаем ПОСТОРОННИМ соединением, а не через объект, вернувшийся из ``wire`` —
        ``unwire_document_sink`` освобождает свой сток вместе с адаптером (симметрично
        ``DocumentStore.close``), и повторное обращение к тому же объекту после unwire
        не является частью проверяемого контракта.
        """
        import sqlite3

        db_path = tmp_path / "docs.db"
        svc = _svc_with_documents_section({"factory": FACTORY, "config": {"db_path": str(db_path)}})
        wire_document_sink(svc)
        layers = process_observability_layers(svc)
        layers.audit.record("set", origin="command:config.reload", key="log_level", value="DEBUG")

        unwire_document_sink(svc)

        assert layers.audit.sink is None
        layers.audit.record("set", origin="command:config.reload", key="log_level", value="INFO")

        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute('SELECT "kind", "summary" FROM "documents"').fetchall()
        finally:
            conn.close()
        # Ровно одна строка — та, что уехала ДО unwire; вторая запись до БД не долетела.
        assert rows == [("audit", "set log_level")]


class TestSweepThrottlesByInterval:
    def test_second_call_in_a_row_is_skipped_and_returns_none(self, tmp_path) -> None:
        db_path = tmp_path / "docs.db"
        svc = _svc_with_documents_section(
            {
                "factory": FACTORY,
                "config": {
                    "db_path": str(db_path),
                    "retention_sec": {KIND_AUDIT: 1.0},
                    # Интервал заведомо больше времени выполнения теста — второй
                    # вызов гарантированно попадает внутрь того же окна.
                    "purge_interval_sec": 60.0,
                },
            }
        )
        store = wire_document_sink(svc)
        try:
            store.append({"kind": KIND_AUDIT, "ts": time.time() - 10_000_000.0, "summary": "protuhshiy"})
            assert store.count(kind=KIND_AUDIT) == 1

            first = sweep_process_documents(svc)
            second = sweep_process_documents(svc)

            assert first is not None and first >= 1, "первый вызов обязан реально убрать протухшее"
            assert store.count(kind=KIND_AUDIT) == 0
            assert second is None, "второй вызов подряд обязан быть пропущен, а не повторить уборку"
        finally:
            close = getattr(store, "close", None)
            if callable(close):
                close()


class TestSweepDoesNotLetDbFailuresEscape:
    def test_broken_db_during_sweep_does_not_raise(self, tmp_path) -> None:
        db_path = tmp_path / "docs.db"
        svc = _svc_with_documents_section(
            {
                "factory": FACTORY,
                "config": {
                    "db_path": str(db_path),
                    "retention_sec": {KIND_AUDIT: 1.0},
                    "purge_interval_sec": 0.0,
                },
            }
        )
        store = wire_document_sink(svc)
        store.append({"kind": KIND_AUDIT, "ts": time.time() - 10_000_000.0, "summary": "protuhshiy"})
        close = getattr(store, "close", None)
        if callable(close):
            close()

        # Ломаем БД под уборкой: файл заменяется директорией того же имени — любое
        # sqlite-соединение к этому пути обязано отказать.
        os.remove(db_path)
        os.mkdir(db_path)
        try:
            result = sweep_process_documents(svc)  # не должно бросать
            assert result is None or result == 0
        finally:
            if db_path.is_dir():
                os.rmdir(db_path)


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
