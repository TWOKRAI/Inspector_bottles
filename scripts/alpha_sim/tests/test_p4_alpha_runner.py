"""P4 скрипт α, прогон ``run(...)`` на фейках: REDS 9-11 (plans/word-layout/tasks/P4.md, Д1-Д3).

Фейки — по таблице форм Д3. Время — фейковые часы (``sleep`` двигает их); ``run`` идёт в daemon-потоке
с ``join(timeout=30)``. ``scripts.alpha_sim.run_alpha`` импортируется внутри тестов.

Что фейк делает сверх таблицы Д3 (предположения теста, не контракта; см. отчёт tester):
- аргумент ``state.get`` — ключ берётся из любого строкового значения args (имя поля в спеке не названо);
- паспорт объекта ``sim.objects`` — ``{"class_name": <буква>, "angle_deg": <подача>, ...}``;
- ответы ``scene.pause`` / ``scene.defect_rate`` / ``vfd_run`` — ``{"status": "ok", "ok": True}``.
"""

from __future__ import annotations

import importlib
import io
import json
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

_TREE = "/stand"
_LOG_DIR = "/stand/data/logs/prototype"
_SUMMARY_OK = "итог: B=PASS D=PASS C=PASS ДОМОЙ=PASS СТОП=PASS → код 0 (вердикт α — Task 1.2, не этот скрипт)"


def _RA():
    return importlib.import_module("scripts.alpha_sim.run_alpha")


# --- литералы случаев (design.md §2.4-§2.6; те же, что в te ---


def _take(cell: int, y: str, r: str, k: int, n: int) -> str:
    return f"ячейка {cell}: взять(458.2,-343.0) → положить x320.0 y{y} z-132.0 r{r}° [{k}/{n}]"


_SKIP_B = "пропуск: нет в слове 'ПЕРЕМИРИЕ'"
_SKIP_FULL = "пропуск: ячейки 'Е' заняты (1, 3, 8)"
_SKIP_D = "пропуск: нет в слове 'МИР'"

_CASES = {
    "B": {
        "word": "ПЕРЕМИРИЕ",
        "word_line": "WordLayoutPlugin: слово 'ПЕРЕМИРИЕ' (источник: регистр)",
        "discs": [
            ("Р", 0),
            ("А", 0),
            ("Е", 30),
            ("И", 60),
            ("Е", 90),
            ("Б", 0),
            ("Р", 300),
            ("Е", 330),
            ("И", 30),
            ("Е", 60),
            ("П", 90),
            ("М", 300),
        ],  # fmt: skip
        "decisions": [
            _take(2, "-220.0", "0.0", 1, 9),
            _SKIP_B,
            _take(1, "-330.0", "-30.0", 2, 9),
            _take(5, "110.0", "-60.0", 3, 9),
            _take(3, "-110.0", "-90.0", 4, 9),
            _SKIP_B,
            _take(6, "220.0", "60.0", 5, 9),
            _take(8, "440.0", "30.0", 6, 9),
            _take(7, "330.0", "-30.0", 7, 9),
            _SKIP_FULL,
            _take(0, "-440.0", "-90.0", 8, 9),
            _take(4, "0.0", "60.0", 9, 9),
        ],  # fmt: skip
        "jobs": [
            (63336, 64536),
            (62236, 64236),
            (1100, 63936),
            (64436, 63636),
            (2200, 65136),
            (4400, 64836),
            (3300, 64236),
            (61136, 63636),
            (0, 65136),
        ],  # fmt: skip
        "regs": {
            "target_word": "ПЕРЕМИРИЕ",
            "word_norm": "ПЕРЕМИРИЕ",
            "slots_total": 9,
            "slots_filled": 9,
            "jobs_emitted": 9,
            "done": True,
        },  # fmt: skip
    },
    "D": {
        "word": "МИР",
        "word_line": "WordLayoutPlugin: смена слова 'ПЕРЕМИРИЕ' → 'МИР' (источник: регистр) — "
        "ячейки с нуля (было заполнено 9/9)",
        "discs": [("П", 0), ("М", 30), ("Е", 0), ("И", 90), ("Р", 300)],
        "decisions": [
            _SKIP_D,
            _take(0, "-440.0", "-30.0", 1, 3),
            _SKIP_D,
            _take(1, "-330.0", "-90.0", 2, 3),
            _take(2, "-220.0", "60.0", 3, 3),
        ],  # fmt: skip
        "jobs": [(61136, 64236), (62236, 63636), (63336, 65136)],
        "regs": {
            "target_word": "МИР",
            "word_norm": "МИР",
            "slots_total": 3,
            "slots_filled": 3,
            "jobs_emitted": 12,
            "done": True,
        },  # fmt: skip
    },
    "C": {
        "word": "ПЕРЕМИРИЕ",
        "word_line": "WordLayoutPlugin: смена слова 'МИР' → 'ПЕРЕМИРИЕ' (источник: регистр) — "
        "ячейки с нуля (было заполнено 3/3)",
        "discs": [("Е", 0), ("Е", 30), ("Е", 60), ("Е", 90)],
        "decisions": [
            _take(1, "-330.0", "0.0", 1, 9),
            _take(3, "-110.0", "-30.0", 2, 9),
            _take(8, "440.0", "-60.0", 3, 9),
            _SKIP_FULL,
        ],  # fmt: skip
        "jobs": [(62236, 64536), (64436, 64236), (4400, 63936)],
        "regs": {
            "target_word": "ПЕРЕМИРИЕ",
            "word_norm": "ПЕРЕМИРИЕ",
            "slots_total": 9,
            "slots_filled": 3,
            "jobs_emitted": 15,
            "done": False,
        },  # fmt: skip
    },
}


def _cvt_texts(seq: int, a7: int, a9: int) -> list[str]:
    return [
        f"W* CMD_SEQ = {seq}", "W* CMD_OPCODE = 32 (CVT_JOB)", "W* CMD_ARGC = 10",
        "W* CMD_ARGS[0] = 18178", "W* CMD_ARGS[1] = 0", "W* CMD_ARGS[2] = 4582", "W* CMD_ARGS[3] = 62106",
        "W* CMD_ARGS[4] = 64216", "W* CMD_ARGS[5] = 3", "W* CMD_ARGS[6] = 3200", f"W* CMD_ARGS[7] = {a7}",
        "W* CMD_ARGS[8] = 64216", f"W* CMD_ARGS[9] = {a9}", "W CMD_FLAG = 1",
        f"R RES_SEQ..+12 RES_SEQ = {seq}, RES_STATUS = 1, RES_ERRNO = 0 (ОК)",
    ]  # fmt: skip


_PARK_TEXTS = [
    "W* CMD_SEQ = 40001", "W* CMD_OPCODE = 48 (SC_RUN)", "W* CMD_ARGC = 0", "W CMD_FLAG = 1",
    "R RES_SEQ..+12 RES_SEQ = 40001, RES_STATUS = 1, RES_ERRNO = 0 (ОК)",
    "W* CMD_SEQ = 40002", "W* CMD_OPCODE = 65 (SERVO)", "W* CMD_ARGC = 1", "W* CMD_ARGS[0] = 0", "W CMD_FLAG = 1",
    "R RES_SEQ..+12 RES_SEQ = 40002, RES_STATUS = 1, RES_ERRNO = 0 (ОК)",
]  # fmt: skip

_B_LIST = [["Р", 0], ["А", 0], ["Е", 30], ["И", 60], ["Е", 90], ["Б", 0],
           ["Р", 300], ["Е", 330], ["И", 30], ["Е", 60], ["П", 90], ["М", 300]]  # fmt: skip
_D_LIST = [["П", 0], ["М", 30], ["Е", 0], ["И", 90], ["Р", 300]]
_C_LIST = [["Е", 0], ["Е", 30], ["Е", 60], ["Е", 90]]


# --- фейковый мир ---


class _Runaway(BaseException):
    """Фейковые часы ушли слишком далеко: скрипт крутится без выхода."""


@dataclass
class Call:
    idx: int
    drv: str
    method: str
    args: tuple
    kwargs: dict


def _norm(x):
    return json.loads(json.dumps(x))


class World:
    STREAM_PERIOD = 8.1

    def __init__(self, *, log_dir: str = _LOG_DIR, c_job2_a7: int | None = None, no_recog: bool = False,
                 invalid_b: bool = False, infos: dict | None = None) -> None:  # fmt: skip
        self.t = 1000.0
        self.calls: list[Call] = []
        self.errors: list[str] = []
        self.order: list[tuple] = []
        self.log_dir = log_dir
        self.c_job2_a7 = c_job2_a7
        self.no_recog = no_recog
        self.invalid_b = invalid_b
        RA = _RA()
        self.infos = infos if infos is not None else {
            8766: RA.ListenerInfo(8766, 111, "python apps/line_sim/run.py", _TREE),
            8765: RA.ListenerInfo(8765, 222, "python multiprocess_prototype/run.py --recipe "
                                  "multiprocess_prototype/recipes/letter_robot_sim.yaml", _TREE),
        }  # fmt: skip
        # сим
        self.paused = False
        self.active = 0
        self.seq = {"mode": "idle", "total": 0, "fed": 0, "skipped": 0, "remaining": 0}
        self.objects: dict = {}
        self.obj_n = 0
        self.jobs_total = 0
        self.done_total = 0
        self.pending_case: str | None = None
        # прототип
        self.word = ""
        self.regs = {"target_word": "", "word_norm": "", "slots_total": 0, "slots_filled": 0,
                     "jobs_emitted": 0, "done": False}  # fmt: skip
        self.events: list[tuple[int, dict]] = []
        self.ev_seq = 0
        self.ex_lines: list[dict] = []
        self.ex_last = 570
        self.stream_on = False
        self.stream_next = 0.0
        self.stream_n = 0
        self.straggler_done = False
        self.pending_ev: list[tuple[float, str]] = []
        self.sched: list = []
        self.conn_polls = 0
        self.park_seq = 3
        self.park_polls = 0
        self.park_done = False
        self.shutdown_called = False
        self.file_lines: list[str] = [
            "#103 2026-11-09 10:00:00,000 [INFO] S.d.d.e.robot_main: #3 in W STOP_REQ = 5",
            "#104 2026-11-09 10:00:00,100 [INFO] S.d.d.e.robot_main: #4  disconnect",
        ]

    # --- время -----------------------------------------------------------------------------------------------------
    def clock(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.t += dt
        if self.t > 1000.0 + 20000.0:
            raise _Runaway

    def tick(self) -> None:
        if self.stream_on and not self.paused and not self.no_recog:
            while self.stream_next <= self.t:
                self.stream_n += 1
                self.emit(f"WordLayoutPlugin: диск 'Р' {self.stream_n * 7 % 360:.1f}° → пропуск: слово не задано")
                self.stream_next += self.STREAM_PERIOD
        for due, msg in sorted(self.pending_ev):
            if due <= self.t:
                self.emit(msg)
        self.pending_ev = [(d, m) for d, m in self.pending_ev if d > self.t]
        due_now = sorted((d, i) for i, (d, _) in enumerate(self.sched) if d <= self.t)
        for _, i in due_now:
            self.sched[i][1]()
        self.sched = [x for x in self.sched if x[0] > self.t]

    def emit(self, msg: str) -> None:
        self.ev_seq += 1
        self.events.append((self.ev_seq, {"command": "log.record", "data": {"record": {"message": msg}}}))

    def add_ex(self, text: str, side: str = "in") -> None:
        self.ex_last += 1
        self.ex_lines.append(
            {"seq": self.ex_last, "t": self.t, "side": side, "text": text, "tag": "", "n": 1, "ms": 0.0}
        )

    # --- порт-сторож и фабрика -------------------------------------------------------------------------------------
    def listeners(self, port: int):
        self.order.append(("listeners", port))
        if port == 8765 and self.shutdown_called:
            return None
        return self.infos.get(port)

    def driver_factory(self, port: int):
        self.order.append(("factory", port))
        return FakeDriver(self, "proto" if port == 8765 else "sim")

    def read_lines(self, path: Path):
        self.order.append(("read_lines", str(path)))
        if str(path) != str(Path(self.log_dir) / "devices" / "robot_exchange.log"):
            return None
        return list(self.file_lines)

    # --- разбор вызовов для проверок -------------------------------------------------------------------------------
    def cmds(self, drv: str) -> list[tuple[int, str, dict, dict]]:
        return [
            (c.idx, c.args[1], c.args[2], c.kwargs) for c in self.calls if c.drv == drv and c.method == "send_command"
        ]

    def first(self, drv: str, method: str, command: str | None = None, pred=None):
        for c in self.calls:
            if c.drv != drv or c.method != method:
                continue
            if command is not None and (c.method != "send_command" or c.args[1] != command):
                continue
            if pred is None or pred(c):
                return c
        return None

    def count(self, drv: str, method: str, command: str | None = None, args: dict | None = None) -> int:
        n = 0
        for c in self.calls:
            if c.drv != drv or c.method != method:
                continue
            if command is not None and c.args[1] != command:
                continue
            if args is not None and c.args[2] != args:
                continue
            n += 1
        return n

    # --- случаи ----------------------------------------------------------------------------------------------------
    def release(self, case: str) -> None:
        """Случай пошёл: диск k приходит через k с (журнал, обмен, journal.done, fed); регистры — в конце."""
        data = _CASES[case]
        self.emit(data["word_line"])
        self.events.append((self.ev_seq, {"command": "state.update", "data": {}}))  # посторонний event
        self.objects = {}
        for letter, angle in data["discs"]:
            self.obj_n += 1
            self.objects[f"o{self.obj_n:03d}"] = {"class_name": letter, "angle_deg": float(angle), "x_mm": 0.0}
        total = len(data["discs"])
        seq0 = 33000 + 100 * len(self.calls)
        jobs = iter(enumerate(data["jobs"]))
        for k, (letter, angle) in enumerate(data["discs"]):
            decision = data["decisions"][k]
            taken = decision.startswith("ячейка")
            job = next(jobs) if taken else None

            def arrive(k=k, letter=letter, angle=angle, decision=decision, job=job) -> None:
                self.emit(f"WordLayoutPlugin: диск '{letter}' {angle:.1f}° → {decision}")
                if job is not None:
                    n, (a7, a9) = job
                    if case == "C" and n == 1 and self.c_job2_a7 is not None:
                        a7 = self.c_job2_a7
                    for text in _cvt_texts(seq0 + 2 * n, a7, a9):
                        self.add_ex(text, "out" if text.startswith("W") else "in")
                    self.add_ex("W 0x1204 = 1")
                    self.jobs_total += 1
                    self.done_total += 1
                self.seq = {"mode": "list", "total": total, "fed": k + 1, "skipped": 0, "remaining": total - k - 1}
                if k == total - 1:
                    self.emit("RobotIoPlugin: задание принято в очередь")
                    self.regs = dict(data["regs"])

            self.sched.append((self.t + 1.0 * (k + 1), arrive))

def _state_get_key(args: dict) -> str:
    for v in args.values():
        if isinstance(v, str):
            return v
    return ""


class FakeDriver:
    def __init__(self, world: World, role: str) -> None:
        self.w = world
        self.role = role
        self.connected = False

    def _enter(self, method: str, *a, **kw) -> None:
        w = self.w
        if method != "connect" and not self.connected:
            w.errors.append(f"{self.role}.{method} без connect()")
        w.tick()
        w.calls.append(Call(len(w.calls), self.role, method, _norm(a), _norm(kw)))

    def connect(self):
        self._enter("connect")
        self.connected = True

    def close(self):
        self._enter("close")

    def log_tail(self, process, *, level):
        self._enter("log_tail", process, level=level)
        return {"success": True}

    def introspect_plugins(self, process):
        self._enter("introspect_plugins", process)
        return {"success": True, "result": {"plugins": ["recog"]}}

    def introspect_registers(self, process):
        self._enter("introspect_registers", process)
        regs = dict(self.w.regs)
        regs["target_word"] = self.w.word
        return {"result": {"success": True, "process": process, "registers": {"word_layout": regs}}}

    def set_register_verified(self, process, register, field, value, *, timeout=None):
        self._enter("set_register_verified", process, register, field, value)
        if self.role != "proto":
            self.w.errors.append("set_register_verified у сима")
        self.w.word = value
        return {"success": True, "verified": True, "found": True, "expected": value, "actual": value}

    def events_page(self, plane, *, cursor=None, limit=None):
        self._enter("events_page", plane, cursor=cursor, limit=limit)
        w = self.w
        lim = 100 if limit is None else limit
        if lim > 500:
            w.errors.append(f"events_page limit {lim} > 500")
        start = 0 if cursor is None else int(cursor)
        items = [{"seq": s, "event": ev} for s, ev in w.events[start : start + lim]]
        nxt = start + len(items)
        return {"success": True, "plane": plane, "items": items, "count": len(items), "next_cursor": nxt,
                "dropped": 0, "bookmark": nxt}  # fmt: skip

    def system_shutdown(self, *, wait, wait_timeout):
        self._enter("system_shutdown", wait=wait, wait_timeout=wait_timeout)
        w = self.w
        if self.role != "proto":
            w.errors.append("system_shutdown у сима")
        w.shutdown_called = True
        w.file_lines += [
            f"#{w.ex_last + 101} 2026-11-10 12:30:00,123 [INFO] S.d.d.e.robot_main: #{w.ex_last + 1} in W STOP_REQ = 9",
            f"#{w.ex_last + 102} 2026-11-10 12:30:00,456 [INFO] S.d.d.e.robot_main: #{w.ex_last + 2}  disconnect",
        ]
        return {"accepted": True, "mode": "graceful", "elapsed_s": 1.0, "pm_gone": True,
                "outcomes": {"layout": "exited"}, "unconfirmed": [], "timed_out": False}  # fmt: skip

    def send_command(self, target, command, args, *, timeout=None):
        self._enter("send_command", target, command, args, timeout=timeout)
        handler = self._sim if self.role == "sim" else self._proto
        return {"result": handler(command, args)}

    # --- сим -------------------------------------------------------------------------------------------------------
    def _sim(self, command: str, args: dict) -> dict:
        w = self.w
        if command == "scene.status":
            active = w.active
            w.active = max(0, w.active - 1)
            return {"active": active, "sequence": dict(w.seq)}
        if command == "scene.defect_rate":
            return {"status": "ok", "ok": True}
        if command == "scene.pause":
            paused = bool(args["paused"])
            if paused:
                w.active = 2
                if w.stream_on and not w.straggler_done:
                    w.straggler_done = True
                    w.pending_ev.append((w.t + 1.0, "WordLayoutPlugin: диск 'Е' 12.0° → пропуск: слово не задано"))
                w.stream_on = False
            elif w.pending_case is not None:
                case, w.pending_case = w.pending_case, None
                w.release(case)
            w.paused = paused
            return {"status": "ok", "ok": True, "paused": paused}
        if command == "scene.sequence":
            if args == {"random": True}:  # возврат к случайной подаче (идемпотентно)
                w.seq = {"mode": "random", "total": 0, "fed": 0, "skipped": 0, "remaining": 0}
                return {"status": "ok", "mode": "random", "dropped": 0}
            discs = _norm(args["discs"])
            case = next((k for k, v in (("B", _B_LIST), ("D", _D_LIST), ("C", _C_LIST)) if discs == v), None)
            if case is None:
                w.errors.append(f"scene.sequence с неизвестным списком {discs}")
                return {"status": "error", "code": "invalid", "index": 0, "unknown": "?"}
            if case == "B" and w.invalid_b:
                return {"status": "error", "code": "invalid", "index": 5, "unknown": "Б"}
            w.pending_case = case
            w.seq = {"mode": "list", "total": len(discs), "fed": 0, "skipped": 0, "remaining": len(discs)}
            return {"status": "ok", "queued": len(discs), "dropped": 0}
        if command == "sim_robot.status":
            return {"journal": {"jobs": w.jobs_total, "done": w.done_total}}
        if command == "state.get":
            key = _state_get_key(args)
            if key == "sim.objects":
                return {"status": "ok", "request_id": "r", "value": dict(w.objects)}
            return {"status": "error", "request_id": "r"}
        w.errors.append(f"sim: неизвестная команда {command}")
        return {"status": "error"}

    # --- прототип --------------------------------------------------------------------------------------------------
    def _proto(self, command: str, args: dict) -> dict:
        w = self.w
        if command == "state.get":
            key = _state_get_key(args)
            if key == "devices.state.robot_main.conn":
                w.conn_polls += 1
                if w.conn_polls <= 2:
                    return {"status": "error", "request_id": "r"}  # ключа ещё нет
                state = "connecting" if w.conn_polls == 3 else "connected"
                return {"status": "ok", "request_id": "r", "value": {"conn": state, "ts": 1.0 * w.conn_polls}}
            if key == "devices.state.robot_main.park":
                if not w.park_done:
                    return {"status": "error", "request_id": "r"}
                w.park_polls += 1
                seq = w.park_seq - 1 if w.park_polls == 1 else w.park_seq  # первый снимок устарел
                return {"status": "ok", "request_id": "r", "value": {"seq": seq, "state": "done", "ts": 2.0}}
            if key == "processes.layout.state.word_layout":
                return {"status": "ok", "request_id": "r", "value": {"word_norm": w.regs["word_norm"]}}
            return {"status": "error", "request_id": "r"}
        if command == "robot_param_get_all":
            return {"params": {"P_PICK_RZ": {"raw": -1000}, "P_WS_R_MAX": {"raw": 6000}}}
        if command in ("robot_exchange_log_get", "robot_exchange_log_set"):
            if command.endswith("_set") and args.get("clear"):
                w.ex_lines = []
            since = int(args.get("since_seq", 0))
            limit = int(args.get("limit", 2000))
            lines = [dict(ln) for ln in w.ex_lines if ln["seq"] >= since][:limit]
            return {"enabled": True, "periodic": False, "lines": lines, "last_seq": w.ex_last, "dropped": 0,
                    "counters": {}}  # fmt: skip
        if command == "robot_park_all":
            w.park_done = True
            w.park_polls = 0
            w.park_seq += 1
            for text in _PARK_TEXTS:
                w.add_ex(text, "out" if text.startswith("W") else "in")
            return {"status": "ok", "timeout_s": 30.0, "elapsed_s": 2.0,
                    "robots": {"robot_main": {"result": "done", "seq": w.park_seq, "home": "moved",
                                              "elapsed_s": 2.0}}}  # fmt: skip
        if command == "vfd_run":
            w.stream_on = True
            w.stream_next = w.t + World.STREAM_PERIOD
            return {"status": "ok", "ok": True}
        w.errors.append(f"proto: неизвестная команда {command}")
        return {"status": "error"}


# --- запуск ---


def _run(world: World, argv: list[str] | None = None) -> tuple[int, str]:
    RA = _RA()
    out = io.StringIO()
    box: dict = {}

    def target() -> None:
        try:
            box["rc"] = RA.run(
                argv if argv is not None else ["--tree", _TREE],
                driver_factory=world.driver_factory,
                listeners=world.listeners,
                clock=world.clock,
                sleep=world.sleep,
                out=out,
                read_lines=world.read_lines,
            )
        except BaseException as exc:  # noqa: BLE001 - тест сообщает любое падение run
            box["exc"] = exc

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(timeout=30)
    assert not th.is_alive(), "run не вышел за 30 с (завис)"
    assert "exc" not in box, f"run бросил {box.get('exc')!r}"
    return box["rc"], out.getvalue()


def _after(world: World, drv: str, method: str, idx: int, command: str | None = None) -> bool:
    return any(c.idx > idx and c.drv == drv and c.method == method and (command is None or c.args[1] == command)
               for c in world.calls)  # fmt: skip


# --- RED 9 ---


def test_port_guard_mismatch_sends_nothing() -> None:
    RA = _RA()
    other = RA.ListenerInfo(8766, 111, "python apps/line_sim/run.py", "/other/tree")
    world = World(infos={8766: other, 8765: RA.ListenerInfo(8765, 222, "python multiprocess_prototype/run.py "
                                                           "--recipe letter_robot_sim", _TREE)})  # fmt: skip
    rc, out = _run(world)
    assert rc == 3
    assert [o for o in world.order if o[0] == "factory"] == []
    assert world.calls == []
    assert "8766" in out
    assert "/other/tree" in out

    # контроль: тот же порт с cwd под деревом → фабрика вызвана для обоих портов, connect у обоих
    ok_world = World()
    rc_ok, _ = _run(ok_world)
    assert rc_ok == 0
    assert sorted(o[1] for o in ok_world.order if o[0] == "factory") == [8765, 8766]
    assert {c.drv for c in ok_world.calls if c.method == "connect"} == {"sim", "proto"}
    # сторож — до первой фабрики
    first_factory = next(i for i, o in enumerate(ok_world.order) if o[0] == "factory")
    assert {o[1] for o in ok_world.order[:first_factory] if o[0] == "listeners"} == {8765, 8766}


@pytest.mark.parametrize(
    ("port", "command", "cwd", "needle"),
    [
        (8765, "python multiprocess_prototype/run.py --recipe other_recipe.yaml", _TREE, "8765"),
        (8765, "python multiprocess_prototype/run.py --recipe letter_robot_sim", "/other/tree", "/other/tree"),
        (8766, "python other/run.py", _TREE, "8766"),
    ],
    ids=["proto_without_recipe", "proto_other_tree", "sim_other_script"],
)
def test_port_guard_other_mismatches(port, command, cwd, needle) -> None:
    RA = _RA()
    infos = {
        8766: RA.ListenerInfo(8766, 111, "python apps/line_sim/run.py", _TREE),
        8765: RA.ListenerInfo(8765, 222, "python multiprocess_prototype/run.py --recipe letter_robot_sim", _TREE),
    }
    infos[port] = RA.ListenerInfo(port, 333, command, cwd)
    world = World(infos=infos)
    rc, out = _run(world)
    assert rc == 3
    assert [o for o in world.order if o[0] == "factory"] == []
    assert needle in out


# --- RED 10 ---


def _subseq(seq: list, wanted: list) -> bool:
    it = iter(seq)
    return all(any(item == w for item in it) for w in wanted)


def test_order_and_unknown_letter_precondition() -> None:
    world = World(invalid_b=True)
    rc, out = _run(world)
    assert world.errors == []
    assert rc == 3

    sim = [(c[1], c[2]) for c in world.cmds("sim")]
    assert sim[0][0] == "scene.status"
    wanted = [
        ("scene.status", {}),
        ("scene.defect_rate", {"probability": 0.0}),
        ("scene.pause", {"paused": True}),
        ("scene.status", {}),
        ("scene.sequence", {"discs": _B_LIST}),
    ]
    assert _subseq(sim, wanted), sim
    assert sim.count(("scene.defect_rate", {"probability": 0.0})) == 1

    tail = world.first("proto", "log_tail")
    setw = world.first("proto", "set_register_verified")
    assert tail is not None and setw is not None
    assert tail.args == ["layout"] and tail.kwargs == {"level": "INFO"}
    assert setw.args == ["layout", "word_layout", "target_word", "ПЕРЕМИРИЕ"]
    assert tail.idx < setw.idx

    # cleanup: park и shutdown по разу, снятие паузы — после shutdown
    assert world.count("proto", "send_command", "robot_park_all") == 1
    assert world.count("proto", "system_shutdown") == 1
    shutdown = world.first("proto", "system_shutdown")
    unpause = world.first("sim", "send_command", "scene.pause", lambda c: c.args[2] == {"paused": False})
    park = world.first("proto", "send_command", "robot_park_all")
    assert unpause is not None
    assert park.idx < shutdown.idx < unpause.idx
    assert world.count("sim", "send_command", "scene.pause", {"paused": False}) == 1
    # сим не останавливают, слово следующих случаев не ставят
    assert world.count("sim", "system_shutdown") == 0
    assert world.count("sim", "send_command", "scene.sequence", {"discs": _B_LIST}) == 1  # список только B
    assert world.count("sim", "send_command", "scene.sequence", {"random": True}) == 2  # P3 и cleanup
    assert world.count("proto", "set_register_verified") == 1

    assert "предусловие" in out
    assert "'Б'" in out
    assert "cleanup: " in out


# --- RED 11 ---


def test_full_run_on_fakes() -> None:
    world = World()
    rc, out = _run(world)
    assert world.errors == []
    assert rc == 0, out
    lines = out.rstrip("\n").splitlines()
    assert lines[-1] == _SUMMARY_OK
    assert len([ln for ln in lines if ln.startswith("B #")]) == 12
    assert len([ln for ln in lines if ln.startswith("D #")]) == 5
    assert len([ln for ln in lines if ln.startswith("C #")]) == 4
    assert not any(ln.startswith("cleanup: ") for ln in lines)
    assert "FAIL" not in "\n".join(ln for ln in lines[:-1] if ln.startswith(("B ", "D ", "C ")))
    assert "B #1 вход Р 0.0° → наблюдение: диск 'Р' 0.0° → ячейка 2: взять(458.2,-343.0) → положить " \
           "x320.0 y-220.0 z-132.0 r0.0° [1/9] | CVT_JOB ARGS[7]=63336 ARGS[9]=64536 RES=1 → PASS" in lines  # fmt: skip
    assert "C #4 вход Е 90.0° → наблюдение: диск 'Е' 90.0° → пропуск: ячейки 'Е' заняты (1, 3, 8) → PASS" in lines
    assert "совпала" in out  # блок углов: подача = сеть

    # порядок и форма вызовов
    assert world.count("sim", "send_command", "scene.sequence", {"discs": _B_LIST}) == 1
    assert world.count("sim", "send_command", "scene.sequence", {"discs": _D_LIST}) == 1
    assert world.count("sim", "send_command", "scene.sequence", {"discs": _C_LIST}) == 1
    assert world.count("sim", "send_command", "scene.sequence", {"random": True}) == 2  # P3 и возврат в конце
    assert world.count("sim", "send_command", "scene.sequence") == 5
    assert world.count("sim", "send_command", "scene.defect_rate", {"probability": 0.0}) == 1
    assert world.count("sim", "send_command", "scene.pause", {"paused": True}) == 3
    assert world.count("sim", "send_command", "scene.pause", {"paused": False}) == 3
    words = [c.args[3] for c in world.calls if c.method == "set_register_verified"]
    assert words == ["ПЕРЕМИРИЕ", "МИР", "ПЕРЕМИРИЕ"]
    assert world.count("sim", "system_shutdown") == 0

    park = world.first("proto", "send_command", "robot_park_all")
    shutdown = world.first("proto", "system_shutdown")
    assert park.args[0] == "devices"
    assert park.args[2] == {"timeout_s": 30.0}
    assert park.kwargs == {"timeout": 40.0}
    assert shutdown.kwargs == {"wait": True, "wait_timeout": 60.0}
    assert park.idx < shutdown.idx
    assert world.count("proto", "send_command", "robot_park_all") == 1
    assert world.count("proto", "system_shutdown") == 1
    after = [c.method for c in world.calls if c.drv == "proto" and c.idx > shutdown.idx]
    assert [m for m in after if m != "close"] == [], "после system_shutdown прототипу ничего не шлют"
    vfd = world.first("proto", "send_command", "vfd_run")
    assert vfd.args[2] == {"device_id": "vfd_belt", "freq_hz": 10.0}
    # файл журнала читается по умолчанию из <tree>/data/logs/prototype и после shutdown
    reads = [o for o in world.order if o[0] == "read_lines"]
    assert reads == [("read_lines", "/stand/data/logs/prototype/devices/robot_exchange.log")]


def test_full_run_failing_job_still_does_home_and_stop() -> None:
    world = World(log_dir="/alt/logs", c_job2_a7=4400)
    rc, out = _run(world, ["--tree", _TREE, "--log-dir", "/alt/logs"])
    assert world.errors == []
    assert rc == 1
    lines = out.rstrip("\n").splitlines()
    assert lines[-1] == (
        "итог: B=PASS D=PASS C=FAIL ДОМОЙ=PASS СТОП=PASS → код 1 (вердикт α — Task 1.2, не этот скрипт)"
    )
    c2 = next(ln for ln in lines if ln.startswith("C #2 "))
    assert "→ FAIL: " in c2
    assert "ARGS[7]" in c2
    c1 = next(ln for ln in lines if ln.startswith("C #1 "))
    assert c1.endswith("→ PASS")
    assert world.count("proto", "send_command", "robot_park_all") == 1
    assert world.count("proto", "system_shutdown") == 1
    assert [o for o in world.order if o[0] == "read_lines"] == [("read_lines", "/alt/logs/devices/robot_exchange.log")]


def test_no_recognition_stops_at_p3() -> None:
    world = World(no_recog=True)
    rc, out = _run(world)
    assert world.errors == []
    assert rc == 3
    assert "распознавания нет" in out
    assert "предусловие: распознавания нет — сеть/модель не загружены или лента стоит" in out
    assert "не измерено" in out
    plug = world.first("proto", "introspect_plugins")
    assert plug is not None and plug.args == ["recog"]
    assert world.count("proto", "system_shutdown") == 0
    assert world.count("proto", "send_command", "robot_park_all") == 0
    assert world.count("proto", "set_register_verified") == 0
    assert [c for c in world.cmds("sim") if c[1] in ("scene.defect_rate", "scene.pause")] == []
    assert [c[2] for c in world.cmds("sim") if c[1] == "scene.sequence"] == [{"random": True}]  # только P3
    # срок P3 — 120 с по фейковым часам (не раньше), от vfd_run
    vfd = world.first("proto", "send_command", "vfd_run")
    assert vfd is not None
    waited = world.t - 1000.0
    assert 120.0 <= waited <= 400.0, waited
