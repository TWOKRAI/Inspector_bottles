# -*- coding: utf-8 -*-
"""Задача S-2: опасности МЕХАНИЗМА редакции шапки flight-дампа, видимые автору.

Приёмка (``test_flight_manifest_redaction_acceptance.py``) доказывает критерии
C1-C7 от независимого тестировщика и её трогать нельзя (см. задание). Здесь —
то, что видно только изнутри устройства ``FlightRecorder._write`` /
``_resolve_path`` и общего редактора ``redaction.py``:

* маска не течёт в СОСЕДНИЕ поля шапки;
* слова, содержащие корень секретного имени подстрокой (``keyboard``,
  ``monkey``), не дают ложного срабатывания;
* неупаковываемое поле рядом с СЕКРЕТНЫМ не роняет дамп, и уже отредактированный
  ``reason`` переживает fallback-ветку сериализации;
* редакция ``reason`` не просачивается в голоса ``note_flight_disabled`` /
  ``note_flight_no_ring`` — эти голоса вне контракта задачи S-2 (они уже едут
  через обычную цепочку логгера в проде, редактировать их здесь — вторая копия
  правил);
* вложенный словарь в ``fields`` маскируется на глубине;
* сам факт «голос едет через обычную цепочку логгера в проде» (предыдущий
  пункт) доказан ЗАПУСКОМ, а не только фейковым харнессом ``_Services`` ниже
  (ревью 6, tests-gap): один тест проводит голос отказа через РЕАЛЬНЫЙ
  ``ProcessModule`` -> ``_log_warning`` -> ``_call_manager("logger", ...)`` ->
  ``LoggerCore._run_processors`` -> ``SecretRedactor`` и проверяет, что секрет
  в итоговой записи замаскирован.

Харнесс — независимая копия минимального харнесса приёмки (не импортируется
оттуда: этот файл не обязан зависеть от внутреннего устройства приёмки, и
наоборот). Проводка настоящая: реальный ``LoggerManager`` с memory-каналом,
реальный ``FlightRecorder``, реальный ``PluginContext`` — fake-harness здесь
доказывал бы только harness. Ниже, у ``TestRealLoggerChainMasksTheSecretInTheRefusalVoice``,
проводка НАСТОЯЩАЯ и по стороне процесса: реальный ``ProcessModule``, а не
``_Services`` — потому что предмет теста ровно то, что ``_Services.log_warning``
у остальных классов этого файла обходит (``_call_manager`` целиком).
"""

from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any, Dict, List

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.core.redaction import MASK
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.managers.observability_flight import (
    NO_RECORDER_KNOBS,
    FlightRecorder,
    note_flight_disabled,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext


class _Services:
    """Минимальный процесс: то же, что читает `flight_dump` и голос отказов."""

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
    config: Dict[str, Any] = {
        "app_name": "flight_manifest_redaction_hazards",
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
    mgr = LoggerManager(manager_name="FlightManifestRedactionHazardsProbe", config=config)
    mgr.initialize()
    return mgr


def _recorder(enabled: bool = True) -> FlightRecorder:
    return FlightRecorder(enabled=enabled, sink="flight_ring", keep=5)


def _flight_files(base: Path, process: str = "inspector") -> List[str]:
    return sorted(glob.glob(str(base / process / "flight" / "*.jsonl")))


def _dump_header(path: str) -> Dict[str, Any]:
    first_line = Path(path).read_text(encoding="utf-8").splitlines()[0]
    return json.loads(first_line)


# ---------------------------------------------------------------------------
# Маска не течёт в соседние поля.
# ---------------------------------------------------------------------------


class TestMaskDoesNotLeakIntoNeighboringFields:
    def test_a_secret_sibling_field_stays_untouched(self, tmp_path: Path) -> None:
        logger = _real_logger(tmp_path)
        try:
            services = _Services(flight_recorder=_recorder(), logger_manager=logger)
            logger.info("кадр", module="observability")

            ok = _ctx(services).flight_dump("reject", token="SECRET_XYZ", worker="cam_0", fps=30)
            assert ok is True

            header = _dump_header(_flight_files(tmp_path)[0])
            assert header["token"] == MASK
            assert header["worker"] == "cam_0", "маска утекла в соседнее ПОЛЕ (не секретное имя)"
            assert header["fps"] == 30, "числовое соседнее поле пострадало от редакции"
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# Ложных срабатываний на подстроку корня в НЕсекретном имени нет.
# ---------------------------------------------------------------------------


class TestNoFalsePositiveOnRootSubstring:
    def test_keyboard_and_monkey_survive_verbatim_in_reason_and_filename(self, tmp_path: Path) -> None:
        """``keyboard`` содержит ``key``, ``monkey`` содержит ``key`` — оба лишь
        подстрокой внутри слова, а не как отдельное секретное имя. Предфильтр
        обязан сработать (корень есть), точная регулярка — НЕТ (нет разделителя
        ``=``/``:`` после целого секретного имени)."""
        for reason in ("keyboard подключена", "monkey patch применён"):
            logger = _real_logger(tmp_path)
            try:
                services = _Services(flight_recorder=_recorder(), logger_manager=logger)
                logger.info("кадр", module="observability")

                assert _ctx(services).flight_dump(reason) is True

                files = _flight_files(tmp_path)
                filename = Path(files[-1]).name
                word = reason.split()[0]
                assert word in filename, f"{word!r} обязано доехать до имени файла дословно, получено {filename!r}"

                header = _dump_header(files[-1])
                assert header.get("reason") == reason, (
                    f"причина без секрета обязана доехать до шапки дословно, получено {header.get('reason')!r}"
                )
            finally:
                logger.shutdown()


# ---------------------------------------------------------------------------
# Неупаковываемое поле рядом с СЕКРЕТНЫМ не роняет дамп, redacted-reason
# переживает fallback-ветку сериализации.
# ---------------------------------------------------------------------------


class TestUnpackableFieldNextToSecretStillWritesRedactedReason:
    def test_cyclic_field_beside_a_secret_field_falls_back_without_leaking_reason(self, tmp_path: Path) -> None:
        raw_reason_secret = "SECRET_IN_REASON_HAZARD_1"
        logger = _real_logger(tmp_path)
        try:
            services = _Services(flight_recorder=_recorder(), logger_manager=logger)
            logger.info("кадр", module="observability")

            cyclic: Dict[str, Any] = {}
            cyclic["self"] = cyclic

            ok = _ctx(services).flight_dump(f"token={raw_reason_secret}", broken=cyclic, token="SECRET_FIELD_HAZARD")
            assert ok is True, "неупаковываемое поле не имеет права уронить дамп, даже рядом с секретным"

            header = _dump_header(_flight_files(tmp_path)[0])
            assert raw_reason_secret not in json.dumps(header, ensure_ascii=False), (
                "уже отредактированный reason обязан пережить fallback-ветку сериализации без утечки"
            )
            assert "broken" not in header, "неупаковываемое поле не имеет права попасть в шапку"
            assert "fields_unreadable" in header, "fallback-ветка обязана оставить след отказа сериализации полей"
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# Редакция reason не просачивается в голоса note_flight_disabled/no_ring —
# они вне контракта S-2 (едут через обычную цепочку логгера в проде).
# ---------------------------------------------------------------------------


class TestRedactionDoesNotCorruptRefusalVoices:
    def test_disabled_refusal_voice_still_carries_the_raw_reason(self, tmp_path: Path) -> None:
        logger = _real_logger(tmp_path)
        try:
            services = _Services(flight_recorder=_recorder(enabled=False), logger_manager=logger)

            raw_reason = "token=SECRET_REFUSAL_VOICE"
            assert _ctx(services).flight_dump(raw_reason) is False

            warnings = [entry for entry in services.logs if entry["level"] == "WARNING"]
            assert warnings, "отказ обязан быть озвучен"
            assert raw_reason in warnings[0]["message"], (
                "S-2 правит только путь ЗАПИСИ дампа; голос отказа 'выключен' не обязан и не должен "
                f"тайно менять текст reason — получено {warnings[0]['message']!r}"
            )
        finally:
            logger.shutdown()

    def test_no_ring_refusal_voice_still_carries_the_raw_reason(self, tmp_path: Path) -> None:
        logger = _real_logger(tmp_path)
        try:
            # sink, которого нет в конфиге логгера — путь note_flight_no_ring.
            recorder = FlightRecorder(enabled=True, sink="absent_sink", keep=5)
            services = _Services(flight_recorder=recorder, logger_manager=logger)

            raw_reason = "token=SECRET_NO_RING_VOICE"
            assert _ctx(services).flight_dump(raw_reason) is False

            warnings = [entry for entry in services.logs if entry["level"] == "WARNING"]
            assert warnings, "отказ обязан быть озвучен"
            assert raw_reason in warnings[0]["message"], (
                f"голос 'нет кольца' не обязан тайно менять текст reason — получено {warnings[0]['message']!r}"
            )
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# Вложенный словарь в fields маскируется на глубине.
# ---------------------------------------------------------------------------


class TestNestedDictInFieldsIsMaskedAtDepth:
    def test_a_secret_two_levels_deep_in_fields_is_masked(self, tmp_path: Path) -> None:
        logger = _real_logger(tmp_path)
        try:
            services = _Services(flight_recorder=_recorder(), logger_manager=logger)
            logger.info("кадр", module="observability")

            nested = {"inner": {"token": "DEEP_SECRET_HAZARD", "neighbor": "keep_me"}}
            ok = _ctx(services).flight_dump("reject", outer=nested)
            assert ok is True

            header = _dump_header(_flight_files(tmp_path)[0])
            assert header["outer"]["inner"]["token"] == MASK, "секрет на глубине 2 не замаскирован"
            assert header["outer"]["inner"]["neighbor"] == "keep_me", "сосед на той же глубине пострадал"
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# Ревью 6 (tests-gap): голос отказа проходит через РЕАЛЬНУЮ цепочку логгера
# (не фейковый _Services выше), и секрет в итоговой записи замаскирован.
# ---------------------------------------------------------------------------


def _real_process_and_logger(tmp_path: Path, *, channel: str = "a") -> "tuple[ProcessModule, LoggerManager]":
    """Реальный ``ProcessModule`` + реальный ``LoggerManager`` с ФАЙЛОВЫМ каналом.

    Не ``_Services`` (фейк выше): предмет этого теста — ровно то, что фейк
    обходит целиком, а именно продовый путь ``ObservableMixin._log_warning``
    -> ``_call_manager("logger", "warning", ...)`` -> зарегистрированный
    ``LoggerManager`` -> ``LoggerCore._run_processors`` -> ``SecretRedactor``
    (``self._processors = (self._redactor, self._sampler)`` заведён
    БЕЗУСЛОВНО в ``LoggerCore.__init__``, ``logger_core.py:409``). Файловый
    канал, а не ``memory``: голос отказа читается текстом из файла на диске,
    той же дорогой, что и у ``test_flight_recorder_default_and_revoice_hazards.py``.
    """
    config: Dict[str, Any] = {"app_name": "flight_refusal_redaction_hazard"}
    proc = ProcessModule("inspector", config=config)
    logger_config: Dict[str, Any] = {
        "app_name": "flight_refusal_redaction_hazard",
        "log_directory": str(tmp_path),
        "modules": {},
        "channels": {channel: {"type": "file", "enabled": True, "file_path": f"{channel}.log"}},
        "scopes": {
            "SYSTEM": {"channels": [channel]},
            "BUSINESS": {"channels": [channel]},
            "DEBUG": {"channels": [channel]},
        },
    }
    logger = LoggerManager(manager_name="FlightRefusalRedactionHazardProbe", config=logger_config, process=proc)
    logger.initialize()
    proc.logger_manager = logger
    proc.register_manager("logger", logger, enabled=True)
    return proc, logger


class TestRealLoggerChainMasksTheSecretInTheRefusalVoice:
    """``TestRedactionDoesNotCorruptRefusalVoices`` (выше) доказывает, что голос
    отказа несёт СЫРУЮ причину — и это правда на уровне самого модуля. Но её
    харнесс — ``_Services.log_warning``, фейк, который аппендит строку в список
    МИМО ``_call_manager`` целиком: сломай кто-нибудь роутинг ``_call_manager``
    или выключи ``SecretRedactor`` из цепочки процессоров — ни один тест того
    класса не покраснеет, потому что ни один не проходит через них.

    Здесь голос идёт через РЕАЛЬНЫЙ ``ProcessModule`` -> ``_log_warning`` ->
    ``_call_manager`` -> зарегистрированный ``LoggerManager`` -> ``SecretRedactor``,
    и утверждение — что в проде секрет из ``reason`` всё равно замаскирован,
    даже при том что ``note_flight_disabled`` сам его не редактирует (см.
    класс выше и модульный докстринг ``observability_flight.py`` про Р5.1-12/S-2:
    редакция ``reason``/``fields`` там — только для ТЕЛА дампа, а голос отказа
    в контракт S-2 не входит и полагается на общую цепочку логгера)."""

    def test_disabled_refusal_voice_is_masked_by_the_real_processor_chain(self, tmp_path: Path) -> None:
        proc, logger = _real_process_and_logger(tmp_path)
        try:
            raw_reason = "token=SEKRET_XYZ_REAL_CHAIN"
            note_flight_disabled(proc, raw_reason, NO_RECORDER_KNOBS)
            said = (tmp_path / "inspector" / "a.log").read_text(encoding="utf-8", errors="replace")
        finally:
            logger.shutdown()

        assert "SEKRET_XYZ_REAL_CHAIN" not in said, (
            "секрет из reason доехал до файла НЕотредактированным — реальная цепочка "
            "_log_warning -> _call_manager -> SecretRedactor не сработала"
        )
        assert "token=***" in said, f"ожидалась маска 'token=***' в записи, получено: {said!r}"
