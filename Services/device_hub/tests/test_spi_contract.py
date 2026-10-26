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

# 55 команд с описанием каталога (T5.3c + SPI.c2): 10 данных + 17 v2 + 27 v1 - 4 общих + 5 vfd
_DESCRIBED = {
    "robot_jog_hold",
    "robot_jog_release",
    "robot_get_telemetry",
    "robot_enqueue_job",
    "robot_return_job",
    "robot_abort",
    "robot_exchange_log_get",
    "robot_exchange_log_set",
    "robot_stop",
    "robot_servo",
    "robot_do_set",
    "robot_jog_step",
    "robot_point_capture",
    "robot_param_set",
    "robot_param_apply",
    "robot_program_run",
    "robot_program_abort",
    "robot_send_test_job",
    "robot_set_mode",
    "robot_jog",
    "robot_jog_abort",
    "robot_set_servo",
    "robot_set_robot_config",
    "robot_get_robot_config",
    "robot_read_echo",
    "robot_set_manual_mode",
    "robot_clear_queue",
    "robot_set_encoder_offset",
    "robot_toolchange",
    "robot_draw_polyline",
    "robot_draw_circle",
    "robot_draw_square",
    "robot_draw_set_pen",
    "robot_draw_set_speed",
    "robot_draw_set_travel",
    "robot_draw_set_accel",
    "robot_draw_set_pass_size",
    "robot_draw_set_overlap",
    "robot_draw_abort",
    "robot_draw_progress",
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
    "vfd_run",
    "vfd_set_freq",
    "vfd_stop",
    "vfd_reset_fault",
    "vfd_get_status",
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


def test_command_table_descriptions_are_the_55() -> None:
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


def test_set_degraded_default_and_vfd() -> None:
    """Умолчание базы — False без ``disconnect()``; ``VfdDriver`` деградирует (True)."""
    disconnects: list[int] = []

    class Plain(BaseDeviceDriver):
        kind = "test"

        def disconnect(self) -> None:
            disconnects.append(1)

    assert Plain(_entry("robot", "delta_v2")).set_degraded() is False
    assert disconnects == []
    assert _BUILDERS[VfdDriver]().set_degraded() is True


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
    assert missing == []
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


# --- SPI.b2: менеджер и плагин зовут контракт драйвера напрямую — 0 getattr / hasattr к драйверу ---
#
# Получатель определяется потоком данных внутри функции (и её вложенных функций), а не списком имён переменных:
# имя, связанное с вызовом get_driver / _get_driver / _get_connected_driver / _get_or_create_driver; переменные цикла
# (и включений) по ``_drivers`` или его снимку (``drivers = list(self._drivers.items())``); элемент ``_drivers[...]``;
# параметр с аннотацией ``DeviceDriver``; параметр локальной функции, куда передан получатель
# (``make_tick_fn(did, drv)``).

_DRIVER_GETTERS = frozenset({"get_driver", "_get_driver", "_get_connected_driver", "_get_or_create_driver"})
_DUCK_FUNCS = frozenset({"getattr", "hasattr"})
_DUCK_FILES = ("Services/device_hub/manager.py", "Plugins/hub/device_hub/plugin.py")
_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            return func.attr
        if isinstance(func, ast.Name):
            return func.id
    return None


def _is_drivers_ref(node: ast.AST) -> bool:
    """``x._drivers`` и вызовы над ним (``.items()`` / ``.values()`` / ``.copy()``, ``list(...)``, ``dict(...)``)."""
    if isinstance(node, ast.Attribute) and node.attr == "_drivers":
        return True
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in ("items", "values", "copy") and _is_drivers_ref(func.value):
            return True
        if isinstance(func, ast.Name) and func.id in ("list", "dict", "tuple", "sorted") and node.args:
            return _is_drivers_ref(node.args[0])
    return False


def _own_nodes(func: ast.AST) -> list[ast.AST]:
    """Узлы функции без тел вложенных функций (у них своя область; сами вложенные узлы — в списке)."""
    out: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        out.append(node)
        if not isinstance(node, _FUNC_NODES):
            stack.extend(ast.iter_child_nodes(node))
    return out


def _params(func: ast.AST) -> list[ast.arg]:
    args = func.args
    return [*args.posonlyargs, *args.args, *args.kwonlyargs]


def _duck_typing_sites(source: str) -> list[int]:
    """Строки ``getattr`` / ``hasattr``, чей первый аргумент — драйвер по потоку данных (до неподвижной точки)."""
    tree = ast.parse(source)
    funcs = [n for n in ast.walk(tree) if isinstance(n, _FUNC_NODES)]
    parent: dict[ast.AST, ast.AST] = {}
    for f in funcs:
        for node in _own_nodes(f):
            if isinstance(node, _FUNC_NODES):
                parent[node] = f
    local_defs = {n.name: n for n in funcs if not isinstance(n, ast.Lambda)}
    drivers: dict[ast.AST, set[str]] = {f: set() for f in funcs}
    containers: dict[ast.AST, set[str]] = {f: set() for f in funcs}
    for f in funcs:
        for arg in _params(f):
            if arg.annotation is not None and "DeviceDriver" in ast.unparse(arg.annotation):
                drivers[f].add(arg.arg)

    def visible(f: ast.AST | None, table: dict[ast.AST, set[str]]) -> set[str]:
        names: set[str] = set()
        while f is not None:
            names |= table[f]
            f = parent.get(f)
        return names

    def is_container(expr: ast.AST, f: ast.AST) -> bool:
        return _is_drivers_ref(expr) or (isinstance(expr, ast.Name) and expr.id in visible(f, containers))

    def is_driver(expr: ast.AST, f: ast.AST) -> bool:
        if isinstance(expr, ast.Name):
            return expr.id in visible(f, drivers)
        if _call_name(expr) in _DRIVER_GETTERS:
            return True
        return isinstance(expr, ast.Subscript) and is_container(expr.value, f)

    def add(table: dict[ast.AST, set[str]], f: ast.AST, name: str) -> bool:
        if name in table[f]:
            return False
        table[f].add(name)
        return True

    changed = True
    while changed:
        changed = False
        for f in funcs:
            for node in _own_nodes(f):
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name) and is_driver(node.value, f):
                            changed |= add(drivers, f, target.id)
                        elif isinstance(target, ast.Name) and is_container(node.value, f):
                            changed |= add(containers, f, target.id)
                elif isinstance(node, (ast.For, ast.comprehension)) and is_container(node.iter, f):
                    target = node.target
                    elt = target.elts[-1] if isinstance(target, ast.Tuple) and target.elts else target
                    if isinstance(elt, ast.Name):
                        changed |= add(drivers, f, elt.id)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in local_defs:
                    callee = local_defs[node.func.id]
                    params = _params(callee)
                    for i, arg in enumerate(node.args):
                        if i < len(params) and is_driver(arg, f):
                            changed |= add(drivers, callee, params[i].arg)
    return sorted(
        node.lineno
        for f in funcs
        for node in _own_nodes(f)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _DUCK_FUNCS
        and node.args
        and is_driver(node.args[0], f)
    )


def test_no_duck_typing_on_drivers() -> None:
    """D3: в менеджере и плагине ``getattr`` / ``hasattr`` к драйверу — 0 (на базе SPI — 13 узлов)."""
    root = _HUB.parents[1]
    found = {rel: _duck_typing_sites((root / rel).read_text(encoding="utf-8")) for rel in _DUCK_FILES}
    assert found == {rel: [] for rel in _DUCK_FILES}


_CLOSURE_SRC = """
def f(self):
    def mk(did, z):
        def run():
            return getattr(z, "x")
        return run
    q = self.get_driver(1)
    return mk(1, q)
"""


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("def f(self):\n    d = self.get_driver(1)\n    return getattr(d, 'x', None)\n", 1, id="getter"),
        pytest.param("def f(self):\n    return hasattr(self._get_connected_driver(1), 'x')\n", 1, id="inline"),
        pytest.param(
            "def f(self):\n    ds = list(self._drivers.items())\n    return [getattr(v, 'x') for k, v in ds]\n",
            1,
            id="snapshot_comprehension",
        ),
        pytest.param("def f(self):\n    for v in self._drivers.values():\n        hasattr(v, 'x')\n", 1, id="loop"),
        pytest.param("def f(self):\n    return getattr(self._drivers['a'], 'x')\n", 1, id="subscript"),
        pytest.param("def f(drv: DeviceDriver):\n    return getattr(drv, 'x')\n", 1, id="annotated"),
        pytest.param(_CLOSURE_SRC, 1, id="closure_renamed"),
        pytest.param("def f(self, ctx):\n    return getattr(ctx.worker_manager, 'x', None)\n", 0, id="not_driver"),
    ],
)
def test_duck_typing_guard_sees_data_flow(source: str, expected: int) -> None:
    """Сам сторож: получатель — по потоку данных; переименование переменной его не обходит."""
    assert len(_duck_typing_sites(source)) == expected


# --- SPI.g: затвор переподключения в базе ---


def test_reconnect_throttle_intervals_per_class_are_literals() -> None:
    assert BaseDeviceDriver.RECONNECT_THROTTLE_S == 2.0
    assert RobotDriver.RECONNECT_THROTTLE_S == 2.0
    assert RobotDriverV2.RECONNECT_THROTTLE_S == 2.0
    assert VfdDriver.RECONNECT_THROTTLE_S == 3.0


def test_reconnect_due_gate_opens_once_per_interval() -> None:
    """Затвор базы: метка 0.0 -> закрыт до 2 с; открылся — метка «сейчас», следующий вызов закрыт до +2 с."""
    now = [0.0]

    class _Gate(BaseDeviceDriver):
        kind = "gate"

        def due(self) -> bool:
            return self._reconnect_due()

    drv = _Gate(_entry("gate"), clock=lambda: now[0])
    seen = []
    for t in (0.0, 1.9, 2.0, 3.9, 4.0, 4.5, 6.0):
        now[0] = t
        seen.append(drv.due())
    assert seen == [False, False, True, False, True, False, True]
