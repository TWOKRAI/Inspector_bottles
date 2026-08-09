# -*- coding: utf-8 -*-
"""Ф8.5c — плоскость документов на НАСТОЯЩЕЙ проводке процесса.

Соседние файлы проверяют механизм на фейковом ``svc`` — дёшево и подробно. Но фейк
объявляет ``get_config``/``name``/``_log_warning`` сам, поэтому переименуй кто-нибудь
атрибут в ``ProcessModule`` — и все они останутся зелёными при мёртвой плоскости в проде
(«фальшивый харнесс доказывает харнесс», правило проекта).

Здесь проводка настоящая на всём пути: реальный ``ProcessModule``, реальный вызов
``_wire_observability_hub`` (тот же, что зовёт ``initialize``), реальная фабрика
``Services.documents.wiring:make_document_sink``, реальный файл SQLite. Проверка — по
СОДЕРЖИМОМУ БД, а не по списку вызовов шпиона.

Тест дорогой и потому один на плечо. Его задача — доказать, что дешёвый харнесс
подключён к тому же, к чему подключён прод.

Отдельно закреплено плечо «процесс БЕЗ hub'а»: hub есть только у пилота (worker_module),
а аудит — у каждого процесса. Сшей мы документы внутри условия ``hub is not None`` —
«когда включили DEBUG» отвечалось бы на одном процессе из восьми, и ни один фейковый
тест этого бы не увидел.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from multiprocess_framework.modules.process_module.configs.observability_layers import (
    process_observability_layers,
)
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule


def _config(tmp_path: Path, factory: str = "Services.documents.wiring:make_document_sink") -> Dict[str, Any]:
    """Конфиг процесса ровно той формы, какой его кладёт ассемблер (ключ ``observability_app``)."""
    return {
        "observability_app": {
            "documents": {
                "factory": factory,
                "config": {
                    "db_path": str(tmp_path / "documents.db"),
                    "retention_sec": {"audit": 31536000},
                    "purge_interval_sec": 3600,
                },
            }
        }
    }


@pytest.fixture
def process(tmp_path: Path):
    """Реальный ProcessModule с ключом плоскости. Сток закрывается тем же кодом, что в проде."""
    proc = ProcessModule("documents_probe", config=_config(tmp_path))
    try:
        yield proc
    finally:
        proc._flush_observability()


class TestRealWiring:
    def test_audit_record_reaches_the_database(self, process: ProcessModule) -> None:
        """Главное плечо приёмки: ключ в конфиге → запись аудита лежит в БД.

        Ходим тем же входом, каким ходит прод: ``_wire_observability_hub`` зовётся из
        ``initialize``, аудит берётся у стека слоёв процесса. Ни одного подставного
        объекта на пути.
        """
        process._wire_observability_hub()

        assert process._observability_hub is None, (
            "у процесса без воркеров hub'а нет — и это то самое плечо, ради которого "
            "сшивка документов вынесена из-под условия"
        )
        sink = process.document_sink
        assert sink is not None, "плоскость обязана подняться и без hub'а"

        process_observability_layers(process).audit.record(
            "set", origin="command:config.reload", key="log_level", value="DEBUG"
        )

        rows = sink.query(kind="audit")
        assert len(rows) == 1
        assert rows[0]["key"] == "log_level"
        assert rows[0]["value"] == "DEBUG"
        assert rows[0]["source"] == "documents_probe", "документ обязан называть процесс-источник"

    def test_no_key_keeps_the_previous_behaviour(self, tmp_path: Path) -> None:
        """Пара к предыдущему: без ключа поведение прежнее и молчаливое."""
        proc = ProcessModule("documents_probe_off", config={})

        proc._wire_observability_hub()

        assert getattr(proc, "document_sink", None) is None
        entry = process_observability_layers(proc).audit.record("set", origin="switch", key="log_level")
        assert "document_failed" not in entry, "плоскости нет — и жаловаться не на что"
        proc._flush_observability()

    def test_teardown_closes_the_store_and_detaches_it(self, process: ProcessModule) -> None:
        """``stop()`` зовёт ``_flush_observability``; после него плоскость отцеплена.

        Проверяется на настоящем процессе, потому что порядок вызовов внутри
        ``_flush_observability`` — это и есть то, что фейк воспроизвести не может.
        """
        process._wire_observability_hub()
        audit = process_observability_layers(process).audit
        assert audit.sink is not None

        process._flush_observability()

        assert audit.sink is None
        assert process.document_sink is None
