"""Слепая приёмка SPI хаба, слой Services: каталоги операций и контракт драйвера (А10 б-г, А11, А12, А13, А16, А21).

Purpose:
    Строки ``plans/robot-protocol-v2/tasks/SPI.acceptance.md``, которые проверяются без плагина: таблица команд
    (``command_table``), флаги ``immediate`` / ``executor`` в каталогах ``*_OPS``, единый набор свойств всех драйверов,
    подкласс ``BaseDeviceDriver`` с присвоением публичных полей в ``__init__``, иерархия ошибок.
    Ожидаемые значения — литералы файла приёмки. Имена из ``Services.device_hub.spi`` импортируются ВНУТРИ тестов
    (``spi()``): модуля до реализации нет, и каждый тест докладывает свой красный, а не одну ошибку сбора.
    Приватных имён драйвера в файле нет (сторож ``test_no_private_driver_state.py``).

Public API:
    Только тесты ``test_a<N>_*``.

Stability: lite
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

import pytest

from Services.device_hub.drivers.base import BaseDeviceDriver
from Services.device_hub.drivers.generic_modbus_driver import GenericModbusDriver
from Services.device_hub.drivers.hikvision_driver import HikvisionDriver
from Services.device_hub.drivers.robot_driver import RobotDriver
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.drivers.vfd_driver import VfdDriver
from Services.device_hub.registry.entry import DeviceEntry

_TCP = {"type": "tcp", "host": "127.0.0.1", "port": 502, "unit_id": 1}

# 10 операций данных робота v2 (А12 «10 ROBOT_DATA_OPS»; имена — без префикса ``robot_``, как в А19)
_DATA_OPS = {
    "param_get_all",
    "point_list",
    "point_save",
    "point_delete",
    "frame_list",
    "frame_teach",
    "program_list",
    "program_get",
    "program_save",
    "program_delete",
}


def spi() -> ModuleType:
    """Модуль ``Services.device_hub.spi`` — импорт в теле теста."""
    return importlib.import_module("Services.device_hub.spi")


def _entry(kind: str, protocol: str = "", transport: dict | None = None, params: dict | None = None) -> DeviceEntry:
    return DeviceEntry(
        id=f"{kind}_1",
        name=kind,
        kind=kind,
        protocol=protocol,
        transport=transport if transport is not None else dict(_TCP),
        params=params or {},
    )


def _vfd() -> VfdDriver:
    return VfdDriver(_entry("vfd", "gd20_bridge", {"type": "bridge", "bridge": "robot_1"}))


def _hik() -> HikvisionDriver:
    return HikvisionDriver(DeviceEntry(id="cam_1", name="Камера", kind="hikvision", params={"serial": "SN1"}))


def _robot_v1() -> RobotDriver:
    return RobotDriver(_entry("robot", "delta_universal3"))


def _robot_v2() -> RobotDriverV2:
    return RobotDriverV2(_entry("robot", "delta_v2"), None)


def _generic() -> GenericModbusDriver:
    return GenericModbusDriver(_entry("generic_modbus", "gd20_bridge"))


# класс -> фабрика экземпляра «с записью реестра своего вида, без подключения» (А16)
_BUILDERS: dict[str, Any] = {
    "RobotDriver": _robot_v1,
    "RobotDriverV2": _robot_v2,
    "VfdDriver": _vfd,
    "HikvisionDriver": _hik,
    "GenericModbusDriver": _generic,
}
_CLASSES: dict[str, type] = {
    "RobotDriver": RobotDriver,
    "RobotDriverV2": RobotDriverV2,
    "VfdDriver": VfdDriver,
    "HikvisionDriver": HikvisionDriver,
    "GenericModbusDriver": GenericModbusDriver,
}


# --------------------------------------------------------------------------------------------------
# А10 (б, в, г) — ValueError таблицы команд и описания операции
# --------------------------------------------------------------------------------------------------


def _source(prefix: str, *ops: Any) -> Any:
    return spi().OpSource(prefix=prefix, kind="fake", route="driver", ops=tuple(ops))


def test_a10b_same_prefix_same_name_different_description_raises() -> None:
    """А10(б): два ``OpSource`` одного префикса, одноимённые ``OpSpec`` с разным ``description`` — ``ValueError``."""
    mod = spi()
    first = _source("fake", mod.OpSpec(name="x", description="Фейк: один"))
    second = _source("fake", mod.OpSpec(name="x", description="Фейк: два"))
    with pytest.raises(ValueError):
        mod.command_table([first, second])


def test_a10b_pair_distinct_names_under_one_prefix_are_accepted() -> None:
    """А10(б), пара: тот же префикс, но имена разные — таблица строится, проверка не режет префикс как таковой."""
    mod = spi()
    first = _source("fake", mod.OpSpec(name="x", description="Фейк: один"))
    second = _source("fake", mod.OpSpec(name="y", description="Фейк: два"))
    table = mod.command_table([first, second])
    assert "fake_x" in table and "fake_y" in table, table


def test_a10b_pair_identical_duplicate_is_accepted() -> None:
    """А10(б), пара (вывод из формулировки «разными по description»): совпадающая пара одноимённых не ошибка."""
    mod = spi()
    first = _source("fake", mod.OpSpec(name="x", description="Фейк: один"))
    second = _source("fake", mod.OpSpec(name="x", description="Фейк: один"))
    table = mod.command_table([first, second])
    assert "fake_x" in table, table


def test_a10c_same_prefix_same_name_different_needs_link_raises() -> None:
    """А10(в): то же, разные по ``needs_link`` — ``ValueError``."""
    mod = spi()
    first = _source("fake", mod.OpSpec(name="x", description="Фейк: икс", needs_link=True))
    second = _source("fake", mod.OpSpec(name="x", description="Фейк: икс", needs_link=False))
    with pytest.raises(ValueError):
        mod.command_table([first, second])


def test_a10d_executor_and_immediate_together_raises() -> None:
    """А10(г): ``OpSpec(name="x", executor="device_io", immediate=True)`` — ``ValueError`` (создание или таблица)."""
    mod = spi()
    with pytest.raises(ValueError):
        spec = mod.OpSpec(name="x", executor="device_io", immediate=True)
        mod.command_table([_source("fake", spec)])


def test_a10d_pair_each_flag_alone_is_accepted() -> None:
    """А10(г), пара: ``executor`` без ``immediate`` и ``immediate`` без ``executor`` по отдельности допустимы."""
    mod = spi()
    only_executor = mod.OpSpec(name="x", description="Фейк: x", executor="device_io")
    only_immediate = mod.OpSpec(name="y", description="Фейк: y", immediate=True)
    table = mod.command_table([_source("fake", only_executor, only_immediate)])
    assert "fake_x" in table and "fake_y" in table, table


# --------------------------------------------------------------------------------------------------
# А11 — драйверы без подключения: безопасные значения контракта
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("build", [_vfd, _hik], ids=["VfdDriver", "HikvisionDriver"])
@pytest.mark.parametrize(
    ("attr", "expected"),
    [
        ("disconnect_pending", False),
        ("stop_unconfirmed", False),
        ("stop_unconfirmed_text", None),
        ("transport", None),
        ("last_io", None),
    ],
)
def test_a11_fresh_driver_contract_values(build: Any, attr: str, expected: Any) -> None:
    """А11: ``VfdDriver`` / ``HikvisionDriver`` без подключения отдают литеральные значения свойств контракта."""
    driver = build()
    assert getattr(driver, attr) is expected


@pytest.mark.parametrize("build", [_vfd, _hik], ids=["VfdDriver", "HikvisionDriver"])
def test_a11_request_disconnect_returns_none_without_exception(build: Any) -> None:
    """А11: ``request_disconnect()`` без подключения — ``None``, без исключения."""
    driver = build()
    assert driver.request_disconnect() is None


def test_a11_hikvision_set_degraded_returns_false() -> None:
    """А11: ``HikvisionDriver.set_degraded()`` → ``False``."""
    assert _hik().set_degraded() is False


# --------------------------------------------------------------------------------------------------
# А12 — флаги immediate / executor в каталогах
# --------------------------------------------------------------------------------------------------

_IMMEDIATE = {
    "ROBOT_V2_OPS": {"stop", "abort", "jog_hold", "jog_release", "program_abort"},
    "ROBOT_V1_OPS": {"abort", "jog_abort", "draw_abort", "clear_queue", "set_servo"},
    "VFD_OPS": {"stop"},
    "ROBOT_DATA_OPS": set(),
}


@pytest.mark.parametrize("catalog", list(_IMMEDIATE))
def test_a12_immediate_exactly_the_listed_names(catalog: str) -> None:
    """А12: ``immediate=True`` ровно у перечисленных операций каждого каталога."""
    ops = getattr(spi(), catalog)
    assert len(list(ops)) > 0, f"каталог {catalog} пуст"
    assert {s.name for s in ops if s.immediate} == _IMMEDIATE[catalog]


def test_a12_executor_device_io_exactly_on_the_ten_data_ops() -> None:
    """А12 ``[d]``: ``executor == "device_io"`` у 10 операций ``ROBOT_DATA_OPS``; в прочих каталогах — ни у одной."""
    mod = spi()
    data = list(mod.ROBOT_DATA_OPS)
    assert {s.name for s in data} == _DATA_OPS
    assert [s.name for s in data if s.executor == "device_io"] == [s.name for s in data]
    for catalog in ("ROBOT_V1_OPS", "ROBOT_V2_OPS", "VFD_OPS"):
        assert [s.name for s in getattr(mod, catalog) if s.executor] == [], catalog


def test_a12_no_operation_has_both_executor_and_immediate() -> None:
    """А12: ни у одной операции нет одновременно ``executor`` и ``immediate`` (все каталоги и ``DEFAULT_SOURCES``)."""
    mod = spi()
    ops = [s for cat in ("ROBOT_V1_OPS", "ROBOT_V2_OPS", "VFD_OPS", "ROBOT_DATA_OPS") for s in getattr(mod, cat)]
    ops += [s for source in mod.DEFAULT_SOURCES for s in source.ops]
    assert len(ops) > 0
    assert [s.name for s in ops if s.executor and s.immediate] == []
    assert any(s.immediate for s in ops), "недостижимо: нет ни одной immediate-операции"


# --------------------------------------------------------------------------------------------------
# А13 — иерархия ошибок
# --------------------------------------------------------------------------------------------------


def test_a13_register_transport_unavailable_is_device_hub_error() -> None:
    """А13: ``issubclass(RegisterTransportUnavailable, DeviceHubError)``."""
    errors = importlib.import_module("Services.device_hub.errors")
    assert issubclass(errors.RegisterTransportUnavailable, errors.DeviceHubError)


# --------------------------------------------------------------------------------------------------
# А16 — единый набор свойств у пяти классов драйверов
# --------------------------------------------------------------------------------------------------

_CLASS_METHODS = ("connect", "disconnect", "tick", "call", "reset_reconnect", "request_disconnect", "set_degraded")
_CLASS_ATTRS = ("kind", "OP_SPECS", "stop_aware")
_INSTANCE_ATTRS = (
    "entry",
    "protocol",
    "desired_connected",
    "reconnect_exhausted",
    "transport",
    "disconnect_pending",
    "stop_unconfirmed",
    "stop_unconfirmed_text",
    "last_io",
    "is_connected",
    "stats",
)


@pytest.mark.parametrize("name", list(_CLASSES))
@pytest.mark.parametrize("attr", _CLASS_ATTRS)
def test_a16_class_has_attribute(name: str, attr: str) -> None:
    """А16: на КЛАССЕ есть ``kind``, ``OP_SPECS``, ``stop_aware``."""
    assert hasattr(_CLASSES[name], attr)


@pytest.mark.parametrize("name", list(_CLASSES))
@pytest.mark.parametrize("method", _CLASS_METHODS)
def test_a16_class_has_callable_method(name: str, method: str) -> None:
    """А16: на КЛАССЕ методы ``connect, disconnect, tick, call, reset_reconnect, request_disconnect, set_degraded``."""
    assert callable(getattr(_CLASSES[name], method, None))


@pytest.mark.parametrize("name", list(_CLASSES))
def test_a16_stop_aware_matches_request_stop(name: str) -> None:
    """А16: ``cls.stop_aware == hasattr(cls, "request_stop")``."""
    cls = _CLASSES[name]
    assert cls.stop_aware == hasattr(cls, "request_stop")


@pytest.mark.parametrize("name", list(_CLASSES))
def test_a16_stop_aware_true_only_for_robot_driver_v2(name: str) -> None:
    """А16: ``stop_aware`` истинно только у ``RobotDriverV2``."""
    assert bool(_CLASSES[name].stop_aware) is (name == "RobotDriverV2")


@pytest.mark.parametrize("name", list(_BUILDERS))
@pytest.mark.parametrize("attr", _INSTANCE_ATTRS)
def test_a16_instance_has_attribute(name: str, attr: str) -> None:
    """А16: на ЭКЗЕМПЛЯРЕ (запись реестра своего вида, без подключения) есть все свойства контракта."""
    instance = _BUILDERS[name]()
    assert hasattr(instance, attr)


# --------------------------------------------------------------------------------------------------
# А21 — подкласс BaseDeviceDriver присваивает публичные поля в __init__
# --------------------------------------------------------------------------------------------------


class _Marker:
    """Объект-метка: проверка идёт по тождеству, а не по равенству."""


def test_a21_subclass_assigning_contract_fields_in_init_is_created_and_returns_them() -> None:
    """А21: подкласс присваивает ``self.transport / disconnect_pending / stop_unconfirmed / last_io`` в ``__init__``."""
    marker = _Marker()
    last_io = {"op": "ping"}

    class Assigning(BaseDeviceDriver):
        kind = "test"

        def __init__(self, entry: DeviceEntry) -> None:
            super().__init__(entry)
            self.transport = marker
            self.disconnect_pending = True
            self.stop_unconfirmed = True
            self.last_io = last_io

    driver = Assigning(_entry("robot", "delta_v2"))
    assert driver.transport is marker
    assert driver.disconnect_pending is True
    assert driver.stop_unconfirmed is True
    assert driver.last_io is last_io


def test_a21_pair_subclass_without_assignment_keeps_base_defaults() -> None:
    """А21, пара: подкласс без присвоений отдаёт значения по умолчанию из А11 (``None`` / ``False``)."""

    class Plain(BaseDeviceDriver):
        kind = "test"

    driver = Plain(_entry("robot", "delta_v2"))
    assert driver.transport is None
    assert driver.disconnect_pending is False
    assert driver.stop_unconfirmed is False
    assert driver.last_io is None
