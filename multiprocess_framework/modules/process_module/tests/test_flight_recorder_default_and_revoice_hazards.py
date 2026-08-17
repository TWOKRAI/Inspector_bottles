# -*- coding: utf-8 -*-
"""Ф6 (S-5/S-6) — опасности МЕХАНИЗМА, видимые только автору.

Приёмка (`test_flight_recorder_default_disabled_acceptance.py`,
`test_flight_recorder_no_ring_revoice_acceptance.py`) судит контракт с трёх
пунктов задания — единый источник дефолта (D1-D3) и повторный голос при
смене настроек (D4-D6). Здесь — то, что видно только изнутри устройства:

* сброс голоса «уже сказали» (С-6) держится на СРАВНЕНИИ текущей четвёрки
  ``knobs`` с меткой, записанной в момент прошлого голоса (см.
  ``_say_once``/``_WARNED_*_KNOBS_ATTR`` в ``observability_flight.py``) — а
  не на явном "сбросе" где-то в ``configure()``/``apply_flight_recorder``.
  Значит сброс обязан сработать на смену ЛЮБОЙ из четырёх ручек, а не только
  ``sink`` (единственная ручка, которую воспроизводит приёмка D4), и обязан
  МОЛЧАТЬ, если пересборка переприменила ТЕ ЖЕ значения;
* три флага (`_flight_warned_disabled/_no_ring/_failed`) читаются и пишутся
  независимо — устаревание метки одного класса не имеет права породить
  голос другого класса;
* единый источник дефолта (S-5) обязан отдавать СХЕМНЫЕ значения остальных
  трёх ручек, если секция задаёт только одну (``sink``) — а не нули;
* мусорная секция (не словарь: строка/число/список) обязана вести себя
  ТАК ЖЕ, как до правки: голос + прежняя (схемная) политика, реестр не падает.

Проводка настоящая (реальный ``LoggerManager`` с memory-каналом, реальный
``ProcessModule``, реальный ``PluginContext``) — ровно тот же фикстурный
приём, что и у `test_flight_recorder_hazards.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.managers.observability_flight import (
    apply_flight_recorder,
    flight_plane_report,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext

RING = "ring"

#: Тот же устойчивый маркер, что у приёмки D4-D6 (см.
#: `test_flight_recorder_no_ring_revoice_acceptance.py`) — текст голоса
#: «кольца нет».
NO_RING_MARKER = "проверь, что приёмник объявлен"
#: Маркер голоса «выключено» (`note_flight_disabled`).
DISABLED_MARKER = "flight recorder выключен"
#: Маркер голоса «секция не словарь» (`_flight_knobs`, ветка мусора).
GARBAGE_SECTION_MARKER = "не словарь"


def _logger_config(tmp_path: Path, capacity: int = 50) -> Dict[str, Any]:
    return {
        "app_name": "flight_hazards",
        "log_directory": str(tmp_path),
        "modules": {},
        "channels": {
            "a": {"type": "file", "enabled": True, "file_path": "a.log"},
            RING: {"type": "memory", "enabled": True, "capacity": capacity},
        },
        "scopes": {
            "SYSTEM": {"channels": ["a", RING]},
            "BUSINESS": {"channels": ["a", RING]},
            "DEBUG": {"channels": ["a", RING]},
        },
    }


def _boot(tmp_path: Path, flight: Optional[Dict[str, Any]]):
    """``flight=None`` — секции ``observability.flight`` нет ни в одном слое вовсе."""
    config: Dict[str, Any] = {"observability_app": {"flight": flight}} if flight is not None else {}
    proc = ProcessModule("inspector", config=config)
    logger = LoggerManager(manager_name="HazardsProbe", config=_logger_config(tmp_path), process=proc)
    logger.initialize()
    proc.logger_manager = logger
    proc.register_manager("logger", logger, enabled=True)
    proc._wire_observability_hub()
    ctx = PluginContext(services=proc, plugin_name="robot_control")
    return proc, ctx, logger


def _said_text(tmp_path: Path, process: str = "inspector") -> str:
    return (tmp_path / process / "a.log").read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# S-6: сброс срабатывает на смену КАЖДОЙ из четырёх ручек, не только sink
# ---------------------------------------------------------------------------


class TestResetFiresOnEachKnobIndividually:
    @pytest.mark.parametrize(
        "second_flight",
        [
            {"enabled": True, "sink": "тайпо", "keep": 9},  # изменена только keep
            {"enabled": True, "sink": "тайпо", "limit": 3},  # изменена только limit
        ],
    )
    def test_reset_fires_even_when_only_keep_or_limit_changes(
        self, tmp_path: Path, second_flight: Dict[str, Any]
    ) -> None:
        """``sink`` в обоих вызовах ОДИН И ТОТ ЖЕ (опечатка не чинится) — значит
        отказ остаётся ТЕМ ЖЕ классом (`no_ring`) на обоих шагах. Если бы сброс
        был завязан на "проверить, поменялся ли именно sink", эта пересборка
        осталась бы немой, и второй голос не прозвучал бы — ровно тот пробел,
        который D4 приёмки не покрывает (она меняет sink, только его).
        """
        proc, ctx, logger = _boot(tmp_path, {"enabled": True, "sink": "тайпо"})
        try:
            assert ctx.flight_dump("first") is False
            first_count = _said_text(tmp_path).count(NO_RING_MARKER)
            assert first_count == 1

            applied = apply_flight_recorder(proc.flight_recorder, second_flight)
            assert applied is not None

            assert ctx.flight_dump("second") is False
            second_count = _said_text(tmp_path).count(NO_RING_MARKER)
        finally:
            logger.shutdown()

        assert second_count == first_count + 1, (
            f"смена ТОЛЬКО {set(second_flight) - {'enabled', 'sink'}} (sink не менялся) "
            f"обязана дать НОВЫЙ голос — было {first_count}, стало {second_count}"
        )


# ---------------------------------------------------------------------------
# S-6: пересборка с ТЕМИ ЖЕ значениями сброса не делает
# ---------------------------------------------------------------------------


class TestReconfigureWithIdenticalValuesDoesNotReset:
    def test_reapplying_the_identical_section_adds_no_voice(self, tmp_path: Path) -> None:
        """Иначе поток слов, против которого флаг заводился (Р5.1-10), вернулся
        бы на КАЖДОЙ пересборке конфига — а она случается часто (``config.reload``
        гоняет ВСЕ секции разом, не только изменившиеся)."""
        flight = {"enabled": True, "sink": "тайпо", "keep": 5, "limit": 0}
        proc, ctx, logger = _boot(tmp_path, flight)
        try:
            assert ctx.flight_dump("a") is False
            before = _said_text(tmp_path).count(NO_RING_MARKER)
            assert before == 1

            # Пересборка теми же значениями — не другой словарь по identity,
            # а РАВНЫЙ по содержимому: ровно так выглядит config.reload без
            # правки этой секции.
            applied = apply_flight_recorder(proc.flight_recorder, dict(flight))
            assert applied == {"enabled": True, "sink": "тайпо", "keep": 5, "limit": 0}

            assert ctx.flight_dump("b") is False
            assert ctx.flight_dump("c") is False
            after = _said_text(tmp_path).count(NO_RING_MARKER)
        finally:
            logger.shutdown()

        assert after == before, (
            f"пересборка БЕЗ реальной смены значений добавила голос ({before} -> {after}) — "
            "спам, который сброс не имеет права порождать"
        )


# ---------------------------------------------------------------------------
# S-6: три флага независимы
# ---------------------------------------------------------------------------


class TestTheThreeFlagsAreIndependent:
    def test_a_no_ring_revoice_does_not_resurrect_the_disabled_voice(self, tmp_path: Path) -> None:
        """Сценарий: сперва "выключено" (голос №1, класс disabled). Потом
        включили, но с плохим sink — новый класс (no_ring), голос №1 своего
        класса. Ни один из двух голосов не имеет права породить ЧУЖОЙ текст,
        и счётчик своего класса не имеет права расти от чужого отказа.
        """
        proc, ctx, logger = _boot(tmp_path, {"enabled": False, "sink": "тайпо"})
        try:
            assert ctx.flight_dump("off") is False
            report_1 = flight_plane_report(proc)["flight"]
            assert (report_1["refused_disabled"], report_1["refused_no_ring"]) == (1, 0)
            said_1 = _said_text(tmp_path)
            assert said_1.count(DISABLED_MARKER) == 1
            assert said_1.count(NO_RING_MARKER) == 0

            applied = apply_flight_recorder(proc.flight_recorder, {"enabled": True, "sink": "другое_тайпо"})
            assert applied is not None and applied["enabled"] is True

            assert ctx.flight_dump("bad-ring") is False
            report_2 = flight_plane_report(proc)["flight"]
            said_2 = _said_text(tmp_path)
        finally:
            logger.shutdown()

        assert (report_2["refused_disabled"], report_2["refused_no_ring"]) == (1, 1), (
            "переход в класс no_ring не имеет права шевельнуть счётчик disabled"
        )
        assert said_2.count(DISABLED_MARKER) == 1, "устаревание метки no_ring не воскрешает голос disabled"
        assert said_2.count(NO_RING_MARKER) == 1, "новый класс отказа обязан заговорить один раз, как и первый"


# ---------------------------------------------------------------------------
# S-5: частичная секция добирает остальные ручки из СХЕМЫ, а не из нуля
# ---------------------------------------------------------------------------


class TestPartialSectionFillsRemainingKnobsFromTheSchema:
    def test_only_sink_given_the_rest_come_from_the_schema_defaults(self, tmp_path: Path) -> None:
        proc, ctx, logger = _boot(tmp_path, {"sink": "custom_ring"})
        try:
            knobs = proc.flight_recorder.knobs
        finally:
            logger.shutdown()

        assert knobs == (False, "custom_ring", 5, 0), (
            "enabled/keep/limit не заданы явно — обязаны добраться из дефолтов схемы "
            "(False/5/0), а не остаться нулями/пустотой"
        )


# ---------------------------------------------------------------------------
# S-5: мусор вместо секции — прежнее поведение (голос + прежняя политика)
# ---------------------------------------------------------------------------


class TestGarbageSectionBehavesAsBefore:
    @pytest.mark.parametrize("garbage", ["просто строка", 42, ["не", "словарь"]])
    def test_a_non_dict_section_logs_and_falls_back_to_the_schema_default(self, tmp_path: Path, garbage: Any) -> None:
        """До S-5 фолбэк на мусорной секции при сшивке был захардкожен как
        ``(False, "", 5, 0)`` — числа теперь читаются схемой, но обязаны
        остаться ТЕМИ ЖЕ, и голос обязан прозвучать так же, как раньше."""
        proc, ctx, logger = _boot(tmp_path, garbage)
        try:
            knobs = proc.flight_recorder.knobs
            said = _said_text(tmp_path)
        finally:
            logger.shutdown()

        assert knobs == (False, "", 5, 0), f"мусорная секция {garbage!r} обязана дать прежнюю политику"
        assert GARBAGE_SECTION_MARKER in said, "мусорная секция обязана быть названа голосом, а не молчанием"
