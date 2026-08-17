# -*- coding: utf-8 -*-
"""Приёмочные тесты: шапка flight-дампа не открывает секреты (продолжение Р5.1-12).

`FlightRecorder._write` (`managers/observability_flight.py`) кормит ``SecretRedactor``
ТЕЛО кольца (оно уже прошло цепочку процессоров логгера до попадания в кольцо), но
шапку (``envelope`` — первая строка файла, род ``flight_manifest``) собирает из
``reason`` и прикладных ``**fields`` НАПРЯМУЮ, без прогона через редактор — эти две
строки приходят от вызывающего в момент ``ctx.flight_dump(reason, **fields)`` и
редактору не показывались никогда. Заявленное свойство модуля («секреты дамп не
открывает») критериями C1-C7 задачи распространено и на шапку.

Часть тестов ниже КРАСНАЯ на HEAD: это и есть дефект, а не ошибка теста — критерий
утверждается дословно, а не подгоняется под текущее поведение (см. текст задания
тестировщику, раздел «жёсткие запреты», п.4). Контрольные тесты (C4, C6, C7)
проверяют, что существующее поведение НЕ ломается будущим фиксом.

Секреты в тестах ниже — литералы, специально сконструированные для теста, не
настоящие учётные данные.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any, Dict, List

from multiprocess_framework.modules.logger_module.core import redaction
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.core.redaction import MASK
from multiprocess_framework.modules.process_module.managers.observability_flight import (
    FlightRecorder,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext

# ---------------------------------------------------------------------------
# Общий харнесс (независимая копия — своя, не импортируется из соседних тестов
# 5.1, чтобы этот файл не зависел от их внутреннего устройства).
# ---------------------------------------------------------------------------


class _Services:
    """Минимальный процесс: то, что читает `PluginContext.flight_dump` и
    `process_say` (`log_warning`/`log_info` и т. д. — голос отказов)."""

    def __init__(self, name: str = "inspector", flight_recorder: Any = None, logger_manager: Any = None) -> None:
        self.name = name
        self.logs: List[Dict[str, Any]] = []
        self.logger_manager = logger_manager
        self.flight_recorder = flight_recorder

    def _record(self, level: str, message: str, **kwargs: Any) -> None:
        self.logs.append({"level": level, "message": message, **kwargs})

    def log_debug(self, message: str, **kwargs: Any) -> None:
        self._record("DEBUG", message, **kwargs)

    def log_info(self, message: str, **kwargs: Any) -> None:
        self._record("INFO", message, **kwargs)

    def log_warning(self, message: str, **kwargs: Any) -> None:
        self._record("WARNING", message, **kwargs)

    def log_error(self, message: str, **kwargs: Any) -> None:
        self._record("ERROR", message, **kwargs)

    def log_critical(self, message: str, **kwargs: Any) -> None:
        self._record("CRITICAL", message, **kwargs)


def _ctx(services: _Services) -> PluginContext:
    return PluginContext(services=services, plugin_name="robot_control")


def _real_logger(tmp_path: Path, *, capacity: int = 50, channel: str = "flight_ring") -> LoggerManager:
    """Настоящий `LoggerManager` с memory-каналом — та же дорога, которой кормится
    кольцо `FlightRecorder` (никаких фейков вместо `read_sink_tail`/`SecretRedactor`:
    оба реальных компонента и оба разрешены к использованию по заданию тестировщика)."""
    config: Dict[str, Any] = {
        "app_name": "flight_manifest_redaction",
        "log_directory": str(tmp_path),
        "enable_batching": False,
        "modules": {},
        "channels": {channel: {"capacity": capacity, "enabled": True, "type": "memory"}},
        "scopes": {
            "SYSTEM": {"channels": [channel]},
            "BUSINESS": {"channels": [channel]},
            "DEBUG": {"channels": [channel]},
        },
    }
    mgr = LoggerManager(manager_name="FlightManifestRedactionProbe", config=config)
    mgr.initialize()
    return mgr


def _flight_files(base: Path, process: str = "inspector") -> List[str]:
    return sorted(glob.glob(str(base / process / "flight" / "*.jsonl")))


def _dump_header(path: str) -> Dict[str, Any]:
    first_line = Path(path).read_text(encoding="utf-8").splitlines()[0]
    return json.loads(first_line)


def _recorder() -> FlightRecorder:
    return FlightRecorder(enabled=True, sink="flight_ring", keep=5)


# ---------------------------------------------------------------------------
# C1 — секрет в ПРИЧИНЕ не имеет права оказаться в ИМЕНИ файла.
# ---------------------------------------------------------------------------


class TestC1SecretInReasonAbsentFromFileName:
    def test_secret_in_reason_is_absent_from_the_dump_file_name(self, tmp_path: Path) -> None:
        raw_secret = "SECRET_IN_REASON_9f8e7d6c"
        logger = _real_logger(tmp_path)
        try:
            services = _Services(flight_recorder=_recorder(), logger_manager=logger)
            logger.info("кадр", module="observability")

            assert _ctx(services).flight_dump(f"token={raw_secret}") is True

            files = _flight_files(tmp_path)
            assert len(files) == 1
            filename = Path(files[0]).name
            assert raw_secret not in filename, (
                f"секрет из reason НЕ имеет права попасть в ИМЯ файла (видно в листинге "
                f"каталога, не открывая файл), получено {filename!r}"
            )
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# C2 — секрета нет в ШАПКЕ: ни из причины, ни из прикладных полей.
# ---------------------------------------------------------------------------


class TestC2SecretsAbsentFromTheManifestHeader:
    def test_neither_reason_secret_nor_field_secret_reach_the_header(self, tmp_path: Path) -> None:
        raw_reason_secret = "SECRET_R_1a2b3c"
        raw_field_secret = "SECRET_F_4d5e6f"
        logger = _real_logger(tmp_path)
        try:
            services = _Services(flight_recorder=_recorder(), logger_manager=logger)
            logger.info("кадр", module="observability")

            ok = _ctx(services).flight_dump(f"token={raw_reason_secret}", token=raw_field_secret)
            assert ok is True

            files = _flight_files(tmp_path)
            header_line = Path(files[0]).read_text(encoding="utf-8").splitlines()[0]
            assert raw_reason_secret not in header_line, (
                "секрет из ПРИЧИНЫ (форма 'ключ=значение') не имеет права оказаться в шапке"
            )
            assert raw_field_secret not in header_line, (
                "секрет из прикладного ПОЛЯ (точное имя ключа) не имеет права оказаться в шапке"
            )
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# C3 — значение замаскировано, а не выброшено: ключ в шапке остаётся.
# ---------------------------------------------------------------------------


class TestC3MaskedValueNotDroppedKey:
    def test_secret_field_key_survives_masked_in_the_header(self, tmp_path: Path) -> None:
        logger = _real_logger(tmp_path)
        try:
            services = _Services(flight_recorder=_recorder(), logger_manager=logger)
            logger.info("кадр", module="observability")

            assert _ctx(services).flight_dump("reject", token="SECRET_VALUE_ABC") is True

            header = _dump_header(_flight_files(tmp_path)[0])
            assert "token" in header, "ключ поля обязан ОСТАТЬСЯ в шапке — факт наличия поля тоже улика"
            assert header["token"] == MASK, (
                f"значение обязано быть маской {MASK!r} (SecretRedactor), получено {header.get('token')!r}"
            )
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# C4 (контроль) — тело записей кольца остаётся отредактированным.
# ---------------------------------------------------------------------------


class TestC4RingBodyStaysRedactedControl:
    def test_body_records_remain_redacted(self, tmp_path: Path) -> None:
        raw_secret = "RAW_BODY_SECRET_123"
        logger = _real_logger(tmp_path)
        try:
            services = _Services(flight_recorder=_recorder(), logger_manager=logger)
            logger.info("подключение к сервису", module="observability", password=raw_secret)

            assert _ctx(services).flight_dump("reject") is True

            body_text = "\n".join(Path(_flight_files(tmp_path)[0]).read_text(encoding="utf-8").splitlines()[1:])
            assert raw_secret not in body_text, (
                "контроль: тело кольца обязано остаться отредактированным существующим "
                "SecretRedactor, независимо от правки шапки"
            )
            assert MASK in body_text
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# C5 — одна реализация правил редакции, а не вторая копия набора имён.
# ---------------------------------------------------------------------------


class TestC5SingleRulesSourceNotADuplicateCopy:
    def test_a_name_added_to_the_shared_redaction_set_is_masked_in_the_header_too(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        custom_field = "acceptance_custom_secret_field"
        raw_value = "DYNAMIC_SECRET_VALUE_777"
        assert custom_field not in redaction.SECRET_FIELD_NAMES, (
            "имя обязано отсутствовать в дефолтном наборе — иначе тест ничего не доказывает"
        )
        monkeypatch.setattr(redaction, "SECRET_FIELD_NAMES", redaction.SECRET_FIELD_NAMES | {custom_field})

        logger = _real_logger(tmp_path)
        try:
            services = _Services(flight_recorder=_recorder(), logger_manager=logger)
            logger.info("кадр", module="observability")

            assert _ctx(services).flight_dump("reject", **{custom_field: raw_value}) is True

            header = _dump_header(_flight_files(tmp_path)[0])
            assert custom_field in header
            assert header[custom_field] == MASK, (
                "имя, добавленное в ОБЩИЙ redaction.SECRET_FIELD_NAMES ВО ВРЕМЯ теста, обязано "
                "маскироваться и в шапке дампа — иначе в модуле живёт ВТОРАЯ копия набора правил"
            )
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# C6 (контроль) — неупаковываемое прикладное поле не роняет дамп.
# ---------------------------------------------------------------------------


class TestC6UnpackableFieldStillWritesTheHeaderControl:
    def test_a_circular_reference_field_does_not_crash_the_dump_and_reason_survives(self, tmp_path: Path) -> None:
        logger = _real_logger(tmp_path)
        try:
            services = _Services(flight_recorder=_recorder(), logger_manager=logger)
            logger.info("кадр", module="observability")

            cyclic: Dict[str, Any] = {}
            cyclic["self"] = cyclic  # циклическая ссылка — json.dumps не сериализует ни при каком default

            ok = _ctx(services).flight_dump("reject", broken=cyclic)
            assert ok is True, "неупаковываемое прикладное поле не имеет права уронить дамп целиком"

            header = _dump_header(_flight_files(tmp_path)[0])
            assert header.get("reason") == "reject", (
                "причина обязана остаться в шапке даже при отказе сериализации прикладных полей"
            )
            assert "broken" not in header, "поле, не пережившее сериализацию, не имеет права попасть в шапку"
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# C7 (контроль) — дамп без секретов доезжает дословно, ложных срабатываний нет.
# ---------------------------------------------------------------------------


class TestC7CleanReasonSurvivesVerbatimNoFalsePositive:
    def test_reason_without_secrets_reaches_header_and_filename_verbatim(self, tmp_path: Path) -> None:
        reason = "keyboard failure mode"
        logger = _real_logger(tmp_path)
        try:
            services = _Services(flight_recorder=_recorder(), logger_manager=logger)
            logger.info("кадр", module="observability")

            assert _ctx(services).flight_dump(reason) is True

            files = _flight_files(tmp_path)
            filename = Path(files[0]).name
            assert "keyboard" in filename, (
                f"причина без секретов обязана доехать до ИМЕНИ ФАЙЛА дословно ('keyboard' "
                f"содержит 'key', маскировать его нельзя), получено {filename!r}"
            )

            header = _dump_header(files[0])
            assert header.get("reason") == reason, (
                f"причина без секретов обязана доехать до ШАПКИ дословно, получено {header.get('reason')!r}"
            )
        finally:
            logger.shutdown()
