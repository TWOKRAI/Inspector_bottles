# -*- coding: utf-8 -*-
"""Независимая приёмка Ф6 — Предмет 2: повторный отказ «кольца нет» обязан
прозвучать СНОВА после того, как настройки приёмника менялись, и не имеет
права превратиться в поток при серии отказов БЕЗ смены настроек.

Три пункта — D4 (дефект: голос молчит навсегда после первой опечатки, даже
если между двумя опечатками sink чинили), D5 (контроль: счётчик растёт всегда,
до и после починки — молчание не значит слепоту) и D6 (контроль на обратную
крайность: серия ПОДРЯД без смены настроек по-прежнему даёт ОДИН голос, а не
спам). Публичные символы (`apply_flight_recorder`, `flight_plane_report`)
вызываются напрямую; поведение установлено прогоном реального `ProcessModule`
+ `LoggerManager` с memory-каналом.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.managers.observability_flight import (
    apply_flight_recorder,
    flight_plane_report,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext

RING = "ring"

#: Устойчивый кусок текста именно отказа «кольца нет» (see
#: `note_flight_no_ring`) — не совпадает ни с «выключен», ни с «запись отказала».
NO_RING_MARKER = "проверь, что приёмник объявлен"


def _logger_config(tmp_path: Path, capacity: int = 50) -> Dict[str, Any]:
    return {
        "app_name": "flight_revoice",
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


def _boot(tmp_path: Path, flight: Dict[str, Any]):
    proc = ProcessModule("inspector", config={"observability_app": {"flight": flight}})
    logger = LoggerManager(manager_name="RevoiceProbe", config=_logger_config(tmp_path), process=proc)
    logger.initialize()
    proc.logger_manager = logger
    proc.register_manager("logger", logger, enabled=True)
    proc._wire_observability_hub()
    ctx = PluginContext(services=proc, plugin_name="robot_control")
    return proc, ctx, logger


def _said_text(tmp_path: Path, process: str = "inspector") -> str:
    return (tmp_path / process / "a.log").read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# D4 — дефект: голос обязан прозвучать СНОВА после починки и новой опечатки.
# ---------------------------------------------------------------------------


class TestD4_TheNoRingVoiceSpeaksAgainAfterTheSinkWasFixedAndBrokenOnceMore:
    def test_a_second_typo_after_a_working_fix_gets_a_new_voice(self, tmp_path: Path) -> None:
        """Воспроизведение дословно по заданию: опечатка → голос; починили → дамп
        проходит; снова опечатка → счётчик растёт, а НОВЫХ слов сегодня нет —
        это и есть дефект D4."""
        proc, ctx, logger = _boot(tmp_path, {"enabled": True, "sink": "тайпо_раз"})
        try:
            # 1. Опечатка в sink → первый голос про "кольца нет".
            assert ctx.flight_dump("first") is False
            said_after_first = _said_text(tmp_path)
            first_count = said_after_first.count(NO_RING_MARKER)
            assert first_count == 1, "первая опечатка обязана дать РОВНО один голос"

            # 2. Чиним sink на реально существующий и смаршрутизированный — дамп проходит.
            applied = apply_flight_recorder(proc.flight_recorder, {"enabled": True, "sink": RING, "keep": 5})
            assert applied is not None and applied["sink"] == RING
            assert ctx.flight_dump("fixed") is True, "предпосылка: починка обязана реально сработать"

            # 3. Снова опечатка (другая, чтобы не спутать со старым текстом) —
            # это НОВЫЙ повод, а не хвост первого отказа.
            applied2 = apply_flight_recorder(proc.flight_recorder, {"enabled": True, "sink": "тайпо_два", "keep": 5})
            assert applied2 is not None and applied2["sink"] == "тайпо_два"
            assert ctx.flight_dump("second") is False

            said_after_second = _said_text(tmp_path)
            second_count = said_after_second.count(NO_RING_MARKER)
        finally:
            logger.shutdown()

        assert second_count == first_count + 1, (
            "после починки настроек и НОВОЙ опечатки обязан прозвучать ЕЩЁ ОДИН голос — "
            f"было вхождений {first_count}, стало {second_count} "
            "(флаг «уже сказали» не сбрасывается при смене настроек — дефект D4)"
        )


# ---------------------------------------------------------------------------
# D5 — контроль: молчание не значит слепоту, счётчик растёт всегда.
# ---------------------------------------------------------------------------


class TestD5_SilenceDoesNotMeanBlindness:
    def test_the_refusal_counter_grows_both_before_and_after_the_fix(self, tmp_path: Path) -> None:
        proc, ctx, logger = _boot(tmp_path, {"enabled": True, "sink": "тайпо_раз"})
        try:
            ctx.flight_dump("a")
            ctx.flight_dump("b")
            before_fix = flight_plane_report(proc)["flight"]["refused_no_ring"]

            apply_flight_recorder(proc.flight_recorder, {"enabled": True, "sink": RING, "keep": 5})
            ctx.flight_dump("c")  # успешный дамп, счётчик отказов не растёт

            apply_flight_recorder(proc.flight_recorder, {"enabled": True, "sink": "тайпо_два", "keep": 5})
            ctx.flight_dump("d")
            ctx.flight_dump("e")
            after_fix = flight_plane_report(proc)["flight"]["refused_no_ring"]
        finally:
            logger.shutdown()

        assert before_fix == 2, "два отказа ДО починки — счётчик обязан их оба посчитать"
        assert after_fix == 4, (
            "счётчик обязан расти И ДО, И ПОСЛЕ починки — молчание голоса (D4) "
            "не имеет права означать, что механизм перестал считать"
        )


# ---------------------------------------------------------------------------
# D6 — контроль на обратную крайность: серия ПОДРЯД без смены настроек даёт
# ОДИН голос, а не спам. Починка D4 не имеет права сломать именно это.
# ---------------------------------------------------------------------------


class TestD6_ConsecutiveFailuresWithoutASettingsChangeStayOneVoice:
    def test_five_consecutive_typo_dumps_produce_exactly_one_voice(self, tmp_path: Path) -> None:
        proc, ctx, logger = _boot(tmp_path, {"enabled": True, "sink": "тайпо_раз"})
        try:
            for _ in range(5):
                assert ctx.flight_dump("reject") is False
            said = _said_text(tmp_path)
            refused = flight_plane_report(proc)["flight"]["refused_no_ring"]
        finally:
            logger.shutdown()

        assert refused == 5, "счётчик обязан отразить ВСЕ пять отказов подряд"
        assert said.count(NO_RING_MARKER) == 1, (
            "БЕЗ смены настроек серия отказов подряд обязана дать ОДИН голос, а не поток — "
            "это исходный смысл механизма, и починка D4 не имеет права превратить голос в спам"
        )
