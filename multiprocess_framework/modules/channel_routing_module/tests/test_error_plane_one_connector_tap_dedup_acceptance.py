# -*- coding: utf-8 -*-
"""RED (независимый тестер, plans/observability-closure): «один разъём на точку».

Критерий приёмки 4: логгер-tap стора (``StoreTapChannel``, обычно вешается на
``logger_manager`` через ``wire_observability_store``) не должен ДУБЛИРОВАТЬ
запись, которая уже была учтена плоскостью ошибок. Маркер — ``origin=error_manager``
в ``extra`` записи (``LogRecord.to_dict()['extra']``). Снятие маркера обязано
уронить тест (проверено ниже отдельным контролем внутри той же функции — по
тому же приёму, что ``backend_ctl/tests/test_overview_thread_exceptions_acceptance.py``:
ноль-контроль и позитив в одной функции, иначе ноль-контроль был бы зелёным уже
сегодня и нарушал бы правило «весь файл красный»).

Источник истины — докстринг задачи (маркер ``origin=error_manager``); в коде
``StoreTapChannel.write()`` (``store_tap.py``) сегодня ТАКОЙ проверки нет вовсе —
метод безусловно принимает любую запись, прошедшую порог ``min_level`` у
``add_tap``. Харнес — ``StoreTapChannel``/``ObservabilityStore`` напрямую, тем же
приёмом, что сосед ``test_store_tap.py`` (``_log_record_dict`` форма — дословно
оттуда, LogRecord.to_dict()).
"""

from __future__ import annotations

from typing import Any, Dict

from multiprocess_framework.modules.channel_routing_module.observability import (
    ObservabilityStore,
    StoreTapChannel,
)


def _log_record_dict(
    level: str = "WARNING", message: str = "boom", module: str = "worker_module", **extra: Any
) -> Dict[str, Any]:
    """Форма ``LogRecord.to_dict()`` — дословно ``test_store_tap.py::_log_record_dict``."""
    return {
        "timestamp": 12.5,
        "level": level,
        "scope": "system",
        "message": message,
        "module": module,
        "extra": dict(extra),
    }


class TestLoggerTapDoesNotDuplicateAnAlreadyRecordedIncident:
    def test_tap_skips_records_marked_origin_error_manager_but_keeps_plain_ones(self, tmp_path) -> None:
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        tap = StoreTapChannel(store, name="logger_error_tap", process="camera_0")

        # Контроль: обычная диагностическая запись (без маркера) — tap обязан
        # её принять, как и делает сегодня. Это ДОЛЖНО оставаться верным и после
        # фикса, поэтому проверяется тут же, а не отдельным вечнозелёным тестом.
        tap.write(_log_record_dict(message="обычная диагностика, не инцидент"))
        after_control = store.list_records(process="camera_0")
        assert len(after_control) == 1, f"контроль сломан ещё ДО позитива: {after_control}"

        # Позитив (RED): запись с маркером origin=error_manager — это ДУБЛЬ
        # инцидента, который уже учтён плоскостью ошибок (см. критерий 2: одна
        # строка на инцидент). Сегодня StoreTapChannel.write() маркер не читает
        # и добавит вторую строку.
        tap.write(_log_record_dict(message="дубль инцидента здоровья", origin="error_manager"))
        rows = store.list_records(process="camera_0")
        assert len(rows) == 1, (
            f"logger-tap задублировал запись с маркером origin=error_manager в extra "
            f"(ожидалась 1 строка от контроля, получено {len(rows)}): {rows}"
        )
        store.close()
