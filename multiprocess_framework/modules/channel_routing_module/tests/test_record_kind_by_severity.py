# -*- coding: utf-8 -*-
"""Ф5.2, Б-4: вид записи считает ИСТОЧНИК (её важность), а не канал-перевозчик.

Дефект жил в конструкторе: и стор-tap, и live-форвардер получали ``kind`` параметром
со значением ``'error'`` и висели ОБА на ``logger_manager``. Порог tap'а с Ф6.х.5
задаёт подписчик — то есть под ``kind=error`` в хвост поехало всё, что этот порог
пропустил. Живьём: INFO-снимок метрик приехал во вкладку ошибкой.

Пары «до/после» здесь и есть приёмка находки: до — INFO помечен ошибкой, после —
логом, и обе дороги (хвост и история) метят одну запись ОДИНАКОВО.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.channel_routing_module.levels import ERROR_SEVERITY, SEVERITY_NUMBERS
from multiprocess_framework.modules.channel_routing_module.observability import (
    ObservabilityStore,
    RecordForwardChannel,
    StoreTapChannel,
    log_record_to_display,
)
from multiprocess_framework.modules.channel_routing_module.observability.record_display import kind_for_severity


def _log_record(level: str, message: str = "запись"):
    return {
        "timestamp": 12.5,
        "level": level,
        "scope": "system",
        "message": message,
        "module": "worker_module",
        "extra": {},
    }


class _SpyRouter:
    def __init__(self) -> None:
        self.sent: list = []

    def send_async(self, message, priority="normal") -> None:
        self.sent.append(message)


class TestKindIsDerivedFromSeverity:
    @pytest.mark.parametrize(
        ("level", "expected"),
        [
            ("DEBUG", "log"),
            ("INFO", "log"),
            ("WARNING", "log"),
            ("ERROR", "error"),
            ("CRITICAL", "error"),
        ],
    )
    def test_every_level_lands_under_its_own_kind(self, level: str, expected: str) -> None:
        assert log_record_to_display(_log_record(level))["kind"] == expected

    def test_threshold_is_the_one_already_used_for_the_error_invariant(self) -> None:
        """Второго определения аварийности не заводится.

        Порог берётся из `ERROR_SEVERITY` (Ф3.1, «≥17 = ошибка»). Литералы взяты из
        таблицы уровней, а не из функции под тестом: тест, выводящий ожидаемое из
        проверяемого кода, согласится с любым ответом.
        """
        assert kind_for_severity(SEVERITY_NUMBERS["WARNING"]) == "log"
        assert kind_for_severity(SEVERITY_NUMBERS["ERROR"]) == "error"
        assert kind_for_severity(ERROR_SEVERITY - 1) == "log"

    def test_unknown_level_is_a_log_not_an_error(self) -> None:
        """Опечатка в имени уровня — не повод объявить запись аварией."""
        assert log_record_to_display(_log_record("НЕИЗВЕСТНО"))["kind"] == "log"

    def test_kind_agrees_with_severity_number_in_the_same_row(self) -> None:
        """`kind` и `severity_number` считаются из одного прочтения уровня.

        Разойдись они — строка сказала бы «ошибка» колонкой и «ниже порога» числом,
        и фильтр вкладки разошёлся бы с её же содержимым.
        """
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            row = log_record_to_display(_log_record(level))
            assert (row["kind"] == "error") is (row["severity_number"] >= ERROR_SEVERITY), level


class TestBothRoadsAgree:
    def test_live_tail_and_history_label_the_same_record_identically(self, tmp_path) -> None:
        """Хвост и история — две дороги одной записи; разные метки на них и были Б-4."""
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        router = _SpyRouter()
        try:
            record = _log_record("INFO", "снимок метрик")

            tap = StoreTapChannel(store, process="camera_0")
            tap.write(record)
            tap.flush(timeout=2.0)  # Task 3.3: дожать очередь перед чтением своих же строк
            RecordForwardChannel(router=router, subscriber="gui", sender="camera_0").write(record)

            history = store.list_records()
            assert len(history) == 1
            live = router.sent[0]["data"]["record"]
            assert history[0]["kind"] == "log", "история пометила INFO ошибкой (Б-4)"
            assert live["kind"] == "log", "живой хвост пометил INFO ошибкой (Б-4)"
            assert history[0]["kind"] == live["kind"]
        finally:
            store.close()

    def test_error_still_lands_as_error_on_both_roads(self, tmp_path) -> None:
        """Обратная половина пары: починка не увела ошибки из своей вкладки."""
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        router = _SpyRouter()
        try:
            record = _log_record("ERROR", "упало")

            tap = StoreTapChannel(store, process="camera_0")
            tap.write(record)
            tap.flush(timeout=2.0)  # Task 3.3: дожать очередь перед чтением своих же строк
            RecordForwardChannel(router=router, subscriber="gui", sender="camera_0").write(record)

            assert store.list_records(kind="error")[0]["message"] == "упало"
            assert router.sent[0]["data"]["record"]["kind"] == "error"
        finally:
            store.close()
