"""Слепые приёмочные тесты T5.3c, часть c2: правило ``P_WDG_TIMEOUT_MS = 0`` во всех путях и источник параметров.

Purpose:
    Закрепить по ``plans/robot-protocol-v2/tasks/T5.3c.reds.md`` (REDS 16, 17; DESIGN 8, 12 из ``T5.3c.md``):
    ``Services/robot_comm/robot_data.py`` отвергает ``P_WDG_TIMEOUT_MS = 0`` подклассом ``RobotWatchdogDisabled``
    во ВСЕХ путях (файл, ``overrides``, запись), публичная ``param_bounds`` знает продуктовую границу, а источник
    ``make_param_source`` отказывает плохим ``overrides`` и при существующем файле (RED 17 зелёный на старте).

Как устроено:
    * Не существующие на базе имена (``RobotWatchdogDisabled``, ``param_bounds``) берутся внутри тела теста:
      файл собирается, тест падает (FAILED), а не уходит в ERROR на сборке.
    * Ожидания — литералы брифа. Умолчания «полной карты» берутся из таблицы ``PARAMS`` (ВХОД теста, не ожидание);
      ревизия файла — из ``RobotDataStore.read`` (T5.2), не из кода под тестом.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS
from Services.robot_comm.store import RobotDataStore

TEXT_WDG_OFF = "Сторож робота нельзя выключить: P_WDG_TIMEOUT_MS = 0"
_WDG = "P_WDG_TIMEOUT_MS"


def _full_values(**override: int) -> dict[str, int]:
    """Полная карта умолчаний (все имена кроме ``P_CONFIG_EPOCH``) с заменами ``override``."""
    values = {name: int(PARAMS[pid]["default"]) for name, pid in PARAM_ID.items() if name != "P_CONFIG_EPOCH"}
    assert set(override) <= set(values)
    values.update(override)
    return values


def _write_file(store: RobotDataStore, device_id: str, epoch: int, values: dict[str, int]) -> str:
    """Записать ``params.yaml`` мимо ``save_params`` (формат брифа); вернуть ревизию файла."""
    body: dict[str, Any] = {"version": 1, "epoch": epoch, "values": values}
    return store.write(device_id, "params", body, base_rev=None)


def _doc(tmp: Path, device_id: str) -> Path:
    return tmp / device_id / "params.yaml"


# --------------------------------------------------------------------------------------------------
# RED 16
# --------------------------------------------------------------------------------------------------


def test_wdg_zero_refused_in_all_paths(tmp_path: Path) -> None:
    from Services.robot_comm import robot_data  # noqa: PLC0415
    from Services.robot_comm.errors import RobotDataInvalid, RobotWatchdogDisabled  # noqa: PLC0415

    store = RobotDataStore(tmp_path)

    # --- файл с нулём: load_params -> подкласс, rev - ревизия ЭТОГО файла ---
    file_rev = _write_file(store, "r1", 1, _full_values(**{_WDG: 0}))
    assert isinstance(file_rev, str)
    with pytest.raises(RobotWatchdogDisabled) as info:
        robot_data.load_params(store, "r1")
    assert str(info.value) == TEXT_WDG_OFF
    assert isinstance(info.value, RobotDataInvalid)
    assert info.value.rev == file_rev

    # --- overrides без файла ---
    with pytest.raises(RobotWatchdogDisabled) as info:
        robot_data.load_params(store, "r2", overrides={_WDG: 0})
    assert str(info.value) == TEXT_WDG_OFF
    assert info.value.rev is None

    # --- overrides при исправном файле ---
    _write_file(store, "r3", 1, _full_values(**{_WDG: 5000}))
    with pytest.raises(RobotWatchdogDisabled) as info:
        robot_data.load_params(store, "r3", overrides={_WDG: 0})
    assert str(info.value) == TEXT_WDG_OFF
    assert info.value.rev is None

    # --- save_params без файла: отказ, файл не создан ---
    with pytest.raises(RobotWatchdogDisabled) as info:
        robot_data.save_params(store, "r4", _full_values(**{_WDG: 0}), 1, base_rev=None)
    assert str(info.value) == TEXT_WDG_OFF
    assert info.value.rev is None
    assert not _doc(tmp_path, "r4").exists()

    # --- save_params при файле: отказ, байты прежние ---
    good_rev = _write_file(store, "r5", 1, _full_values(**{_WDG: 5000}))
    before = _doc(tmp_path, "r5").read_bytes()
    with pytest.raises(RobotWatchdogDisabled) as info:
        robot_data.save_params(store, "r5", _full_values(**{_WDG: 0}), 1, base_rev=good_rev)
    assert str(info.value) == TEXT_WDG_OFF
    assert _doc(tmp_path, "r5").read_bytes() == before

    # --- границы: 1 и 60000 проходят (и прочие нули полной карты тоже), param_bounds - литералы ---
    rev = None
    for raw in (1, 60000):
        rev = robot_data.save_params(store, "r6", _full_values(**{_WDG: raw}), 1, base_rev=rev)
        assert robot_data.load_params(store, "r6").values[_WDG] == raw

    assert robot_data.param_bounds(_WDG) == (1, 60000)
    assert robot_data.param_bounds("P_SPD_DEFAULT") == (1, 100)
    for name in ("P_NOPE", "P_CONFIG_EPOCH"):
        with pytest.raises(RobotDataInvalid) as info:
            robot_data.param_bounds(name)
        assert type(info.value) is RobotDataInvalid, name
        assert not isinstance(info.value, RobotWatchdogDisabled), name
        assert info.value.rev is None, name
    assert "param_bounds" in robot_data.__all__


# --------------------------------------------------------------------------------------------------
# RED 17 (зелёный на старте: на main уже так, robot_data.py:132)
# --------------------------------------------------------------------------------------------------


def test_make_param_source_bad_override_with_file(tmp_path: Path) -> None:
    from Services.robot_comm import robot_data  # noqa: PLC0415
    from Services.robot_comm.errors import RobotDataInvalid  # noqa: PLC0415

    store = RobotDataStore(tmp_path)
    _write_file(store, "r1", 9, _full_values(P_SPD_DEFAULT=55))
    bad = ({"P_NOPE": 1}, {"P_SPD_DEFAULT": 50.0}, {"P_SPD_DEFAULT": True})

    for where, device_id in (("файл есть", "r1"), ("файла нет", "r2")):
        for overrides in bad:
            source = robot_data.make_param_source(store, device_id, overrides=overrides)
            with pytest.raises(RobotDataInvalid) as info:
                source()
            assert info.value.rev is None, (where, overrides)

    # контроль, что источник вообще работает: допустимый override при файле не применяется (источник истины - файл)
    values, epoch = robot_data.make_param_source(store, "r1", overrides={"P_SPD_DEFAULT": 30}, epoch_default=3)()
    assert (values["P_SPD_DEFAULT"], epoch) == (55, 9)
    # ... а без файла применяется, метка - epoch_default
    values, epoch = robot_data.make_param_source(store, "r2", overrides={"P_SPD_DEFAULT": 30}, epoch_default=3)()
    assert (values["P_SPD_DEFAULT"], epoch) == (30, 3)
