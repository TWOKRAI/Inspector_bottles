# -*- coding: utf-8 -*-
# ruff: noqa: F811 — фикстура `make` из core_rig подключена импортом
"""Слепые тесты приёмки Task 4.2d: автоусиление `gain_auto` и условная запись `gain` / `exposure_time` (Hikvision).

Критерии (1)-(6) задачи -> тесты:
  (1) привязка            -> test_bindings_gain_auto_это_genicam_GainAuto_enum
  (2) register            -> test_register_gain_auto_значения_ровно_off_once_continuous,
                             test_register_gain_auto_значение_вне_набора_отвергается,
                             test_register_gain_auto_умолчание_off,
                             test_register_gain_auto_объявлен_раньше_gain,
                             test_register_gain_enabled_if_только_при_gain_auto_off,
                             test_register_exposure_time_enabled_if_только_при_exposure_auto_off
  (3) план `build_plan`   -> test_план_gain_auto_off_пишет_gain_auto_и_gain_по_порядку,
                             test_план_gain_auto_not_off_пишет_родителя_и_пропускает_gain,
                             test_план_exposure_auto_off_пишет_exposure_time,
                             test_план_exposure_auto_not_off_пишет_родителя_и_пропускает_exposure_time
  (4) сеанс, take_device  -> test_take_device_при_автоусилении_и_автоэкспозиции_не_пишет_gain_и_exposure_time,
                             test_take_device_при_автоусилении_пишет_родителей_continuous
  (5) живая правка        -> test_живая_правка_gain_при_gain_auto_continuous_ничего_не_пишет_и_не_перезахватывает
  (6) повторный take      -> test_повторный_take_device_после_gain_auto_off_пишет_gain_из_register

Поле `gain_auto` до реализации в register'е нет: его читают внутри тестов (а не на импорте), поэтому файл
собирается и красные различимы по тексту отказа. Каркас — `core_rig.py` (настоящий плагин над фейк-камерой
`FakeMvCamera`, журнал `cam.journal`); фейк и записи не менялись.
"""

from __future__ import annotations

import time
from typing import get_args

import pytest
from pydantic import ValidationError

from Services.camera_device.interface import Binding
from Services.camera_device.params import build_plan
from Services.hikvision_camera import driver
from Services.hikvision_camera.plugin.registers import HikvisionCameraRegisters
from Services.hikvision_camera.tests.core_rig import _bounded, _gated_cam, _pos, _quiet, _wait
from Services.hikvision_camera.tests.core_rig import make  # noqa: F401 — фикстура pytest

pytestmark = pytest.mark.timeout(60)

# Записи узлов в журнале фейк-камеры: `(имя вызова, (узел, значение))`.
SET_CALLS = frozenset(
    {
        "MV_CC_SetEnumValue",
        "MV_CC_SetEnumValueByString",
        "MV_CC_SetIntValue",
        "MV_CC_SetFloatValue",
        "MV_CC_SetBoolValue",
    }
)
# Барьер «после»: полный перезахват Stop/Close/Open на фейке виден через ~1 с (см. задачу); берём с запасом.
BARRIER_S = 1.5


# ---------------------------------------------------------------------------------------------- #
# Помощники
# ---------------------------------------------------------------------------------------------- #


def _writes(log: list[tuple], node: str) -> list[tuple]:
    """Все записи узла `node` (любого типа) в журнале `_quiet`."""
    return [entry for entry in log if entry[0] in SET_CALLS and entry[1][0] == node]


def _values(**overrides) -> dict:
    """Значения register'а Hikvision (все умолчания) с подменами; `gain_auto` подставляется явно, поле не читается."""
    return {**HikvisionCameraRegisters().model_dump(), **overrides}


def _plan(**overrides):
    return build_plan(HikvisionCameraRegisters, _values(**overrides), driver.BINDINGS)


def _step(plan, name: str):
    """Шаг плана по имени поля; отсутствие — отказ теста с перечнем шагов (причина красного видна)."""
    for step in plan:
        if step.field == name:
            return step
    pytest.fail(f"в плане нет шага {name!r}: шаги {[s.field for s in plan]}")


def _stop_calls(log: list[tuple]) -> list[tuple]:
    return [entry for entry in log if entry[0] == "MV_CC_StopGrabbing"]


# ---------------------------------------------------------------------------------------------- #
# (1) Таблица привязки драйвера
# ---------------------------------------------------------------------------------------------- #


def test_bindings_gain_auto_это_genicam_GainAuto_enum():
    assert "gain_auto" in driver.BINDINGS, f"ключа gain_auto нет в BINDINGS: {sorted(driver.BINDINGS)}"
    assert driver.BINDINGS["gain_auto"] == Binding("genicam", "GainAuto", "enum")


# ---------------------------------------------------------------------------------------------- #
# (2) Register Hikvision
# ---------------------------------------------------------------------------------------------- #


def test_register_gain_auto_значения_ровно_off_once_continuous():
    assert "gain_auto" in HikvisionCameraRegisters.model_fields, "поля gain_auto нет в register'е"
    annotation = HikvisionCameraRegisters.model_fields["gain_auto"].annotation
    assert sorted(get_args(annotation)) == ["Continuous", "Off", "Once"]


def test_register_gain_auto_значение_вне_набора_отвергается():
    # `Auto` — не узел GenICam GainAuto; пока поля нет, pydantic молча проглатывает лишнее (тест красный до поля)
    with pytest.raises(ValidationError):
        HikvisionCameraRegisters(gain_auto="Auto")


def test_register_gain_auto_умолчание_off():
    assert "gain_auto" in HikvisionCameraRegisters.model_fields, "поля gain_auto нет в register'е"
    assert HikvisionCameraRegisters().gain_auto == "Off"


def test_register_gain_auto_объявлен_раньше_gain():
    names = list(HikvisionCameraRegisters.get_all_fields_meta())
    assert "gain_auto" in names, f"gain_auto нет среди полей: {names}"
    assert names.index("gain_auto") < names.index("gain")


def test_register_gain_enabled_if_только_при_gain_auto_off():
    meta = HikvisionCameraRegisters.get_all_fields_meta()["gain"]
    assert meta.enabled_if == {"gain_auto": ["Off"]}


def test_register_exposure_time_enabled_if_только_при_exposure_auto_off():
    meta = HikvisionCameraRegisters.get_all_fields_meta()["exposure_time"]
    assert meta.enabled_if == {"exposure_auto": ["Off"]}


# ---------------------------------------------------------------------------------------------- #
# (3) План записи: build_plan(HikvisionCameraRegisters, values, driver.BINDINGS)
# ---------------------------------------------------------------------------------------------- #


def test_план_gain_auto_off_пишет_gain_auto_и_gain_по_порядку():
    plan = _plan(gain_auto="Off", gain=5.0)
    parent, child = _step(plan, "gain_auto"), _step(plan, "gain")
    assert parent.skip is None
    assert child.skip is None
    assert child.value == 5.0
    assert [s.field for s in plan].index("gain_auto") < [s.field for s in plan].index("gain")


@pytest.mark.parametrize(
    ("mode", "reason"),
    [("Once", "не нужен: gain_auto=Once"), ("Continuous", "не нужен: gain_auto=Continuous")],
    ids=["Once", "Continuous"],
)
def test_план_gain_auto_not_off_пишет_родителя_и_пропускает_gain(mode, reason):
    plan = _plan(gain_auto=mode, gain=5.0)
    parent, child = _step(plan, "gain_auto"), _step(plan, "gain")
    assert parent.skip is None
    assert parent.value == mode
    assert child.skip == reason


def test_план_exposure_auto_off_пишет_exposure_time():
    plan = _plan(exposure_auto="Off", exposure_time=5000.0)
    assert _step(plan, "exposure_auto").skip is None
    assert _step(plan, "exposure_time").skip is None


@pytest.mark.parametrize(
    ("mode", "reason"),
    [("Once", "не нужен: exposure_auto=Once"), ("Continuous", "не нужен: exposure_auto=Continuous")],
    ids=["Once", "Continuous"],
)
def test_план_exposure_auto_not_off_пишет_родителя_и_пропускает_exposure_time(mode, reason):
    plan = _plan(exposure_auto=mode, exposure_time=5000.0)
    parent, child = _step(plan, "exposure_auto"), _step(plan, "exposure_time")
    assert parent.skip is None
    assert parent.value == mode
    assert child.skip == reason


# ---------------------------------------------------------------------------------------------- #
# (4) Сеанс на фейке: take_device при автоусилении и автоэкспозиции
# ---------------------------------------------------------------------------------------------- #

AUTO_CFG = {"gain_auto": "Continuous", "gain": 5.0, "exposure_auto": "Continuous"}


def test_take_device_при_автоусилении_и_автоэкспозиции_не_пишет_gain_и_exposure_time(make):
    cam = _gated_cam()
    rig = make(AUTO_CFG, cam_cls=cam)
    answer = rig.take()
    assert answer["status"] == "ok", answer
    log = _quiet(cam)
    # пустой param_errors один не отличает «до» от «после»: смотрим журнал записи фейк-камеры
    assert _writes(log, "Gain") == []
    assert _writes(log, "ExposureTime") == []
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}


def test_take_device_при_автоусилении_пишет_родителей_continuous(make):
    cam = _gated_cam()
    rig = make(AUTO_CFG, cam_cls=cam)
    assert rig.take()["status"] == "ok"
    log = _quiet(cam)
    # против «зелёного вхолостую»: журнал не пуст, родители реально записаны со значением из register'а
    i_gain_auto = _pos(log, ("MV_CC_SetEnumValueByString", ("GainAuto", "Continuous")))
    i_exposure_auto = _pos(log, ("MV_CC_SetEnumValueByString", ("ExposureAuto", "Continuous")))
    i_start = _pos(log, ("MV_CC_StartGrabbing", ()))
    assert i_gain_auto < i_start
    assert i_exposure_auto < i_start
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}


# ---------------------------------------------------------------------------------------------- #
# (5) Живая правка gain при gain_auto=Continuous
# ---------------------------------------------------------------------------------------------- #


def test_живая_правка_gain_при_gain_auto_continuous_ничего_не_пишет_и_не_перезахватывает(make):
    cam = _gated_cam()
    rig = make({"gain_auto": "Continuous", "gain": 5.0}, cam_cls=cam)
    assert rig.take()["status"] == "ok"
    base = len(_quiet(cam))

    result = rig.register_update("gain", 6.0)
    assert result["success"] is True, result
    # Отсутствие проверяем ПОСЛЕ барьера: на фейке перезахват Stop/Close/Open виден через ~1 с, сразу окно пусто.
    time.sleep(BARRIER_S)

    window = _quiet(cam)[base:]
    assert _writes(window, "Gain") == []
    assert _stop_calls(window) == []
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}

    # Контроль окна (не критерий приёмки): правка поля, которое перезахватывает, в этом же окне видна,
    # и полный план при перезахвате по-прежнему не пишет Gain. Без контроля пустое окно ничего не доказывало бы.
    control = rig.register_update("exposure_time", 7000.0)
    assert control["success"] is True, control
    _wait(
        lambda: ("MV_CC_StartGrabbing", ()) in _quiet(cam)[base:],
        "контроль: перезахват после правки exposure_time",
        10.0,
    )
    after = _quiet(cam)[base:]
    assert len(_stop_calls(after)) == 1, "контроль: перезахват не виден в журнале, окно слепое"
    _pos(after, ("MV_CC_SetFloatValue", ("ExposureTime", 7000.0)))
    assert _writes(after, "Gain") == []


# ---------------------------------------------------------------------------------------------- #
# (6) Повторный take_device после gain_auto Continuous -> Off (свой rig, не общий с пунктом 5)
# ---------------------------------------------------------------------------------------------- #


def test_повторный_take_device_после_gain_auto_off_пишет_gain_из_register(make):
    cam = _gated_cam()
    rig = make({"gain_auto": "Continuous", "gain": 6.0}, cam_cls=cam)
    assert rig.take()["status"] == "ok"
    assert _writes(_quiet(cam), "Gain") == [], "предусловие: при Continuous первый take Gain не пишет"

    # Повторный take_device при идущем захвате цикл не меняет, поэтому прибор сначала отпускаем.
    released = _bounded(lambda: rig.plugin.cmd_release_device({}))
    assert released["status"] == "ok", released
    changed = rig.register_update("gain_auto", "Off")
    assert changed["success"] is True, changed
    base = len(_quiet(cam))

    answer = rig.take()
    assert answer["status"] == "ok", answer

    window = _quiet(cam)[base:]
    i_parent = _pos(window, ("MV_CC_SetEnumValueByString", ("GainAuto", "Off")))
    i_gain = _pos(window, ("MV_CC_SetFloatValue", ("Gain", 6.0)), after=i_parent)
    i_start = _pos(window, ("MV_CC_StartGrabbing", ()))
    assert i_parent < i_gain < i_start
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}
