# -*- coding: utf-8 -*-
"""C3 — «документ без приёмника» получает счётчик и голос, как записи.

Основание — major-10 приёмочного ревью 2026-08-09:

* ``PluginContext.write_document`` при отсутствии плоскости отдавал молчаливый
  ``return False`` — ни счётчика, ни строки. У записей симметричный случай
  назван четвёртым классом потери (``records_without_channels``);
* отказ уже настроенного стока (``append`` вернул ``False``) тоже был молчаливым:
  ``DocumentStore.dropped`` растёт, но **не читает никто**;
* в ``introspect.observability`` секции ``documents`` нет вовсе — при том что
  докстринг той же команды формулирует «без readback'а ручка неотличима от
  сломанной».

Два случая обязаны РАЗЛИЧАТЬСЯ: «плоскости нет» лечится конфигом
(``observability.documents``), «сток отказал» — базой. Счётчик, сливающий их,
отправляет искать поломку не туда.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..managers.observability_wiring import DOCUMENT_SINK_ATTR, document_plane_report
from ..plugins.base import PluginContext


class _Services:
    """Процесс без плоскости документов; логирование — в список."""

    def __init__(self) -> None:
        self.name = "docs_proc"
        self.said: List[str] = []

    def _say(self, message: str, **kw: Any) -> None:
        self.said.append(str(message))

    log_debug = _say
    log_info = _say
    log_warning = _say
    log_error = _say
    log_critical = _say


class _RefusingSink:
    """Сток, который УМЕЕТ отказать — иначе свойство непроверяемо в принципе."""

    def __init__(self) -> None:
        self.dropped = 0
        self.accepted = 0

    def append(self, document: Dict[str, Any]) -> bool:
        self.dropped += 1
        return False


class _WorkingSink:
    def __init__(self) -> None:
        self.dropped = 0
        self.documents: List[Dict[str, Any]] = []

    def append(self, document: Dict[str, Any]) -> bool:
        self.documents.append(document)
        return True


def _ctx(sink: Any = None) -> tuple:
    services = _Services()
    if sink is not None:
        setattr(services, DOCUMENT_SINK_ATTR, sink)
    return PluginContext(services=services, plugin_name="verdict_plugin"), services


class TestNoPlaneAtAll:
    def test_the_loss_is_counted_and_visible_in_the_readback(self) -> None:
        ctx, svc = _ctx()
        assert ctx.write_document("verdict", "деталь бракована") is False
        assert ctx.write_document("verdict", "и ещё одна") is False
        report = document_plane_report(svc)["documents"]
        assert report["declared"] is False
        assert report["without_sink"] == 2, report

    def test_the_first_loss_speaks_with_the_address_then_counts_silently(self) -> None:
        ctx, svc = _ctx()
        for _ in range(4):
            ctx.write_document("verdict", "деталь бракована", source="line_7")
        spoken = [line for line in svc.said if "documents" in line]
        assert len(spoken) == 1, f"голос не однократен: {spoken}"
        assert "verdict" in spoken[0] and "line_7" in spoken[0], f"нет адреса (kind+source): {spoken[0]}"
        assert "observability.documents" in spoken[0], f"нет адреса ключа конфига: {spoken[0]}"
        assert document_plane_report(svc)["documents"]["without_sink"] == 4


class TestSinkRefused:
    def test_refusal_is_told_apart_from_a_missing_plane(self) -> None:
        """и-14 плана: объявленная плоскость со сломанным стоком — ДРУГОЙ случай."""
        sink = _RefusingSink()
        ctx, svc = _ctx(sink)
        assert ctx.write_document("verdict", "деталь бракована") is False
        report = document_plane_report(svc)["documents"]
        assert report["declared"] is True
        assert report["without_sink"] == 0, "отказ стока посчитан как отсутствие плоскости"
        assert report["dropped"] == 1, report

    def test_the_first_refusal_speaks_too(self) -> None:
        sink = _RefusingSink()
        ctx, svc = _ctx(sink)
        for _ in range(3):
            ctx.write_document("audit", "смена уровня", source="operator")
        spoken = [line for line in svc.said if "documents" in line]
        assert len(spoken) == 1, f"голос не однократен: {spoken}"
        assert "audit" in spoken[0] and "operator" in spoken[0], spoken[0]
        assert document_plane_report(svc)["documents"]["dropped"] == 3


class TestHealthyPathStaysQuiet:
    def test_a_working_sink_neither_counts_nor_speaks(self) -> None:
        """Пара к обоим отказам: детектор, срабатывающий всегда, ничего не значит."""
        sink = _WorkingSink()
        ctx, svc = _ctx(sink)
        assert ctx.write_document("verdict", "годная") is True
        report = document_plane_report(svc)["documents"]
        assert report == {"declared": True, "without_sink": 0, "dropped": 0}
        assert [line for line in svc.said if "documents" in line] == []


class TestReadbackShape:
    def test_the_report_is_a_section_named_documents(self) -> None:
        _ctx_unused, svc = _ctx()
        report = document_plane_report(svc)
        assert set(report) == {"documents"}
        assert set(report["documents"]) == {"declared", "without_sink", "dropped"}

    def test_dropped_is_none_when_the_sink_does_not_count(self) -> None:
        """Сток без счётчика — «не измерено», а не «ноль потерь».

        Молчание детектора и его ноль обязаны различаться: чужая реализация
        ``IDocumentSink`` не обязана вести ``dropped``, и выдавать за неё ноль
        значило бы объявить проверенным то, что не проверялось.
        """

        class _Bare:
            def append(self, document: Dict[str, Any]) -> bool:
                return True

        _ctx_unused, svc = _ctx(_Bare())
        assert document_plane_report(svc)["documents"]["dropped"] is None
