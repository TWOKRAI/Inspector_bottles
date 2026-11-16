# -*- coding: utf-8 -*-
"""Честный фейк порта камеры (Task 1.5): ведёт себя как прибор, а не как заглушка.

`make_port(**opts)` строит порт с узлами по умолчанию, `from_recording(path, **opts)` — с узлами из записи
(формат — `plans/2026-10-18_camera-device-service/recording-schema.md`, `schema_version: 1`).

Опции: `neter_after_stop`, `applied_but_error` (`bool | frozenset[str]`), `busy_for_s`, `capabilities`;
для сеанса (Task 2.1): `open_delay_s`, `frame_period_s`, `get_frame_hang_s` (+ `arm_hang`), `get_frame_errors`,
`get_frame_script`, `read_offset` (умолчания сохраняют поведение 1.5).
Журнал вызовов `FakePort.calls` — список `(имя, args, threading.get_ident())`; пишется ДО проверок
состояния, поэтому отказ тоже виден. Фейковый `DeviceSdk` пишет в тот же журнал.
"""

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from Services.camera_device.interface import (
    Binding,
    DeviceIdentity,
    ParamInfo,
    PortError,
    RawFrame,
)

SCHEMA_VERSION = 1

# Шаги `get_frame_script`: `err` — `PortError("other","get_frame")`, `none` — `None` без ожидания,
# `frame` — кадр без ожидания.
SCRIPT_STEPS = frozenset({"err", "none", "frame"})

ALL_CAPABILITIES = frozenset({"read_back", "live_write", "node_describe", "software_trigger", "restart_regrab"})

# MV_CODEREADER_E_NETER — не опечатка: код сетевой ошибки записи после stop_grabbing.
CODE_NETER = 0x80020206
# Узел закрыт (access NA): прибор отказывает и в чтении, и в записи.
CODE_NODE_CLOSED = 0x80020106
# Запись запрещена в текущем состоянии (при захвате узел без live; RO).
CODE_NOT_WRITABLE = 0x80000106

# Закрытый узел открывается, когда родитель получает нужное значение
# (основание — tasks/6.2.result.md: «TriggerSource закрыт при TriggerMode=Off, период — при Source≠SelfTrigger»).
PARENTS: dict[str, tuple[str, str]] = {
    "TriggerSource": ("TriggerMode", "On"),
    "TriggerSelfTriggerPeriod": ("TriggerSource", "SelfTrigger"),
}

FRAME_WIDTH = 4
FRAME_HEIGHT = 2
FRAME_PIXEL_FORMAT = "mono8"
FAKE_SERIAL = "FAKE-0001"

# Таблица привязки полей register'а базового плагина к узлам фейка (`driver: fake`); вендор держит свою (`BINDINGS`).
FAKE_BINDINGS = {
    "trigger_mode": Binding("genicam", "TriggerMode", "enum"),
    "trigger_source": Binding("genicam", "TriggerSource", "enum"),
    "trigger_period_ms": Binding("genicam", "TriggerSelfTriggerPeriod", "int"),
    "exposure_time": Binding("genicam", "ExposureTime", "float"),
}


@dataclass
class _Node:
    """Узел фейка. `grab_access=None` — при захвате доступ такой же, как в `idle`."""

    key: str
    type: str | None
    min: float | int | None
    max: float | int | None
    inc: float | int | None
    entries: tuple[str, ...] | None
    value: object
    idle_access: str = "RW"
    grab_access: str | None = None
    closed_code: int = CODE_NODE_CLOSED
    read_rc: int = 0


def _default_nodes() -> dict[str, _Node]:
    """Узлы по умолчанию (литерал). Гибрид: диапазон ExposureTime 6.0..9999746.0 — запись MVS;
    закрытые узлы и PARENTS — запись mvcr и 6.2; значения (в т.ч. 10000.0) — решение лида,
    ни одной записи не соответствуют.

    В записи MVS `TriggerMode` при захвате остаётся RW; здесь он RO (запись при захвате отказана).
    """
    nodes = [
        _Node("TriggerMode", "enum", None, None, None, ("Off", "On"), "Off", grab_access="RO"),
        _Node(
            "TriggerSource",
            "enum",
            None,
            None,
            None,
            ("Line0", "Software", "SelfTrigger"),
            "Line0",
            idle_access="NA",
            grab_access="RO",
        ),
        _Node("TriggerSelfTriggerPeriod", "int", 32, 180000, 1, None, 300, idle_access="NA", grab_access="RO"),
        _Node("ExposureTime", "float", 6.0, 9999746.0, 1.0, None, 10000.0, grab_access="RW"),
    ]
    return {node.key: node for node in nodes}


def _parse_rc(rc: object) -> int:
    """`"0x80020106"` -> `int`; не строка или не разобрано -> 0."""
    if isinstance(rc, str):
        try:
            return int(rc, 16)
        except ValueError:
            return 0
    return 0


def _load_nodes(path: str | Path) -> dict[str, _Node]:
    """Загрузчик записи `schema_version: 1`. Проверка версии — первая операция."""
    with open(path, encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("recording: unsupported schema_version")
    if not isinstance(data.get("nodes"), dict):
        raise ValueError("recording: missing nodes")

    nodes: dict[str, _Node] = {}
    for key, raw in data["nodes"].items():
        idle = raw["idle"]
        grabbing = raw.get("grabbing")
        entries = raw.get("entries")
        rc = _parse_rc(idle.get("rc"))
        idle_access = idle["access"]
        nodes[key] = _Node(
            key=key,
            type=raw.get("type"),
            min=raw.get("min"),
            max=raw.get("max"),
            inc=raw.get("inc"),
            entries=tuple(entries) if entries is not None else None,
            value=idle.get("value"),
            idle_access=idle_access,
            grab_access=grabbing["access"] if grabbing is not None else None,
            closed_code=rc if (idle_access == "NA" and rc) else CODE_NODE_CLOSED,
            read_rc=rc if idle_access != "NA" else 0,
        )
    return nodes


class _FakeSdk:
    """Фейковый `DeviceSdk`: счётчик ссылок, один прибор `FAKE-0001`; пишет в журнал порта."""

    def __init__(self, journal) -> None:
        self._journal = journal
        self.refs = 0

    def acquire(self) -> None:
        self._journal("acquire", ())
        self.refs += 1

    def release(self) -> None:
        self._journal("release", ())
        if self.refs <= 0:
            raise RuntimeError("release without acquire")
        self.refs -= 1

    def enum_devices(self) -> list[DeviceIdentity]:
        self._journal("enum_devices", ())
        return [DeviceIdentity("serial", FAKE_SERIAL)]


class FakePort:
    """Фейк `DevicePort`. Значения узлов живут всё время жизни фейка: `close`/`open` их не сбрасывают."""

    def __init__(
        self,
        nodes: dict[str, _Node],
        *,
        neter_after_stop: bool = False,
        applied_but_error: bool | frozenset[str] = False,
        busy_for_s: float = 0.0,
        capabilities: frozenset[str] = ALL_CAPABILITIES,
        open_delay_s: float = 0.0,
        frame_period_s: float = 0.0,
        get_frame_hang_s: float = 0.0,
        get_frame_errors: int = 0,
        get_frame_script: tuple[str, ...] = (),
        read_offset: dict[str, float] | None = None,
    ) -> None:
        script = ("err",) * get_frame_errors + tuple(get_frame_script)
        unknown = sorted(set(script) - SCRIPT_STEPS)
        if unknown:
            raise ValueError(f"неизвестные шаги get_frame_script: {unknown}; допустимы {sorted(SCRIPT_STEPS)}")
        self.capabilities: frozenset[str] = frozenset(capabilities)
        self.calls: list[tuple[str, tuple, int]] = []
        self.sdk = _FakeSdk(self._record)
        self._nodes = nodes
        self._neter_after_stop = neter_after_stop
        self._applied_but_error = applied_but_error
        self._busy_for_s = busy_for_s
        self._created = time.monotonic()
        self._state = "closed"
        self._neter_active = False
        self._frame_num = 0
        self._open_delay_s = open_delay_s
        self._frame_period_s = frame_period_s
        self._hang_s = get_frame_hang_s  # разовое: `arm_hang` взводит повторно
        self._script = script
        self._read_offset = dict(read_offset or {})  # ключ — Binding.key; только чтение, узел не меняется
        self._get_frame_calls = 0  # вызовы `get_frame` с последнего `start_grabbing`
        self._next_frame_at = 0.0

    def arm_hang(self, seconds: float) -> None:
        """Взвести разовое зависание: следующий `get_frame` спит `seconds`, игнорируя `timeout_ms`."""
        self._hang_s = seconds

    # -- служебное -----------------------------------------------------------------------------

    def _record(self, name: str, args: tuple) -> None:
        self.calls.append((name, args, threading.get_ident()))

    def _require_opened(self, where: str) -> None:
        if self._state == "closed":
            raise PortError("closed", where)

    def _parent_open(self, key: str) -> bool:
        parent = PARENTS.get(key)
        if parent is None:
            return False
        parent_key, required = parent
        parent_node = self._nodes.get(parent_key)
        if parent_node is None or self._access(parent_node) == "NA":
            return False
        return parent_node.value == required

    def _access(self, node: _Node) -> str:
        """Текущий доступ узла: закрытый узел открывается родителем; при захвате — `grab_access`."""
        base = node.idle_access
        opened_by_parent = False
        if base == "NA":
            if not self._parent_open(node.key):
                return "NA"
            base = "RW"
            opened_by_parent = True
        if self._state == "grabbing" and node.grab_access is not None:
            # открытый родителем узел не закрывается снова записью «grabbing: NA» (она снята при закрытом родителе)
            if opened_by_parent and node.grab_access == "NA":
                return "RO"
            return node.grab_access
        return base

    def _node(self, b: Binding, where: str) -> _Node:
        node = self._nodes.get(b.key)
        if node is None:
            raise PortError("other", where)
        return node

    @staticmethod
    def _coerce(node: _Node, value: object) -> object:
        """float-узел с шагом: `floor(v / inc) * inc`; без шага значение хранится как есть."""
        if node.type == "float" and node.inc:
            return math.floor(float(value) / node.inc) * node.inc
        return value

    # -- DevicePort ----------------------------------------------------------------------------

    def open(self, ident: DeviceIdentity) -> None:
        self._record("open", (ident.kind, ident.value))
        if self._open_delay_s > 0:
            time.sleep(self._open_delay_s)
        if time.monotonic() - self._created < self._busy_for_s:
            raise PortError("busy", "open")
        if self._state != "closed":
            raise PortError("other", "open")
        self._state = "opened"

    def get_param(self, b: Binding) -> object:
        self._record("get_param", (b.key,))
        self._require_opened("get_param")
        node = self._node(b, "get_param")
        if self._access(node) == "NA":
            raise PortError("access", "get_param", node.closed_code)
        if node.value is None:
            raise PortError("other", "get_param", node.read_rc or None)
        offset = self._read_offset.get(b.key)
        if offset is not None and node.type in ("int", "float"):
            shifted = node.value + offset
            return int(shifted) if node.type == "int" else shifted
        return node.value

    def set_param(self, b: Binding, value: object) -> None:
        self._record("set_param", (b.key, value))
        self._require_opened("set_param")
        node = self._node(b, "set_param")
        access = self._access(node)
        if access == "NA":
            raise PortError("access", "set_param", node.closed_code)
        if access != "RW":
            raise PortError("access", "set_param", CODE_NOT_WRITABLE)
        if self._neter_active:
            raise PortError("network", "set_param", CODE_NETER)
        node.value = self._coerce(node, value)
        if self._applied_but_error is True or (
            isinstance(self._applied_but_error, frozenset) and b.key in self._applied_but_error
        ):
            raise PortError("network", "set_param")

    def describe_param(self, b: Binding) -> ParamInfo | None:
        self._record("describe_param", (b.key,))
        self._require_opened("describe_param")
        if "node_describe" not in self.capabilities:
            return None
        node = self._node(b, "describe_param")
        return ParamInfo(min=node.min, max=node.max, inc=node.inc, entries=node.entries, access=self._access(node))

    def execute(self, b: Binding) -> None:
        self._record("execute", (b.key,))
        self._require_opened("execute")
        if "software_trigger" not in self.capabilities:
            raise PortError("access", "execute")
        if b.key != "TriggerSoftware":
            raise PortError("other", "execute")

    def start_grabbing(self) -> None:
        self._record("start_grabbing", ())
        self._require_opened("start_grabbing")
        if self._state == "grabbing":
            return
        self._state = "grabbing"
        self._frame_num = 0
        self._get_frame_calls = 0
        self._next_frame_at = time.monotonic() + self._frame_period_s

    def get_frame(self, timeout_ms: int) -> RawFrame | None:
        self._record("get_frame", (timeout_ms,))
        if self._state != "grabbing":
            raise PortError("closed", "get_frame")
        hung = self._hang_s > 0
        if hung:
            seconds, self._hang_s = self._hang_s, 0.0
            time.sleep(seconds)  # зависание игнорирует timeout_ms; кадр отдаётся после него
        step = self._script[self._get_frame_calls] if self._get_frame_calls < len(self._script) else None
        self._get_frame_calls += 1
        if step == "err":
            raise PortError("other", "get_frame")
        if step == "none":
            return None
        if self._frame_period_s > 0 and step is None and not hung and not self._wait_next_frame(timeout_ms):
            return None
        self._frame_num += 1
        return RawFrame(
            data=bytearray(range(8)),
            width=FRAME_WIDTH,
            height=FRAME_HEIGHT,
            pixel_format=FRAME_PIXEL_FORMAT,
            frame_num=self._frame_num,
            extras={},
        )

    def _wait_next_frame(self, timeout_ms: int) -> bool:
        """Ждать срока следующего кадра, не дольше `timeout_ms`; `False` — срок не наступил (таймаут).

        Сон не прерывается `close`/`stop_grabbing`: так ведёт себя `get_frame` в SDK.
        """
        wait = min(timeout_ms / 1000.0, max(0.0, self._next_frame_at - time.monotonic()))
        if wait > 0:
            time.sleep(wait)
        now = time.monotonic()
        if now < self._next_frame_at:
            return False
        self._next_frame_at = now + self._frame_period_s
        return True

    def stop_grabbing(self) -> None:
        self._record("stop_grabbing", ())
        if self._state != "grabbing":
            return
        self._state = "opened"
        if self._neter_after_stop:
            self._neter_active = True

    def close(self) -> None:
        self._record("close", ())
        self._state = "closed"
        self._neter_active = False


def make_port(
    *,
    neter_after_stop: bool = False,
    applied_but_error: bool | frozenset[str] = False,
    busy_for_s: float = 0.0,
    capabilities: frozenset[str] = ALL_CAPABILITIES,
    open_delay_s: float = 0.0,
    frame_period_s: float = 0.0,
    get_frame_hang_s: float = 0.0,
    get_frame_errors: int = 0,
    get_frame_script: tuple[str, ...] = (),
    read_offset: dict[str, float] | None = None,
) -> FakePort:
    """Фейк с узлами по умолчанию."""
    return FakePort(
        _default_nodes(),
        neter_after_stop=neter_after_stop,
        applied_but_error=applied_but_error,
        busy_for_s=busy_for_s,
        capabilities=capabilities,
        open_delay_s=open_delay_s,
        frame_period_s=frame_period_s,
        get_frame_hang_s=get_frame_hang_s,
        get_frame_errors=get_frame_errors,
        get_frame_script=get_frame_script,
        read_offset=read_offset,
    )


def from_recording(
    path: str | Path,
    *,
    neter_after_stop: bool = False,
    applied_but_error: bool | frozenset[str] = False,
    busy_for_s: float = 0.0,
    capabilities: frozenset[str] = ALL_CAPABILITIES,
    open_delay_s: float = 0.0,
    frame_period_s: float = 0.0,
    get_frame_hang_s: float = 0.0,
    get_frame_errors: int = 0,
    get_frame_script: tuple[str, ...] = (),
    read_offset: dict[str, float] | None = None,
) -> FakePort:
    """Фейк с узлами из записи (относительный путь читается от cwd; тесты идут из корня репозитория)."""
    return FakePort(
        _load_nodes(path),
        neter_after_stop=neter_after_stop,
        applied_but_error=applied_but_error,
        busy_for_s=busy_for_s,
        capabilities=capabilities,
        open_delay_s=open_delay_s,
        frame_period_s=frame_period_s,
        get_frame_hang_s=get_frame_hang_s,
        get_frame_errors=get_frame_errors,
        get_frame_script=get_frame_script,
        read_offset=read_offset,
    )
