"""Скрипт α (P4): случаи B, D, C, «домой» и чистый стоп на симе одной командой.

Запуск (из корня дерева стенда)::

    PYTHONUTF8=1 python -m scripts.alpha_sim.run_alpha --tree <корень дерева стенда>

Сим и прототип скрипт НЕ запускает; сим не останавливает; прототип останавливает шагом P6.
Контракт — plans/word-layout/tasks/P4.md (Д1-Д3). Вердикта «α пройдена» скрипт не выносит (Task 1.2):
только PASS/FAIL по литералам и код выхода 0/1/2/3.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from scripts.alpha_sim import logic as L

STEP = 0.25  # шаг опроса, с (кольцо sim_robot.journal и подача 1 диск/с: >= 4 опроса на диск)
SILENCE_S = 3.0  # тишина журнала layout после паузы сима (эвристика, не замер)
_PROTO_SCRIPT = "multiprocess_prototype/run.py"
_SIM_SCRIPT = "apps/line_sim/run.py"
_RECIPE_MARK = "letter_robot_sim"
_EXCHANGE = {"device_id": "robot_main"}


@dataclass(frozen=True)
class ListenerInfo:
    port: int
    pid: int
    command: str
    cwd: str


class ListenerProbeError(Exception):
    """Не удалось определить, кто слушает порт (нет lsof/ps, два PID, неожиданный rc)."""


class Precondition(Exception):
    """Стенд не тот / не готов: rc 3, текст идёт в строку ``предусловие: …``."""


class CaseFail(Exception):
    """FAIL случая, после которого дальше идти нельзя (слово не записано): rc 1."""

    def __init__(self, row: L.Row) -> None:
        super().__init__(row.observed)
        self.row = row


# --- Настоящие зависимости (main) -------------------------------------------------------------------------------------


def _run_tool(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ListenerProbeError(f"{cmd[0]}: {type(exc).__name__}: {exc}") from exc


def _is_spawn_child(command: str) -> bool:
    """Потомок ``multiprocessing`` (spawn): его командная строка не называет скрипт запуска."""
    return "spawn_main" in command or "--multiprocessing-fork" in command


def _root_command(pid: int, command: str) -> str:
    """Командная строка первого предка слушателя без ``spawn_main`` (до 5 уровней; PID 1 или цикл — стоп)."""
    chain = [f"{pid}: {command}"]
    seen = {pid}
    cur = pid
    for _ in range(5):
        pp = _run_tool(["ps", "-o", "ppid=", "-p", str(cur)])
        text = pp.stdout.strip()
        if pp.returncode != 0 or not text.isdigit():
            break
        parent = int(text)
        if parent <= 1 or parent in seen:
            break
        ps = _run_tool(["ps", "-o", "command=", "-p", str(parent)])
        parent_cmd = ps.stdout.strip()
        if ps.returncode != 0 or not parent_cmd:
            break
        chain.append(f"{parent}: {parent_cmd}")
        if not _is_spawn_child(parent_cmd):
            return parent_cmd
        seen.add(parent)
        cur = parent
    raise ListenerProbeError("корень запуска не найден выше spawn_main-потомка; цепочка: " + " <- ".join(chain))


def lsof_listeners(port: int) -> ListenerInfo | None:
    """Кто слушает TCP-порт (macOS/Linux): lsof → PID, ps → команда, lsof → cwd. rc 1 и пусто — слушателя нет."""
    r = _run_tool(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"])
    if r.returncode == 1 and not r.stdout.strip():
        return None
    if r.returncode != 0:
        raise ListenerProbeError(f"lsof порт {port}: rc {r.returncode}: {r.stderr.strip()}")
    pids = sorted({int(ln[1:]) for ln in r.stdout.splitlines() if ln.startswith("p") and ln[1:].isdigit()})
    if not pids:
        return None
    if len(pids) > 1:
        raise ListenerProbeError(f"порт {port}: несколько слушателей {pids}")
    pid = pids[0]
    ps = _run_tool(["ps", "-o", "command=", "-p", str(pid)])
    if ps.returncode != 0 or not ps.stdout.strip():
        raise ListenerProbeError(f"ps -p {pid}: rc {ps.returncode}: {ps.stderr.strip()}")
    cwd_out = _run_tool(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"])
    cwd = next((ln[1:] for ln in cwd_out.stdout.splitlines() if ln.startswith("n")), "")
    if cwd_out.returncode != 0 or not cwd:
        raise ListenerProbeError(f"lsof cwd PID {pid}: rc {cwd_out.returncode}: {cwd_out.stderr.strip()}")
    command = ps.stdout.strip()
    if _is_spawn_child(command):
        command = _root_command(pid, command)
    return ListenerInfo(port, pid, command, cwd)


def _read_lines(path: Path) -> list[str] | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return None


# --- Мелочи ответов ---------------------------------------------------------------------------------------------------


def _res(reply: Any) -> dict:
    """Ответ команды лежит в ``result`` (amendments 4); не словарь — пустой словарь."""
    if isinstance(reply, dict):
        inner = reply.get("result")
        return inner if isinstance(inner, dict) else reply
    return {}


def _ok(res: dict) -> bool:
    return res.get("status") == "ok" or bool(res.get("ok"))


def _fmt_exc(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


# --- Читатели журналов ------------------------------------------------------------------------------------------------


class _LayoutReader:
    """Журнал layout: ``events_page("logs")`` страницами по 500 до пустой, ``dropped`` копится."""

    def __init__(self, drv: Any) -> None:
        self._drv = drv
        self._cursor: Any = None
        self.dropped = 0
        self.events: list[tuple[Any, str]] = []

    def drain(self) -> list[str]:
        out: list[str] = []
        while True:
            page = self._drv.events_page("logs", cursor=self._cursor, limit=500)
            if page.get("success") is False:  # курсор сброшен — слепая зона, считаем как потерю
                self.dropped += 1
                self._cursor = page.get("resume_cursor", page.get("bookmark"))
                return out
            self.dropped += int(page.get("dropped") or 0)
            items = page.get("items") or []
            if page.get("next_cursor") is not None:
                self._cursor = page["next_cursor"]
            if not items:
                return out
            for item in items:
                event = item.get("event") or {}
                if event.get("command") != "log.record":
                    continue
                msg = (((event.get("data") or {}).get("record")) or {}).get("message")
                if isinstance(msg, str):
                    out.append(msg)
                    self.events.append((item.get("seq"), msg))


class _Exchange:
    """Журнал обмена: ``get(since_seq=<последний seq>)`` + замена строки по ``seq`` (склейка поднимает ``n``)."""

    def __init__(self, alpha: _Alpha, n0: int) -> None:
        self._alpha = alpha
        self.n0 = n0
        self.acc: dict[int, dict] = {}
        self.dropped = 0
        self.last_seq = n0

    def poll(self) -> None:
        since = max(self.acc) if self.acc else self.n0
        res = self._alpha.proto_cmd(
            "devices", "robot_exchange_log_get", {**_EXCHANGE, "since_seq": since, "limit": 2000}
        )
        L.merge_exchange_lines(self.acc, res.get("lines") or [])
        self.dropped += int(res.get("dropped") or 0)
        self.last_seq = int(res.get("last_seq", self.last_seq))

    def texts(self) -> list[str]:
        return [str(self.acc[s].get("text", "")) for s in sorted(self.acc) if s > self.n0]


@dataclass
class _CaseState:
    """Что нужно хвосту следующего случая: откуда читать обмен и какой прирост ждать."""

    case: L.Case
    n0: int
    jobs0: int
    done0: int


# --- Сам прогон -------------------------------------------------------------------------------------------------------


class _Alpha:
    def __init__(
        self,
        args: argparse.Namespace,
        *,
        driver_factory: Callable[[int], Any],
        listeners: Callable[[int], ListenerInfo | None],
        clock: Callable[[], float],
        sleep: Callable[[float], None],
        out: TextIO,
        read_lines: Callable[[Path], list[str] | None],
    ) -> None:
        self.args = args
        self._factory = driver_factory
        self._listeners = listeners
        self.clock = clock
        self.sleep = sleep
        self._out = out
        self._read_lines = read_lines
        self.tree = os.path.realpath(args.tree)
        self.log_dir = Path(args.log_dir) if args.log_dir else Path(args.tree) / "data" / "logs" / "prototype"
        self.proto: Any = None
        self.sim: Any = None
        self.layout: _LayoutReader | None = None
        self.statuses: dict[str, str | None] = {k: None for k in ("B", "D", "C", "ДОМОЙ", "СТОП")}
        self.results: list[L.CaseResult | L.Row] = []
        self.precond = False
        self.paused = False  # пауза сима поставлена нами и не снята
        self.changed_defect_rate = False
        self.changed_belt = False
        self.angle_pairs: list[tuple[str, float, float]] = []
        self.angle_note = ""
        self.prev: _CaseState | None = None
        self.n8: int | None = None
        self.n9: int | None = None
        self.dump: dict[str, Any] = {"cases": {}, "replies": {}}

    # --- вывод и вызовы -------------------------------------------------------------------------------------------
    def emit(self, line: str) -> None:
        self._out.write(line + "\n")
        flush = getattr(self._out, "flush", None)
        if flush is not None:
            flush()

    def proto_cmd(self, target: str, command: str, args: dict, **kw: Any) -> dict:
        return _res(self.proto.send_command(target, command, args, **kw))

    def sim_cmd(self, target: str, command: str, args: dict, **kw: Any) -> dict:
        return _res(self.sim.send_command(target, command, args, **kw))

    def state_value(self, drv: Any, path: str) -> Any:
        """``state.get`` через ProcessManager; ключа нет (``status: error``) — ``None``."""
        res = _res(drv.send_command("ProcessManager", "state.get", {"path": path}))
        return res.get("value") if res.get("status") == "ok" else None

    def wait_until(self, what: str, deadline_s: float, step: Callable[[], bool]) -> bool:
        """Опрос с потолком: ``step`` истинен — выходим; срок вышел — ``False`` (вызывающий решает, что это)."""
        end = self.clock() + deadline_s
        while True:
            if step():
                return True
            if self.clock() >= end:
                return False
            self.sleep(STEP)

    # --- P0: сторож слушателей ------------------------------------------------------------------------------------
    def _listener_problem(self, port: int, script: str, need_recipe: bool) -> str | None:
        info = self._listeners(port)
        if info is None:
            return f"на порту {port} нет слушателя (сим/прототип не запущен)"
        tokens = shlex.split(info.command) if info.command else []
        found = None
        for tok in tokens:
            path = tok if os.path.isabs(tok) else os.path.join(info.cwd, tok)
            if os.path.realpath(path) == os.path.join(self.tree, script):
                found = tok
                break
        if found is None or (need_recipe and _RECIPE_MARK not in info.command):
            want = f"{self.tree}/{script}" + (f" с рецептом {_RECIPE_MARK}" if need_recipe else "")
            return f"порт {port}: PID {info.pid}, команда {info.command!r}, cwd {info.cwd} — ожидалось {want}"
        return None

    def p0(self) -> bool:
        problems = [
            self._listener_problem(self.args.sim_port, _SIM_SCRIPT, False),
            self._listener_problem(self.args.proto_port, _PROTO_SCRIPT, True),
        ]
        for text in filter(None, problems):
            self.emit(f"предусловие: {text}")
        return not any(problems)

    # --- P1-P3 ----------------------------------------------------------------------------------------------------
    def connect(self) -> None:
        self.sim = self._factory(self.args.sim_port)
        self.proto = self._factory(self.args.proto_port)
        self.sim.connect()
        self.proto.connect()

    def p1(self) -> None:
        status = self.sim_cmd("camera", "scene.status", {})
        seq = status.get("sequence")
        if not isinstance(seq, dict) or not (seq.get("remaining") == 0 or seq.get("mode") != "list"):
            raise Precondition(f"сим занят прошлым списком: scene.status.sequence = {seq}")
        regs = L.regs_from_introspect(self.proto.introspect_registers("layout"))
        if regs.get("target_word") != "" or regs.get("jobs_emitted") != 0:
            raise Precondition(
                f"нужен свежий прототип: target_word={regs.get('target_word')!r}, "
                f"jobs_emitted={regs.get('jobs_emitted')}"
            )
        self.emit("P1: сим и прототип на связи, прототип свежий (target_word пуст, jobs_emitted 0)")

    def p2(self) -> None:
        def connected() -> bool:
            value = self.state_value(self.proto, "devices.state.robot_main.conn")
            return isinstance(value, dict) and value.get("conn") == "connected"

        end = self.clock() + 60.0
        while not connected():
            if self.clock() >= end:
                raise Precondition("S0: robot_main не подключился за 60 с")
            self.sleep(0.5)
        params = self.proto_cmd("devices", "robot_param_get_all", dict(_EXCHANGE)).get("params") or {}
        raw = (params.get("P_PICK_RZ") or {}).get("raw")
        if raw != -1000:
            raise Precondition(f"S1: P_PICK_RZ.raw {raw} ≠ -1000 (рецепт/параметры не те)")
        tail = self.proto.log_tail("layout", level="INFO")
        if isinstance(tail, dict) and tail.get("success") is False:
            raise Precondition(f"S2: log_tail layout не принят: {tail}")
        self.layout = _LayoutReader(self.proto)
        self.layout.drain()
        res = self.proto_cmd("devices", "robot_exchange_log_get", {**_EXCHANGE, "since_seq": 0, "limit": 1})
        if res.get("enabled") is not True:
            raise Precondition("журнал обмена robot_main выключен (enabled не True)")
        self.emit("P2: robot_main connected, P_PICK_RZ -1000, log_tail layout INFO, журнал обмена включён")

    def p3(self) -> None:
        assert self.layout is not None
        res = self.proto_cmd("devices", "vfd_run", {"device_id": "vfd_belt", "freq_hz": 10.0})
        if not _ok(res):
            raise Precondition(f"vfd_run не принят: {res}")
        self.changed_belt = True
        seen = self.wait_until(
            "диск", 120.0, lambda: any(L.parse_layout_line(m) is not None for m in self.layout.drain())
        )
        if not seen:
            self.emit("предусловие: распознавания нет — сеть/модель не загружены или лента стоит")
            plugins = json.dumps(self.proto.introspect_plugins("recog"), ensure_ascii=False, default=str)
            self.emit(f"диагностика: introspect_plugins('recog') = {plugins[:2000]}")
            models = Path(self.args.tree) / "data" / "models"
            self.emit(f"диагностика: {models} {'есть' if models.is_dir() else 'нет'}")
            raise Precondition("за 120 с после vfd_run в журнале layout нет ни одной строки диска")
        self.emit("P3: лента 10 Гц, сеть жива (строка диска получена)")

    # --- P4: случай -----------------------------------------------------------------------------------------------
    def last_seq(self) -> int:
        res = self.proto_cmd("devices", "robot_exchange_log_get", {**_EXCHANGE, "since_seq": 0, "limit": 1})
        return int(res.get("last_seq", 0))

    def sim_journal(self) -> tuple[int, int]:
        journal = self.sim_cmd("robot", "sim_robot.status", {}).get("journal") or {}
        return int(journal.get("jobs", 0)), int(journal.get("done", 0))

    def _set_pause(self, paused: bool) -> None:
        res = self.sim_cmd("camera", "scene.pause", {"paused": paused})
        if not _ok(res):
            raise Precondition(f"scene.pause {{paused: {paused}}} не принят: {res}")
        self.paused = paused

    def _wait_scene_empty(self) -> None:
        def empty() -> bool:
            return self.sim_cmd("camera", "scene.status", {}).get("active") == 0

        if not self.wait_until("active", 60.0, empty):
            raise Precondition("сцена сима не опустела за 60 с после паузы (active ≠ 0)")

    def _tail_of_previous(self) -> None:
        prev = self.prev
        if prev is None:
            return
        exch = _Exchange(self, prev.n0)

        def arrived() -> bool:
            exch.poll()
            jobs = len(L.parse_cvt_jobs(exch.texts()))
            done = self.sim_journal()[1] - prev.done0
            return jobs == prev.case.jobs and done == prev.case.jobs

        if not self.wait_until("хвост", 60.0, arrived):
            raise Precondition(
                f"хвост случая {prev.case.case_id}: CVT_JOB {len(L.parse_cvt_jobs(exch.texts()))} из {prev.case.jobs}, "
                f"journal.done +{self.sim_journal()[1] - prev.done0}"
            )

    def _silence(self) -> None:
        assert self.layout is not None
        start = last = self.clock()

        def quiet() -> bool:
            nonlocal last
            if any(L.parse_layout_line(m) is not None for m in self.layout.drain()):
                last = self.clock()
            return self.clock() - last >= SILENCE_S

        end = start + 30.0
        while not quiet():
            if self.clock() >= end:
                raise Precondition("в журнале layout не наступила тишина: строки диска идут после паузы сима")
            self.sleep(STEP)

    def _send_sequence(self, cid: str, discs: list[list]) -> None:
        res = self.sim_cmd("camera", "scene.sequence", {"discs": discs})
        if res.get("code") == "busy":
            raise Precondition(f"сим занят: scene.sequence busy, remaining {res.get('remaining')}")
        if res.get("code") == "invalid":
            unknown = res.get("unknown")
            if unknown:
                letters = "', '".join(unknown) if isinstance(unknown, list) else str(unknown)
                raise Precondition(
                    f"в каталоге сима нет буквы '{letters}' "
                    "(ассеты — python -m Services.line_sim.tools.build_stand_assets)"
                )
            raise Precondition(f"scene.sequence invalid: {res}")
        if res.get("status") != "ok" or res.get("queued") != len(discs):
            raise Precondition(f"scene.sequence не принят целиком: {res}")
        self.emit(f"{cid} scene.sequence: queued={res.get('queued')} dropped={res.get('dropped')}")

    def run_case(self, cid: str) -> None:
        assert self.layout is not None
        case = L.CASES[cid]
        if cid == "B":
            res = self.sim_cmd("camera", "scene.defect_rate", {"probability": 0.0})
            if not _ok(res):
                raise Precondition(f"scene.defect_rate не принят: {res}")
            self.changed_defect_rate = True
        self._set_pause(True)
        self._wait_scene_empty()
        self._tail_of_previous()
        self._silence()
        # база случая
        self.proto_cmd("devices", "robot_exchange_log_set", {**_EXCHANGE, "clear": True})
        n0 = self.last_seq()
        jobs0, done0 = self.sim_journal()
        self.layout.drain()
        dropped0 = self.layout.dropped
        before = L.regs_from_introspect(self.proto.introspect_registers("layout")).get("jobs_emitted", 0)
        seen_before = self._object_ids()
        # слово
        verified = self.proto.set_register_verified("layout", "word_layout", "target_word", case.word)
        if not (isinstance(verified, dict) and verified.get("verified") is True):
            row = L.Row(None, "word_set", case.word, str(verified), False, (f"word_set verified не True: {verified}",))
            self.emit(L.format_row(cid, row))
            self.statuses[cid] = "FAIL"
            self.results.append(row)
            raise CaseFail(row)
        self._send_sequence(cid, [[letter, angle] for letter, angle in case.discs])
        self._set_pause(False)
        # сбор
        exch = _Exchange(self, n0)
        msgs: list[str] = []
        feed_seen: dict[str, tuple[str, float]] = {}
        done_info: dict[str, Any] = {}

        def collected() -> bool:
            assert self.layout is not None
            msgs.extend(self.layout.drain())
            exch.poll()
            self._collect_feed(seen_before, feed_seen)
            seq = self.sim_cmd("camera", "scene.status", {}).get("sequence")
            done = self.sim_journal()[1] - done0
            done_info.update(seq=seq, done=done)
            total = len(case.discs)
            return (
                sum(1 for m in msgs if L.parse_layout_line(m) is not None) == total
                and len(L.parse_cvt_jobs(exch.texts())) == case.jobs
                and done == case.jobs
                and seq == {"mode": "list", "total": total, "fed": total, "skipped": 0, "remaining": 0}
            )

        arrived = self.wait_until("случай", 180.0, collected)
        regs = L.regs_from_introspect(self.proto.introspect_registers("layout"))
        snap = self.state_value(self.proto, "processes.layout.state.word_layout")
        feed = list(feed_seen.values()) if len(feed_seen) == len(case.discs) else None
        jobs = L.parse_cvt_jobs(exch.texts())
        result = L.judge_case(cid, msgs, jobs, regs, feed, int(before))
        extra: list[L.Row] = []
        if exch.dropped:
            extra.append(
                L.Row(None, "exchange", "", f"dropped={exch.dropped}", False, (f"exchange dropped {exch.dropped} ≠ 0",))
            )
        layout_dropped = self.layout.dropped - dropped0
        if layout_dropped:
            extra.append(
                L.Row(
                    None,
                    "layout_log",
                    "",
                    f"dropped={layout_dropped}",
                    False,
                    (f"layout_log dropped {layout_dropped} ≠ 0",),
                )
            )
        if not arrived:
            extra.append(
                L.Row(None, "feed", "", f"sequence={done_info.get('seq')} journal.done+{done_info.get('done')}", False,
                      (f"feed не пришло за 180 с: sequence={done_info.get('seq')}, "
                       f"journal.done +{done_info.get('done')} из {case.jobs}",))
            )  # fmt: skip
        self._finish_case(cid, case, result, extra, feed, msgs, snap, regs, exch)
        self.prev = _CaseState(case, n0, jobs0, done0)

    def _object_ids(self) -> set[str]:
        objects = self.state_value(self.sim, "sim.objects")
        return set(objects) if isinstance(objects, dict) else set()

    def _collect_feed(self, seen_before: set[str], feed_seen: dict[str, tuple[str, float]]) -> None:
        objects = self.state_value(self.sim, "sim.objects")
        if not isinstance(objects, dict):
            return
        for oid, passport in objects.items():
            if oid in seen_before or oid in feed_seen or not isinstance(passport, dict):
                continue
            letter, angle = passport.get("class_name"), passport.get("angle_deg")
            if isinstance(letter, str) and isinstance(angle, int | float):
                feed_seen[oid] = (letter, float(angle))

    def _finish_case(
        self,
        cid: str,
        case: L.Case,
        result: L.CaseResult,
        extra: list[L.Row],
        feed: list[tuple[str, float]] | None,
        msgs: list[str],
        snap: Any,
        regs: dict,
        exch: _Exchange,
    ) -> None:
        checks = (*result.checks, *extra)
        ok = result.ok and not extra
        result = L.CaseResult(cid, result.rows, checks, ok)
        word = [c for c in checks if c.check == "word_line"]
        for row in word:
            self.emit(L.format_row(cid, row))
        for row in result.rows:
            self.emit(L.format_row(cid, row))
        for row in checks:
            if row.check != "word_line":
                self.emit(L.format_row(cid, row))
        self.emit(f"{cid} INFO state processes.layout.state.word_layout: {snap}")
        if feed is None:
            self.emit(f"{cid} подача: sim.objects не дал полный список — углы по списку")
        # пары для блока углов: (буква, подача, сеть)
        lines = [ln for ln in (L.parse_layout_line(m) for m in msgs) if ln is not None]
        for i, line in enumerate(lines[: len(case.discs)]):
            fed = feed[i][1] if feed is not None else case.discs[i][1]
            self.angle_pairs.append((line.letter, fed, line.angle))
        self.statuses[cid] = "PASS" if ok else "FAIL"
        self.results.append(result)
        self.emit(f"{cid} случай: {self.statuses[cid]}")
        self.dump["cases"][cid] = {
            "layout": list(msgs),
            "exchange": [exch.acc[s] for s in sorted(exch.acc)],
            "feed": feed,
            "regs_after": regs,
            "state_snapshot": snap,
        }

    # --- P5, P6 ---------------------------------------------------------------------------------------------------
    def p5(self) -> None:
        self.n8 = self.last_seq()
        reply = self.proto.send_command("devices", "robot_park_all", {"timeout_s": 30.0}, timeout=40.0)
        res = _res(reply)
        seq = ((res.get("robots") or {}).get("robot_main") or {}).get("seq")
        state: dict | None = None

        def caught_up() -> bool:
            nonlocal state
            value = self.state_value(self.proto, "devices.state.robot_main.park")
            state = value if isinstance(value, dict) else None
            return state is not None and state.get("seq") == seq and state.get("state") == "done"

        self.wait_until("park", 5.0, caught_up)  # первому снимку не верим: статус отстаёт
        exch = _Exchange(self, self.n8)
        exch.poll()
        self.n9 = exch.last_seq
        row = L.judge_home(reply, state, exch.texts())
        self.statuses["ДОМОЙ"] = "PASS" if row.ok else "FAIL"
        self.results.append(row)
        self.emit(L.format_row("ДОМОЙ", row))

    def p6(self) -> None:
        reply = self.proto.system_shutdown(wait=True, wait_timeout=60.0)
        free = self.wait_until("порт", 10.0, lambda: self._listeners(self.args.proto_port) is None)
        shutdown_row = L.judge_shutdown(reply, free)
        path = self.log_dir / "devices" / "robot_exchange.log"
        file_lines = self._read_lines(path)
        if file_lines is None:
            stop_row = L.Row(
                None, "stop", "", "нет файла", False,
                (f"stop нет файла {path} (--log-dir; INSPECTOR_LOG_DIR при запуске прототипа)",),
            )  # fmt: skip
        else:
            after = self.n9 if self.n9 is not None else (self.n8 or 0)
            stop_row = L.judge_stop(file_lines, after)
        ok = shutdown_row.ok and stop_row.ok
        self.statuses["СТОП"] = "PASS" if ok else "FAIL"
        self.results.extend([shutdown_row, stop_row])
        self.emit(L.format_row("СТОП", shutdown_row))
        self.emit(L.format_row("СТОП", stop_row))

    # --- cleanup и итог -------------------------------------------------------------------------------------------
    def _cleanup_step(self, name: str, fn: Callable[[], str | None]) -> None:
        try:
            outcome = fn()
        except Exception as exc:  # noqa: BLE001 — каждый шаг уборки независим, ошибка печатается
            self.emit(f"cleanup: {name} → ошибка {_fmt_exc(exc)}")
            if name in self.statuses:
                self.statuses[name] = "FAIL"
                self.results.append(L.Row(None, name, "", _fmt_exc(exc), False, (f"{name} ошибка {_fmt_exc(exc)}",)))
        else:
            self.emit(f"cleanup: {name} → {outcome}")

    def cleanup(self) -> None:
        """Порядок: сначала прототип (ДОМОЙ, СТОП), потом снять паузу сима (иначе задания среди park)."""
        self.emit("cleanup: ДОМОЙ → СТОП → снять паузу сима")

        def home() -> str:
            self.p5()
            return self.statuses["ДОМОЙ"] or "—"

        def stop() -> str:
            self.p6()
            return self.statuses["СТОП"] or "—"

        def unpause() -> str:
            if not self.paused:
                return "пауза не ставилась"
            self._set_pause(False)
            return "пауза снята"

        self._cleanup_step("ДОМОЙ", home)
        self._cleanup_step("СТОП", stop)
        self._cleanup_step("пауза сима", unpause)

    def normal_tail(self) -> None:
        for name, fn in (("ДОМОЙ", self.p5), ("СТОП", self.p6)):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                self.emit(f"{name}: ошибка {_fmt_exc(exc)}")
                self.emit(traceback.format_exc().rstrip())
                self.statuses[name] = "FAIL"
                self.precond = True
                self.results.append(L.Row(None, name, "", _fmt_exc(exc), False, (f"{name} ошибка {_fmt_exc(exc)}",)))

    def angle_block(self) -> None:
        report = L.angle_report(self.angle_pairs)
        median = f", медиана Δ {report.median_delta:+.1f}°" if report.median_delta is not None else ""
        self.emit(f"углы: {report.verdict}{median}{self.angle_note}")
        for i, row in enumerate(report.rows, 1):
            self.emit(
                f"углы #{i} {row.letter}: подача {row.fed:.1f}° сеть {row.net:.1f}° "
                f"Δ={row.delta:+.1f}° Δинв={row.delta_inv:+.1f}°"
            )

    def finish(self) -> int:
        rc = L.exit_code(self.results, self.precond)
        self.angle_block()
        changed = []
        if self.changed_defect_rate:
            changed.append("defect_rate 0.0")
        if self.changed_belt:
            changed.append("лента 10 Гц (vfd_run прототипа)")
        if changed:
            self.emit("изменено в симе/на стенде: " + ", ".join(changed))
        self.emit(L.format_summary(self.statuses, rc))
        return rc

    def close(self) -> None:
        for drv in (self.proto, self.sim):
            if drv is None:
                continue
            try:
                drv.close()
            except Exception as exc:  # noqa: BLE001
                self.emit(f"close: ошибка {_fmt_exc(exc)}")

    def write_dump(self) -> None:
        if not self.args.dump:
            return
        if self.layout is not None:
            self.dump["layout_events"] = [{"seq": s, "message": m} for s, m in self.layout.events]
        self.dump["statuses"] = self.statuses
        Path(self.args.dump).write_text(
            json.dumps(self.dump, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )

    # --- главный порядок ------------------------------------------------------------------------------------------
    def execute(self) -> int:
        try:
            clean = self.p0()
        except ListenerProbeError as exc:
            self.emit(f"предусловие: не удалось определить слушателя порта: {exc}")
            clean = False
        if not clean:
            self.precond = True
            return self.finish()
        try:
            self.connect()
            self.p1()
            self.p2()
            self.p3()
        except Precondition as exc:
            self.emit(f"предусловие: {exc}")
            self.precond = True
            self.angle_note = " (сети нет)"
            return self._end()
        except Exception as exc:  # noqa: BLE001 — до P3 ничего не уборки: park/shutdown не зовутся
            self.emit(f"ошибка: {_fmt_exc(exc)}")
            self.emit(traceback.format_exc().rstrip())
            self.precond = True
            return self._end()
        aborted = False
        for cid in ("B", "D", "C"):
            try:
                self.run_case(cid)
            except CaseFail:
                aborted = True
            except Precondition as exc:
                self.emit(f"предусловие: {exc}")
                self.precond = True
                aborted = True
            except Exception as exc:  # noqa: BLE001
                self.emit(f"ошибка: {_fmt_exc(exc)}")
                self.emit(traceback.format_exc().rstrip())
                self.precond = True
                aborted = True
            if aborted:
                break
        if aborted:
            self.cleanup()
        else:
            self.normal_tail()
        return self._end()

    def _end(self) -> int:
        rc = self.finish()
        self.close()
        try:
            self.write_dump()
        except Exception as exc:  # noqa: BLE001
            self.emit(f"dump: ошибка {_fmt_exc(exc)}")
        return rc


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m scripts.alpha_sim.run_alpha", description=__doc__.split("\n")[0])
    p.add_argument("--tree", required=True, help="корень дерева стенда (сим и прототип запущены из него)")
    p.add_argument("--log-dir", default=None, help="каталог логов прототипа (умолчание <tree>/data/logs/prototype)")
    p.add_argument("--proto-port", type=int, default=8765)
    p.add_argument("--sim-port", type=int, default=8766)
    p.add_argument("--dump", default=None, help="файл .json: собранные записи (доказательство для Task 1.2)")
    return p


def run(
    argv: list[str],
    *,
    driver_factory: Callable[[int], Any],
    listeners: Callable[[int], ListenerInfo | None],
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    out: TextIO,
    read_lines: Callable[[Path], list[str] | None],
) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # argparse: ошибка аргументов → 2
        return int(exc.code) if isinstance(exc.code, int) else 2
    alpha = _Alpha(
        args,
        driver_factory=driver_factory,
        listeners=listeners,
        clock=clock,
        sleep=sleep,
        out=out,
        read_lines=read_lines,
    )
    return alpha.execute()


def main() -> int:
    import time

    from backend_ctl.driver import BackendDriver

    return run(
        sys.argv[1:],
        driver_factory=lambda port: BackendDriver(port=port, event_queue_maxlen=20000),
        listeners=lsof_listeners,
        clock=time.monotonic,
        sleep=time.sleep,
        out=sys.stdout,
        read_lines=_read_lines,
    )


if __name__ == "__main__":
    raise SystemExit(main())
