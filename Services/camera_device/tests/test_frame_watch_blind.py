# -*- coding: utf-8 -*-
"""Слепая приёмка W2-t1: помощник `FrameWatch` и поля камеры `frame_watch`, `frame_watch_deadline_ms`.

Написано до реализации по `tasks/W2-t1.md` (DESIGN п.1, п.2; REDS). Ожидаемые значения — литералы.
Помощник импортируется внутри теста (`_frame_watch`), чтобы отсутствие модуля не прятало, какой тест о чём,
и не роняло тесты register'а. Время — аргумент `now`, часов и потоков нет.

Не закреплено намеренно (спек молчит): поведение при `deadline_s <= 0`; судьба не отданных `poll` пропусков
после `drop_pending`.
"""

from __future__ import annotations

import importlib

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from Services.camera_device.registers_base import CameraDeviceRegisters

__all__ = []

_RESTART_NOTE = "Правка — перезапуск процесса"


def _frame_watch_module():
    return importlib.import_module("Services.camera_device.frame_watch")


def _frame_watch(deadline_s: float = 0.5):
    return _frame_watch_module().FrameWatch(deadline_s)


def _snap(triggers: int, misses: int, open_miss: bool, last_miss_mono: float | None) -> dict:
    return {"triggers": triggers, "misses": misses, "open_miss": open_miss, "last_miss_mono": last_miss_mono}


# --- Модуль ---


def test_module_public_api_and_lite_docstring():
    module = _frame_watch_module()
    assert module.__all__ == ["FrameWatch"]
    assert "Purpose:" in module.__doc__
    assert "Public API:" in module.__doc__
    assert "Stability: lite" in module.__doc__


# --- Срок и пропуск ---


def test_initial_snapshot():
    watch = _frame_watch()
    assert watch.snapshot() == _snap(0, 0, False, None)
    assert watch.poll(100.0) == 0


def test_frame_within_deadline_no_miss():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    watch.on_frame(0.3)
    assert watch.poll(1.0) == 0
    assert watch.snapshot() == _snap(1, 0, False, None)


def test_no_frame_is_miss_once():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    assert watch.poll(0.6) == 1
    assert watch.snapshot() == _snap(1, 1, True, 0.6)
    assert watch.poll(5.0) == 0
    assert watch.snapshot() == _snap(1, 1, True, 0.6)


def test_deadline_is_strict():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    assert watch.poll(0.5) == 0
    assert watch.snapshot() == _snap(1, 0, False, None)
    assert watch.poll(0.5078125) == 1


def test_frame_at_exact_deadline_is_not_a_miss():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    watch.on_frame(0.5)
    assert watch.snapshot() == _snap(1, 0, False, None)
    assert watch.poll(1.0) == 0


def test_deadline_argument_is_used():
    watch = _frame_watch(2.0)
    watch.on_trigger(0.0)
    assert watch.poll(2.0) == 0
    assert watch.poll(2.5) == 1


def test_one_poll_counts_every_overdue_impulse():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    watch.on_trigger(0.125)
    watch.on_trigger(1.0)
    assert watch.poll(1.25) == 2
    assert watch.snapshot() == _snap(3, 2, True, 1.25)
    assert watch.poll(1.75) == 1
    assert watch.snapshot() == _snap(3, 3, True, 1.75)


# --- Сопоставление кадра (FIFO) ---


def test_frame_matches_oldest():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    watch.on_trigger(0.4)
    watch.on_frame(0.45)
    assert watch.poll(0.85) == 0
    assert watch.poll(0.95) == 1


def test_fifo_limit_pinned():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    watch.on_trigger(0.3)
    watch.on_frame(0.35)
    assert watch.poll(0.7) == 0
    assert watch.poll(0.81) == 1


def test_late_frame_before_poll_keeps_miss():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    watch.on_frame(0.8)
    assert watch.snapshot() == _snap(1, 1, False, 0.8)
    assert watch.poll(1.0) == 1
    assert watch.snapshot() == _snap(1, 1, False, 0.8)
    assert watch.poll(1.0) == 0


def test_late_frame_after_poll_closes_episode():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    assert watch.poll(0.6) == 1
    watch.on_frame(0.7)
    assert watch.snapshot() == _snap(1, 1, False, 0.6)
    assert watch.poll(0.7) == 0


def test_frame_counts_overdue_then_takes_oldest_remaining():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    watch.on_trigger(0.8)
    watch.on_frame(0.9)  # 0.0 просрочен -> пропуск; кадр снимает 0.8
    assert watch.snapshot() == _snap(2, 1, False, 0.9)
    assert watch.poll(5.0) == 1
    assert watch.snapshot() == _snap(2, 1, False, 0.9)


def test_frame_counts_all_overdue():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    watch.on_trigger(0.125)
    watch.on_frame(1.0)
    assert watch.snapshot() == _snap(2, 2, False, 1.0)
    assert watch.poll(1.0) == 2


def test_frame_without_trigger_ignored():
    watch = _frame_watch()
    watch.on_frame(0.0)
    assert watch.snapshot() == _snap(0, 0, False, None)
    watch.on_trigger(0.1)  # кадр до импульса в запас не идёт
    assert watch.poll(0.7) == 1
    assert watch.snapshot() == _snap(1, 1, True, 0.7)


# --- Переполнение 1024 ---


def test_overflow_counts_oldest():
    watch = _frame_watch()
    for _ in range(1025):
        watch.on_trigger(0.0)
    assert watch.snapshot() == _snap(1025, 1, True, 0.0)
    assert watch.poll(0.0) == 1
    assert watch.poll(1.0) == 1024  # в очереди оставалось ровно 1024
    assert watch.snapshot() == _snap(1025, 1025, True, 1.0)


def test_1024_pending_impulses_do_not_overflow():
    watch = _frame_watch()
    for _ in range(1024):
        watch.on_trigger(0.0)
    assert watch.snapshot() == _snap(1024, 0, False, None)
    assert watch.poll(0.0) == 0


def test_overflow_drops_the_oldest_not_the_newest():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    for _ in range(1023):
        watch.on_trigger(0.375)
    watch.on_trigger(0.375)  # 1025-й: снимается импульс 0.0
    assert watch.snapshot() == _snap(1025, 1, True, 0.375)
    assert watch.poll(0.625) == 1  # только переполнение: импульса 0.0 в очереди уже нет


# --- drop_pending, reset_counts, withdraw_last ---


def test_drop_pending_keeps_counts_and_empties_queue():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    assert watch.poll(0.6) == 1
    watch.on_trigger(0.7)
    watch.drop_pending()
    assert watch.snapshot() == _snap(2, 1, False, 0.6)
    assert watch.poll(5.0) == 0
    assert watch.snapshot() == _snap(2, 1, False, 0.6)


def test_reset_counts_zeroes_counts_and_keeps_queue():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    assert watch.poll(0.6) == 1
    watch.on_trigger(0.7)
    watch.reset_counts()
    assert watch.snapshot() == _snap(0, 0, False, None)
    assert watch.poll(1.5) == 1  # импульс 0.7 пережил сброс


def test_reset_counts_discards_unreported_miss_from_late_frame():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    watch.on_frame(0.8)
    watch.reset_counts()
    assert watch.poll(1.0) == 0


def test_reset_counts_discards_unreported_miss_from_overflow():
    watch = _frame_watch()
    for _ in range(1025):
        watch.on_trigger(0.0)
    watch.reset_counts()
    assert watch.snapshot() == _snap(0, 0, False, None)
    assert watch.poll(0.0) == 0


def test_withdraw_last():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    watch.on_trigger(0.4)
    assert watch.withdraw_last() is True
    assert watch.snapshot() == _snap(1, 0, False, None)
    assert watch.poll(0.6) == 1
    assert watch.withdraw_last() is False
    assert watch.snapshot() == _snap(1, 1, True, 0.6)


def test_withdraw_last_on_new_watch_returns_false():
    watch = _frame_watch()
    assert watch.withdraw_last() is False
    assert watch.snapshot() == _snap(0, 0, False, None)


def test_withdraw_after_reset_counts_does_not_go_negative():
    watch = _frame_watch()
    watch.on_trigger(0.0)
    watch.reset_counts()
    assert watch.withdraw_last() is True
    assert watch.snapshot() == _snap(0, 0, False, None)
    assert watch.poll(5.0) == 0


# --- Свойство: счёт сходится на любой последовательности вызовов ---

# Шаг времени кратен 1/8 с: сравнения со сроком 0.5 точны в float.
_OPS = st.lists(
    st.tuples(st.sampled_from(["trigger", "frame", "poll", "withdraw"]), st.integers(min_value=0, max_value=8)),
    max_size=60,
)


@settings(max_examples=200, deadline=None)
@given(ops=_OPS)
def test_property_every_miss_reported_by_poll_exactly_once(ops):
    """Без `reset_counts`: сумма возвратов `poll` равна `misses`, пропусков не больше импульсов."""
    watch = _frame_watch()
    now = 0.0
    reported = 0
    for op, eighths in ops:
        now += eighths / 8
        if op == "trigger":
            watch.on_trigger(now)
        elif op == "frame":
            watch.on_frame(now)
            assert watch.snapshot()["open_miss"] is False
        elif op == "poll":
            reported += watch.poll(now)
        else:
            watch.withdraw_last()
        assert 0 <= watch.snapshot()["misses"] <= watch.snapshot()["triggers"]
    reported += watch.poll(now + 10.0)
    assert reported == watch.snapshot()["misses"]
    assert watch.poll(now + 20.0) == 0


# --- Поля register'а ---


def test_register_fields_defaults():
    registers = CameraDeviceRegisters()
    assert registers.frame_watch == "off"
    assert registers.frame_watch_deadline_ms == 500


@pytest.mark.parametrize("source", ["off", "software", "message"])
def test_register_frame_watch_accepts_source(source):
    assert "frame_watch" in CameraDeviceRegisters.model_fields  # лишние ключи схема глотает молча
    assert CameraDeviceRegisters(frame_watch=source).frame_watch == source


def test_register_frame_watch_rejects_device():
    with pytest.raises(ValidationError):
        CameraDeviceRegisters(frame_watch="device")


@pytest.mark.parametrize("deadline_ms", [1, 10000])
def test_register_deadline_accepts_bounds(deadline_ms):
    assert "frame_watch_deadline_ms" in CameraDeviceRegisters.model_fields
    assert CameraDeviceRegisters(frame_watch_deadline_ms=deadline_ms).frame_watch_deadline_ms == deadline_ms


@pytest.mark.parametrize("deadline_ms", [0, 10001])
def test_register_deadline_rejects_out_of_bounds(deadline_ms):
    with pytest.raises(ValidationError):
        CameraDeviceRegisters(frame_watch_deadline_ms=deadline_ms)


@pytest.mark.parametrize("field", ["frame_watch", "frame_watch_deadline_ms"])
def test_register_field_is_applied_by_process_restart_without_apply(field):
    meta = CameraDeviceRegisters.get_all_fields_meta().get(field)
    assert meta is not None, f"у поля {field} нет FieldMeta"
    assert meta.apply is None
    assert _RESTART_NOTE in meta.info


def test_register_frame_watch_info_states_fifo_limit():
    meta = CameraDeviceRegisters.get_all_fields_meta().get("frame_watch")
    assert meta is not None, "у поля frame_watch нет FieldMeta"
    assert "FIFO" in meta.info
