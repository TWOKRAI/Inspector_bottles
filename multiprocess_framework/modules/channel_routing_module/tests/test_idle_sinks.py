# -*- coding: utf-8 -*-
"""Ф2.6 — приёмник объявлен и не принял ничего: это слышно.

План: plans/observability-unified-routing.md, задача 2.6, решение Р-2.6-Е.

Предикат стоит на ПРИЁМНИКЕ, а не на правиле маршрутизации, и это поправка после
сверки с индустрией. Правило, не совпавшее ни с одним источником, — нормальное
состояние: конфиг пишут раньше кода, плагины грузятся по требованию (у нас их 19),
и сигнал «правило никого не поймало» был бы генератором ложных тревог по построению.
Ни logback, ни Spring, ни .NET такого детектора не имеют.

Молчащий приёмник подозрителен всегда, и предикат на нём строго сильнее: ловит и
опечатку в префиксе правила, и опечатку в имени приёмника, и правило, перекрытое
более длинным префиксом, и скоуп, который вообще не срабатывает. Это буквально тот
детектор, который поймал бы 288 нулевых файлов три месяца назад — они были объявлены
и не принимали ничего.

Живёт в общей базе трёх менеджеров: молчащий приёмник ошибок — такой же симптом, как
молчащий файл логов, и заводить это дважды значило бы разойтись.
"""

from __future__ import annotations

import logging
from typing import Any


from multiprocess_framework.modules.logger_module.configs import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.log_config import LogLevel
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


def _manager(tmp_path) -> Any:
    return LoggerManager(
        config=LoggerManagerConfig(
            app_name="idle26",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={
                "используемый": LoggerChannelSchema(type="file", enabled=True, file_path="u.log", rotate=False),
                "молчащий": LoggerChannelSchema(type="file", enabled=True, file_path="i.log", rotate=False),
            },
            scopes={"SYSTEM": LoggerScopeSchema(enabled=True, min_level="INFO", channels=["используемый"])},
        )
    )


class TestPredicate:
    def test_before_anything_is_written_all_sinks_are_idle(self, tmp_path) -> None:
        manager = _manager(tmp_path)
        try:
            assert manager.idle_sinks() == ["используемый", "молчащий"]
        finally:
            manager.shutdown()

    def test_a_sink_that_received_a_record_clears_itself(self, tmp_path) -> None:
        """Самоочищение по построению: отдельного сброса сигнала не нужно.

        Иначе оператор увидел бы «был молчащим» навсегда — и перестал бы верить,
        ровно как в оплаченном уроке «идемпотентность ≠ монотонность».
        """
        manager = _manager(tmp_path)
        try:
            manager.system(LogLevel.INFO, "проба", module="источник")
            manager.flush()

            assert manager.idle_sinks() == ["молчащий"]
        finally:
            manager.shutdown()

    def test_a_sink_removed_by_the_operator_is_not_blamed(self, tmp_path) -> None:
        """Снятый приёмник молчит законно — жаловаться на штатное действие нельзя.

        Пара к предыдущему. Ровно этим 2.8 уже занималась: ложная тревога на
        действие оператора обесценивает сигнал целиком.
        """
        manager = _manager(tmp_path)
        try:
            manager.system(LogLevel.INFO, "проба", module="источник")
            manager.flush()
            manager.set_sink_enabled("молчащий", False)

            assert manager.idle_sinks() == []
        finally:
            manager.shutdown()


class TestItIsAudible:
    def test_shutdown_names_the_silent_sinks(self, tmp_path, caplog) -> None:
        """Якорь — переход жизненного цикла, не таймер.

        Проверка по времени требовала бы угадать порог: сразу после старта не писал
        никто, и любой ранний срок дал бы ложную тревогу на все приёмники разом.
        Завершение — единственный момент, когда «не принял ничего» значит «за весь
        прогон», а не «ещё не успел».
        """
        manager = _manager(tmp_path)
        manager.system(LogLevel.INFO, "проба", module="источник")
        with caplog.at_level(logging.WARNING):
            manager.shutdown()

        assert any("молчащий" in record.getMessage() for record in caplog.records), [
            r.getMessage() for r in caplog.records
        ]

    def test_silence_when_every_sink_delivered(self, tmp_path, caplog) -> None:
        """Пара: детектор, не показанный молчащим, ничего не доказывает."""
        manager = LoggerManager(
            config=LoggerManagerConfig(
                app_name="idle26q",
                log_directory=str(tmp_path),
                enable_batching=False,
                modules={},
                channels={
                    "единственный": LoggerChannelSchema(type="file", enabled=True, file_path="one.log", rotate=False)
                },
                scopes={"SYSTEM": LoggerScopeSchema(enabled=True, min_level="INFO", channels=["единственный"])},
            )
        )
        manager.system(LogLevel.INFO, "проба", module="источник")
        with caplog.at_level(logging.WARNING):
            manager.shutdown()

        assert not any("не приняли ни одной записи" in r.getMessage() for r in caplog.records)

    def test_no_false_alarm_for_a_sink_that_received(self, tmp_path, caplog) -> None:
        """Приёмник, что-то получивший, молчащим не объявляют.

        Ф7.4: раньше тест назывался «жалоба ПОСЛЕ сброса буфера» и держался на
        батчинге — запись лежала в пачке, и ранняя проверка объявила бы
        работающий приёмник молчащим. Батчинга нет, ложной тревоги этого рода
        тоже; свойство, ради которого тест писался, проверяется прямо.
        """
        manager = LoggerManager(
            config=LoggerManagerConfig(
                app_name="idle26f",
                log_directory=str(tmp_path),
                modules={},
                channels={"буферный": LoggerChannelSchema(type="file", enabled=True, file_path="b.log", rotate=False)},
                scopes={"SYSTEM": LoggerScopeSchema(enabled=True, min_level="INFO", channels=["буферный"])},
            )
        )
        manager.system(LogLevel.INFO, "запись", module="источник")
        assert manager.idle_sinks() == [], "приёмник получил запись — молчащим он не является"

        with caplog.at_level(logging.WARNING):
            manager.shutdown()

        assert not any("не приняли ни одной записи" in r.getMessage() for r in caplog.records)


class TestErrorPlaneHasItToo:
    def test_detector_lives_in_the_shared_base(self, tmp_path) -> None:
        """Общая база трёх менеджеров, а не копия у логгера."""
        from multiprocess_framework.modules.error_module.configs.error_manager_config import (
            ErrorManagerConfig,
        )
        from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager

        manager = ErrorManager(
            config=ErrorManagerConfig(app_name="idle26e", log_directory=str(tmp_path), enable_batching=False)
        )
        try:
            assert callable(manager.idle_sinks)
            assert manager.idle_sinks(), "до первой ошибки приёмники ошибок молчат"
        finally:
            manager.shutdown()
