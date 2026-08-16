# -*- coding: utf-8 -*-
"""Ф5 (5.1) — эмитент дампа на НАСТОЯЩЕЙ проводке: плагин → процесс → файл.

Судятся два заявления плагина, и оба — про АРИФМЕТИКУ, а не про факт вызова:

* **один дамп на фронт, а не на кадр брака.** Дефектное изделие видно детектору
  десятки кадров подряд (живой прогон: 95 кадров брака → 1 срабатывание), а дамп
  кладёт на диск сотни строк. Дамп на кадр съел бы ретеншен за одну серию и
  превратил бы улику в шум;
* **порядок: дамп ПОСЛЕ широкой записи** (Р5.1-11). Кольцо снимается в момент
  вызова, поэтому позови плагин дамп раньше — записи забракованной единицы в нём
  бы не было, а приёмка требует именно её. Свойство проверяется по СОДЕРЖИМОМУ
  файла: спай на порядке вызовов сторожил бы порядок строк в исходнике.

Проводка настоящая целиком (реальный ``ProcessModule``, реальный
``LoggerManager`` с memory-каналом, реальный ``PluginContext``, реальные файлы) —
дубль объявляет ``flight_dump`` сам и потому слеп к тому, доезжает ли запись до
кольца.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pytest

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.managers.observability_flight import flight_plane_report
from multiprocess_framework.modules.process_module.managers.observability_wiring import WideEventSelector
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from Plugins.control.robot_control.plugin import RobotControlPlugin

RING = "flight_ring"


def _observability(tmp_path: Path) -> Dict[str, Any]:
    """Секция ровно той формы, какой её кладёт рецепт стенда (Р5.1-7)."""
    return {
        "channels": {RING: {"type": "memory", "capacity": 200}},
        "scopes": {
            "SYSTEM": {"channels": ["system_file", RING]},
            "BUSINESS": {"channels": ["system_file", "messages_file", RING]},
        },
        "flight": {"enabled": True, "sink": RING, "keep": 5},
    }


@pytest.fixture
def stand(tmp_path: Path):
    # Конфиг логгера собирается ТОЙ ЖЕ сборкой, что на boot: машинная база L0 +
    # раскрытая секция. Одна раскрытая секция несёт ЧАСТИЧНЫЙ словарь каналов, и
    # без merge у логгера не было бы ни system_file, ни messages_file — маршруты
    # скоупов упирались бы в несуществующие имена, а харнесс отличался бы от
    # прода ровно там, где судится маршрут кольца.
    from multiprocess_framework.modules.process_module.configs.managers_config import merge_managers
    from multiprocess_framework.modules.process_module.configs.observability_config import expand_observability
    from multiprocess_framework.modules.process_module.managers.observability_reload import base_managers_payload

    section = _observability(tmp_path)
    proc = ProcessModule("inspector", config={"observability_app": section})
    logger_cfg = merge_managers(
        base_managers_payload(str(tmp_path)).get("logger", {}),
        expand_observability(section)["logger"],
    )
    logger_cfg["app_name"] = "flight"
    logger_cfg["log_directory"] = str(tmp_path)
    logger = LoggerManager(manager_name="FlightLog", config=logger_cfg, process=proc)
    logger.initialize()
    proc.logger_manager = logger
    proc.register_manager("logger", logger, enabled=True)
    proc._wire_observability_hub()
    # Отбор открыт: задача судит дамп, а не лесенку Ф4 — при закрытом отборе
    # поток не пишется, и «широкой записи в дампе нет» означало бы совсем другое.
    proc.event_selector = WideEventSelector(first_n=10_000, every_mth=1)

    ctx = PluginContext(services=proc, config={"min_defect_area": 500}, plugin_name="robot_control")
    plugin = RobotControlPlugin()
    plugin.configure(ctx)
    try:
        yield proc, plugin, tmp_path
    finally:
        logger.shutdown()


def _frame() -> np.ndarray:
    return np.zeros((32, 32, 3), dtype=np.uint8)


def _unit(area: int, trace: str) -> dict:
    detections = [{"bbox": [1, 2, 3, 4], "center": [2, 3], "area": area}] if area else []
    return {"frame": _frame(), "detections": detections, "trace_id": trace}


def _dumps(tmp_path: Path) -> List[Path]:
    directory = tmp_path / "inspector" / "flight"
    return sorted(directory.glob("*.jsonl")) if directory.exists() else []


def _records(path: Path) -> List[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class TestOneDumpPerFront:
    """Арифметика Ф8.7, применённая к дампу: серия кадров — одно решение."""

    def test_a_series_of_defective_frames_is_one_dump(self, stand) -> None:
        proc, plugin, tmp_path = stand

        for i in range(12):
            plugin.process([_unit(900, f"tr-{i}")])

        assert len(_dumps(tmp_path)) == 1, "дамп на КАДР съел бы ретеншен за одну серию"
        assert flight_plane_report(proc)["flight"]["dumps"] == 1

    def test_a_good_frame_between_defects_opens_a_new_front(self, stand) -> None:
        """Фронт закрывается годным изделием — и следующий брак это новое решение."""
        _, plugin, tmp_path = stand

        plugin.process([_unit(900, "tr-1")])
        plugin.process([_unit(900, "tr-2")])
        plugin.process([_unit(0, "tr-good")])
        plugin.process([_unit(900, "tr-3")])

        assert len(_dumps(tmp_path)) == 2

    def test_a_clean_line_writes_nothing(self, stand) -> None:
        """Контроль к обоим числам выше: без брака дампов нет вовсе."""
        proc, plugin, tmp_path = stand

        for i in range(5):
            plugin.process([_unit(0, f"tr-{i}")])

        assert _dumps(tmp_path) == []
        assert flight_plane_report(proc)["flight"]["dumps"] == 0


class TestTheOrderIsLoadBearing:
    """Р5.1-11: дамп последним из трёх жестов фронта."""

    def test_the_wide_event_of_the_rejected_unit_is_inside_the_dump(self, stand) -> None:
        """Приёмка «в дампе wide event бракованной единицы» — по содержимому файла.

        Позови плагин дамп раньше ``_write_unit_event`` — запись оказалась бы в
        СЛЕДУЮЩЕМ дампе, то есть на следующем фронте, и пункт был бы зелёным на
        пустом месте (кольцо-то непустое).
        """
        _, plugin, tmp_path = stand

        plugin.process([_unit(900, "tr-reject")])

        records = _records(_dumps(tmp_path)[0])
        assert records[0]["trace_id"] == "tr-reject", "шапка обязана нести след единицы"
        assert records[0]["reject_seq"] == 1, "и ключ сходимости с вердикт-документом"
        wide = [rec for rec in records[1:] if "event inspection" in str(rec.get("message", ""))]
        assert wide, "широкой записи забракованной единицы в дампе НЕТ — порядок нарушен"
        assert "trace=tr-reject" in wide[-1]["message"]
        assert wide[-1]["extra"]["event"] == "inspection"

    def test_the_preceding_units_are_in_the_dump_too(self, stand) -> None:
        """«Что было вокруг» — весь смысл дампа: соседи по кольцу обязаны доехать."""
        _, plugin, tmp_path = stand

        for i in range(3):
            plugin.process([_unit(0, f"tr-ok-{i}")])
        plugin.process([_unit(900, "tr-reject")])

        body = _dumps(tmp_path)[0].read_text(encoding="utf-8")
        for i in range(3):
            assert f"trace=tr-ok-{i}" in body, "предшествующие единицы — то, ради чего дамп и делают"


class TestTheLineSurvivesTheRefusal:
    """Р5.1-14: дамп — улика, а не часть решения."""

    def test_a_disabled_recorder_costs_the_dump_not_the_verdict(self, tmp_path: Path) -> None:
        """Дефолт механизма — выключен, и линия обязана этого не заметить."""
        proc = ProcessModule("inspector", config={})
        proc._wire_observability_hub()
        ctx = PluginContext(services=proc, config={"min_defect_area": 500}, plugin_name="robot_control")
        plugin = RobotControlPlugin()
        plugin.configure(ctx)
        try:
            out = plugin.process([_unit(900, "tr-1")])

            assert out[0]["inspection_result"]["action"] == "reject", "решение вынесено и уехало"
            assert flight_plane_report(proc)["flight"]["refused_disabled"] == 1, "отказ назван, а не проглочен"
            assert _dumps(tmp_path) == []
        finally:
            proc._flush_observability()
