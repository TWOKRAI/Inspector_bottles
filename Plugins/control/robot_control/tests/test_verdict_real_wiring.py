"""Ф8.7 — вердикт на НАСТОЯЩЕЙ проводке: плагин → процесс → файл БД.

Соседний ``test_verdict_documents.py`` проверяет решение плагина на поддельном
контексте — дёшево и подробно. Но фейк объявляет ``write_document`` сам, поэтому
переименуй кто-нибудь метод в ``PluginContext`` или атрибут стока в процессе — и все
те тесты останутся зелёными при мёртвой дороге в проде («фальшивый харнесс доказывает
харнесс», правило проекта).

Здесь настоящее всё: реальный ``ProcessModule``, реальная сшивка
``_wire_observability_hub`` (тот же вход, что у ``initialize``), реальная фабрика
``Services.documents.wiring:make_document_sink``, реальный файл SQLite. Проверка — по
СОДЕРЖИМОМУ БД.

Главное плечо — **одна плоскость на двоих**: вердикт плагина и аудит фреймворка
обязаны оказаться в ОДНОМ экземпляре стока. Заведи приложение свой стор — писателей
на файл стало бы вдвое больше, а «второе правило допуска — механизм, а не частный
случай аудита» осталось бы словами.

Тест дорогой и потому один на плечо.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.configs.observability_layers import (
    process_observability_layers,
)
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from Plugins.control.robot_control.plugin import RobotControlPlugin
from Services.documents import KIND_AUDIT, KIND_VERDICT


def _config(tmp_path: Path) -> Dict[str, Any]:
    """Конфиг процесса ровно той формы, какой его кладёт ассемблер (ключ ``observability_app``)."""
    return {
        "observability_app": {
            "documents": {
                "factory": "Services.documents.wiring:make_document_sink",
                "config": {
                    "db_path": str(tmp_path / "documents.db"),
                    "retention_sec": {KIND_AUDIT: 31536000, KIND_VERDICT: 315360000},
                    "purge_interval_sec": 3600,
                },
            }
        }
    }


@pytest.fixture
def process(tmp_path: Path):
    """Реальный процесс с поднятой плоскостью; закрывается тем же кодом, что в проде."""
    proc = ProcessModule("inspector", config=_config(tmp_path))
    proc._wire_observability_hub()
    try:
        yield proc
    finally:
        proc._flush_observability()


def _inspect(process: ProcessModule, area: int) -> RobotControlPlugin:
    """Собрать плагин на НАСТОЯЩЕМ контексте процесса и прогнать один кадр."""
    ctx = PluginContext(
        services=process,
        config={"min_defect_area": 500},
        plugin_name="robot_control",
    )
    plugin = RobotControlPlugin()
    plugin.configure(ctx)
    plugin.process(
        [
            {
                "frame": np.zeros((32, 32, 3), dtype=np.uint8),
                "detections": [{"bbox": [1, 1, 5, 5], "center": [3, 3], "area": area}],
            }
        ]
    )
    return plugin


class TestVerdictOnRealWiring:
    def test_verdict_reaches_the_database_through_the_real_context(self, process: ProcessModule) -> None:
        plugin = _inspect(process, area=1600)

        rows = process.document_sink.query(kind=KIND_VERDICT)
        assert len(rows) == 1
        assert rows[0]["source"] == "robot_control", "документ обязан называть писателя"
        assert rows[0]["min_defect_area"] == 500
        assert plugin.cmd_get_stats({})["verdicts_written"] == 1

    def test_a_good_part_writes_nothing(self, process: ProcessModule) -> None:
        """Пара: без неё «вердикт доехал» держалось бы и на записи чего попало."""
        _inspect(process, area=100)

        assert process.document_sink.count(KIND_VERDICT) == 0

    def test_verdict_and_audit_share_one_store(self, process: ProcessModule) -> None:
        """ГЛАВНОЕ плечо: два рода, два писателя, один экземпляр стока и один файл."""
        _inspect(process, area=1600)
        process_observability_layers(process).audit.record(
            "set", origin="command:config.reload", key="log_level", value="DEBUG"
        )

        sink = process.document_sink
        assert sink.count(KIND_VERDICT) == 1
        assert sink.count(KIND_AUDIT) == 1

        kinds = {row["kind"] for row in sink.query(limit=10)}
        assert kinds == {KIND_VERDICT, KIND_AUDIT}, "оба рода читаются одним запросом из одной таблицы"

    def test_process_without_the_plane_keeps_deciding(self, tmp_path: Path) -> None:
        """Плоскости нет — линия работает по-прежнему, а потеря названа счётчиком."""
        proc = ProcessModule("inspector_off", config={})
        proc._wire_observability_hub()
        try:
            plugin = _inspect(proc, area=1600)

            assert plugin.cmd_get_stats({})["verdicts_unwritten"] == 1
            assert plugin.cmd_get_stats({})["total_rejected"] == 1
        finally:
            proc._flush_observability()


class TestUnitTiesTogetherOnRealWiring:
    """Ф4 (4.1): документ и широкая запись одной единицы сходятся по ``trace_id``.

    Сосед (``test_verdict_documents.py``) судит это на дубле контекста — и судить
    там может только то, что ПЕРЕДАЛ плагин. Сам ``trace_id`` в запись кладёт
    фасад ``PluginContext.write_event``, читая его из ``unit``, поэтому дубль
    остаётся зелёным и при полностью снятой сборке следа. Здесь настоящие оба
    конца: реальный контекст процесса, реальный сток документов, реальный
    селектор, поднятый сшивкой; подделан только приёмник записей — иначе строку
    негде увидеть.

    Инъекция, ради которой тест поставлен: снять ``trace_id`` из
    ``_write_verdict`` — до него это не краснело НИ В ОДНОМ из 146 тестов задачи.
    """

    class _Collector:
        """Приёмник плоскости логов в объёме, который зовёт ``ObservableMixin``."""

        def __init__(self) -> None:
            self.records: list[dict] = []

        def info(self, message: str, module: str = "main", **extra: Any) -> None:
            self.records.append({"message": message, "module": module, **extra})

        def __getattr__(self, name: str):  # debug/warning/error/critical — молча
            return lambda *a, **kw: None

    def test_the_document_and_the_wide_record_carry_the_same_trace(self, process: ProcessModule) -> None:
        collector = self._Collector()
        process.register_manager("logger", collector)

        ctx = PluginContext(services=process, config={"min_defect_area": 500}, plugin_name="robot_control")
        plugin = RobotControlPlugin()
        plugin.configure(ctx)
        plugin.process(
            [
                {
                    "frame": np.zeros((32, 32, 3), dtype=np.uint8),
                    "detections": [{"bbox": [1, 1, 5, 5], "center": [3, 3], "area": 1600}],
                    "trace_id": "77665544332211aa",
                }
            ]
        )

        rows = process.document_sink.query(kind=KIND_VERDICT)
        assert len(rows) == 1
        assert rows[0]["trace_id"] == "77665544332211aa"

        events = [rec for rec in collector.records if rec.get("event") == "inspection"]
        assert len(events) == 1, "фронт вердикта — ровно одна широкая запись (дефолт 0/0 душит поток)"
        assert events[0]["trace_id"] == rows[0]["trace_id"]
        # След обязан быть и в ТЕКСТЕ: полнотекстовый индекс стора не смотрит в extra.
        assert events[0]["message"].endswith("trace=77665544332211aa")
        assert events[0]["roi"] == [[1, 1, 5, 5]]
