# -*- coding: utf-8 -*-
# ruff: noqa: F811 — фикстура `make` из core_rig подключена импортом
"""Проводка штампов времени кадра через подкласс `HikvisionCameraPlugin` (T8c, ADR-177).

Purpose: ядро `CameraDevicePlugin` ставит `capture_ns`/`capture_ts` в `_on_frame`; подкласс Hikvision переопределяет
`_build_item` и обязан передать штамп `cap_ns` в `super()` без изменений. Тесты ядра этого не видят: на подклассе
мутанты «в super() передан 0» и «штамп взят заново в `_build_item`» оставались зелёными. Здесь проверяется наблюдаемое:
item из настоящих `_on_frame` и `produce()` (слот не читается и не подменяется).

Часы Windows: шаг `time.time()` бывает 1 мс или 15,6 мс, поэтому для wall-часов только точное равенство
`capture_ts == ts` и контрольный сон 100 мс (100 - 15,6 > 40 при любом шаге); для `perf_counter_ns()` сон 50 мс.
Ожидаемые значения — скобки по часам, литералы порогов; из кода плагина не выводятся.
"""

from __future__ import annotations

import time


from Services.camera_device.interface import RawFrame
from Services.hikvision_camera.tests.core_rig import RGB_24, _feed, _res
from Services.hikvision_camera.tests.core_rig import make  # noqa: F401 — фикстура pytest

__all__: list[str] = []

_SLEEP_NS_S = 0.05  # между `_on_frame` и `produce()` для perf_counter_ns (разрешение много меньше 1 мкс)
_SLEEP_WALL_S = 0.1  # то же для time.time(): устойчиво к шагу 15,6 мс
_MIN_GAP_NS = 40_000_000  # штамп старше момента `produce()` не менее чем на 40 мс
_MIN_GAP_S = 0.04


def _raw() -> RawFrame:
    return RawFrame(bytearray(RGB_24), 4, 2, "rgb8", 1)


def test_hikvision_item_capture_ns_is_int_inside_bracket(make):
    """`capture_ns` item-а Hikvision — настоящий `int` внутри скобки `perf_counter_ns()` вокруг кадра.

    Убивает: в `super()._build_item` передан `0` или константа (вне скобки), штамп `float`, `None`, отсутствие поля.
    """
    plugin = make(_res(4, 2)).plugin
    n0 = time.perf_counter_ns()
    items = _feed(plugin, RGB_24, 4, 2, "rgb8")
    n1 = time.perf_counter_ns()

    assert len(items) == 1
    capture_ns = items[0]["capture_ns"]
    assert type(capture_ns) is int
    assert n0 <= capture_ns <= n1


def test_hikvision_capture_ns_taken_at_on_frame_not_at_produce(make):
    """Между `_on_frame` и `produce()` 50 мс: `capture_ns` в скобке вокруг `_on_frame`, а не около `produce()`.

    Убивает: штамп заново в `_build_item` подкласса (был бы около `produce_ns`), `0`/константа в `super()`.
    """
    plugin = make(_res(4, 2)).plugin
    n0 = time.perf_counter_ns()
    plugin._on_frame(_raw())
    n1 = time.perf_counter_ns()
    time.sleep(_SLEEP_NS_S)
    items = plugin.produce()
    produce_ns = time.perf_counter_ns()

    assert len(items) == 1
    capture_ns = items[0]["capture_ns"]
    assert n0 <= capture_ns <= n1
    assert produce_ns - capture_ns >= _MIN_GAP_NS


def test_hikvision_capture_ts_equals_ts_and_is_taken_at_on_frame(make):
    """`capture_ts` — `float`, равен `ts` (точное равенство), внутри скобки `time.time()` вокруг `_on_frame`.

    Между `_on_frame` и `produce()` 100 мс: `produce_wall - capture_ts >= 40 мс`. Допуск 5 мс не вводится.
    Убивает: `capture_ts = time.time()` в `_build_item` подкласса (разрыв с `ts` и контроль 40 мс).
    """
    plugin = make(_res(4, 2)).plugin
    wall0 = time.time()
    plugin._on_frame(_raw())
    wall1 = time.time()
    time.sleep(_SLEEP_WALL_S)
    items = plugin.produce()
    produce_wall = time.time()

    assert len(items) == 1
    item = items[0]
    assert type(item["capture_ts"]) is float
    assert item["capture_ts"] == item["ts"]
    assert wall0 <= item["capture_ts"] <= wall1
    assert produce_wall - item["capture_ts"] >= _MIN_GAP_S
