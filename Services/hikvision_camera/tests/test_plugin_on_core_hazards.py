# -*- coding: utf-8 -*-
"""Hazard-тесты Task 4.2a: отказ OpenCV в сборке item не роняет `produce()`.

Свойство: `cv2.error` на одном кадре (дебайер в ядре или ресайз в плагине) -> кадр отброшен
(`_dropped` растёт, `_frames` нет, `last_error` непустой, `produce()` вернул `[]`), следующий хороший кадр
проходит как обычно. Отказ подставляется один раз; потом работает настоящая функция.
Каркас (`make`, `_feed`, `_res`) — из слепых тестов `test_plugin_on_core.py`.
"""

from __future__ import annotations

import cv2
import pytest

from Services.hikvision_camera.plugin import plugin as hik_plugin_module
from Services.hikvision_camera.tests import test_plugin_on_core as core

pytestmark = pytest.mark.timeout(60)

RGB_24, _feed, _res = core.RGB_24, core._feed, core._res
make = core.make  # фикстура слепых тестов: pytest берёт её из пространства имён этого модуля


def _fail_once(original):
    """Обёртка: первый вызов бросает `cv2.error("boom")`, дальше — `original`."""
    calls = {"n": 0}

    def wrapper(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise cv2.error("boom")
        return original(*args, **kwargs)

    return wrapper


def _assert_dropped_then_recovers(plugin, bad_feed) -> None:
    assert bad_feed() == []
    assert plugin._dropped == 1
    assert plugin._frames == 0
    last_error = plugin.cmd_get_status({})["last_error"]
    assert isinstance(last_error, str)
    assert last_error != ""

    items = _feed(plugin, RGB_24, 4, 2, "rgb8", number=2)
    assert len(items) == 1
    assert items[0]["pixel_format"] == "bgr8"
    assert plugin._frames == 1
    assert plugin._dropped == 1


def test_отказ_cv2_в_дебайере_отбрасывает_кадр_и_плагин_не_залипает(make, monkeypatch):
    rig = make(_res(4, 2))
    monkeypatch.setattr(cv2, "cvtColor", _fail_once(cv2.cvtColor))
    _assert_dropped_then_recovers(rig.plugin, lambda: _feed(rig.plugin, bytes(8), 4, 2, "bayer_rg8"))


def test_отказ_cv2_в_ресайзе_плагина_отбрасывает_кадр_и_плагин_не_залипает(make, monkeypatch):
    rig = make(_res(4, 2))
    original = hik_plugin_module.FrameConverter.resize
    monkeypatch.setattr(hik_plugin_module.FrameConverter, "resize", _fail_once(original))
    _assert_dropped_then_recovers(rig.plugin, lambda: _feed(rig.plugin, RGB_24, 4, 2, "rgb8"))
