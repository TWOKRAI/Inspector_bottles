# -*- coding: utf-8 -*-
"""Task 0.1 — одна функция исхода звена и один счётчик потерь (unit).

Ожидаемые значения — литералы из Task 0.1, не производные от кода под тестом.
Тесты чистые: без потоков, без ввода-вывода, лок не берут (его держит вызывающий).
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.channel_routing_module.core.channel_routing_manager import (
    count_outcome,
)
from multiprocess_framework.modules.channel_routing_module.interfaces import (
    channel_accepted,
    outcome_of,
)


def test_dropped_is_refused():
    assert outcome_of({"status": "dropped"}) == "refused"


def test_refused_is_refused():
    assert outcome_of({"status": "refused"}) == "refused"


def test_error_is_failed():
    assert outcome_of({"status": "error"}) == "failed"


def test_skipped_is_accepted():
    """Характеризация прежнего ``channel_accepted``: ``skipped`` — не отказ."""
    assert outcome_of({"status": "skipped"}) == "accepted"


def test_dict_without_status_is_accepted():
    assert outcome_of({}) == "accepted"
    assert outcome_of({"channel": "x"}) == "accepted"


def test_none_and_non_dict_accepted():
    """Канал без ответа считался принявшим и раньше; ломать это нельзя."""
    for result in (None, "x", 0, []):
        assert outcome_of(result) == "accepted", result


#: Таблица «вход -> channel_accepted»: 13 литералов Task 0.1.
_ACCEPTED_TABLE = (
    (None, True),
    ("x", True),
    (0, True),
    ({}, True),
    ({"channel": "x"}, True),
    ({"status": "success"}, True),
    ({"status": "ok"}, True),
    ({"status": "skipped"}, True),
    ({"status": "dropped"}, False),
    ({"status": "refused"}, False),  # расширение 0.1: раньше было True
    ({"status": "error"}, False),
    ({"status": None}, True),
    ({"status": ["error"]}, True),  # список не хэшируется: кортеж, не set
)


def test_channel_accepted_parity():
    for result, expected in _ACCEPTED_TABLE:
        assert channel_accepted(result) is expected, result


def test_count_outcome_channel_refused():
    c: dict = {}
    count_outcome(c, "channel", "refused")
    assert c == {"channel_refused_records": 1}


def test_count_outcome_channel_failed():
    c: dict = {}
    count_outcome(c, "channel", "failed")
    assert c == {"channel_refused_records": 1}


def test_count_outcome_tap_refused():
    c: dict = {}
    count_outcome(c, "tap", "refused")
    assert c == {"tap_refused_records": 1}


def test_count_outcome_tap_failed():
    c: dict = {}
    count_outcome(c, "tap", "failed")
    assert c == {"tap_write_errors": 1}


def test_count_outcome_bridge_refused():
    c: dict = {}
    count_outcome(c, "bridge", "refused")
    assert c == {"lost_responses": 1}


def test_count_outcome_bridge_failed():
    c: dict = {}
    count_outcome(c, "bridge", "failed")
    assert c == {"lost_responses": 1}


def test_count_outcome_accepted_is_noop():
    c: dict = {}
    assert count_outcome(c, "tap", "accepted") is None
    assert c == {}


def test_count_outcome_adds_to_existing_value():
    c = {"tap_write_errors": 2}
    count_outcome(c, "tap", "failed")
    assert c == {"tap_write_errors": 3}


def test_count_outcome_unknown_hop_rejected():
    c: dict = {}
    with pytest.raises(ValueError, match="count_outcome: unknown hop") as exc:
        count_outcome(c, "nope", "refused")
    assert "nope" not in str(exc.value)  # значение в сообщение не попадает
    assert c == {}
    # hop проверяется и на здоровом пути: опечатка видна без отказа
    with pytest.raises(ValueError, match="count_outcome: unknown hop"):
        count_outcome({}, "nope", "accepted")


def test_count_outcome_unknown_outcome_rejected():
    c: dict = {}
    with pytest.raises(ValueError, match="count_outcome: unknown outcome") as exc:
        count_outcome(c, "tap", "weird")  # type: ignore[arg-type]
    assert "weird" not in str(exc.value)
    assert c == {}
