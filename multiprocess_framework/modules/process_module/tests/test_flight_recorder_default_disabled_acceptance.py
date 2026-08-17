# -*- coding: utf-8 -*-
"""Независимая приёмка Ф6 (`plans/telemetry-stage6.md`) — Предмет 1: дефолт
«flight выключен» у процесса, который улик не заказывал.

Писано независимым тестировщиком от трёх пунктов приёмки D1/D2/D3 (задание
оркестратора, не файл плана — здесь план телеметрии-этапа-6 ещё не описывает
эту находку словами задачи). Критерий: процесс без секции
``observability.flight`` НИГДЕ (ни в app, ни в recipe, ни в session слое)
после старта не пишет НИ ОДНОГО файла дампа и рекордер неактивен.

Измерено ревью ДО этого файла (см. промпт задания): инъекция «секции в
конфиге нет → считаем, что включено» даёт 76 passed и ноль красных у
существующего набора — потому что ни один тест не воспроизводит именно
ПОЛНОЕ отсутствие секции (``test_flight_recorder_acceptance.py`` и
``test_flight_recorder_hazards.py`` заводят рекордер явным
``FlightRecorder(enabled=False)`` — это ДРУГОЕ состояние по букве
Р5.1-5/D1: явный False и «секции нет вообще» обязаны быть НЕОТЛИЧИМЫ
СНАРУЖИ, но у них не должно быть двух РАЗНЫХ путей КОДА, которые СЕГОДНЯ
расходятся, если дефолт когда-то починят в одном месте и забудут в другом).

Публичные символы (`wire_flight_recorder`, `apply_flight_recorder`,
`flight_plane_report`, `FlightRecorder`, `ObservabilityFlightConfig`)
импортируются и вызываются напрямую как чёрный ящик; их поведение
устанавливается ПРОГОНОМ реальных компонентов (`ProcessModule`,
`LoggerManager` с memory-каналом), а не чтением тела функций.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.configs.observability_config import (
    ObservabilityFlightConfig,
)
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.managers.observability_flight import (
    FlightRecorder,
    apply_flight_recorder,
    flight_plane_report,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext

RING = "flight_ring"


def _logger_config(tmp_path: Path, capacity: int = 50) -> Dict[str, Any]:
    """Логгер с ФАЙЛОМ (контроль) и реальным memory-кольцом, смаршрутизированным
    на все скоупы — кольцо ЕСТЬ и МОГЛО БЫ принять дамп, если бы дефолт оказался
    'включено'. Без этого «0 файлов» ничего бы не доказывало: тишина совпадала
    бы что при живом дефолте False, что при мёртвой проводке кольца.
    """
    return {
        "app_name": "flight_default_off",
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


def _boot_without_any_flight_section(tmp_path: Path):
    """Процесс, у которого секции ``observability.flight`` НЕТ ВООБЩЕ ни в одном
    слое: ``config={}`` — ключа ``observability_app`` в конфиге процесса нет
    вовсе, значит app-слой пуст, recipe/session тоже пусты по умолчанию, и
    ``ObservabilityLayers.resolve().get("flight")`` обязано вернуть ``None`` —
    ОТСУТСТВИЕ ключа, а не материализованный дефолт-словарь.
    """
    proc = ProcessModule("inspector", config={})
    logger = LoggerManager(manager_name="DefaultOffProbe", config=_logger_config(tmp_path), process=proc)
    logger.initialize()
    proc.logger_manager = logger
    proc.register_manager("logger", logger, enabled=True)
    proc._wire_observability_hub()
    ctx = PluginContext(services=proc, plugin_name="robot_control")
    return proc, ctx, logger


def _dump_files(tmp_path: Path, process: str = "inspector") -> List[Path]:
    directory = tmp_path / process / "flight"
    return sorted(directory.glob("*.jsonl")) if directory.exists() else []


# ---------------------------------------------------------------------------
# D1 — процесс без секции даёт 0 файлов, отказ НАЗВАН и это именно «выключено»
# ---------------------------------------------------------------------------


class TestD1_NoFlightSectionAnywhereMeansZeroFilesAndInactive:
    def test_process_without_any_flight_section_writes_zero_dump_files(self, tmp_path: Path) -> None:
        proc, ctx, logger = _boot_without_any_flight_section(tmp_path)
        try:
            ctx.log_info("кадр 1")
            ctx.log_info("кадр 2")
            result = ctx.flight_dump("reject", trace_id="t1")
        finally:
            logger.shutdown()

        assert result is False, "секции observability.flight нет ни в одном слое — дамп не может состояться"
        assert _dump_files(tmp_path) == [], (
            "процесс, который улик не заказывал, не имеет права написать НИ ОДНОГО файла дампа"
        )

    def test_the_refusal_is_specifically_disabled_not_a_missing_ring(self, tmp_path: Path) -> None:
        """Кольцо РЕАЛЬНО существует и смаршрутизировано (см. `_logger_config`) —
        если отказ уйдёт под 'no_ring', значит дефолт 'включено' протёк мимо
        флага ``enabled`` куда-то в сторону, и это уже ДРУГОЙ, более тяжёлый
        дефект, который этот тест обязан отличить от D1 по счётчику.
        """
        proc, ctx, logger = _boot_without_any_flight_section(tmp_path)
        try:
            ctx.flight_dump("reject")
            report = flight_plane_report(proc)["flight"]
        finally:
            logger.shutdown()

        assert report["refused_disabled"] == 1
        assert report["refused_no_ring"] == 0


# ---------------------------------------------------------------------------
# D2 — литерал дефолта пришпилен ОТДЕЛЬНОЙ строкой, не выведен из кода под
# проверкой. Обязан упасть, если дефолт когда-либо поменяют на True.
# ---------------------------------------------------------------------------


class TestD2_TheDefaultLiteralIsPinnedNotDerived:
    def test_schema_default_for_enabled_is_hardcoded_false(self) -> None:
        """Якорь: по умолчанию ``enabled`` есть РОВНО ``False`` — если это когда-нибудь
        станет ``True``, тест обязан покраснеть. Значение здесь — литерал ``False``,
        а не импорт какой-либо константы из модуля под проверкой."""
        cfg = ObservabilityFlightConfig()
        assert cfg.enabled is False
        assert cfg.sink == ""
        assert cfg.keep == 5
        assert cfg.limit == 0

    def test_bare_flight_recorder_constructor_default_is_disabled(self) -> None:
        """Вторая копия дефолта (сигнатура ``FlightRecorder.__init__``) — пришпилена
        ОТДЕЛЬНЫМ литералом, не тем же самым, что в предыдущем тесте."""
        assert FlightRecorder().knobs == (False, "", 5, 0)

    def test_process_without_a_flight_section_lands_on_the_same_pinned_literal(self, tmp_path: Path) -> None:
        """Третья копия (поведенческий дефолт `wire_flight_recorder` при отсутствии
        секции) обязана СОВПАСТЬ с тем же литералом — числа сходятся, потому что
        сегодня оба места независимо содержат один и тот же текст ``(False, "", 5, 0)``,
        а НЕ потому что один вычислен из другого (это отдельно проверяет D3)."""
        proc, ctx, logger = _boot_without_any_flight_section(tmp_path)
        try:
            knobs = proc.flight_recorder.knobs
        finally:
            logger.shutdown()
        assert knobs == (False, "", 5, 0)


# ---------------------------------------------------------------------------
# D3 — дефолт обязан жить в ОДНОМ источнике: правка там долетает до ОБЕИХ
# дорог (стартовая сшивка `wire_flight_recorder` + пересборка
# `apply_flight_recorder`). Сегодня копий четыре — тест целится ровно в это.
# ---------------------------------------------------------------------------


class TestD3_TheDefaultLivesInOneSourceNotFourCopies:
    """Единственный разумный кандидат на роль «источника» — сама схема
    ``ObservabilityFlightConfig`` (она и есть объявленный контракт ручки,
    `docs/observability/CONTROL_PANEL.md`). Каждый тест патчит ЕЁ дефолт и
    смотрит, увидела ли РОВНО ОДНА дорога новое значение — раздельно, чтобы
    починка одной дороги и забытая вторая не прошла бы как «готово» (общая
    проверка на обе дороги зеленеет уже при частичной починке).

    Предсказание ДО прогона у обоих: НЕ увидят. `_flight_knobs` в ветке
    ``section is None`` возвращает захардкоженный литерал ``(False, "", 5, 0)``,
    минуя ``ObservabilityFlightConfig.model_validate`` целиком — а эта ветка
    обслуживает И `wire_flight_recorder`, И `apply_flight_recorder`.
    """

    def test_patching_the_schema_default_reaches_the_boot_road(self, tmp_path: Path) -> None:
        """Дорога 1 — стартовая сшивка (`wire_flight_recorder`) процесса без
        секции flight вообще. Самостоятельна: патчит и восстанавливает схему
        сама, не полагаясь на соседний тест дороги пересборки."""
        original_default = ObservabilityFlightConfig.model_fields["enabled"].default
        ObservabilityFlightConfig.model_fields["enabled"].default = True
        ObservabilityFlightConfig.model_rebuild(force=True)
        try:
            # Предпосылка патча: схема САМА видит новое значение — иначе тест
            # ничего не доказывает (не тот класс отказа).
            assert ObservabilityFlightConfig.model_validate({}).enabled is True, (
                "патч дефолта схемы не сработал — тест не может служить доказательством"
            )

            proc, ctx, logger = _boot_without_any_flight_section(tmp_path)
            try:
                boot_enabled = proc.flight_recorder.knobs[0]
            finally:
                logger.shutdown()
        finally:
            ObservabilityFlightConfig.model_fields["enabled"].default = original_default
            ObservabilityFlightConfig.model_rebuild(force=True)

        assert boot_enabled is True, (
            "стартовая сшивка (wire_flight_recorder) обязана увидеть НОВЫЙ дефолт схемы — "
            "не увидела, значит дефолт продублирован отдельным литералом (D3, дорога сшивки)"
        )

    def test_patching_the_schema_default_reaches_the_reload_road(self, tmp_path: Path) -> None:
        """Дорога 2 — пересборка (`apply_flight_recorder`), секция ``flight`` не
        объявлена ни в одном слое (`section=None`). Самостоятельна: не зависит
        от того, прошёл ли тест дороги сшивки — свой собственный патч/восстановление,
        свой собственный свежий ``FlightRecorder``, никакого общего состояния."""
        original_default = ObservabilityFlightConfig.model_fields["enabled"].default
        ObservabilityFlightConfig.model_fields["enabled"].default = True
        ObservabilityFlightConfig.model_rebuild(force=True)
        try:
            assert ObservabilityFlightConfig.model_validate({}).enabled is True, (
                "патч дефолта схемы не сработал — тест не может служить доказательством"
            )

            fresh_recorder = FlightRecorder()
            applied = apply_flight_recorder(fresh_recorder, None)
        finally:
            ObservabilityFlightConfig.model_fields["enabled"].default = original_default
            ObservabilityFlightConfig.model_rebuild(force=True)

        assert applied is not None and applied["enabled"] is True, (
            "пересборка (apply_flight_recorder) обязана увидеть НОВЫЙ дефолт схемы — "
            "не увидела, значит дефолт продублирован отдельным литералом (D3, дорога пересборки)"
        )
