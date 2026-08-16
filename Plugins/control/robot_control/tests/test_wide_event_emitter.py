# -*- coding: utf-8 -*-
"""Что эмитент ЗАЯВЛЯЕТ в широкой записи (Ф4, задача 4.1) — тесты автора.

Ревью 4.1: каждое заявление плагина было незасторожено — снятие любого поля
давало ноль красных, включая те, ради которых поля и заводились:

* ``defect_area_max`` / ``min_defect_area`` — весь смысл решения Р4.1-12. У
  площадного детектора вероятностной модели нет, ``confidence`` подделывать
  нечем, и решение выносит ПОРОГ. Уйди порог из записи — вердикт станет нечем
  оспорить, а запись при этом останется выглядящей полной;
* ``reject_seq`` — задокументированный ключ сходимости с вердикт-документом;
* запись у ВЫКЛЮЧЕННОГО плагина — намеренное решение: единица через линию
  прошла, и молчание означало бы «изделий не было».

Проверяется СОДЕРЖИМОЕ записи, а не факт вызова: спай на имени метода сторожил
бы имя, а не свойство.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pytest

from Plugins.control.robot_control.plugin import RobotControlPlugin


class _Ctx:
    """PluginContext в объёме, который использует плагин. Пишет всё, что дали."""

    def __init__(self) -> None:
        self.config: Dict[str, Any] = {}
        self.registers = None
        self.command_manager = None
        self.process_name = "inspector"
        self.plugin_name = "robot_control"
        self.events: List[Dict[str, Any]] = []
        self.documents: List[Dict[str, Any]] = []

    def write_document(self, kind: str, summary: str = "", /, **fields: Any) -> bool:
        self.documents.append({"kind": kind, "summary": summary, **fields})
        return True

    def write_event(
        self,
        kind: str,
        summary: str = "",
        /,
        *,
        unit: Any = None,
        decisive: bool = False,
        **fields: Any,
    ) -> bool:
        self.events.append({"kind": kind, "summary": summary, "decisive": decisive, "unit": unit, **fields})
        return True

    def log_info(self, message: str, **kwargs: Any) -> None: ...

    def log_error(self, message: str, **kwargs: Any) -> None: ...


def _frame() -> np.ndarray:
    return np.zeros((64, 64, 3), dtype=np.uint8)


def _defect(area: int = 900, bbox=(10, 10, 50, 50)) -> dict:
    return {"bbox": list(bbox), "center": [30, 30], "area": area}


def _unit(detections: list, trace: str = "trace-1") -> dict:
    return {"frame": _frame(), "detections": detections, "trace_id": trace}


@pytest.fixture
def plugin() -> tuple:
    ctx = _Ctx()
    p = RobotControlPlugin()
    p.configure(ctx)
    p._reg.min_defect_area = 100
    return p, ctx


class TestTheThresholdIsTheEvidence:
    """``confidence`` подделывать нечем — едет то, чем решение вынесено."""

    def test_the_threshold_that_decided_rides_in_the_record(self, plugin) -> None:
        p, ctx = plugin
        p._reg.min_defect_area = 250

        p.process([_unit([_defect(area=900)])])

        record = ctx.events[-1]
        assert record["min_defect_area"] == 250, "порог — то, чем вердикт оспаривают"
        assert record["defect_area_max"] == 900.0, "и величина, которую с ним сравнили"
        assert "confidence" not in record, "у площадного детектора её нет по построению"

    def test_a_clean_unit_carries_zero_area_not_a_missing_key(self, plugin) -> None:
        """Отсутствие ключа и ноль — разные факты; запись обязана быть однородной."""
        p, ctx = plugin

        p.process([_unit([])])

        assert ctx.events[-1]["defect_area_max"] == 0.0
        assert ctx.events[-1]["min_defect_area"] == 100


class TestTheJoinKeyToTheVerdictDocument:
    """Широкая запись и вердикт-документ обязаны сходиться без догадок."""

    def test_the_front_record_carries_the_join_key(self, plugin) -> None:
        p, ctx = plugin

        p.process([_unit([_defect()], trace="tr-front")])

        record = ctx.events[-1]
        document = ctx.documents[-1]
        assert record["decisive"] is True, "фронт вердикта идёт мимо отбора"
        assert record["reject_seq"] == document["reject_seq"] == 1
        assert record["unit"]["trace_id"] == document["trace_id"] == "tr-front"

    def test_a_stream_unit_has_no_join_key(self, plugin) -> None:
        """На рядовой единице ключа нет: сходиться не с чем, а пустое поле врало бы."""
        p, ctx = plugin

        p.process([_unit([])])

        assert ctx.events[-1]["decisive"] is False
        assert "reject_seq" not in ctx.events[-1]


class TestEveryUnitIsReported:
    def test_a_disabled_plugin_still_reports_the_unit(self, plugin) -> None:
        """Выключенная отбраковка — состояние линии, а не отсутствие изделий.

        Молчание здесь читалось бы как «единиц не было», тогда как их просто
        никто не судил — и счёт изделий разошёлся бы с записями необъяснимо.
        """
        p, ctx = plugin
        p._reg.enabled = False

        p.process([_unit([_defect()])])

        record = ctx.events[-1]
        assert record["action"] == "pass"
        assert record["reason"] == "disabled"
        assert record["decisive"] is False

    def test_one_record_per_unit_even_on_the_front(self, plugin) -> None:
        """ОДНА запись на единицу — две были бы двумя ответами на один вопрос."""
        p, ctx = plugin

        p.process([_unit([]), _unit([_defect()]), _unit([_defect()])])

        assert len(ctx.events) == 3, "по записи на кадр, включая фронтовый"
        assert [e["decisive"] for e in ctx.events] == [False, True, False]
        assert len(ctx.documents) == 1, "документ — только на фронте"


class TestRoiIsBoundedAndSaysSo:
    def test_the_roi_list_is_capped_and_the_rest_is_counted(self, plugin) -> None:
        """Вес записи не имеет права быть функцией шума маски.

        Потолок без счётчика опущенных был бы хуже: «дефектов 200, ROI восемь»
        читалось бы как потеря 192 дефектов, а не как усечение списка.
        """
        p, ctx = plugin
        many = [_defect(bbox=(i, i, i + 5, i + 5)) for i in range(20)]

        p.process([_unit(many)])

        record = ctx.events[-1]
        assert len(record["roi"]) == RobotControlPlugin.ROI_LIMIT
        assert record["roi_omitted"] == 20 - RobotControlPlugin.ROI_LIMIT
        assert record["defect_count"] == 20, "число дефектов при этом полное"
