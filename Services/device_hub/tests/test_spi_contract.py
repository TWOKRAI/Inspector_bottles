"""Контракт-тесты ``Services/device_hub/spi.py`` (SPI.b1): ``OpSpec``, ``command_table``, каталоги, умолчания базы.

Purpose:
    Тесты автора к модулю контракта (``tests/contract/`` в репозитории нет — плоский файл, записано в докстринге
    ``spi.py``). Сторож полноты: для каждого драйвера имена ``OP_SPECS`` == ключи его таблицы операций; ключи v1 и ПЧ
    читаются из AST модулей драйверов (приватное имя таблицы в тесте не трогается — сторож
    ``test_no_private_driver_state.py``), v2 — публичная ``robot_driver_v2.ops.OPS``.
    Ожидания — литералы.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

import ast
import dataclasses
import sys
from pathlib import Path
from typing import Any

import pytest

from Services.device_hub import spi
from Services.device_hub.drivers.base import BaseDeviceDriver
from Services.device_hub.drivers.generic_modbus_driver import GenericModbusDriver
from Services.device_hub.drivers.hikvision_driver import HikvisionDriver
from Services.device_hub.drivers.robot_driver import RobotDriver
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.drivers.robot_driver_v2.ops import OPS as V2_OPS_TABLE
from Services.device_hub.drivers.vfd_driver import VfdDriver
from Services.device_hub.registry.entry import DeviceEntry

_HUB = Path(__file__).resolve().parents[1]
_TCP = {"type": "tcp", "host": "127.0.0.1", "port": 502, "unit_id": 1}

# Литерал исключений сторожа полноты «OP_SPECS == таблица операций»: пуст (на базе 27/27, 17/17, 5/5)
_OPS_EXCEPTIONS: dict[str, set[str]] = {"RobotDriver": set(), "RobotDriverV2": set(), "VfdDriver": set()}

# 21 команда с описанием каталога (T5.3c): 10 данных + 11 операций драйвера v2
_DESCRIBED = {
    "robot_param_get_all",
    "robot_point_list",
    "robot_point_save",
    "robot_point_delete",
    "robot_frame_list",
    "robot_frame_teach",
    "robot_program_list",
    "robot_program_get",
    "robot_program_save",
    "robot_program_delete",
    "robot_param_set",
    "robot_param_apply",
    "robot_stop",
    "robot_servo",
    "robot_do_set",
    "robot_jog_step",
    "robot_jog_hold",
    "robot_jog_release",
    "robot_point_capture",
    "robot_program_run",
    "robot_program_abort",
}


def _entry(kind: str, protocol: str = "", transport: dict | None = None, params: dict | None = None) -> DeviceEntry:
    return DeviceEntry(
        id=f"{kind}_1",
        name=kind,
        kind=kind,
        protocol=protocol,
        transport=transport if transport is not None else dict(_TCP),
        params=params or {},
    )


_BUILDERS: dict[type, Any] = {
    RobotDriver: lambda: RobotDriver(_entry("robot", "delta_universal3")),
    RobotDriverV2: lambda: RobotDriverV2(_entry("robot", "delta_v2"), None),
    VfdDriver: lambda: VfdDriver(_entry("vfd", "gd20_bridge", {"type": "bridge", "bridge": "robot_1"})),
    HikvisionDriver: lambda: HikvisionDriver(
        DeviceEntry(id="cam_1", name="Камера", kind="hikvision", params={"serial": "SN1"})
    ),
    GenericModbusDriver: lambda: GenericModbusDriver(_entry("generic_modbus", "gd20_bridge")),
}


def _ops_table_keys(module_file: str, class_name: str) -> set[str]:
    """Ключи словаря-таблицы операций класса (``_OPS = {...}`` в теле класса) — из AST модуля драйвера."""
    tree = ast.parse((_HUB / "drivers" / module_file).read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    for node in cls.body:
        target = (
            node.target
            if isinstance(node, ast.AnnAssign)
            else (node.targets[0] if isinstance(node, ast.Assign) else None)
        )
        if isinstance(target, ast.Name) and target.id == "_OPS" and isinstance(node.value, ast.Dict):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    raise AssertionError(f"таблица операций не найдена: {module_file}::{class_name}")


# --- OpSpec / OpSource ---


def test_opspec_defaults() -> None:
    spec = spi.OpSpec(name="x")
    assert (spec.description, spec.args_schema, spec.needs_link, spec.executor, spec.immediate) == (
        "",
        (),
        True,
        None,
        False,
    )


def test_opspec_is_frozen() -> None:
    spec = spi.OpSpec(name="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.name = "y"  # type: ignore[misc]


def test_opspec_executor_with_immediate_raises_each_alone_ok() -> None:
    with pytest.raises(ValueError):
        spi.OpSpec(name="x", executor="device_io", immediate=True)
    assert spi.OpSpec(name="x", executor="device_io").executor == "device_io"
    assert spi.OpSpec(name="x", immediate=True).immediate is True


def test_opsource_key_from_default() -> None:
    assert spi.OpSource(prefix="p", kind="k", route="driver", ops=()).key_from == "device_id"


# --- command_table ---


def test_command_table_default_sources_has_55_commands() -> None:
    table = spi.command_table(spi.DEFAULT_SOURCES)
    assert len(table) == 55
    assert sum(1 for name in table if name.startswith("robot_")) == 50
    assert {name for name in table if name.startswith("vfd_")} == {
        "vfd_run",
        "vfd_set_freq",
        "vfd_stop",
        "vfd_reset_fault",
        "vfd_get_status",
    }


def test_command_table_routes_and_links() -> None:
    table = spi.command_table(spi.DEFAULT_SOURCES)
    data = {name for name, (source, _spec) in table.items() if source.route == "data"}
    assert len(data) == 10
    no_link = {name for name, (_source, spec) in table.items() if spec.needs_link is False}
    assert no_link == data | {"robot_exchange_log_get", "robot_exchange_log_set"}


def test_command_table_shared_robot_ops_one_row_one_object() -> None:
    """``abort``, ``enqueue_job``, ``get_telemetry``, ``return_job`` — один объект в v1 и v2, одна строка таблицы."""
    v1 = {s.name: s for s in spi.ROBOT_V1_OPS}
    v2 = {s.name: s for s in spi.ROBOT_V2_OPS}
    shared = set(v1) & set(v2)
    assert shared == {"abort", "enqueue_job", "get_telemetry", "return_job"}
    assert all(v1[name] is v2[name] for name in shared)
    table = spi.command_table(spi.DEFAULT_SOURCES)
    assert table["robot_abort"][1] is v2["abort"]


def test_command_table_descriptions_are_the_21() -> None:
    table = spi.command_table(spi.DEFAULT_SOURCES)
    assert {name for name, (_source, spec) in table.items() if spec.description} == _DESCRIBED


def test_command_table_conflict_raises_equal_duplicate_kept_once() -> None:
    a = spi.OpSource(prefix="p", kind="k", route="driver", ops=(spi.OpSpec(name="x", immediate=True),))
    same = spi.OpSource(prefix="p", kind="k", route="driver", ops=(spi.OpSpec(name="x", immediate=True),))
    other_flag = spi.OpSource(prefix="p", kind="k", route="driver", ops=(spi.OpSpec(name="x"),))
    other_route = spi.OpSource(prefix="p", kind="k", route="data", ops=(spi.OpSpec(name="x", immediate=True),))
    table = spi.command_table([a, same])
    assert list(table) == ["p_x"] and table["p_x"][0] is a
    with pytest.raises(ValueError):
        spi.command_table([a, other_flag])
    with pytest.raises(ValueError):
        spi.command_table([a, other_route])


# --- каталоги против таблиц операций драйверов ---


@pytest.mark.parametrize(
    ("cls", "keys"),
    [
        pytest.param(RobotDriver, lambda: _ops_table_keys("robot_driver.py", "RobotDriver"), id="RobotDriver"),
        pytest.param(RobotDriverV2, lambda: set(V2_OPS_TABLE), id="RobotDriverV2"),
        pytest.param(VfdDriver, lambda: _ops_table_keys("vfd_driver.py", "VfdDriver"), id="VfdDriver"),
    ],
)
def test_op_specs_match_driver_ops_table(cls: type, keys: Any) -> None:
    names = [s.name for s in cls.OP_SPECS]
    assert len(names) == len(set(names)), "имя операции повторено в OP_SPECS"
    assert set(names) ^ keys() == _OPS_EXCEPTIONS[cls.__name__]


def test_op_specs_sizes() -> None:
    assert (len(RobotDriver.OP_SPECS), len(RobotDriverV2.OP_SPECS), len(VfdDriver.OP_SPECS)) == (27, 17, 5)
    assert len(spi.ROBOT_DATA_OPS) == 10
    assert HikvisionDriver.OP_SPECS == () and GenericModbusDriver.OP_SPECS == ()


# --- умолчания базы (D2) и соответствие Protocol ---

_BASE_DEFAULTS = {
    "OP_SPECS": (),
    "stop_aware": False,
    "transport": None,
    "disconnect_pending": False,
    "stop_unconfirmed": False,
    "stop_unconfirmed_text": None,
    "last_io": None,
}


@pytest.mark.parametrize(("name", "value"), list(_BASE_DEFAULTS.items()))
def test_base_defaults_are_plain_class_attributes(name: str, value: Any) -> None:
    raw = vars(BaseDeviceDriver)[name]
    assert not isinstance(raw, property)
    assert raw == value and type(raw) is type(value)


def test_base_request_disconnect_default() -> None:
    class Plain(BaseDeviceDriver):
        kind = "test"

    driver = Plain(_entry("robot", "delta_v2"))
    assert driver.request_disconnect() is None
    assert not hasattr(driver, "request_stop")  # стоп фазы 1 умолчания не получает (D2)


# Члены контракта, которых у драйвера ещё нет: умолчание ``set_degraded`` базы — SPI.b2 (вместе с ``-> bool`` и
# ``if set_degraded():`` в менеджере, чтобы поведение каскада моста не менялось между коммитами). b2 пустит литерал.
_NOT_YET: dict[str, list[str]] = {
    "RobotDriver": ["set_degraded"],
    "RobotDriverV2": ["set_degraded"],
    "VfdDriver": [],
    "HikvisionDriver": ["set_degraded"],
    "GenericModbusDriver": ["set_degraded"],
}


def _protocol_members(proto: type) -> set[str]:
    names = set(getattr(proto, "__annotations__", {}))
    names |= {n for n, v in vars(proto).items() if not n.startswith("_") and (callable(v) or isinstance(v, property))}
    return names


def test_protocol_member_list() -> None:
    assert _protocol_members(spi.DeviceDriver) == {
        "kind",
        "entry",
        "protocol",
        "desired_connected",
        "reconnect_exhausted",
        "OP_SPECS",
        "stop_aware",
        "transport",
        "disconnect_pending",
        "stop_unconfirmed",
        "stop_unconfirmed_text",
        "last_io",
        "is_connected",
        "stats",
        "connect",
        "disconnect",
        "tick",
        "call",
        "reset_reconnect",
        "request_disconnect",
        "set_degraded",
    }
    assert _protocol_members(spi.StopAwareDriver) == {"request_stop"}


@pytest.mark.parametrize("cls", list(_BUILDERS), ids=[c.__name__ for c in _BUILDERS])
def test_driver_conforms_to_device_driver(cls: type) -> None:
    """Каждый член ``DeviceDriver`` есть у экземпляра пяти фабрик; ``StopAwareDriver`` — ровно при ``stop_aware``."""
    driver = _BUILDERS[cls]()
    missing = sorted(n for n in _protocol_members(spi.DeviceDriver) if not hasattr(driver, n))
    assert missing == _NOT_YET[cls.__name__]
    assert callable(getattr(cls, "request_stop", None)) is bool(cls.stop_aware)


def test_spi_imports_only_stdlib() -> None:
    tree = ast.parse((_HUB / "spi.py").read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots, "недостижимо: импортов нет"
    assert roots - set(sys.stdlib_module_names) == set()
