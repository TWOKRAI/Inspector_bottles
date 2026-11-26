# -*- coding: utf-8 -*-
"""Тесты автора W2-t1: помощник `FrameWatch` и два поля register'а камеры.

Все помощники — `FrameWatch(0.5)`; время — аргумент `now`, часов и потоков нет, ожидания — литералы.
Помощник импортируется внутри `_watch`, чтобы отсутствие модуля не роняло тест register'а.
"""

from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError

from Services.camera_device.registers_base import CameraDeviceRegisters


def _watch():
    return importlib.import_module("Services.camera_device.frame_watch").FrameWatch(0.5)


def _snap(triggers: int, misses: int, open_miss: bool, last_miss_mono: float | None) -> dict:
    return {"triggers": triggers, "misses": misses, "open_miss": open_miss, "last_miss_mono": last_miss_mono}


def test_initial_snapshot():
    assert _watch().snapshot() == {"triggers": 0, "misses": 0, "open_miss": False, "last_miss_mono": None}


def test_frame_within_deadline_no_miss():
    watch = _watch()
    watch.on_trigger(0.0)
    watch.on_frame(0.3)
    assert watch.poll(1.0) == 0


def test_no_frame_is_miss_once():
    watch = _watch()
    watch.on_trigger(0.0)
    assert watch.poll(0.6) == 1
    assert watch.snapshot() == _snap(1, 1, True, 0.6)
    assert watch.poll(5.0) == 0


def test_deadline_is_strict():
    watch = _watch()
    watch.on_trigger(0.0)
    assert watch.poll(0.5) == 0
    assert watch.poll(0.5078125) == 1


def test_frame_matches_oldest():
    watch = _watch()
    watch.on_trigger(0.0)
    watch.on_trigger(0.4)
    watch.on_frame(0.45)
    assert watch.poll(0.85) == 0
    assert watch.poll(0.95) == 1


def test_fifo_limit_pinned():
    """Предел сопоставления FIFO: кадр гасит импульс 0.0, а импульс 0.3 просрочивается по своему сроку."""
    watch = _watch()
    watch.on_trigger(0.0)
    watch.on_trigger(0.3)
    watch.on_frame(0.35)
    assert watch.poll(0.7) == 0
    assert watch.poll(0.81) == 1


def test_late_frame_before_poll_keeps_miss():
    watch = _watch()
    watch.on_trigger(0.0)
    watch.on_frame(0.8)
    assert watch.poll(1.0) == 1
    assert watch.snapshot() == _snap(1, 1, False, 0.8)


def test_late_frame_after_poll_closes_episode():
    watch = _watch()
    watch.on_trigger(0.0)
    assert watch.poll(0.6) == 1
    watch.on_frame(0.7)
    assert watch.snapshot() == _snap(1, 1, False, 0.6)


def test_frame_without_trigger_ignored():
    watch = _watch()
    watch.on_frame(0.0)
    assert watch.snapshot() == _snap(0, 0, False, None)
    assert watch.poll(5.0) == 0


def test_overflow_counts_oldest():
    watch = _watch()
    for _ in range(1025):
        watch.on_trigger(0.0)
    assert watch.snapshot() == _snap(1025, 1, True, 0.0)
    assert watch.poll(0.0) == 1


def test_drop_pending_and_reset_counts():
    watch = _watch()
    watch.on_trigger(0.0)
    assert watch.poll(0.6) == 1
    watch.on_trigger(0.7)
    watch.drop_pending()
    assert watch.snapshot() == _snap(2, 1, False, 0.6)
    assert watch.poll(5.0) == 0

    # Решение лида: пропуск, не отданный `poll`, при `drop_pending` не теряется — он уже произошёл.
    watch.on_trigger(6.0)
    watch.on_frame(7.0)
    watch.drop_pending()
    assert watch.snapshot() == _snap(3, 2, False, 7.0)
    assert watch.poll(7.0) == 1

    watch.on_trigger(8.0)
    watch.reset_counts()
    assert watch.snapshot() == _snap(0, 0, False, None)
    assert watch.poll(9.0) == 1  # очередь пережила сброс


def test_withdraw_last():
    watch = _watch()
    watch.on_trigger(0.0)
    watch.on_trigger(0.4)
    assert watch.withdraw_last() is True
    assert watch.snapshot() == _snap(1, 0, False, None)
    assert watch.poll(0.6) == 1  # остался старый (0.0): сними withdraw его, здесь было бы 0
    assert watch.withdraw_last() is False


def test_register_fields():
    registers = CameraDeviceRegisters()
    assert registers.frame_watch == "off"
    assert registers.frame_watch_deadline_ms == 500
    for bad in ({"frame_watch": "device"}, {"frame_watch_deadline_ms": 0}, {"frame_watch_deadline_ms": 10001}):
        with pytest.raises(ValidationError):
            CameraDeviceRegisters(**bad)
    assert CameraDeviceRegisters(frame_watch_deadline_ms=1).frame_watch_deadline_ms == 1
    assert CameraDeviceRegisters(frame_watch_deadline_ms=10000).frame_watch_deadline_ms == 10000
