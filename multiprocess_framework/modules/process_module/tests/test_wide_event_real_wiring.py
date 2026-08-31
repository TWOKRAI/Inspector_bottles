# -*- coding: utf-8 -*-
"""Ф4 (4.1) — широкая запись на НАСТОЯЩЕЙ проводке процесса.

Соседний ``test_wide_event_hazards.py`` судит механизм на дубле — дёшево и
подробно. Но дубль объявляет ``log_info`` сам, и именно поэтому он слеп к двум
дефектам, которые нашло ревью 4.1 живым прогоном:

* ``ObservableMixin._call_manager`` ЛОВИТ исключение менеджера у себя, считает
  его в ``manager_call_failures`` и наружу не отдаёт. Поля с именами
  ``scope``/``level`` теряли запись молча: ``write_event`` возвращал ``True``,
  ``refused`` оставался нулём, строк на диске не появлялось;
* штамп источника ставит ``functools.partial(log_fn, module=…)``, а keyword на
  call-site партиал перебивает БЕЗ ошибки — прикладное поле ``module`` уводило
  запись под чужое имя, то есть портило ровно ту колонку, по которой ищет FTS.

Ни то, ни другое на дубле не воспроизводится по построению. Поэтому здесь
проводка настоящая на всём пути: реальный ``ProcessModule``, реальный
``LoggerManager``, реальный файл, и проверка — по СТРОКАМ С ДИСКА, а не по
списку вызовов шпиона.

Тесты дорогие и потому по одному на плечо: их задача — доказать, что дешёвый
харнесс подключён к тому же, к чему подключён прод.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    WideEventSelector,
    event_plane_report,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext

#: Имена, у которых есть шанс столкнуться с параметром носителя. Разделены по
#: ДОРОГЕ отказа, а не по важности: первые два падают на границе ``_log_info``,
#: вторые два — внутри ``LoggerCore.log``, то есть под ``try`` миксина.
CARRIER_NAMES = ("message", "msg", "scope", "level")


def _logger_config(tmp_path: Path) -> Dict[str, Any]:
    log_file = tmp_path / "wide.log"
    return {
        "app_name": "wide",
        "log_directory": str(tmp_path),
        "modules": {},
        "channels": {"a": {"type": "file", "enabled": True, "file_path": str(log_file)}},
        "scopes": {
            "SYSTEM": {"channels": ["a"]},
            "BUSINESS": {"channels": ["a"]},
            "DEBUG": {"channels": ["a"]},
        },
    }


@pytest.fixture
def wired(tmp_path: Path):
    """Процесс с живым логгером и открытым отбором (пишем всё, что попросили)."""
    logger = LoggerManager(manager_name="WideLog", config=_logger_config(tmp_path))
    logger.initialize()
    proc = ProcessModule("inspector")
    proc.logger_manager = logger
    proc.register_manager("logger", logger, enabled=True)
    proc.event_selector = WideEventSelector(first_n=1_000_000, every_mth=1)
    ctx = PluginContext(services=proc, plugin_name="robot_control")
    try:
        yield proc, ctx, tmp_path / "wide.log"
    finally:
        logger.shutdown()


def _event_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    return [line for line in text.splitlines() if "event " in line]


class TestTheCarrierOutcomeIsChecked:
    """«Отдали» и «записано» — разные факты, и разница наблюдаема только здесь."""

    @pytest.mark.parametrize("field", CARRIER_NAMES)
    def test_all_four_carrier_names_cost_the_record_and_are_counted(self, wired, field: str) -> None:
        """Любое из четырёх имён: ``False``, счётчик вырос, строки НЕТ.

        Замер до правки (ревью 4.1, строки считаны с диска)::

            поле=message  write_event=False refused+1 строк+0
            поле=msg      write_event=False refused+1 строк+0
            поле=scope    write_event=True  refused+0 строк+0   ← молчащая потеря
            поле=level    write_event=True  refused+0 строк+0

        Инвариант, который держит ``events.refused``: ``selected`` минус
        ``refused`` равно числу строк в плоскости. Для ``scope``/``level`` он был
        неверен — исключение не долетало до фасада вовсе.
        """
        proc, ctx, log_path = wired
        before_lines = len(_event_lines(log_path))
        before = event_plane_report(proc)["events"]

        written = ctx.write_event("inspection", f"ПРОБА-{field}", unit={"trace_id": "t" * 8}, **{field: "ЧУЖОЕ"})

        after = event_plane_report(proc)["events"]
        assert written is False, "запись не доехала — значит и ответ обязан быть отрицательным"
        assert len(_event_lines(log_path)) == before_lines, "строк на диске не прибавилось"
        assert after["refused"] == before["refused"] + 1, "потеря обязана быть посчитана"
        assert after["kinds"]["inspection"]["selected"] == before["kinds"].get("inspection", {}).get("selected", 0) + 1

    def test_the_control_without_a_collision_does_reach_the_disk(self, wired) -> None:
        """Контроль к четырём отрицательным: неподключённый носитель дал бы ноль всегда.

        Без него «строк+0» читалось бы как здоровье и при полностью мёртвой
        проводке — подтверждающий ноль засчитывается только в паре с контролем,
        дающим ненулевое.
        """
        proc, ctx, log_path = wired
        before = len(_event_lines(log_path))

        assert ctx.write_event("inspection", "ЭТАЛОН", unit={"trace_id": "e" * 8}) is True

        lines = _event_lines(log_path)
        assert len(lines) == before + 1
        assert "trace=eeeeeeee" in lines[-1], "след обязан быть в ТЕКСТЕ — FTS не смотрит в extra"
        assert event_plane_report(proc)["events"]["refused"] == 0


class TestTheSourceStampIsPartOfTheEnvelope:
    """Штамп — колонка поиска, а не прикладное поле."""

    def test_a_payload_field_named_module_cannot_move_the_stamp(self, wired) -> None:
        """Воспроизведение ревью 4.1 (строки с диска)::

            #1 [INFO] robot_control: event inspection: ЭТАЛОН trace=aaa
            #2 [INFO] ЧУЖОЕ-ИМЯ:     event inspection: ПОДМЕНА trace=bbb

        при ``write_event(...) is True`` и ``refused=0``: тихая порча, а не отказ.
        Правило конверта защищало ``event``/``trace_id``/``spans`` и не защищало
        имя источника — то самое, по которому строится FTS-поиск.
        """
        proc, ctx, log_path = wired
        before = len(_event_lines(log_path))

        assert ctx.write_event("inspection", "ЭТАЛОН-ШТАМП", unit={"trace_id": "a" * 8}) is True
        assert ctx.write_event("inspection", "ПОДМЕНА", unit={"trace_id": "b" * 8}, module="ЧУЖОЕ-ИМЯ") is True

        reference, suspect = _event_lines(log_path)[before:]
        assert "robot_control" in reference
        assert "robot_control" in suspect, "штамп обязан остаться штампом источника"
        assert "ЧУЖОЕ-ИМЯ" not in suspect.split("event ")[0], "прикладное имя не имеет права стать штампом"

    def test_the_hijack_attempt_is_dropped_by_the_envelope(self, wired) -> None:
        """Прикладное значение ВЫТЕСНЯЕТСЯ конвертом — как ``event``/``trace_id``/``spans``.

        Имя теста и его прежний докстринг обещали другое («поле не теряется, оно
        просто перестаёт быть штампом»), а код всё это время вытеснял значение
        целиком: ``write_event(..., module="line_7")`` кладёт в запись
        ``module="robot_control"``, и ``line_7`` не сохраняется нигде. Старая
        проверка была ОТРИЦАТЕЛЬНОЙ («значения нет в штампе») и потому зелёной
        при обоих поведениях — найдено ревью 4.1 прогоном, а не чтением.

        Здесь утверждается то, что есть: штамп остался своим, чужое значение
        отброшено, соседние прикладные поля целы.
        """
        proc, ctx, log_path = wired
        before = len(_event_lines(log_path))
        written = ctx.write_event("inspection", "С ПОЛЕМ", unit={"trace_id": "c" * 8}, module="line_7", action="pass")

        assert written is True, "столкновение по этому имени не стоит записи — в отличие от scope/level"
        assert len(_event_lines(log_path)) == before + 1
        line = _event_lines(log_path)[-1]
        assert "robot_control" in line.split("event ")[0], "штамп остался именем плагина"
        assert "line_7" not in line, "прикладное значение вытеснено, а не спрятано в extra"


class TestBootWiring:
    """Сшивка на старте — ТОТ ЖЕ вход, что зовёт ``initialize``."""

    def test_boot_wiring_reads_events_from_the_config(self, tmp_path: Path) -> None:
        """Ключ в конфиге процесса → живой селектор с этими ручками.

        Ходим боевым входом ``_wire_observability_hub``. Без него boot-конфиг
        игнорируется молча: ``declared`` отвечает ``false``, ручка перестаёт
        подтверждаться, и ни один тест на дубле этого не видит — дубль селектор
        получает готовым из фикстуры.
        """
        proc = ProcessModule(
            "inspector",
            config={"observability_app": {"events": {"first_n": 4, "every_mth": 9}}},
        )
        try:
            proc._wire_observability_hub()

            report = event_plane_report(proc)["events"]
            assert report["declared"] is True, "сшивка не прошла — селектора у процесса нет"
            assert (report["first_n"], report["every_mth"]) == (4, 9), "boot-конфиг не доехал до живого объекта"
            assert proc.event_selector.knobs == (4, 9)
        finally:
            proc._flush_observability()

    def test_a_process_without_the_key_is_wired_all_the_same(self, tmp_path: Path) -> None:
        """«Ключа нет» — не «механизма нет»: фронты обязано быть где считать."""
        proc = ProcessModule("inspector", config={})
        try:
            proc._wire_observability_hub()

            report = event_plane_report(proc)["events"]
            assert report["declared"] is True
            assert (report["first_n"], report["every_mth"]) == (0, 0)
        finally:
            proc._flush_observability()
