# -*- coding: utf-8 -*-
"""Слепая приёмка T8c: синтетический источник ставит ``capture_ns`` и ``capture_ts`` сам.

Purpose: пригвоздить контракт штампов кадра для ``SyntheticFrameSourcePlugin.produce()``:
``capture_ns`` (int, ``perf_counter_ns``) и ``capture_ts`` (float, ``time.time``) поставлены
внутри ``produce()``; ``timestamp`` остаётся монотонным float; прочие поля как были;
``group_id`` синтетика не назначает.

Тесты написаны по вырезке критериев приёмки, до реализации. Часы Windows: шаг ``time.time()`` и
``time.monotonic()`` бывает 1 мс или 15,6 мс, поэтому для них только скобка (чтения монотонны),
без допусков.
"""

from __future__ import annotations

import time

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.sources.synthetic_frame_source.plugin import SyntheticFrameSourcePlugin

__all__: list[str] = []

_CFG = {"camera_id": 5, "resolution_width": 64, "resolution_height": 48}


@pytest.fixture
def plugin() -> SyntheticFrameSourcePlugin:
    services = MockProcessServices(name="synthetic_proc", config=_CFG)
    ctx = PluginContext(services=services, config=_CFG, plugin_name=SyntheticFrameSourcePlugin.name)
    instance = SyntheticFrameSourcePlugin()
    instance.configure(ctx)
    return instance


def test_synthetic_item_has_capture_ns_and_capture_ts(plugin) -> None:
    """Item синтетики несёт ``capture_ns`` типа int и ``capture_ts`` типа float.

    Убивает: отсутствие штампов; ``capture_ns`` float (``perf_counter()``); ``capture_ts`` int
    (``time.time_ns()``/округление).
    """
    items = plugin.produce()
    assert len(items) == 1
    assert type(items[0]["capture_ns"]) is int
    assert type(items[0]["capture_ts"]) is float


def test_synthetic_capture_ns_stamped_inside_produce(plugin) -> None:
    """``capture_ns`` лежит в скобке ``perf_counter_ns()`` вокруг ``produce()``.

    Убивает: ``time.time_ns()`` вместо ``perf_counter_ns()`` (другая эпоха); штамп в ``configure()``
    (раньше левой границы скобки); константу.
    """
    n0 = time.perf_counter_ns()
    items = plugin.produce()
    n1 = time.perf_counter_ns()
    assert n0 <= items[0]["capture_ns"] <= n1


def test_synthetic_capture_ts_stamped_inside_produce(plugin) -> None:
    """``capture_ts`` лежит в скобке ``time.time()`` вокруг ``produce()``.

    Убивает: ``perf_counter()``/``monotonic()`` вместо wall-часов; штамп в ``configure()``.
    """
    w0 = time.time()
    items = plugin.produce()
    w1 = time.time()
    assert w0 <= items[0]["capture_ts"] <= w1


def test_synthetic_capture_ns_differs_between_produce_calls(plugin) -> None:
    """Пять отдельных ``produce()``: ``capture_ns`` строго растёт (штамп ставится на каждом вызове).

    Убивает: одно значение на весь прогон (штамп один раз в ``configure()`` или кэш).
    """
    stamps = [plugin.produce()[0]["capture_ns"] for _ in range(5)]
    assert all(later > earlier for earlier, later in zip(stamps, stamps[1:]))


def test_synthetic_timestamp_stays_monotonic_float(plugin) -> None:
    """``timestamp`` остаётся ``time.monotonic()`` (float): внутри скобки ``monotonic()`` вокруг ``produce()``.

    Убивает: подмену ``timestamp`` новым штампом (``perf_counter_ns`` int или wall-время).
    """
    m0 = time.monotonic()
    item = plugin.produce()[0]
    m1 = time.monotonic()
    assert type(item["timestamp"]) is float
    assert m0 <= item["timestamp"] <= m1


def test_synthetic_item_keeps_existing_fields(plugin) -> None:
    """Прочие поля item как были: значения из конфига и счётчик кадров."""
    item = plugin.produce()[0]
    assert item["camera_id"] == 5
    assert (item["width"], item["height"], item["channels"], item["dtype"]) == (64, 48, 3, "uint8")
    assert (item["seq_id"], item["frame_id"]) == (1, 1)
    assert item["frame"].shape == (48, 64, 3)


def test_synthetic_does_not_assign_group_id(plugin) -> None:
    """Синтетика ``group_id`` не назначает: ключа нет или значение ``None``.

    Убивает: назначение group_id источником (счётчик, 0, seq_id).
    """
    assert plugin.produce()[0].get("group_id") is None
