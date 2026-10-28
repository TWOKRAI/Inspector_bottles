# ruff: noqa: E501
"""Оркестратор живого стенда T5.3e: сценарии park P1-P3 (L1-L3 брифа T5.3e.3) + регрессия SPI.stand (S0, S1, G).

Копия `SPI.stand/run_stand.py` с правками T5.3e.3s: ключи `--scenario P1|P2|P3`, `--regress`, новая семантика
`--repeats`, счёт park (park.jsonl, jog.jsonl, program.jsonl). Основа - стенд SPI (S0-S3 как C-29 + device_io).
Восстановлено по описанию стенда C-29 (`plans/robot-protocol-v2/tasks/C-29.stand.md`, handoff T5.3h) - скрипты C-29
жили в scratchpad и потеряны (урок C-29: скрипты стенда - в git). Точная последовательность, время и числа - `README.md`.

Режимы:
    --scenario P1|P2|P3  сценарий park (L1-L3): группа D, подключение, готовность, сценарий, system_shutdown, count.py;
                    --repeats N (по умолчанию 3) - повтор прогона целиком, каждый в своём run-<время>/
    --regress       один прогон S0, S1 и G с прежними порогами SPI.stand (S2/S3 - только `--only S2,S3`)
    --dry-run       печатает план (команды, переменные, шаги), ничего не пишет и не запускает
    --prepare-only  пишет копию манифеста и рецепта `delta_v2` в --stand-root (вне git), проверяет загрузку манифеста
    (без флагов)    полный прогон: сим + бэкенд + сценарии + останов + count.py. ТОЛЬКО в окне стенда координатора.

Запускать главным .venv, `PYTHONPATH=<worktree>`, не из каталога `process_module`. Никаких `uv sync` / `uv run`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import socket
import subprocess  # nosec B404 - стенд запускает свои процессы по спискам аргументов, без shell
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
WORKTREE = HERE.parents[3]  # plans/robot-protocol-v2/tasks/T5.3e.stand -> корень worktree
MAIN_TREE = Path("D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles")
MAIN_PYTHON = MAIN_TREE / ".venv" / "Scripts" / "python.exe"
DEFAULT_STAND_ROOT = Path(tempfile.gettempdir()) / "t53e-stand"  # вне git; --stand-root переопределяет

ROBOT_ID = "robot_main"
VFD_ID = "vfd_belt"
SCENARIOS = ("S0", "S1", "S2", "S3")
PARAM_SETS_FULL = 58  # len(PARAM_ID) в Services/robot_comm/core/params_v2.py (проверено импортом, 2026-10-26)
S0_CONNECT_WAIT_S = 0.5  # S0: «Отключить» через столько после «Подключить» при сим DOWN
SETTLE_S = 2.0  # тишина после `disconnected`: поймать поздние SERVO/DO и тик-переподключение
TRIGGER_TIMEOUT_S = 260.0  # S3: 58 PARAM_SET при 300 мс - замер 2026-10-26: ~150 с
DISC_TIMEOUT_S = 30.0  # потолок ожидания `disconnected` после команды (критерий C-29 - 5,0 с)
POLL_S = 0.025
# Замер гонки introspect.* после старта бэкенда (одинаковый на ветке и на main - не менять между деревьями):
RACE_PAUSE_S = 0.1  # пауза между кругами опроса
RACE_CALL_TIMEOUT_S = 2.0  # срок одного вызова
RACE_EXTRA_S = 20.0  # после первого успешного device_list ждать introspect.* ещё не дольше
RACE_CMDS = ("introspect.status", "introspect.executors")
PARK_SCENARIOS = ("P1", "P2", "P3")
READY_DEADLINE_S = 20.0  # C-57: каждое из двух условий готовности, шаг 0,05 с
READY_STEP_S = 0.05
PARK_POLL_DEADLINE_S = 40.0  # итог park: опрос `.park`, шаг 0,05 с
PARK_POLL_STEP_S = 0.05
JOG_PERIOD_S = 0.05  # держатель P1: robot_jog_hold каждые <= 0,1 с
USER_PROGRAM = "p3"  # P3: программа пользователя
USER_PROGRAM_LEGS = 20  # P3: ходов (JOINT a/b, ~0,28 с каждый на симе без задержки)


# --------------------------------------------------------------------------- план / конфиг


def build_env(args: argparse.Namespace, run_dir: Path) -> dict[str, str]:
    """Окружение бэкенда: код из worktree, данные и логи - в каталог прогона (вне git), манифест - копия."""
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(args.worktree),
            "PYTHONUTF8": "1",
            "BACKEND_CTL": "1",
            "BACKEND_CTL_PORT": str(args.backend_port),
            "INSPECTOR_MANIFEST": str(args.stand_root / "manifest" / "app.yaml"),
            "INSPECTOR_DATA_DIR": str(run_dir / "data"),  # реестр devices.yaml и data/robot (хранилище точек)
            "MULTIPROCESS_LOG_DIR": str(run_dir / "logs"),
            "INSPECTOR_HEADLESS": "1",
        }
    )
    return env


def sim_cmd(args: argparse.Namespace, run_dir: Path) -> list[str]:
    return [
        str(args.python),
        str(HERE / "sim_v2.py"),
        "--log", str(run_dir / "sim.log"),
        "--ctl", str(run_dir / "sim.ctl"),
        "--port", str(args.sim_port),
        "--delay-ms", str(args.delay_ms),
        "--start-down",
    ]  # fmt: skip


def backend_cmd(args: argparse.Namespace) -> list[str]:
    return [str(args.python), "-m", "multiprocess_prototype.main", "--headless"]


PARK_PLAN_STEPS = {
    "P1": "mark P1; держатель robot_jog_hold каждые 0,05 с (до возврата system_shutdown); moving + 0,3 с -> robot_park; итог `.park`",
    "P2": "mark P2; robot_jog_step dx=80 (вне дома, без jog); robot_park -> done; robot_servo on; второй robot_park -> already",
    "P3": "mark P3; robot_point_save a, b; robot_program_save p3 (20 ходов); robot_program_run; done >= 3 -> robot_park; опрос `.program` 25 мс",
}


def print_park_plan(args: argparse.Namespace, env: dict[str, str], run_dir: Path, show: tuple[str, ...]) -> None:
    lines = [
        "ПЛАН park (dry-run: ничего не пишется и не запускается)",
        f"  worktree        {args.worktree}",
        f"  python          {args.python}",
        f"  stand-root      {args.stand_root}  (манифест и рецепт - вне git; каталог прогона - внутри)",
        f"  порты           сим 127.0.0.1:{args.sim_port} unit 2, backend_ctl 127.0.0.1:{args.backend_port}",
        f"  сценарий        {args.scenario}, повторов {args.repeats} (каждый - прогон целиком в своём run-<время>/), задержка сима {args.delay_ms} мс",
        "  окружение бэкенда и сима (cwd = каталог прогона):",
        *(f"    {k}={env[k]}" for k in show),
        "  шаги одного прогона:",
        "    0  preflight: порты свободны; import multiprocess_framework лежит в worktree; md5 app.yaml главного дерева; git status",
        "    1  сим:    " + " ".join(shlex.quote(c) for c in sim_cmd(args, run_dir)),
        "    2  бэкенд: " + " ".join(shlex.quote(c) for c in backend_cmd(args)) + f"   (до {args.boot_timeout:.0f} с)",
        "    3  D  (связи нет): introspect.executors; robot_point_list; key_missing; robot_stop {}; vfd_get_status",
        "    4  сим `up 0`; device_connect; готовность C-57: .conn connected, затем .status.ts > t_conn (по 20 с, шаг 0,05 с)",
        f"    5  {PARK_PLAN_STEPS[args.scenario]}",
        "    6  system_shutdown (graceful, настоящий process.stop); ctl `quit` симу; порты свободны; count.py (P-таблица, d1/L1/A1/E1)",
        "  время одного прогона: ~1 мин (старт бэкенда 10-30 с, D ~10 с, подключение ~5 с, сценарий 2-35 с, останов ~5 с); x повторов",
        "  ОКНО: живой прогон - только в stand-окне координатора (heavy); этот режим ничего не запускает.",
    ]
    print("\n".join(lines))


def print_plan(args: argparse.Namespace) -> None:
    run_dir = args.stand_root / "run-<ГГГГММДД-ЧЧММСС>"
    env = build_env(args, run_dir)
    show = ("PYTHONPATH", "PYTHONUTF8", "BACKEND_CTL", "BACKEND_CTL_PORT", "INSPECTOR_MANIFEST", "INSPECTOR_DATA_DIR",
            "MULTIPROCESS_LOG_DIR", "INSPECTOR_HEADLESS")  # fmt: skip
    only = ",".join(args.only)
    if args.scenario:
        print_park_plan(args, env, run_dir, show)
        return
    lines = [
        "ПЛАН (dry-run: ничего не пишется и не запускается)",
        f"  worktree        {args.worktree}",
        f"  python          {args.python}",
        f"  stand-root      {args.stand_root}  (манифест и рецепт - вне git; каталог прогона - внутри)",
        f"  порты           сим 127.0.0.1:{args.sim_port} unit 2, backend_ctl 127.0.0.1:{args.backend_port}",
        f"  сценарии        {only} (+ группы D до S0 и G после S3), задержка сима {args.delay_ms} мс",
        "  окружение бэкенда и сима (cwd = каталог прогона):",
        *(f"    {k}={env[k]}" for k in show),
        "  шаги:",
        "    0  preflight: порты свободны; import multiprocess_framework лежит в worktree; md5 app.yaml главного дерева; git status",
        "    1  сим:    " + " ".join(shlex.quote(c) for c in sim_cmd(args, run_dir)),
        "    2  бэкенд: " + " ".join(shlex.quote(c) for c in backend_cmd(args)) + "   (ждать ответ device_list, до "
        f"{args.boot_timeout:.0f} с)",
        "    3  D  (сим DOWN, робот не подключён): introspect.executors; robot_point_list {device_id}; "
        "robot_point_list {} -> key_missing; robot_stop {} ; vfd_get_status",
        f"    4  S0 сим DOWN: mark S0, device_connect, +{S0_CONNECT_WAIT_S} с device_disconnect, ctl `up 300`, ждать disconnected",
        "    5  S1 probe: mark S1, device_connect, триггер = первое чтение после `connect ok` в журнале драйвера -> device_disconnect",
        f"    6  S2 sync_params: триггер = 3-я запись PARAM_SET из {PARAM_SETS_FULL}",
        f"    7  S3 после sync, до SERVO: триггер = первая строка `out` после {PARAM_SETS_FULL}-й PARAM_SET",
        "    8  G  (ctl `delay 0`): device_connect до connected; robot_stop SOFT; vfd_get_status; robot_point_list; device_disconnect",
        "    9  останов: system_shutdown (graceful), ctl `quit` симу, порты свободны, git status, md5 app.yaml; count.py",
        "  процессы: оркестратор 1 + сим 1 + бэкенд 4 (корень/PM, devices, gui, robot) = 6 python (оценка; не замерено)",
        "  время: ~5 мин (старт бэкенда 10-30 с, S0 ~3 с, S1 ~6 с, S2 ~10 с, S3 ~1-2 мин, G ~15 с, останов ~5 с)",
        "  ОКНО: полный прогон - только в stand-окне координатора (heavy); этот режим ничего не запускает.",
    ]
    print("\n".join(lines))


# --------------------------------------------------------------------------- копия манифеста и рецепта


def prepare_copies(args: argparse.Namespace) -> Path:
    """Копия манифеста (абсолютные пути) и рецепта `delta_v2` без камеры и дисплея - вне git. Возвращает путь манифеста."""
    import yaml

    proto = args.worktree / "multiprocess_prototype"
    mdir = args.stand_root / "manifest"
    mdir.mkdir(parents=True, exist_ok=True)

    recipe = yaml.safe_load((proto / "recipes" / "robot_demo.yaml").read_text(encoding="utf-8"))
    recipe["name"] = "spi_stand_delta_v2"
    recipe["description"] = (
        "Стенд SPI: robot_demo с delta_v2 на 127.0.0.1:5021 unit 2, без камеры и дисплея (копия вне git)"
    )
    for dev in recipe["devices"]:
        if dev["id"] == ROBOT_ID:
            dev["protocol"] = "delta_v2"
            dev["transport"] = {"type": "tcp", "host": "127.0.0.1", "port": args.sim_port, "unit_id": 2}
            # on_connect: и SERVO, и DO, чтобы критерий «SERVO+DO после команды = 0» мог сработать на обоих
            dev["params"] = {"poll_interval_s": 0.5, "on_connect": {"servo": True, "do": {"1": True}}}
    if args.no_vfd:
        recipe["devices"] = [d for d in recipe["devices"] if d["kind"] != "vfd"]
    bp = recipe["blueprint"]
    bp["name"] = "spi_stand_delta_v2"
    bp["processes"] = [p for p in bp["processes"] if p["process_name"] != "camera_0"]
    bp.pop("displays", None)
    recipe.pop("displays", None)
    recipe_path = mdir / "stand_delta_v2.yaml"
    recipe_path.write_text(yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False), encoding="utf-8")

    app = yaml.safe_load((proto / "app.yaml").read_text(encoding="utf-8"))
    app["system"] = str((proto / app["system"]).resolve())
    if app.get("styles"):
        app["styles"]["dir"] = str((proto / app["styles"]["dir"]).resolve())
    base = app["base"] if isinstance(app["base"], list) else [app["base"]]
    app["base"] = [str((proto / b).resolve()) for b in base]
    app["recipes"] = str((proto / app["recipes"]).resolve())
    app["pipeline"] = str(recipe_path.resolve())
    manifest_path = mdir / "app.yaml"
    manifest_path.write_text(yaml.safe_dump(app, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"копия манифеста: {manifest_path}\nкопия рецепта:   {recipe_path}")

    # Проверка загрузки (чистая загрузка конфига, бэкенд не поднимается); cwd - не process_module.
    code = (
        "from multiprocess_prototype.backend.config.manifest import load_manifest;"
        f"m=load_manifest(r'{manifest_path}');print('manifest ok: pipeline =', m.pipeline, '| base =', len(m.base))"
    )
    res = subprocess.run(  # nosec B603
        [str(args.python), "-c", code], cwd=args.stand_root, env={**os.environ, "PYTHONPATH": str(args.worktree), "PYTHONUTF8": "1"},
        capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    print((res.stdout or res.stderr).strip())
    if res.returncode != 0:
        raise SystemExit("загрузка копии манифеста не удалась")
    return manifest_path


# --------------------------------------------------------------------------- рабочие части прогона


class EventLog:
    """`events.jsonl`: метки и команды оркестратора с `time.time()` - читает count.py."""

    def __init__(self, path: Path) -> None:
        self._fh = path.open("a", encoding="utf-8", buffering=1)
        self._lock = threading.Lock()

    def __call__(self, ev: str, **kw: Any) -> float:
        t = time.time()
        with self._lock:
            self._fh.write(json.dumps({"t": round(t, 3), "ev": ev, **kw}, ensure_ascii=False, default=str) + "\n")
        return t


class Poller(threading.Thread):
    """Поток со своим драйвером backend_ctl: опрос каждые 25 мс до `stop`."""

    period = POLL_S  # пауза между шагами; наследник вправе задать свою

    def __init__(self, name: str, port: int) -> None:
        super().__init__(name=name, daemon=True)
        from backend_ctl.driver import BackendDriver

        self.drv = BackendDriver(port=port)
        self.drv.connect(5.0)
        self.halt = threading.Event()
        self.lock = threading.Lock()

    def step(self) -> None:  # переопределяется
        raise NotImplementedError

    def run(self) -> None:
        while not self.halt.is_set():
            try:
                self.step()
            except Exception as exc:  # noqa: BLE001 - стенд: сбой опроса считаем, не роняем поток
                with self.lock:
                    self.errors = getattr(self, "errors", 0) + 1
                    self.last_error = f"{type(exc).__name__}: {exc}"
            self.halt.wait(self.period)

    def close(self) -> None:
        self.halt.set()
        self.join(timeout=5.0)
        self.drv.close()


class StatusPoller(Poller):
    """`devices.state.<id>.conn` через `state.get` -> `status.jsonl` (запись на каждую смену значения)."""

    def __init__(self, port: int, path: Path) -> None:
        super().__init__("status-poller", port)
        self._fh = path.open("a", encoding="utf-8", buffering=1)
        self.history: list[tuple[float, str]] = []

    def step(self) -> None:
        res = self.drv.send_command(
            "ProcessManager", "state.get", {"path": f"devices.state.{ROBOT_ID}.conn"}, timeout=2.0
        )
        value = find_key(res, "value")
        conn = value.get("conn") if isinstance(value, dict) else (value if isinstance(value, str) else "none")
        t = time.time()
        with self.lock:
            if not self.history or self.history[-1][1] != conn:
                self.history.append((t, conn))
                self._fh.write(json.dumps({"t": round(t, 3), "conn": conn}) + "\n")

    def current(self) -> str:
        with self.lock:
            return self.history[-1][1] if self.history else "none"

    def first_after(self, t0: float, conn: str) -> float | None:
        with self.lock:
            return next((t for t, c in self.history if t > t0 and c == conn), None)


class JournalPoller(Poller):
    """Журнал обмена драйвера (`robot_exchange_log_get`) -> `journal.jsonl`; строка пишется при новом (seq, n)."""

    def __init__(self, port: int, path: Path) -> None:
        super().__init__("journal-poller", port)
        self._fh = path.open("a", encoding="utf-8", buffering=1)
        self.lines: dict[int, dict[str, Any]] = {}
        self._cursor = 0

    def step(self) -> None:
        res = self.drv.send_command("devices", "robot_exchange_log_get",
                                    {"device_id": ROBOT_ID, "since_seq": self._cursor, "limit": 500}, timeout=2.0)  # fmt: skip
        for line in find_key(res, "lines") or []:
            seq, n = int(line["seq"]), int(line.get("n", 1))
            with self.lock:
                known = self.lines.get(seq)
                if known is not None and int(known.get("n", 1)) == n:
                    continue
                self.lines[seq] = line
                self._cursor = max(self._cursor, seq)
                self._fh.write(json.dumps({"t_rx": round(time.time(), 3), **line}, ensure_ascii=False) + "\n")

    def last_seq(self) -> int:
        with self.lock:
            return max(self.lines, default=0)

    def after(self, seq0: int) -> list[dict[str, Any]]:
        with self.lock:
            return [self.lines[s] for s in sorted(self.lines) if s > seq0]


def reply_body(res: Any) -> Any:
    """Тело ответа команды хаба: `{result: {...}}` без `status` разворачивается, иначе ответ как есть."""
    return res.get("result", res) if isinstance(res, dict) and set(res) >= {"result"} and "status" not in res else res


class JogHolder(Poller):
    """Держатель P1: `robot_jog_hold` каждые ~0,05 с до `close()`; каждый ответ - строка `jog.jsonl` (`t` - отправка)."""

    period = JOG_PERIOD_S

    def __init__(self, port: int, path: Path) -> None:
        super().__init__("jog-holder", port)
        self._fh = path.open("a", encoding="utf-8", buffering=1)
        self.ok = 0
        self.total = 0

    def step(self) -> None:
        t_send = time.time()
        try:
            res = self.drv.send_command(
                "devices", "robot_jog_hold", {"device_id": ROBOT_ID, "dir": 1, "spd": 20}, timeout=1.0
            )
            body = reply_body(res)
            status = body.get("status") if isinstance(body, dict) else None
            message = body.get("message") if isinstance(body, dict) else repr(body)[:200]
        except Exception as exc:  # noqa: BLE001 - ответа нет (бэкенд закрывается): строка с исключением
            status, message = "exception", f"{type(exc).__name__}: {exc}"[:200]
        row = {"t": round(t_send, 3), "t_rx": round(time.time(), 3), "status": status, "message": message}
        with self.lock:
            self.total += 1
            self.ok += status == "ok"
            self._fh.write(json.dumps(row, ensure_ascii=False) + "\n")


class ProgramPoller(Poller):
    """`devices.state.<id>.program` через `state.get` каждые 25 мс -> `program.jsonl` (строка на смену name/state/done)."""

    def __init__(self, port: int, path: Path) -> None:
        super().__init__("program-poller", port)
        self._fh = path.open("a", encoding="utf-8", buffering=1)
        self.last: dict[str, Any] | None = None

    def step(self) -> None:
        res = self.drv.send_command(
            "ProcessManager", "state.get", {"path": f"devices.state.{ROBOT_ID}.program"}, timeout=2.0
        )
        value = find_key(res, "value")
        if not isinstance(value, dict):
            return
        key = (value.get("name"), value.get("state"), value.get("done"))
        with self.lock:
            if self.last is not None and (self.last.get("name"), self.last.get("state"), self.last.get("done")) == key:
                return
            self.last = value
            self._fh.write(json.dumps({"t": round(time.time(), 3), "value": value}, ensure_ascii=False) + "\n")

    def current(self) -> dict[str, Any] | None:
        with self.lock:
            return self.last


def op_count(lines: list[dict[str, Any]], opname: str) -> int:
    """Сколько записей кода операции `opname` (сумма `n` склеек)."""
    pat = re.compile(rf"^W\*? CMD_OPCODE = \d+ \({opname}\)")
    return sum(int(x.get("n", 1)) for x in lines if pat.match(x.get("text", "")))


class Stand:
    def __init__(self, args: argparse.Namespace, run_dir: Path) -> None:
        self.args, self.run_dir = args, run_dir
        self.env = build_env(args, run_dir)
        self.ev = EventLog(run_dir / "events.jsonl")
        self.procs: dict[str, subprocess.Popen] = {}
        self.drv: Any = None
        self.status: StatusPoller
        self.journal: JournalPoller
        self.checks: dict[str, Any] = {"meta": {"device_io_expected": not getattr(args, "base", False)}}
        self.holder: JogHolder | None = None
        self.program: ProgramPoller | None = None
        self.park_fh = (run_dir / "park.jsonl").open("a", encoding="utf-8", buffering=1)
        self.spawn_t: dict[str, float] = {}

    # ---- процессы
    def spawn(self, name: str, cmd: list[str]) -> None:
        out = (self.run_dir / f"{name}.out.log").open("w", encoding="utf-8")
        self.spawn_t[name] = time.time()  # точка отсчёта замера гонки - до Popen
        self.procs[name] = subprocess.Popen(  # nosec B603
            cmd, cwd=self.run_dir, env=self.env, stdout=out, stderr=subprocess.STDOUT
        )
        self.ev("spawn", name=name, pid=self.procs[name].pid, cmd=cmd)

    def sim_ctl(self, line: str) -> None:
        with (self.run_dir / "sim.ctl").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        self.ev("sim_ctl", line=line)

    def hub(self, cmd: str, timeout: float = 10.0, **data: Any) -> Any:
        t0 = time.time()
        res = self.drv.send_command("devices", cmd, data, timeout=timeout)
        self.ev("hub", cmd=cmd, data=data, reply=res, elapsed_s=round(time.time() - t0, 3))
        return res

    def wait_for(self, pred, timeout: float, what: str):
        end = time.time() + timeout
        while time.time() < end:
            got = pred()
            if got:
                return got
            time.sleep(0.01)
        self.ev("timeout", what=what, timeout_s=timeout)
        return None

    # ---- запуск бэкенда и замер гонки introspect.* (одно правило на ветке и на main)
    def race_probe(self, t_spawn: float) -> None:
        """Опрос сразу после старта процесса бэкенда: круг = connect (если нет) -> device_list -> introspect.* у devices.

        Каждая попытка пишется в `race.jsonl`: {i, cmd, t_start_s, t_end_s (от `Popen` бэкенда), ok, err}. Команда,
        получившая ok, больше не опрашивается. Конец: device_list с robot_main И introspect.status ok И (introspect.executors
        ok ИЛИ прошло RACE_EXTRA_S после первого успешного device_list). Итог - `race.json` и таблица в stdout.
        """
        from backend_ctl.driver import BackendDriver

        fh = (self.run_dir / "race.jsonl").open("a", encoding="utf-8", buffering=1)
        calls: dict[str, list[dict[str, Any]]] = {}

        def rec(i: int, cmd: str, t0: float, ok: bool, err: str = "") -> bool:
            row = {
                "i": i,
                "cmd": cmd,
                "t_start_s": round(t0 - t_spawn, 3),
                "t_end_s": round(time.time() - t_spawn, 3),
                "ok": ok,
                "err": err,
            }
            calls.setdefault(cmd, []).append(row)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            return ok

        def err_text(res: Any) -> str:
            return str(find_key(res, "reason") or find_key(res, "error") or find_key(res, "message") or repr(res))[:200]

        t_hub_ok: float | None = None
        deadline = time.time() + self.args.boot_timeout
        i = 0
        while time.time() < deadline:
            i += 1
            if self.procs["backend"].poll() is not None:
                raise SystemExit(f"бэкенд завершился при старте, код {self.procs['backend'].returncode}")
            if self.drv is None:
                t0 = time.time()
                try:
                    drv = BackendDriver(port=self.args.backend_port)
                    drv.connect(1.0)
                    self.drv = drv
                    rec(i, "connect", t0, True)
                except Exception as exc:  # noqa: BLE001 - бэкенд ещё поднимается: текст ошибки в журнал
                    rec(i, "connect", t0, False, repr(exc)[:200])
                    time.sleep(RACE_PAUSE_S)
                    continue
            if t_hub_ok is None:
                t0 = time.time()
                try:
                    res = self.drv.send_command("devices", "device_list", {}, timeout=RACE_CALL_TIMEOUT_S)
                    ids = [d.get("id") for d in (find_key(res, "devices") or []) if isinstance(d, dict)]
                    if rec(i, "device_list", t0, ROBOT_ID in ids, "" if ROBOT_ID in ids else err_text(res)):
                        t_hub_ok = time.time()
                except Exception as exc:  # noqa: BLE001
                    rec(i, "device_list", t0, False, repr(exc)[:200])
            for cmd in RACE_CMDS:
                if any(c["ok"] for c in calls.get(cmd, [])):
                    continue
                t0 = time.time()
                try:
                    res = self.drv.send_command("devices", cmd, {}, timeout=RACE_CALL_TIMEOUT_S)
                    ok = isinstance(res, dict) and res.get("success") is True
                    rec(i, cmd, t0, ok, "" if ok else err_text(res))
                except Exception as exc:  # noqa: BLE001
                    rec(i, cmd, t0, False, repr(exc)[:200])
            got = {c: any(x["ok"] for x in calls.get(c, [])) for c in RACE_CMDS}
            if (
                t_hub_ok is not None
                and got["introspect.status"]
                and (got["introspect.executors"] or time.time() - t_hub_ok > RACE_EXTRA_S)
            ):
                break
            time.sleep(RACE_PAUSE_S)
        fh.close()
        summary: dict[str, Any] = {}
        for cmd in ("connect", "device_list", *RACE_CMDS):
            rows = calls.get(cmd, [])
            first = next((r for r in rows if r["ok"]), None)
            errs: dict[str, int] = {}
            for r in rows:
                if not r["ok"]:
                    errs[r["err"]] = errs.get(r["err"], 0) + 1
            summary[cmd] = {
                "ok": first is not None,
                "attempts_to_first_ok": (rows.index(first) + 1) if first else None,
                "attempts_total": len(rows),
                "t_first_ok_s": first["t_end_s"] if first else None,
                "errors": errs,
            }
        (self.run_dir / "race.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        self.checks["race"] = summary
        self.ev("race", summary=summary)
        print(f"ГОНКА introspect (от Popen бэкенда; пауза {RACE_PAUSE_S} с, вызов <= {RACE_CALL_TIMEOUT_S} с):")
        for cmd, v in summary.items():
            print(
                f"  {cmd}: ok={v['ok']} попыток до успеха={v['attempts_to_first_ok']} (всего {v['attempts_total']}), "
                f"первый успех на {v['t_first_ok_s']} с, ошибки={v['errors']}"
            )

    def start_race_only(self) -> None:
        self.spawn("backend", backend_cmd(self.args))
        self.race_probe(self.spawn_t["backend"])

    # ---- старт
    def start(self) -> None:
        self.spawn("sim", sim_cmd(self.args, self.run_dir))
        if not self.wait_for(lambda: "SIM start" in (self.run_dir / "sim.log").read_text(encoding="utf-8", errors="replace")
                             if (self.run_dir / "sim.log").exists() else False, 30, "sim start"):  # fmt: skip
            raise SystemExit("сим не стартовал за 30 с (см. sim.out.log)")
        self.spawn("backend", backend_cmd(self.args))
        self.race_probe(self.spawn_t["backend"])
        self.status = StatusPoller(self.args.backend_port, self.run_dir / "status.jsonl")
        self.journal = JournalPoller(self.args.backend_port, self.run_dir / "journal.jsonl")
        self.status.start()
        self.journal.start()
        self.ev("ready")

    # ---- группа D: device_io и формы ответов до связи
    def group_d(self) -> None:
        d: dict[str, Any] = {}
        # introspect.* у devices сразу после старта мог отвечать «No handler» (замер 2026-10-26) - повторы до 20 с
        for attempt in range(3 if self.args.base else 20):
            d["executors"] = self.drv.send_command("devices", "introspect.executors", {}, timeout=5.0)
            st = self.drv.send_command("devices", "introspect.status", {}, timeout=5.0)
            d["introspect_attempts"] = attempt + 1
            if "No handler" not in json.dumps(d["executors"], ensure_ascii=False):
                break
            time.sleep(1.0)
        d["workers_keyed"] = sorted(
            w for w in json.dumps(st, ensure_ascii=False).split('"') if w.startswith("keyed-device_io")
        )
        t0 = time.time()
        d["point_list"] = self.hub("robot_point_list", device_id=ROBOT_ID)
        d["point_list_s"] = round(time.time() - t0, 3)
        d["point_list_no_id"] = self.hub("robot_point_list")  # ждём {"success": False, "error": "key_missing", ...}
        d["robot_stop_no_id"] = self.hub("robot_stop")  # не привязана к исполнителю: ждём "device_id обязателен"
        if not self.args.no_vfd:
            d["vfd_get_status_offline"] = self.hub("vfd_get_status", device_id=VFD_ID)
        self.checks["D"] = d

    # ---- сценарии S0-S3
    def scenario(self, name: str) -> None:
        sim_log = self.run_dir / "sim.log"
        self.sim_ctl(f"mark {name}")
        time.sleep(0.2)  # дать симу записать MARK раньше первого обмена сценария
        seq0 = self.journal.last_seq()
        t_mark = self.ev("scenario_start", scen=name, seq0=seq0)
        self.hub("device_connect", device_id=ROBOT_ID)
        reached = self._wait_trigger(name, seq0)
        seq_at_cmd = self.journal.last_seq()
        t_cmd = self.ev("disconnect_send", scen=name, seq_at_cmd=seq_at_cmd, trigger_reached=bool(reached))
        reply = self.hub("device_disconnect", device_id=ROBOT_ID)
        t_reply = self.ev("disconnect_reply", scen=name, reply=reply)
        if name == "S0":
            self.sim_ctl("up 300")
        t_disc = self.wait_for(
            lambda: self.status.first_after(t_cmd, "disconnected"), DISC_TIMEOUT_S, f"{name} disconnected"
        )
        self.ev("disconnected_seen", scen=name, t_disc=t_disc, disc_s=round(t_disc - t_cmd, 3) if t_disc else None)
        time.sleep(SETTLE_S)
        lines = self.journal.after(seq0)
        before = [x for x in lines if x["seq"] <= seq_at_cmd]
        self.ev("scenario_end", scen=name, t_mark=t_mark, t_reply=t_reply, sim_log_bytes=sim_log.stat().st_size,
                phase={"connect_ok": any(x["text"] == "connect ok" for x in before),
                       "param_set_before": op_count(before, "PARAM_SET"), "servo_before": op_count(before, "SERVO")})  # fmt: skip

    def _wait_trigger(self, name: str, seq0: int) -> bool:
        if name == "S0":
            time.sleep(S0_CONNECT_WAIT_S)
            return True

        def trig() -> bool:
            lines = self.journal.after(seq0)
            if name == "S1":
                ok = next((x["seq"] for x in lines if x["text"] == "connect ok"), None)
                return ok is not None and any(x["seq"] > ok and x["side"] == "out" for x in lines)
            n_need = 3 if name == "S2" else self.args.param_sets
            seen = 0
            for x in lines:
                if seen >= n_need and name == "S3" and x["side"] == "out":
                    return True  # первая строка `out` после последней PARAM_SET
                if re.match(r"^W\*? CMD_OPCODE = \d+ \(PARAM_SET\)", x.get("text", "")):
                    seen += int(x.get("n", 1))
            return name == "S2" and seen >= n_need

        return bool(self.wait_for(trig, TRIGGER_TIMEOUT_S, f"{name} trigger"))

    # ---- сценарии park P1-P3 (L1-L3): сим без задержки, готовность C-57, итог по `.park`
    def state_value(self, leaf: str) -> Any:
        res = self.drv.send_command(
            "ProcessManager", "state.get", {"path": f"devices.state.{ROBOT_ID}.{leaf}"}, timeout=2.0
        )
        return find_key(res, "value")

    def telemetry(self) -> dict[str, Any]:
        value = self.state_value("status")
        tel = value.get("telemetry") if isinstance(value, dict) else None
        return tel if isinstance(tel, dict) else {}

    def wait_ready(self) -> int:
        """C-57: `.conn` -> connected (t_conn = этот момент), затем `.status.ts > t_conn`; по 20 с, шаг 0,05 с. Число попыток."""
        attempts = 0
        t_conn: float | None = None
        end = time.time() + READY_DEADLINE_S
        while t_conn is None and time.time() < end:
            attempts += 1
            try:
                value = self.state_value("conn")
            except Exception:  # noqa: BLE001 - timeout / нет хендлера: ждать дальше
                value = None
            if isinstance(value, dict) and value.get("conn") == "connected":
                t_conn = time.time()
            else:
                time.sleep(READY_STEP_S)
        if t_conn is None:
            raise SystemExit(f"не готов: .conn не стал connected за {READY_DEADLINE_S} с")
        end = time.time() + READY_DEADLINE_S
        while time.time() < end:
            attempts += 1
            try:
                value = self.state_value("status")
            except Exception:  # noqa: BLE001
                value = None
            if isinstance(value, dict) and isinstance(value.get("ts"), (int, float)) and value["ts"] > t_conn:
                return attempts
            time.sleep(READY_STEP_S)
        raise SystemExit(f"не готов: .status с ts > t_conn не появился за {READY_DEADLINE_S} с")

    def park_cmd(self, label: str) -> tuple[dict[str, Any], float]:
        """`robot_park {device_id}`: ответ, момент его прихода. Событие `park_reply` - читает count.py."""
        t_send = time.time()
        res = self.hub("robot_park", device_id=ROBOT_ID)
        t_rx = time.time()
        body = reply_body(res)
        body = body if isinstance(body, dict) else {"raw": repr(body)[:200]}
        self.ev(
            "park_reply",
            label=label,
            t_send=round(t_send, 3),
            t_rx=round(t_rx, 3),
            elapsed_s=round(t_rx - t_send, 3),
            reply=body,
        )
        return body, t_rx

    def park_final(self, label: str, reply: dict[str, Any], t_reply: float) -> dict[str, Any] | None:
        """Опрос `.park` до `value.seq == seq ответа` и `state in {done, failed}` (40 с, шаг 0,05 с); пишет `park.jsonl`."""
        seq = reply.get("seq")
        last: Any = None
        end = time.time() + PARK_POLL_DEADLINE_S
        final: dict[str, Any] | None = None
        t_final: float | None = None
        while isinstance(seq, int) and time.time() < end:
            value = self.state_value("park")
            t = time.time()
            if isinstance(value, dict) and value != last:
                last = value
                self.park_fh.write(
                    json.dumps({"t": round(t, 3), "label": label, "value": value}, ensure_ascii=False) + "\n"
                )
            if isinstance(value, dict) and value.get("seq") == seq and value.get("state") in ("done", "failed"):
                final, t_final = value, t
                break
            time.sleep(PARK_POLL_STEP_S)
        self.ev(
            "park_final",
            label=label,
            t_reply=round(t_reply, 3),
            t_final=round(t_final, 3) if t_final else None,
            value=final,
        )
        return final

    def park_scenario(self, name: str) -> None:
        """Подъём связи (сим был DOWN на группе D), подключение, готовность C-57, затем P1 / P2 / P3."""
        self.sim_ctl("up 0")
        sim_log = self.run_dir / "sim.log"
        if not self.wait_for(
            lambda: "done up 0" in sim_log.read_text(encoding="utf-8", errors="replace"), 10, "sim up"
        ):
            raise SystemExit("сим не поднял слушатель за 10 с")
        self.hub("device_connect", device_id=ROBOT_ID)
        self.ev("ready", attempts=self.wait_ready())
        self.sim_ctl(f"mark {name}")
        time.sleep(0.2)  # дать симу записать MARK раньше первого обмена сценария
        self.ev("scenario_start", scen=name)
        getattr(self, f"scenario_{name.lower()}")()
        self.ev("scenario_end", scen=name)

    def scenario_p1(self) -> None:
        """L1: держатель jog шлёт `robot_jog_hold` до возврата `system_shutdown`; через 0,3 с после moving - `robot_park`."""
        self.holder = JogHolder(self.args.backend_port, self.run_dir / "jog.jsonl")
        self.holder.start()
        if not self.wait_for(lambda: self.holder.ok >= 1, 3.0, "P1 первый ok держателя"):
            self.ev("precondition_failed", what="держатель не получил ok за 3 с")
        if not self.wait_for(lambda: self.telemetry().get("moving") is True, 5.0, "P1 moving"):
            self.ev("precondition_failed", what="telemetry.moving не стал True за 5 с")
        time.sleep(0.3)
        reply, t_reply = self.park_cmd("P1")
        self.park_final("P1", reply, t_reply)  # затем finish(): system_shutdown, держатель живёт до его возврата

    def scenario_p2(self) -> None:
        """L2: первый park без jog (робот вне дома, простой), `robot_servo on`, второй park."""
        x0 = self.telemetry().get("x_mm")

        def stands_off_home() -> bool:
            tel = self.telemetry()
            return (
                isinstance(x0, (int, float))
                and abs((tel.get("x_mm") or 0.0) - (x0 + 80.0)) <= 0.1
                and tel.get("moving") is False
            )

        self.hub("robot_jog_step", device_id=ROBOT_ID, dx=80, dy=0, spd=50)
        if not self.wait_for(stands_off_home, 10.0, "P2 робот вне дома, стоит"):
            self.ev("precondition_failed", what="робот не вышел из дома шагом jog за 10 с")
        reply1, t1 = self.park_cmd("P2.1")
        self.park_final("P2.1", reply1, t1)
        self.hub("robot_servo", device_id=ROBOT_ID, on=True)
        time.sleep(0.5)
        reply2, t2 = self.park_cmd("P2.2")
        self.park_final("P2.2", reply2, t2)

    def scenario_p3(self) -> None:
        """L3: точки a, b и программа p3 (20 ходов) через хранилище, `robot_program_run`, park после >= 3 ходов."""
        point_a = {"name": "a", "x": 400.0, "y": 100.0, "z": -60.0, "rz": 0.0, "hand": 1, "frame": None}
        # b не должна совпадать с P_HOME (300, -210, -40, -100): иначе после abort робот уже дома (home == already)
        point_b = {"name": "b", "x": 300.0, "y": 210.0, "z": -40.0, "rz": 100.0, "hand": 1, "frame": None}
        first = reply_body(self.hub("robot_point_save", device_id=ROBOT_ID, point=point_a, base_rev=None))
        rev = first.get("rev") if isinstance(first, dict) else None
        self.hub("robot_point_save", device_id=ROBOT_ID, point=point_b, base_rev=rev)
        steps = [{"op": "move", "point": "a" if i % 2 == 0 else "b", "kind": "JOINT"} for i in range(USER_PROGRAM_LEGS)]
        self.hub(
            "robot_program_save", device_id=ROBOT_ID, program={"name": USER_PROGRAM, "steps": steps}, base_rev=None
        )
        self.program = ProgramPoller(self.args.backend_port, self.run_dir / "program.jsonl")
        self.program.start()
        self.hub("robot_program_run", device_id=ROBOT_ID, name=USER_PROGRAM)

        def three_legs() -> bool:
            cur = self.program.current() if self.program else None
            return (
                bool(cur)
                and cur.get("name") == USER_PROGRAM
                and cur.get("state") == "running"
                and (cur.get("done") or 0) >= 3
            )

        if not self.wait_for(three_legs, 20.0, "P3 программа пользователя: running, done >= 3"):
            self.ev("precondition_failed", what="программа пользователя не дошла до 3 ходов в running за 20 с")
        reply, t_reply = self.park_cmd("P3")
        self.park_final("P3", reply, t_reply)

    # ---- группа G: подключённый робот на быстром симе
    def group_g(self) -> None:
        g: dict[str, Any] = {}
        self.sim_ctl("delay 0")
        self.sim_ctl("mark G")
        time.sleep(0.3)
        self.hub("device_connect", device_id=ROBOT_ID)
        g["connected"] = bool(self.wait_for(lambda: self.status.current() == "connected", 90, "G connected"))
        if g["connected"]:
            self.sim_ctl("mark G_STOP")
            time.sleep(0.2)
            g["robot_stop"] = self.hub("robot_stop", device_id=ROBOT_ID, level="SOFT")
            time.sleep(1.0)
            if not self.args.no_vfd:
                g["vfd_get_status"] = self.hub("vfd_get_status", device_id=VFD_ID)
            g["point_list"] = self.hub("robot_point_list", device_id=ROBOT_ID)
        t_cmd = self.ev("disconnect_send", scen="G")
        self.hub("device_disconnect", device_id=ROBOT_ID)
        g["disconnected"] = bool(
            self.wait_for(lambda: self.status.first_after(t_cmd, "disconnected"), DISC_TIMEOUT_S, "G disc")
        )
        self.checks["G"] = g

    # ---- останов и уборка
    def finish(self, main_md5_before: str, status_before: str) -> None:
        for p in (getattr(self, "status", None), getattr(self, "journal", None), self.program):
            if p is not None:
                p.close()
        res: dict[str, Any] = {}
        if self.drv is not None:
            self.ev("shutdown_send")
            try:
                res["shutdown"] = self.drv.system_shutdown(wait=True, wait_timeout=20.0)
            except Exception as exc:  # noqa: BLE001
                res["shutdown_error"] = f"{type(exc).__name__}: {exc}"
            self.ev("shutdown_reply")
            self.drv.close()
        if self.holder is not None:  # P1: держатель шлёт до возврата system_shutdown
            self.holder.close()
        self.park_fh.close()
        for name in ("backend", "sim"):
            proc = self.procs.get(name)
            if proc is None:
                continue
            if name == "sim":
                self.sim_ctl("quit")
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                res[f"{name}_terminated"] = True  # только свой PID, не taskkill /IM
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            res[f"{name}_exit"] = proc.returncode
        res["ports_free"] = {p: port_free(p) for p in (self.args.sim_port, self.args.backend_port)}
        res["main_app_yaml_md5_same"] = md5(MAIN_TREE / "multiprocess_prototype" / "app.yaml") == main_md5_before
        res["worktree_status_same"] = git_status(self.args.worktree) == status_before
        # Строки хаба про исполнитель: WARNING «исполнитель ... не найден» здесь быть не должно (А23 наоборот).
        hits = []
        for log in (self.run_dir / "logs").rglob("*.log"):
            if "devices" in log.parts:
                hits += [f"{log.name}: {ln.strip()}" for ln in log.read_text(encoding="utf-8", errors="replace").splitlines()
                         if "исполнител" in ln]  # fmt: skip
        res["devices_log_executor_lines"] = hits
        self.checks["finish"] = res
        (self.run_dir / "checks.json").write_text(
            json.dumps(self.checks, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )


def find_key(res: Any, key: str, depth: int = 3) -> Any:
    """Значение `key` в ответе команды: на верхнем уровне или во вложенных `result` (форма обёртки не проверялась)."""
    if isinstance(res, dict):
        if key in res:
            return res[key]
        if depth:
            for v in res.values():
                got = find_key(v, key, depth - 1)
                if got is not None:
                    return got
    return None


def port_free(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def git_status(tree: Path) -> str:
    return subprocess.run(  # nosec B603 B607
        ["git", "status", "--porcelain"], cwd=tree, capture_output=True, text=True, timeout=60
    ).stdout


def preflight(args: argparse.Namespace, run_dir: Path) -> None:
    busy = [p for p in (args.sim_port, args.backend_port) if not port_free(p)]
    if busy:
        raise SystemExit(f"порты заняты: {busy} (чужой стенд? проверь stand.lock)")
    res = subprocess.run([str(args.python), "-c", "import multiprocess_framework as m; print(m.__file__)"], cwd=run_dir,  # nosec B603
                         env={**os.environ, "PYTHONPATH": str(args.worktree)}, capture_output=True, text=True, timeout=120)  # fmt: skip
    path = res.stdout.strip()
    print(f"import multiprocess_framework -> {path}")
    if Path(path).resolve().as_posix().lower().find(args.worktree.resolve().as_posix().lower()) != 0:
        raise SystemExit("ЛОЖНАЯ ЗЕЛЁНКА: multiprocess_framework импортируется не из worktree")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="напечатать план, ничего не писать и не запускать")
    ap.add_argument("--prepare-only", action="store_true", help="записать копию манифеста и рецепта и выйти")
    ap.add_argument("--worktree", type=Path, default=WORKTREE)
    ap.add_argument("--python", type=Path, default=MAIN_PYTHON, help="python главного .venv")
    ap.add_argument("--stand-root", type=Path, default=DEFAULT_STAND_ROOT)
    ap.add_argument("--only", default=",".join(SCENARIOS), help="сценарии через запятую, по умолчанию S0,S1,S2,S3")
    ap.add_argument("--no-vfd", action="store_true", help="убрать ПЧ из рецепта и vfd_get_status из прогона")
    ap.add_argument("--delay-ms", type=int, default=None, help="задержка сима, мс; умолчание 300, для --scenario 0")
    ap.add_argument("--sim-port", type=int, default=5021)
    ap.add_argument("--backend-port", type=int, default=8765)
    ap.add_argument(
        "--param-sets", type=int, default=PARAM_SETS_FULL, help="сколько PARAM_SET в sync_params (триггер S3)"
    )
    ap.add_argument("--boot-timeout", type=float, default=90.0)
    ap.add_argument(
        "--base", action="store_true", help="дерево без device_io (main): проверки исполнителя n/a, не красные"
    )
    ap.add_argument(
        "--race-only",
        action="store_true",
        help="только старт бэкенда и замер гонки introspect.* (без сима и сценариев)",
    )
    ap.add_argument("--scenario", choices=PARK_SCENARIOS, help="один сценарий park (L1-L3) на прогон; sim delay 0")
    ap.add_argument(
        "--regress", action="store_true", help="один прогон S0, S1 и G с порогами SPI.stand (S2/S3: --only S2,S3)"
    )
    ap.add_argument(
        "--repeats",
        type=int,
        default=None,
        help="--scenario: повтор прогона целиком, каждый в своём run-<время>/ (умолчание 3); --race-only: повтор замера (1)",
    )
    args = ap.parse_args()
    if args.scenario and (args.regress or args.race_only or args.base):
        ap.error("--scenario несовместим с --regress, --race-only и --base")
    if args.regress and args.race_only:
        ap.error("--regress несовместим с --race-only")
    if args.regress:
        args.only = "S0,S1"
    args.only = [s for s in args.only.split(",") if s]
    if args.delay_ms is None:
        args.delay_ms = 0 if args.scenario else 300
    if args.repeats is None:
        args.repeats = 3 if args.scenario else 1
    if bad := [s for s in args.only if s not in SCENARIOS]:
        ap.error(f"неизвестные сценарии: {bad}")
    sys.path.insert(0, str(args.worktree))

    if args.dry_run:
        print_plan(args)
        return 0
    prepare_copies(args)
    if args.prepare_only:
        return 0

    if args.race_only:
        code = 0
        for k in range(args.repeats):
            code |= one_run(args, race_only=True, label=f"-race{k + 1}")[0]
        return code
    if args.scenario:
        code, dirs = 0, []
        for _ in range(args.repeats):
            run_code, run_dir = one_run(args, race_only=False, label=f"-{args.scenario}", run_count=False)
            code |= run_code
            dirs.append(str(run_dir))
            time.sleep(1.0)  # имя каталога - с точностью до секунды
        cnt = subprocess.run([str(args.python), str(HERE / "count.py"), *dirs], text=True)  # nosec B603
        return code or cnt.returncode
    return one_run(args, race_only=False, label="-regress" if args.regress else "")[0]


def one_run(args: argparse.Namespace, race_only: bool, label: str, run_count: bool = True) -> tuple[int, Path]:
    run_dir = args.stand_root / f"run-{datetime.now():%Y%m%d-%H%M%S}{label}"
    (run_dir / "data").mkdir(parents=True)
    (run_dir / "logs").mkdir()
    preflight(args, run_dir)
    md5_before = md5(MAIN_TREE / "multiprocess_prototype" / "app.yaml")
    status_before = git_status(args.worktree)
    stand = Stand(args, run_dir)
    code = 0
    try:
        if race_only:
            stand.start_race_only()
        else:
            stand.start()
            stand.group_d()
            if args.scenario:
                stand.checks["meta"]["scenario"] = args.scenario
                stand.park_scenario(args.scenario)
            else:
                for name in args.only:
                    stand.scenario(name)
                stand.group_g()
    except BaseException as exc:  # noqa: BLE001 - уборка обязана пройти при любом отказе
        stand.ev("abort", error=f"{type(exc).__name__}: {exc}")
        print(f"ПРЕРВАНО: {type(exc).__name__}: {exc}", file=sys.stderr)
        code = 2
    finally:
        stand.finish(md5_before, status_before)
    print(f"каталог прогона: {run_dir}")
    if race_only or not run_count:
        return code, run_dir
    cnt = subprocess.run([str(args.python), str(HERE / "count.py"), str(run_dir)], text=True)  # nosec B603
    return code or cnt.returncode, run_dir


if __name__ == "__main__":
    sys.exit(main())
