# -*- coding: utf-8 -*-
# ruff: noqa: F811 — фикстура `make` из core_rig подключена импортом
"""Слепые приёмочные тесты Task 4.2a: плагин `HikvisionCameraPlugin` «на ядре» `CameraDevicePlugin`.

Написаны ДО кода плагина по критериям приёмки и по готовым интерфейсам (`Services/camera_device/*`,
`driver.py`, фейк MVS-камеры из `conftest.py`). Реализацию плагина (`plugin/plugin.py`, `plugin/registers.py`)
автор не читал. Проверяется наблюдаемое: item из `produce()`, журналы фейк-порта и фейк-камеры, ответы
команд, поля register'а. Ожидаемые значения — литералы из критериев приёмки.

Что собрано настоящим: плагин + `RegistersManager` + `PluginOrchestrator` (обработчик `register_update`) +
настоящие `DeviceSession`/`WorkerManager` + настоящий драйвер `mvs` (`driver.make_port`) над фейковым `MvCamera`.
Фейки: `MvCamera` (журнал `MV_CC_*`), `FakePort` ядра (там, где нужны capability `restart_regrab` и
`open_delay_s`) и менеджер процесса (`MockProcessServices`).
Кадры в плагин подаются мимо порта: `plugin._on_frame(RawFrame(...))`, затем `produce()`; один тест гонит кадр
через настоящий порт. Всё, что может зависнуть, идёт в daemon-потоке с дедлайном (`_bounded`).

Размер вывода: в тестах цвета задан `resolution_width/height`, равный размеру кадра: тогда ресайз — no-op при любом
правиле «когда ресайзить» (умолчание register'а 1440x1080 не равно размеру тестовых кадров 4x2 и 6x6).

Разрезан: каркас — `core_rig.py`, контракт — `test_plugin_on_core_contract.py`,
сеанс — `test_plugin_on_core_session.py`.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.health import get_or_create_health_state
from Services.hikvision_camera.sdk.constants import PixelType
from Services.hikvision_camera.tests.core_rig import RGB_24, _feed, _gated_cam, _res, _wait
from Services.hikvision_camera.tests.core_rig import make  # noqa: F401 — фикстура pytest

pytestmark = pytest.mark.timeout(60)


# ---------------------------------------------------------------------------------------------- #
# 1. Цвет: плагин отдаёт потребителям BGR
# ---------------------------------------------------------------------------------------------- #


def test_rgb8_отдаётся_как_bgr_с_переставленными_каналами(make):
    rig = make(_res(4, 2))
    items = _feed(rig.plugin, RGB_24, 4, 2, "rgb8")
    assert len(items) == 1
    frame = items[0]["frame"]
    assert frame.shape == (2, 4, 3)
    assert frame[0, 0].tolist() == [2, 1, 0]
    assert frame[1, 3].tolist() == [23, 22, 21]


def test_rgb8_метаданные_item(make):
    rig = make(_res(4, 2))
    item = _feed(rig.plugin, RGB_24, 4, 2, "rgb8")[0]
    assert item["pixel_format"] == "bgr8"
    assert item["source_format"] == "rgb8"
    assert item["frame"].flags.c_contiguous
    assert rig.plugin._frames == 1


def test_bgr8_проходит_без_перестановки(make):
    rig = make(_res(4, 2))
    item = _feed(rig.plugin, RGB_24, 4, 2, "bgr8")[0]
    assert item["frame"].shape == (2, 4, 3)
    assert item["frame"][0, 0].tolist() == [0, 1, 2]
    assert item["pixel_format"] == "bgr8"
    assert item["source_format"] == "bgr8"


def test_mono8_растягивается_в_три_одинаковых_канала(make):
    rig = make(_res(4, 2))
    item = _feed(rig.plugin, bytes(range(8)), 4, 2, "mono8")[0]
    assert item["frame"].shape == (2, 4, 3)
    assert item["frame"][1, 3].tolist() == [7, 7, 7]


# ---------------------------------------------------------------------------------------------- #
# 2. Дебайер: цвет по GenICam-паттерну (имена кодов OpenCV инвертированы — решает цвет сцены, не имя)
# ---------------------------------------------------------------------------------------------- #

# паттерн -> (строка, столбец) красного пикселя в мозаике 2x2 по GenICam (литерал из критериев приёмки)
RED_AT = {
    "bayer_rg8": (0, 0),
    "bayer_bg8": (1, 1),
    "bayer_gr8": (0, 1),
    "bayer_gb8": (1, 0),
}


@pytest.mark.parametrize("pixel_format", sorted(RED_AT))
def test_красная_сцена_bayer8_даёт_красный_bgr(make, pixel_format):
    row, col = RED_AT[pixel_format]
    mosaic = np.zeros((6, 6), dtype=np.uint8)
    mosaic[row::2, col::2] = 255
    rig = make(_res(6, 6))
    items = _feed(rig.plugin, mosaic.tobytes(), 6, 6, pixel_format)
    assert len(items) == 1
    frame = items[0]["frame"]
    assert frame.shape == (6, 6, 3)
    assert items[0]["pixel_format"] == "bgr8"
    interior = frame[2:4, 2:4].astype(int)
    np.testing.assert_allclose(interior, np.tile([0, 0, 255], (2, 2, 1)), atol=1)


def test_bayer_rg8_пиксель_2_2_красный_по_эталону_критериев(make):
    mosaic = np.zeros((6, 6), dtype=np.uint8)
    mosaic[0::2, 0::2] = 255
    rig = make(_res(6, 6))
    frame = _feed(rig.plugin, mosaic.tobytes(), 6, 6, "bayer_rg8")[0]["frame"]
    np.testing.assert_allclose(frame[2, 2].astype(int), [0, 0, 255], atol=1)


# ---------------------------------------------------------------------------------------------- #
# 3. Отброс неподдерживаемого / битого кадра
# ---------------------------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("pixel_format", "width", "height", "size"),
    [
        pytest.param("bayer_rg10", 6, 6, 36, id="bayer_rg10_буфер_36"),
        pytest.param("bayer_rg10", 6, 6, 72, id="bayer_rg10_буфер_72"),
        pytest.param("mono16", 4, 2, 16, id="mono16"),
    ],
)
def test_неподдерживаемый_формат_отбрасывается_без_исключения(make, pixel_format, width, height, size):
    rig = make(_res(width, height))
    plugin = rig.plugin
    errors_before = get_or_create_health_state(rig.services).snapshot()["errors"]
    items = _feed(plugin, bytes(size), width, height, pixel_format)
    assert items == []
    assert plugin._dropped == 1
    assert plugin._frames == 0
    last_error = plugin.cmd_get_status({})["last_error"]
    assert isinstance(last_error, str)
    assert last_error != ""
    assert get_or_create_health_state(rig.services).snapshot()["errors"] == errors_before


# ---------------------------------------------------------------------------------------------- #
# 7. Item после 130 кадров
# ---------------------------------------------------------------------------------------------- #


def test_item_после_130_кадров_номера_не_сворачиваются_и_поля_полны(make):
    cam = _gated_cam()  # шлюз закрыт: сеанс сам кадров не отдаёт, их подаёт тест
    rig = make(_res(4, 2), cam_cls=cam)
    assert rig.take()["status"] == "ok"
    plugin = rig.plugin
    items = []
    for number in range(1, 131):
        got = _feed(plugin, RGB_24, 4, 2, "bgr8", number)
        assert len(got) == 1
        items.append(got[0])

    assert [item["seq_id"] for item in items] == list(range(1, 131))
    last = items[-1]
    assert last["seq_id"] == 130
    assert last["frame_id"] == 130
    assert last["device_frame_num"] == 130
    assert last["camera_id"] == 3
    assert last["device_id"] == "SN1"
    assert isinstance(last["timestamp"], float)
    assert abs(last["ts"] - time.time()) < 5
    required = {
        "frame",
        "camera_id",
        "device_id",
        "seq_id",
        "frame_id",
        "timestamp",
        "ts",
        "pixel_format",
        "source_format",
    }
    assert required <= set(last)


def test_кадр_через_настоящий_порт_доходит_как_bgr_item(make):
    """Плагин + сеанс + драйвер mvs + фейк-камера целиком: rgb8 из `GetImageBuffer` -> item в BGR."""
    cam = _gated_cam(pixel_type=PixelType.RGB8, data=RGB_24, width=4, height=2)
    rig = make(_res(4, 2), cam_cls=cam)
    assert rig.take()["status"] == "ok"
    cam.gate.release()
    items: list[dict] = []
    _wait(lambda: items.extend(rig.plugin.produce()) or bool(items), "item из настоящего порта")
    item = items[0]
    assert item["frame"].shape == (2, 4, 3)
    assert item["frame"][0, 0].tolist() == [2, 1, 0]
    assert item["source_format"] == "rgb8"
    assert item["device_frame_num"] == 1
    assert item["device_id"] == "SN1"


# ---------------------------------------------------------------------------------------------- #
# 10. Выход и ресайз
# ---------------------------------------------------------------------------------------------- #


def test_letterbox_4x2_в_8x4_без_полей(make):
    rig = make({**_res(8, 4), "resize_mode": "letterbox"})
    frame = _feed(rig.plugin, RGB_24, 4, 2, "bgr8")[0]["frame"]
    assert frame.shape == (4, 8, 3)


def test_letterbox_4x2_в_4x4_чёрные_поля_сверху_и_снизу(make):
    rig = make({**_res(4, 4), "resize_mode": "letterbox"})
    frame = _feed(rig.plugin, RGB_24, 4, 2, "bgr8")[0]["frame"]
    assert frame.shape == (4, 4, 3)
    assert int(frame[0].sum()) == 0
    assert int(frame[1].sum()) == 66
    assert int(frame[3].sum()) == 0


def test_stretch_4x2_в_4x4_верхняя_строка_не_чёрная(make):
    rig = make({**_res(4, 4), "resize_mode": "stretch"})
    frame = _feed(rig.plugin, RGB_24, 4, 2, "bgr8")[0]["frame"]
    assert frame.shape == (4, 4, 3)
    assert int(frame[0].sum()) > 0
