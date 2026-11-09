# -*- coding: utf-8 -*-
"""Task 1.4 (gui-graceful-close) — слепая приёмка ``pre_stop``: шаги перед системным стопом (REDS 1-7).

Написано ДО реализации по критериям приёмки брифа (DESIGN/FILES задачи не читались). ``interface.py`` нет —
тесты строятся на тексте REDS.

Контракт (из REDS): ключ конфига PM ``pre_stop`` — список ``{process, command, args, timeout_s}``. ``system.shutdown``
(graceful) при непустом списке отвечает сразу ``{"accepted": True, "mode": "graceful", "phase": "pre_stop"}``, шаги
идут по порядку на отдельном потоке, и только после них взводятся ``_system_stop_event`` и ``stop_event`` (фаза
``children``). ``force`` и внешний ``_system_stop_event`` отменяют шаги. Негодная запись схемы — ERROR
``pre_stop[<i>]: <поле> — <причина>`` и пропуск записи.

Обвязка (настоящие объекты): настоящий ``ProcessManagerProcess`` в процессе теста, настоящий ``SharedResourcesManager``,
настоящий роутер PM; команды — настоящие сообщения в системную очередь PM, ответы читает зонд ``Probe``.
Дети двух видов:
  * ``AckChild`` (``_pre_stop_ack_plugin``) — настоящий spawn-процесс (REDS 1(а));
  * «заглушка» ``add_stub`` — запись в реестре PM (двойник ОС-процесса с очередями SRM) + поток, читающий очередь
    ребёнка и отвечающий в очередь PM (``ack`` / ``nack`` / молчит). Шаги в реестре видят её как живого ребёнка.
Роутер PM обёрнут шпионом ``send``: он записывает все сообщения с командой ``t14.*`` (кому и когда) и умеет
подменять исход отправки для выбранного адресата (исключение / ``{"status": "error", ...}``).

Допущения (текста REDS не хватает, проверьте при реализации):
  * ``pre_stop`` лежит в словаре ``config`` PM (как ``shutdown_timeout``) — ``get_config("pre_stop")``;
  * запрос шага уходит через ``router_manager.send`` адресату ``targets=[<process>]`` с командой шага на верхнем
    уровне сообщения (допускается и конверт ``data.command``/``data.target``);
  * ход стопа читается ``pm._system_stop_snapshot()`` (поля ``phase``, ``pre_stop_step``, ``started_at``,
    ``deadline_at``) и командой ``supervision.status`` (``result.system_stop``);
  * WARNING/ERROR PM идут через ``pm._log_warning`` / ``pm._log_error``.
Ожидаемые значения — литералы из REDS. Всё, что может блокироваться, ждёт с дедлайном.

Стражи (зелёные и до правки): 1(б) и 1(в) по времени событий (но не по ``phase`` в ответе), страж «без стопа
принимаются» в 5.
"""

from __future__ import annotations

import contextlib
import multiprocessing
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager

from ..core.stop_budget import stop_budget
from ..process.process_manager_process import ProcessManagerProcess
from ._pre_stop_ack_plugin import ACK_CHILD_CLASS_PATH, STEP_PREFIX

SPAWN_DEADLINE_S = 90.0  # подъём PM (и spawn-ребёнка) на загруженной машине
REPLY_DEADLINE_S = 30.0  # потолок ожидания ответа: дальше «ответа нет» = упавший ассерт
EVENTS_DEADLINE_S = 15.0  # потолок ожидания взвода событий стопа
_QUEUES = {"system": {"maxsize": 100}, "data": {"maxsize": 50}}


# --------------------------------------------------------------------------- #
# Двойник ОС-процесса и конверты
# --------------------------------------------------------------------------- #


class _StopEvent:
    def __init__(self, proc: "FakeProc") -> None:
        self._proc = proc
        self._flag = threading.Event()

    def set(self) -> None:
        self._flag.set()
        self._proc.die(0)

    def is_set(self) -> bool:
        return self._flag.is_set()

    def clear(self) -> None:
        self._flag.clear()


class FakeProc:
    """Живой «ребёнок» реестра: умирает на сигнале стопа или ``terminate``/``kill``."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.pid = 41000 + abs(hash(name)) % 1000
        self.exitcode: int | None = None
        self.dead = threading.Event()
        self.stop_event = _StopEvent(self)

    def die(self, code: int) -> None:
        if not self.dead.is_set():
            self.exitcode = code
            self.dead.set()

    def is_alive(self) -> bool:
        return not self.dead.is_set()

    def join(self, timeout: float | None = None) -> None:
        self.dead.wait(timeout)

    def terminate(self) -> None:
        self.die(-15)

    def kill(self) -> None:
        self.die(-9)


class Sent:
    def __init__(self, rid: str, t_send: float) -> None:
        self.rid = rid
        self.t_send = t_send


class Reply:
    def __init__(self, message: dict, t_arrival: float) -> None:
        self.message = message
        self.t_arrival = t_arrival

    @property
    def result(self) -> dict:
        value = self.message.get("result")
        return value if isinstance(value, dict) else {}


def _step(process: str, command: str, timeout_s: Any, **args: Any) -> dict:
    return {"process": process, "command": command, "args": dict(args), "timeout_s": timeout_s}


def _child_entry(**extra: Any) -> dict:
    return {"class": ACK_CHILD_CLASS_PATH, "queues": {k: dict(v) for k, v in _QUEUES.items()}, **extra}


def _targets_of(msg: dict) -> list[str]:
    targets = msg.get("targets")
    if isinstance(targets, (list, tuple)) and targets:
        return [str(t) for t in targets]
    data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
    for key in ("target", "process_name", "process"):
        if isinstance(data.get(key), str):
            return [data[key]]
    for key in ("target", "receiver"):
        if isinstance(msg.get(key), str):
            return [msg[key]]
    return []


def _step_command_of(msg: dict) -> str | None:
    command = msg.get("command")
    if isinstance(command, str) and command.startswith(STEP_PREFIX):
        return command
    data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
    nested = data.get("command")
    if isinstance(nested, str) and nested.startswith(STEP_PREFIX):
        return nested
    return None


def _wait_until(predicate: Callable[[], bool], timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def _bounded(fn: Callable[[], Any], deadline_s: float) -> Any:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True, name="bounded")
    th.start()
    th.join(deadline_s)
    assert not th.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


# --------------------------------------------------------------------------- #
# Обвязка
# --------------------------------------------------------------------------- #


class Stub:
    """Заглушка-ребёнок в реестре PM: поток читает очередь ``system`` и по режиму отвечает PM."""

    def __init__(self, rig: "Rig", name: str, reply: str | None, delay_s: float) -> None:
        self.rig = rig
        self.name = name
        self.reply = reply  # None — молчит; "ack" | "nack"
        self.delay_s = delay_s
        self.received: list[tuple[float, str]] = []
        self.proc = FakeProc(name)
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"stub-{name}")
        self._thread.start()

    def _run(self) -> None:
        queue = self.rig.srm.queue_registry.get_queue(self.name, "system")
        while not self.rig.quit.is_set():
            try:
                message = queue.get(timeout=0.02)
            except Exception:  # noqa: BLE001 — пусто / закрытие очереди
                continue
            if not isinstance(message, dict):
                continue
            command = _step_command_of(message)
            if command is None:
                continue
            self.received.append((time.time(), command))
            data = message.get("data") if isinstance(message.get("data"), dict) else {}
            rid = message.get("request_id") or data.get("correlation_id")
            if self.reply is None or not rid:
                continue
            if self.delay_s:
                time.sleep(self.delay_s)
            ok = self.reply == "ack"
            self.rig.srm.queue_registry.get_queue(self.rig.pm.name, "system").put(
                {
                    "type": "response",
                    "command": "command.response",
                    "sender": self.name,
                    "targets": [self.rig.pm.name],
                    "queue_type": "system",
                    "request_id": rid,
                    "success": ok,
                    "result": {"success": ok},
                }
            )


class Rig:
    """Настоящий PM + зонд ответов + заглушки/spawn-дети + шпион роутера."""

    def __init__(
        self,
        *,
        pre_stop: Any = None,
        real_children: dict[str, dict] | None = None,
        graceful_s: float = 5.0,
    ) -> None:
        ctx = multiprocessing.get_context("spawn")
        self._ctx = ctx
        self.system_stop_event = ctx.Event()
        self.srm = SharedResourcesManager()
        assert self.srm.initialize()
        self.srm._system_stop_event = self.system_stop_event
        assert self.srm.register_process("Probe", {"queues": {"system": {"maxsize": 500}}})
        config: dict[str, Any] = {
            "stop_process_timeout": graceful_s,
            "shutdown_timeout": graceful_s,
            "processes_config": dict(real_children or {}),
        }
        if pre_stop is not None:
            config["pre_stop"] = pre_stop
        self.pm = ProcessManagerProcess(shared_resources=self.srm, config=config)
        self.pm.attach_stop_budget(stop_budget(graceful_s))
        self.quit = threading.Event()
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self._wrap_logs()
        self.stubs: dict[str, Stub] = {}
        self.sends: list[tuple[float, tuple[str, ...], str]] = []  # (monotonic, targets, команда шага)
        self.faults: dict[str, tuple[str, Any]] = {}
        self._replies: dict[str, Reply] = {}
        self._lock = threading.Lock()

    def _wrap_logs(self) -> None:
        for attr, sink in (("_log_warning", self.warnings), ("_log_error", self.errors)):
            original = getattr(self.pm, attr)

            def wrapper(message: Any, *args: Any, _o: Any = original, _s: list = sink, **kwargs: Any) -> Any:
                _s.append(str(message))
                return _o(message, *args, **kwargs)

            setattr(self.pm, attr, wrapper)

    # ---- подъём / уборка ------------------------------------------------- #

    def start(self) -> None:
        box: dict[str, Any] = {}

        def _init() -> None:
            try:
                box["ok"] = self.pm.initialize()
            except BaseException as exc:  # noqa: BLE001
                box["error"] = repr(exc)

        th = threading.Thread(target=_init, daemon=True, name="pm-initialize")
        th.start()
        th.join(SPAWN_DEADLINE_S)
        assert not th.is_alive(), f"PM.initialize() не вернулся за {SPAWN_DEADLINE_S} с"
        assert box.get("ok") is True, f"PM.initialize() не удался: {box}; ERROR: {self.errors}"
        from .conftest import wire_planner

        wire_planner(self.pm)
        self._install_send_spy()
        threading.Thread(target=self._collect, daemon=True, name="probe-collector").start()

    def _install_send_spy(self) -> None:
        router = self.pm.router_manager
        original = router.send

        def send(message: Any) -> Any:
            msg = message if isinstance(message, dict) else {}
            command = _step_command_of(msg)
            if command is not None:
                targets = tuple(_targets_of(msg))
                self.sends.append((time.monotonic(), targets, command))
                for target in targets:
                    fault = self.faults.get(target)
                    if fault is not None:
                        kind, payload = fault
                        if kind == "raise":
                            raise payload
                        return payload
            return original(message)

        router.send = send

    def close(self) -> None:
        self.quit.set()
        with contextlib.suppress(Exception):
            self.system_stop_event.set()
        for stub in self.stubs.values():
            stub.proc.die(-9)
        with contextlib.suppress(Exception):
            for proc in list(self.pm._process_registry.os_processes):
                if isinstance(proc, FakeProc):
                    continue
                if proc.is_alive():
                    proc.kill()
        th = threading.Thread(target=self.pm.shutdown, daemon=True, name="pm-shutdown")
        th.start()
        th.join(40.0)
        with contextlib.suppress(Exception):
            for proc in list(self.pm._process_registry.os_processes):
                if isinstance(proc, FakeProc):
                    continue
                if proc.is_alive():
                    proc.kill()
                proc.join(3.0)

    # ---- дети ------------------------------------------------------------ #

    def add_stub(self, name: str, reply: str | None = None, delay_s: float = 0.0) -> Stub:
        """Живой ребёнок реестра с очередями SRM; ``reply``: None (молчит) | ``ack`` | ``nack``."""
        assert self.srm.register_process(name, {"queues": {k: dict(v) for k, v in _QUEUES.items()}})
        stub = Stub(self, name, reply, delay_s)
        self._register_fake(stub.proc, ready=True)
        self.stubs[name] = stub
        return stub

    def add_unready(self, name: str) -> FakeProc:
        """Ребёнок в реестре, событие готовности есть и НЕ взведено."""
        proc = FakeProc(name)
        self._register_fake(proc, ready=False)
        return proc

    def _register_fake(self, proc: FakeProc, *, ready: bool) -> None:
        registry = self.pm._process_registry
        registry.add_process(proc)
        registry._stop_events[proc.name] = proc.stop_event
        event = self._ctx.Event()
        if ready:
            event.set()
        registry._ready_events[proc.name] = event
        self.pm._process_configs[proc.name] = {"class": "fake.Child"}

    def sends_to(self, name: str) -> list[str]:
        return [cmd for _t, targets, cmd in self.sends if name in targets]

    # ---- запросы и ответы ------------------------------------------------ #

    def send(self, command: str, data: dict | None = None) -> Sent:
        rid = uuid.uuid4().hex
        message = {
            "type": "command",
            "command": command,
            "data": dict(data or {}),
            "request_id": rid,
            "sender": "Probe",
        }
        t_send = time.monotonic()
        self.srm.queue_registry.get_queue(self.pm.name, "system").put(message)
        return Sent(rid, t_send)

    def _collect(self) -> None:
        queue = self.srm.queue_registry.get_queue("Probe", "system")
        while not self.quit.is_set():
            try:
                message = queue.get(timeout=0.02)
            except Exception:  # noqa: BLE001
                continue
            t_arrival = time.monotonic()
            rid = message.get("request_id") if isinstance(message, dict) else None
            if rid:
                with self._lock:
                    self._replies.setdefault(rid, Reply(message, t_arrival))

    def wait_reply(self, sent: Sent, timeout: float = REPLY_DEADLINE_S) -> Reply | None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self._lock:
                got = self._replies.get(sent.rid)
            if got is not None:
                return got
            time.sleep(0.003)
        with self._lock:
            return self._replies.get(sent.rid)

    def call(self, command: str, data: dict | None = None) -> tuple[float | None, Reply | None]:
        """Команда -> (секунды до ответа, ответ) или (None, None) по дедлайну."""
        sent = self.send(command, data)
        reply = self.wait_reply(sent)
        return (None if reply is None else reply.t_arrival - sent.t_send), reply

    # ---- наблюдение ------------------------------------------------------ #

    def events_set(self) -> bool:
        sys_ev = getattr(self.pm, "_system_stop_event", None)
        return bool(self.pm.stop_event.is_set() and sys_ev is not None and sys_ev.is_set())

    def snap(self) -> dict:
        return self.pm._system_stop_snapshot() or {}

    def status_system_stop(self) -> tuple[float | None, dict]:
        elapsed, reply = self.call("supervision.status")
        if reply is None:
            return None, {}
        result = reply.result
        if "system_stop" not in result and isinstance(result.get("result"), dict):
            result = result["result"]
        stop = result.get("system_stop")
        return elapsed, stop if isinstance(stop, dict) else {}


@contextlib.contextmanager
def running(**kwargs: Any) -> Iterator[Rig]:
    rig = Rig(**kwargs)
    try:
        rig.start()
        yield rig
    finally:
        rig.close()


def _within(value: float | None, low: float, high: float) -> bool:
    return value is not None and low <= value <= high


def _marker(path: Path) -> dict[str, float]:
    """Файл-метка ``AckChild``: вид события -> время первого появления."""
    out: dict[str, float] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] not in out:
            out[parts[0]] = float(parts[1])
    return out


# --------------------------------------------------------------------------- #
# REDS 1
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(300)
def test_events_order_by_mode(tmp_path: Path) -> None:
    """REDS 1: порядок событий по режимам.

    (а) graceful, настоящий spawn-ребёнок ``AckChild`` отвечает через 1,0 с (шаг ``timeout_s`` 5): ребёнок видит
    ``system_stop_event`` не раньше своего ответа и не позже ответ + 0,3 с (RED: сегодня событие сразу);
    (б) graceful, ``pre_stop`` пустой: события <= 0,05 с после ответа команды, ответ ``phase: "children"``;
    (в) ``force`` при непустом ``pre_stop``: запрос ребёнку не ушёл, события <= 0,05 с после ответа.
    Части (б), (в) по времени событий — стражи (зелёные до правки); ``phase`` в ответе (б) до правки нет.
    """
    problems: list[str] = []

    # (а)
    marker = tmp_path / "ack.marker"
    steps = [_step("ack", "t14.park", 5)]
    child = {"ack": _child_entry(ack_mode="ack", ack_delay_s=1.0, marker_path=str(marker))}
    with running(pre_stop=steps, real_children=child) as rig:
        proc = rig.pm._process_registry.get_process_by_name("ack")
        if proc is None or not proc.is_alive():
            problems.append("(а) spawn-ребёнок 'ack' не стартовал — стенд неисправен")
        _elapsed, reply = rig.call("system.shutdown")
        if reply is None:
            problems.append("(а) ответ system.shutdown не пришёл за дедлайн")
        seen = _wait_until(lambda: "event_seen" in _marker(marker), EVENTS_DEADLINE_S)
        marks = _marker(marker)
        if not seen:
            problems.append(f"(а) ребёнок не увидел system_stop_event за {EVENTS_DEADLINE_S} с; метки {marks}")
        elif "reply_sent" not in marks:
            problems.append(
                f"(а) ребёнок увидел system_stop_event, но шаг до него не дошёл (нет recv/reply_sent): метки {marks} "
                "— событие взведено без ожидания шагов"
            )
        else:
            t_reply, t_event = marks["reply_sent"], marks["event_seen"]
            if not (t_reply <= t_event <= t_reply + 0.3):
                problems.append(
                    f"(а) ребёнок увидел событие через {t_event - t_reply:+.3f} с от своего ответа, ожидалось [0; 0,3]"
                )

    # (б)
    with running(pre_stop=[]) as rig:
        elapsed, reply = rig.call("system.shutdown")
        if reply is None:
            problems.append("(б) ответ system.shutdown не пришёл за дедлайн")
        else:
            if not _wait_until(rig.events_set, 0.05):
                problems.append("(б) события (stop_event, _system_stop_event) не взведены за 0,05 с после ответа")
            if reply.result.get("phase") != "children":
                problems.append(f"(б) ответ без phase: 'children': {reply.result}")

    # (в)
    steps_c = [_step("stub", "t14.park", 5)]
    with running(pre_stop=steps_c) as rig:
        stub = rig.add_stub("stub")
        _elapsed, reply = rig.call("system.shutdown", {"mode": "force", "deadline_s": 1.0})
        if reply is None:
            problems.append("(в) ответ system.shutdown force не пришёл за дедлайн")
        else:
            if not _wait_until(rig.events_set, 0.05):
                problems.append("(в) force: события не взведены за 0,05 с после ответа")
            time.sleep(0.3)
            if rig.sends_to("stub") or stub.received:
                problems.append(f"(в) force: запрос шага ушёл ребёнку: sends={rig.sends}, принято={stub.received}")

    assert not problems, "; ".join(problems)


# --------------------------------------------------------------------------- #
# REDS 2
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(300)
def test_step_failures_warn_and_continue_finally_sets_events() -> None:
    """REDS 2: семь шагов по порядку; сбой шага — одна WARNING и дальше; сбой вне шага — ERROR; события — в ``finally``.

    1 без ответа (0,5); 2 ответ ``success: False``; 3 исключение в запросе (``ValueError``); 4 ребёнок есть, событие
    готовности НЕ взведено (0,5); 5 процесса нет в реестре; 6 синхронный отказ отправки; 7 исключение вне обработки
    шага (``_set_pre_stop_step`` бросает ``RuntimeError`` для ``"p7.t14.s7"``).
    """
    steps = [
        _step("p1", "t14.s1", 0.5, secret="ARGSECRET42"),
        _step("p2", "t14.s2", 5, secret="ARGSECRET42"),
        _step("p3", "t14.s3", 5, secret="ARGSECRET42"),
        _step("p4", "t14.s4", 0.5, secret="ARGSECRET42"),
        _step("p5", "t14.s5", 5, secret="ARGSECRET42"),
        _step("p6", "t14.s6", 5, secret="ARGSECRET42"),
        _step("p7", "t14.s7", 5, secret="ARGSECRET42"),
    ]
    expected_reasons = [
        ("p1", "t14.s1", "timeout"),
        ("p2", "t14.s2", "ошибка ответа"),
        ("p3", "t14.s3", "исключение ValueError"),
        ("p4", "t14.s4", "ребёнок не готов"),
        ("p5", "t14.s5", "процесс не найден"),
        ("p6", "t14.s6", "ошибка отправки"),
    ]
    problems: list[str] = []
    with running(pre_stop=steps) as rig:
        rig.add_stub("p1")  # молчит
        rig.add_stub("p2", reply="nack")
        rig.add_stub("p3")
        rig.add_unready("p4")
        # p5 — нет в реестре
        rig.add_stub("p6")
        rig.add_stub("p7", reply="ack")
        rig.faults["p3"] = ("raise", ValueError("t14 boom"))
        rig.faults["p6"] = ("return", {"status": "error", "reason": "t14 no route"})
        original = getattr(rig.pm, "_set_pre_stop_step", None)

        def set_step(*args: Any, **kwargs: Any) -> Any:
            if "p7.t14.s7" in args or "p7.t14.s7" in kwargs.values():
                raise RuntimeError("t14 outside step")
            return original(*args, **kwargs) if original is not None else None

        rig.pm._set_pre_stop_step = set_step

        _elapsed, reply = rig.call("system.shutdown")
        if reply is None:
            problems.append("ответ system.shutdown не пришёл за дедлайн")
        if not _wait_until(rig.events_set, EVENTS_DEADLINE_S):
            problems.append(f"события не взведены за {EVENTS_DEADLINE_S} с (finally не сработал)")
        warnings, errors = list(rig.warnings), list(rig.errors)

        last_pos = -1
        for process, command, reason in expected_reasons:
            key = f"{process}.{command}"
            lines = [(i, w) for i, w in enumerate(warnings) if f"шаг '{key}'" in w]
            if len(lines) != 1:
                problems.append(f"шаг {key}: WARNING {len(lines)} шт., ожидалась ровно одна; WARNING: {warnings}")
                continue
            pos, text = lines[0]
            if f"pre_stop: шаг '{key}' — {reason}" not in text:
                problems.append(f"шаг {key}: ожидалось 'pre_stop: шаг '{key}' — {reason}', получено {text!r}")
            if pos < last_pos:
                problems.append(f"шаг {key}: WARNING вне порядка шагов")
            last_pos = pos
        if any("ARGSECRET42" in line for line in warnings + errors):
            problems.append("в тексте WARNING/ERROR есть значения args")
        if rig.sends_to("p7"):
            problems.append(f"запрос 7-му ребёнку ушёл, хотя исключение вне обработки шага: {rig.sends_to('p7')}")
        runtime_errors = [e for e in errors if "RuntimeError" in e]
        if len(runtime_errors) != 1:
            problems.append(f"ERROR с RuntimeError: {len(runtime_errors)} шт., ожидалась ровно одна; ERROR: {errors}")

    assert not problems, "; ".join(problems)


# --------------------------------------------------------------------------- #
# REDS 3
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(240)
def test_force_or_external_event_cancels_running_step() -> None:
    """REDS 3: два шага (1-й ``timeout_s`` 30 без ответа). (а) ``force`` 1,0 через 0,5 с: ``accepted``/``escalated``;
    <= 0,1 с: ``stop_event``, ``phase == "children"``, ``pre_stop_step is None``; 2-му шагу запроса нет.
    (б) отдельный PM: ``_system_stop_event.set()`` извне через 0,5 с -> те же три признака <= 0,1 с; 2-му шагу нет."""
    steps = [_step("p1", "t14.s1", 30), _step("p2", "t14.s2", 5)]
    problems: list[str] = []

    def cancelled(rig: Rig) -> bool:
        snap = rig.snap()
        return rig.pm.stop_event.is_set() and snap.get("phase") == "children" and snap.get("pre_stop_step") is None

    # (а)
    with running(pre_stop=steps) as rig:
        p1, _p2 = rig.add_stub("p1"), rig.add_stub("p2")
        rig.send("system.shutdown")
        time.sleep(0.5)
        if not p1.received:
            problems.append("(а) предусловие: 1-й шаг не начался за 0,5 с (ребёнок не получил запрос)")
        t_force = time.monotonic()
        sent = rig.send("system.shutdown", {"mode": "force", "deadline_s": 1.0})
        reply = rig.wait_reply(sent)
        if reply is None:
            problems.append("(а) ответ force не пришёл за дедлайн")
        else:
            if reply.result.get("accepted") is not True or reply.result.get("escalated") is not True:
                problems.append(f"(а) ответ force: ожидалось accepted=True, escalated=True; получено {reply.result}")
            if not _wait_until(lambda: cancelled(rig), max(0.0, t_force + 0.1 - time.monotonic())):
                problems.append(f"(а) за 0,1 с после force: шаг не отменён; ход стопа {rig.snap()}")
        time.sleep(0.3)
        if rig.sends_to("p2"):
            problems.append(f"(а) 2-му шагу ушёл запрос после force: {rig.sends_to('p2')}")

    # (б)
    with running(pre_stop=steps) as rig:
        p1, _p2 = rig.add_stub("p1"), rig.add_stub("p2")
        rig.send("system.shutdown")
        time.sleep(0.5)
        if not p1.received:
            problems.append("(б) предусловие: 1-й шаг не начался за 0,5 с (ребёнок не получил запрос)")
        t_ext = time.monotonic()
        rig.pm._system_stop_event.set()
        if not _wait_until(lambda: cancelled(rig), 0.1):
            problems.append(
                f"(б) за 0,1 с после внешнего _system_stop_event: шаг не отменён ({time.monotonic() - t_ext:.3f} с); "
                f"ход стопа {rig.snap()}, stop_event={rig.pm.stop_event.is_set()}"
            )
        time.sleep(0.3)
        if rig.sends_to("p2"):
            problems.append(f"(б) 2-му шагу ушёл запрос после внешнего события: {rig.sends_to('p2')}")

    assert not problems, "; ".join(problems)


# --------------------------------------------------------------------------- #
# REDS 4
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(240)
def test_reply_immediate_status_responsive_second_graceful_rejected() -> None:
    """REDS 4: шаг 5 с. Ответ первого graceful <= 0,1 с и содержит ``{"accepted": True, "mode": "graceful", "phase":
    "pre_stop"}``; ``supervision.status`` во время шага <= 0,3 с, ``system_stop.phase == "pre_stop"``,
    ``pre_stop_step == "p1.t14.s1"``; второй graceful -> ``{"success": True, "accepted": False, "reason":
    "already_stopping", "phase": "pre_stop"}``, события не взведены, шаг идёт; после списка ``pre_stop_step`` -> null.
    """
    problems: list[str] = []
    with running(pre_stop=[_step("p1", "t14.s1", 5)]) as rig:
        rig.add_stub("p1")
        elapsed, reply = rig.call("system.shutdown")
        if reply is None:
            problems.append("ответ первого graceful не пришёл за дедлайн")
        else:
            first = {"accepted": True, "mode": "graceful", "phase": "pre_stop"}
            if not first.items() <= reply.result.items():
                problems.append(f"ответ первого graceful {reply.result} не содержит {first}")
            if elapsed is None or elapsed > 0.1:
                problems.append(f"ответ первого graceful через {elapsed} с, ожидалось <= 0,1")
        if not _wait_until(lambda: rig.snap().get("pre_stop_step") == "p1.t14.s1", 1.0):
            problems.append(f"шаг не начался: ход стопа {rig.snap()}")
        s_elapsed, stop = rig.status_system_stop()
        if s_elapsed is None or s_elapsed > 0.3:
            problems.append(f"supervision.status во время шага через {s_elapsed} с, ожидалось <= 0,3")
        if stop.get("phase") != "pre_stop" or stop.get("pre_stop_step") != "p1.t14.s1":
            problems.append(f"status.system_stop во время шага: {stop}")

        _e2, second = rig.call("system.shutdown")
        want = {"success": True, "accepted": False, "reason": "already_stopping", "phase": "pre_stop"}
        if second is None:
            problems.append("ответ второго graceful не пришёл за дедлайн")
        elif not want.items() <= second.result.items():
            problems.append(f"ответ второго graceful {second.result} не содержит {want}")
        if rig.pm.stop_event.is_set() or rig.pm._system_stop_event.is_set():
            problems.append("после второго graceful события взведены, а шаг ещё идёт")
        if rig.snap().get("pre_stop_step") != "p1.t14.s1":
            problems.append(f"после второго graceful шаг не идёт: {rig.snap()}")

        if not _wait_until(rig.events_set, 10.0):
            problems.append("события не взведены после конца списка шагов (timeout 5 с)")
        if rig.snap().get("pre_stop_step") is not None:
            problems.append(f"после списка pre_stop_step не null: {rig.snap()}")

    assert not problems, "; ".join(problems)


# --------------------------------------------------------------------------- #
# REDS 5
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(240)
def test_lifecycle_commands_rejected_during_pre_stop() -> None:
    """REDS 5: во время шага (ребёнок-заглушка записал приём команды) ``process.stop``, ``process.restart``,
    ``topology.apply`` получают ``{"success": False, "error": "system_stopping"}``; ребёнок жив. Страж: без стопа
    те же команды принимаются (ответ не ``system_stopping``)."""
    commands = [
        ("process.stop", {"process_name": "p1"}),
        ("process.restart", {"process_name": "p1"}),
        ("topology.apply", {"topology_dict": {"processes": []}}),
    ]
    problems: list[str] = []

    # Страж: без стопа команды принимаются.
    with running(pre_stop=[_step("p1", "t14.s1", 5)]) as rig:
        rig.add_stub("p1")
        for command, data in commands:
            _e, reply = rig.call(command, data)
            if reply is None:
                problems.append(f"страж: ответ {command} без стопа не пришёл за дедлайн")
            elif reply.result.get("error") == "system_stopping":
                problems.append(f"страж: {command} без стопа отклонён как system_stopping: {reply.result}")

    # Во время шага.
    with running(pre_stop=[_step("p1", "t14.s1", 5)]) as rig:
        stub = rig.add_stub("p1")
        rig.send("system.shutdown")
        if not _wait_until(lambda: bool(stub.received), 5.0):
            problems.append("начало шага не наблюдается: ребёнок-заглушка не получил команду шага")
        for command, data in commands:
            _e, reply = rig.call(command, data)
            if reply is None:
                problems.append(f"ответ {command} во время шага не пришёл за дедлайн")
            elif not ({"success": False, "error": "system_stopping"}.items() <= reply.result.items()):
                problems.append(f"{command} во время шага: ожидался отказ system_stopping, получено {reply.result}")
        if not stub.proc.is_alive():
            problems.append("ребёнок p1 не жив после отклонённых команд")

    assert not problems, "; ".join(problems)


# --------------------------------------------------------------------------- #
# REDS 6
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(240)
def test_deadline_at_pre_stop_then_children() -> None:
    """REDS 6: шаги 0,5 + 0,7 с (молчат, кончаются по таймауту). В ``pre_stop``: ``deadline_at - started_at ==
    1,2 +- 0,05``; после перехода ``deadline_at - time.time()`` в [4,8; 5,0] (pm_graceful 5,0), ``phase == "children"``;
    ``force`` 1,0 поверх шага: ``deadline_at`` = момент команды + 1,0 +- 0,05, переход его не сдвигает."""
    steps = [_step("p1", "t14.s1", 0.5), _step("p2", "t14.s2", 0.7)]
    problems: list[str] = []

    with running(pre_stop=steps) as rig:
        rig.add_stub("p1")
        rig.add_stub("p2")
        rig.send("system.shutdown")
        if not _wait_until(lambda: rig.snap().get("phase") == "pre_stop", 1.0):
            problems.append(f"фаза pre_stop не наблюдается: {rig.snap()}")
        snap = rig.snap()
        if snap.get("phase") == "pre_stop":
            span = snap["deadline_at"] - snap["started_at"]
            if abs(span - 1.2) > 0.05:
                problems.append(f"в pre_stop deadline_at - started_at = {span:.3f}, ожидалось 1,2 +- 0,05")
        if not _wait_until(lambda: rig.snap().get("phase") == "children", 5.0):
            problems.append(f"переход в children не случился за 5 с: {rig.snap()}")
        else:
            remaining = rig.snap()["deadline_at"] - time.time()
            if not 4.8 <= remaining <= 5.0:
                problems.append(f"после перехода deadline_at - now = {remaining:.3f}, ожидалось [4,8; 5,0]")

    with running(pre_stop=steps) as rig:
        rig.add_stub("p1")
        rig.add_stub("p2")
        rig.send("system.shutdown")
        time.sleep(0.2)
        t_before = time.time()
        sent = rig.send("system.shutdown", {"mode": "force", "deadline_s": 1.0})
        reply = rig.wait_reply(sent)
        t_after = time.time()
        if reply is None:
            problems.append("ответ force не пришёл за дедлайн")
        else:
            _wait_until(lambda: rig.snap().get("phase") == "children", 2.0)
            first = rig.snap().get("deadline_at")
            if not isinstance(first, float) or not (t_before + 0.95 <= first <= t_after + 1.05):
                problems.append(
                    f"force: deadline_at={first!r}, ожидалось [{t_before:.3f}; {t_after:.3f}] + 1,0 +- 0,05"
                )
            time.sleep(0.6)
            second = rig.snap().get("deadline_at")
            if second != first:
                problems.append(f"переход сдвинул deadline_at force: {first!r} -> {second!r}")

    assert not problems, "; ".join(problems)


# --------------------------------------------------------------------------- #
# REDS 7
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(300)
def test_pre_stop_schema_skips_invalid_with_error_without_value() -> None:
    """REDS 7: два PM. PM-А (схема): 13 записей, годны [1] и [12]; 11 ERROR по [0], [2]-[11], каждая начинается с
    ``pre_stop[<i>]: ``; [7] — ``pre_stop[7]: поле — неизвестный ключ``; во входных значениях в тексте ничего нет;
    исполнены [1], [12] — в этом порядке. PM-Б (потолок суммы): [60, 50, 20, 10] -> одна ERROR
    ``pre_stop[2]: timeout_s — сумма шагов больше 120 с``; исполнены [0], [1], [3]. Оба PM стартовали."""
    problems: list[str] = []

    def entry(i: int, timeout_s: Any = 5, **override: Any) -> Any:
        base = {"process": f"ok{i}", "command": f"t14.c{i}", "args": {}, "timeout_s": timeout_s}
        base.update(override)
        return base

    entries_a: list[Any] = [
        entry(0, 0),
        entry(1, 60),
        entry(2, 60.0001),
        entry(3, float("nan")),
        entry(4, True),
        entry(5, -1),
        entry(6, "5"),
        entry(7, 5, zz_extra="zz_extra"),
        entry(8, 5, process=""),
        entry(9, 5, command=""),
        entry(10, 5, args=[1]),
        7,
        entry(12, 0.5),
    ]
    with running(pre_stop=entries_a) as rig:
        for i in range(13):
            if i != 11:
                rig.add_stub(f"ok{i}", reply="ack")
        rig.send("system.shutdown")
        if not _wait_until(rig.events_set, EVENTS_DEADLINE_S):
            problems.append("PM-А: события не взведены за дедлайн")
        errors = [e for e in rig.errors if e.startswith("pre_stop[")]
        bad = [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        if len(errors) != 11:
            problems.append(f"PM-А: ERROR pre_stop[...] {len(errors)} шт., ожидалось 11; все ERROR: {rig.errors}")
        for i in bad:
            hits = [e for e in errors if e.startswith(f"pre_stop[{i}]: ")]
            if len(hits) != 1:
                problems.append(f"PM-А: для записи [{i}] ERROR {len(hits)} шт., ожидалась ровно одна")
        if not any(e.startswith("pre_stop[7]: поле — неизвестный ключ") for e in errors):
            problems.append(f"PM-А: нет 'pre_stop[7]: поле — неизвестный ключ'; ERROR: {errors}")
        for banned in ("60.0001", "nan", "True", '"5"', "[1]", "zz_extra"):
            if any(banned in e for e in errors):
                problems.append(f"PM-А: во входных значениях в тексте ERROR есть {banned!r}")
        executed = [cmd for _t, _targets, cmd in rig.sends]
        if executed != ["t14.c1", "t14.c12"]:
            problems.append(f"PM-А: исполнены {executed}, ожидалось ['t14.c1', 't14.c12']")

    entries_b = [entry(0, 60), entry(1, 50), entry(2, 20), entry(3, 10)]
    with running(pre_stop=entries_b) as rig:
        for i in range(4):
            rig.add_stub(f"ok{i}", reply="ack")
        rig.send("system.shutdown")
        if not _wait_until(rig.events_set, EVENTS_DEADLINE_S):
            problems.append("PM-Б: события не взведены за дедлайн")
        errors = [e for e in rig.errors if e.startswith("pre_stop[")]
        if len(errors) != 1 or "pre_stop[2]: timeout_s — сумма шагов больше 120 с" not in errors[0]:
            problems.append(f"PM-Б: ожидалась одна ERROR 'pre_stop[2]: timeout_s — сумма шагов больше 120 с': {errors}")
        executed = [cmd for _t, _targets, cmd in rig.sends]
        if executed != ["t14.c0", "t14.c1", "t14.c3"]:
            problems.append(f"PM-Б: исполнены {executed}, ожидалось ['t14.c0', 't14.c1', 't14.c3']")

    assert not problems, "; ".join(problems)
