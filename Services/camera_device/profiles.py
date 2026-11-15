# -*- coding: utf-8 -*-
"""Профили run/rest и проверка записи чтением (Task 2.2, Р6).

`ProfileRunner` пишет шаги плана (`Step` из 1.6) в порт и по чтению решает, записалось ли: результат берётся
из `get_param`, а не из кода SDK. Все вызовы порта идут из потока, который зовёт runner (поток-владелец сеанса).
Состояние (`ProfileState`) и его замок принадлежат сеансу; runner только заполняет его.

Классификация записи (`rc` — `exc.kind` или `None`; код SDK — только в лог):
  ok + чтение в допуске -> verified; ok + вне допуска -> «не подтвердилось чтением»;
  исключение + чтение = цель (H5) -> verified, WARNING «значение на месте»; исключение + чтение != цели -> `<kind>`;
  чтение бросило -> «чтение не удалось: <kind>»; без `read_back`: упала запись -> `<kind>`, прошла -> цель, не verified.
Значения рецепта не попадают в `param_errors`; допустимы только в INFO/WARNING-строке `apply ...`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

from .interface import DeviceIdentity, DevicePort, PortError
from .params import Step

NOT_CONFIRMED = "не подтвердилось чтением"
PARENT_SKIPPED = "пропущен: родитель не записан"


class ProfileState:
    """Состояние профилей сеанса: `params`, `params_status`, `param_errors`, счётчик отказов узлов; под `lock`."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.params: dict[str, Any] = {}
        self.status: dict[str, dict] = {}
        self.errors: dict[str, str] = {}
        self.node_errors = 0  # растёт на 1 за каждый узел, попавший в `errors`; не сбрасывается

    def reset(self) -> None:
        """Начало run каждого `start()`: профили и ошибки узлов сбрасываются, счётчик `node_errors` — нет."""
        with self.lock:
            self.params.clear()
            self.status.clear()
            self.errors.clear()


def within_tolerance(binding, inc: float | None, target: object, read: object) -> bool:
    """Чтение в допуске цели; ветвление по `Binding.vtype`, не по типу значения (Р6)."""
    vtype = binding.vtype
    if vtype in ("float", "int"):
        try:
            delta = abs(float(read) - float(target))  # type: ignore[arg-type]
            if vtype == "int":
                return delta < max(inc or 1, 1)
            return delta <= max(inc or 0, 1e-3 * abs(float(target)), binding.eps_abs)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
    return read == target  # enum сравнивается как имя элемента, bool/string — равенство


class ProfileRunner:
    """Запись планов run/rest; `apply_step`/`apply_plan` зовёт и живая правка (Task 2.4)."""

    def __init__(
        self,
        port: DevicePort,
        ident: DeviceIdentity | None,
        state: ProfileState,
        log: logging.Logger,
        on_timing: Callable[[str, float], None] | None = None,
        call: Callable[..., Any] | None = None,
    ) -> None:
        self._port = port
        self._ident = ident
        self._state = state
        self._log = log
        self._on_timing = on_timing
        # Вызов порта через сеанс (`DeviceSession._port_call`): его видит сторож, `open` попадает в on_timing.
        self._call = call or (lambda name, fn, *args: fn(*args))
        self._inc: dict[str, float | None] = {}  # шаг узла: один раз до первого `set_param` узла

    def apply_plan(self, steps: Sequence[Step]) -> None:
        """Шаги по порядку; отказ узла план не прерывает; потомки отказавшего родителя не пишутся (транзитивно)."""
        skipped: set[str] = set()
        for step in steps:
            if step.skip is not None:
                self._log.info("apply field=%s skip=%s", step.field, step.skip)
                continue
            with self._state.lock:
                blocked = set(self._state.errors) | skipped
            if step.parent is not None and step.parent in blocked:
                skipped.add(step.field)
                self._log.info("apply field=%s skip=%s", step.field, PARENT_SKIPPED)
                continue
            self.apply_step(step)

    def apply_step(self, step: Step) -> None:
        """Запись узла + чтение + классификация (результат — в `ProfileState`)."""
        field, binding, target = step.field, step.binding, step.value
        with self._state.lock:
            self._state.errors.pop(field, None)
            self._state.status.pop(field, None)
        t0 = time.perf_counter()
        inc = self._step_of(binding)
        write_error: PortError | None = None
        try:
            self._call("set_param", self._port.set_param, binding, target)
        except PortError as exc:
            write_error = exc
        rc = write_error.kind if write_error is not None else None
        read: object = None
        verified = False
        if "read_back" not in self._port.capabilities:
            if write_error is None:
                self._set(field, params=target, status={"verified": False, "rc": None})
            else:
                self._fail(field, rc, status={"verified": False, "rc": rc})
        else:
            try:
                read = self._call("get_param", self._port.get_param, binding)
            except PortError as exc:
                self._fail(field, f"чтение не удалось: {exc.kind}", status={"verified": False, "rc": rc})
            else:
                ok = within_tolerance(binding, inc, target, read)
                verified = ok
                if ok:
                    self._set(field, params=read, status={"verified": True, "rc": rc})
                    if write_error is not None:
                        self._log.warning(
                            "apply field=%s значение на месте: запись отказала (%s), чтение = цель", field, rc
                        )
                else:
                    self._fail(
                        field,
                        NOT_CONFIRMED if write_error is None else rc,
                        status={"verified": False, "rc": rc},
                        params=read,
                    )
        seconds = time.perf_counter() - t0
        code = "" if write_error is None or write_error.code is None else f"0x{write_error.code:08X}"
        self._log.info(
            "apply field=%s binding=%s value_written=%r value_read=%r rc=%s code=%s ms=%d verified=%s",
            field, binding.key, target, read, rc, code, int(seconds * 1000), verified,
        )  # fmt: skip
        if self._on_timing is not None:
            self._on_timing("apply", seconds)

    def run_rest(self, steps: Sequence[Step], restart_regrab: bool) -> bool:
        """Профиль rest после `stop_grabbing`. `True` — порт открыт, сеанс закрывает его сам; `False` — `open` упал.

        Без `restart_regrab` (ветка H1): `close`, `open`, rest; `close` после rest зовёт сеанс.
        """
        if not restart_regrab:
            try:
                self._call("close", self._port.close)
                self._call("open", self._port.open, self._ident)
            except Exception as exc:  # noqa: BLE001 — отказ reopen: итоговый close не зовётся, errors += 1
                self._log.warning("rest: reopen не удался: %s", type(exc).__name__)
                with self._state.lock:
                    self._state.node_errors += 1
                return False
        self.apply_plan(steps)
        return True

    # ------------------------------------------------------------------ #

    def _step_of(self, binding) -> float | None:
        """`inc` узла: один раз за жизнь runner, `describe_param` значение не читает."""
        if binding.key not in self._inc:
            info = None
            if "node_describe" in self._port.capabilities:
                try:
                    info = self._call("describe_param", self._port.describe_param, binding)
                except PortError:
                    info = None
            self._inc[binding.key] = None if info is None else info.inc
        return self._inc[binding.key]

    def _set(self, field: str, *, params: object, status: dict) -> None:
        with self._state.lock:
            self._state.params[field] = params
            self._state.status[field] = status

    def _fail(self, field: str, text: str | None, *, status: dict, params: object = None) -> None:
        with self._state.lock:
            self._state.errors[field] = text or "other"
            self._state.status[field] = status
            if params is not None:
                self._state.params[field] = params
            self._state.node_errors += 1
        self._log.warning("apply field=%s не записано: %s", field, text)
