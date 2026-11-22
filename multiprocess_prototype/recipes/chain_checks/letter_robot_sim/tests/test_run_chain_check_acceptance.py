"""Приёмочные тесты запуска `run_chain_check.py` (Task 4a), написаны слепо по тексту задачи.

Источник: docs/reports/sim-audit/tasks/4a.md, DESIGN п. 1-8.

Тесты ходят ТОЛЬКО через CLI (subprocess с sys.executable). Вместо реальных процессов
в конфиге стоят фейки: один маленький скрипт `fake.py` (его текст ниже, FAKE_SRC) в роли
sim / proto / collect / alpha / audit. Фейк открывает TCP-порт, пишет строки в stdout,
пишет в файлы метки времени, свои аргументы, окружение и cwd, а все события добавляет
в общий журнал events.jsonl. Каждый вызов CLI идёт с дедлайном: зависший запуск убивается
вместе с группой процессов, а оставшиеся фейки добивает уборка по журналу.

Пока `run_chain_check.py` не создан, КАЖДЫЙ тест падает на проверке «скрипт запуска есть»
(намеренно: случайный код 2 от `python <нет файла>` не должен засчитать тест (к)).
"""

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="SIGTERM/SIGKILL и POSIX-сессии: Windows вне области проверки"
)

HERE = Path(__file__).resolve().parent
RECIPE_DIR = HERE.parent
SCRIPT = RECIPE_DIR / "run_chain_check.py"
REPO_ROOT = HERE.parents[4]

ALL_REQUIRED_KEYS = [
    "recipe",
    "words",
    "zone_max_mm",
    "ports",
    "timeouts_s",
    "sim_cmd",
    "sim_env",
    "proto_cmd",
    "proto_env",
    "sim_commands",
    "collect_cmd",
    "alpha_cmd",
    "audit_cmd",
]

# ---------------------------------------------------------------------------
# Фейк-процесс. Роли: sim, proto, foreign (слушатели), collect, alpha, audit.
# Параметры роли: позиционные role, events, marks, затем "ключ=значение".
# ---------------------------------------------------------------------------
FAKE_SRC = r"""
import json, os, signal, socket, subprocess, sys, time

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
ROLE, EVENTS, MARKS = sys.argv[1], sys.argv[2], sys.argv[3]
ARGS = sys.argv[4:]
KV = {}
for _a in ARGS:
    _k, _, _v = _a.partition("=")
    KV[_k] = _v
SELF_DESTRUCT = time.time() + 120  # страховка: сирота сам уходит через 2 минуты
ENV_KEYS = ["BACKEND_CTL", "BACKEND_CTL_PORT", "PYTHONUTF8", "INSPECTOR_LOG_DIR"]


def now():
    return time.time_ns()


def log(event, **extra):
    rec = {"ns": now(), "role": ROLE, "event": event, "pid": os.getpid()}
    rec.update(extra)
    with open(EVENTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def mark(name, text):
    with open(os.path.join(MARKS, name), "w", encoding="utf-8") as f:
        f.write(text)


def read_mark(name):
    try:
        with open(os.path.join(MARKS, name), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def port_open(port):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", int(port))) == 0
    finally:
        s.close()


def pid_alive(pid):
    r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    stat = r.stdout.strip()
    return r.returncode == 0 and bool(stat) and not stat.startswith("Z")


def listen(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", int(port)))
    s.listen(16)
    return s


def idle():
    while time.time() < SELF_DESTRUCT:
        time.sleep(0.05)
    sys.exit(0)


os.makedirs(MARKS, exist_ok=True)
mark(ROLE + ".pid", str(os.getpid()))
mark(ROLE + ".started_ns", str(now()))
mark(
    ROLE + ".json",
    json.dumps(
        {
            "argv": ARGS,
            "cwd": os.getcwd(),
            "prefix": sys.prefix,
            "env": {k: os.environ.get(k) for k in ENV_KEYS},
        },
        ensure_ascii=False,
    ),
)
log("start")

if ROLE in ("sim", "proto", "foreign"):
    mode = KV.get("mode", "normal")
    if mode == "ignore_term":
        def _h(signum, frame):
            mark(ROLE + ".sigterm_ns", str(now()))
        signal.signal(signal.SIGTERM, _h)
    srv = None
    if mode != "noport":
        srv = listen(KV["port"])
    if mode == "close_conn":
        srv.settimeout(0.1)
        while time.time() < SELF_DESTRUCT:
            try:
                c, _ = srv.accept()
                c.close()
            except OSError:
                pass
    idle()

elif ROLE == "collect":
    d = KV["dir"]
    os.makedirs(d, exist_ok=True)
    mark(
        "collect.ports_open.json",
        json.dumps({"sim": port_open(KV["sim"]), "proto": port_open(KV["proto"])}),
    )
    stop = os.path.join(d, "STOP")
    while not os.path.exists(stop) and time.time() < SELF_DESTRUCT:
        time.sleep(0.02)
    mark("collect.stop_seen_ns", str(now()))
    log("stop_seen")
    sys.exit(0)

elif ROLE == "alpha":
    run_no = 0
    with open(EVENTS, encoding="utf-8") as f:
        for line in f:
            if '"role": "alpha"' in line and '"event": "start"' in line:
                run_no += 1
    time.sleep(float(KV.get("delay", "0")))
    collect_dir = os.path.join(MARKS, "collect")
    mark(
        "alpha.observed.json",
        json.dumps(
            {
                "alpha_ns": now(),
                "run_no": run_no,
                "collect_started_ns": read_mark("collect.started_ns"),
                "sim_port_open": port_open(KV["sim"]),
                "proto_port_open": port_open(KV["proto"]),
            }
        ),
    )
    if "crash" in KV:
        raise RuntimeError("fake alpha exploded")
    if "hang" in KV:
        idle()
    if "foreign" in KV:
        subprocess.Popen(
            [sys.executable, __file__, "foreign", EVENTS, MARKS, "port=" + KV["foreign"]],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        t_end = time.time() + 10
        while time.time() < t_end and not port_open(KV["foreign"]):
            time.sleep(0.05)
    if KV.get("stop_proto") == "1":
        proto_pid = int(read_mark("proto.pid"))
        os.kill(proto_pid, signal.SIGTERM)
        t_end = time.time() + 10
        while time.time() < t_end and pid_alive(proto_pid):
            time.sleep(0.05)
    time.sleep(float(KV.get("run_s", "0")))
    print("шаг P1: старт", flush=True)
    print("шаг P6: прототип остановлен", flush=True)
    result = KV.get("result", "pass")
    if str(run_no) in KV.get("fail_runs", "").split(","):
        result = "fail"
    if result == "pass":
        print("МЕХАНИЗМ: PASS", flush=True)
    elif result == "fail":
        print("МЕХАНИЗМ: FAIL", flush=True)
    print(KV.get("accuracy", "ТОЧНОСТЬ: прогон %d" % run_no), flush=True)
    mark(
        "alpha.end.json",
        json.dumps(
            {
                "finished_ns": now(),
                "stop_exists": os.path.exists(os.path.join(collect_dir, "STOP")),
            }
        ),
    )
    sys.exit(int(KV.get("code", "0")))

elif ROLE == "audit":
    seen = {}
    for r in ("sim", "proto", "collect", "alpha"):
        p = read_mark(r + ".pid")
        seen[r + "_alive"] = bool(p) and pid_alive(int(p))
    seen["sim_port_open"] = port_open(KV["sim"])
    seen["proto_port_open"] = port_open(KV["proto"])
    mark("audit.seen.json", json.dumps(seen))
    itog = KV.get("itog", "ИТОГ: проверок 9, нарушений 0")
    mark("audit.md", itog + "\n")
    print(itog, flush=True)
    sys.exit(int(KV.get("code", "0")))
"""


def alloc_ports(n: int) -> list[int]:
    socks = [socket.socket() for _ in range(n)]
    for s in socks:
        s.bind(("127.0.0.1", 0))
    ports = [s.getsockname()[1] for s in socks]
    for s in socks:
        s.close()
    return ports


def port_open(port: int) -> bool:
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def pid_state(pid: int) -> str:
    r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def pid_alive(pid: int) -> bool:
    stat = pid_state(pid)
    return bool(stat) and not stat.startswith("Z")


REASON_KEYS = ["alpha", "audit", "порты", "процессы", "сборщик"]


def reasons(text: str) -> set[str]:
    """Причины FAIL, названные в тексте вердикта отдельным словом (не частью имени файла/пути)."""
    found: set[str] = set()
    for key in REASON_KEYS:
        pattern = rf"(?<![\w/.\-]){key}(?!\w|\.(?:out|md|log|json))"
        if re.search(pattern, text, re.IGNORECASE):
            found.add(key)
    return found


MECH_PASS = re.compile(r"МЕХАНИЗМ\s*[:=]\s*PASS")
MECH_FAIL = re.compile(r"МЕХАНИЗМ\s*[:=]\s*FAIL")


@dataclass
class Result:
    code: int
    stdout: str
    stderr: str
    elapsed: float
    alive: list[tuple[str, int]] = field(default_factory=list)
    ports_open: list[int] = field(default_factory=list)

    @property
    def text(self) -> str:
        return self.stdout + "\n" + self.stderr

    @property
    def alive_ours(self) -> list[tuple[str, int]]:
        return [x for x in self.alive if x[0] != "foreign"]


class Env:
    def __init__(self, base: Path):
        base.mkdir(parents=True, exist_ok=True)
        self.base = base
        self.fake = base / "fake.py"
        self.fake.write_text(FAKE_SRC, encoding="utf-8")
        self.events_path = base / "events.jsonl"
        self.out_root = base / "out"
        self.config_path = base / "chain_check.yaml"
        self.sim_port, self.proto_port, self.extra_port = alloc_ports(3)

    # -- конфиг ------------------------------------------------------------
    def cfg(
        self,
        sim=(),
        proto=(),
        collect=(),
        alpha=(),
        audit=(),
        timeouts=None,
        free_after=None,
        **over,
    ) -> dict:
        fake, ev = str(self.fake), str(self.events_path)
        cfg = {
            "recipe": "letter_robot_sim",
            "words": ["ПЕРЕМИРИЕ", "МИР", "ПЕРЕМИРИЕ"],
            "zone_max_mm": 600,
            "ports": {
                "sim": self.sim_port,
                "proto": self.proto_port,
                "free_after": free_after if free_after is not None else [self.sim_port, self.proto_port],
            },
            "timeouts_s": {"backends_up": 10, "alpha": 30, "stop": 5, **(timeouts or {})},
            "sim_cmd": ["python", fake, "sim", ev, "{out}", "port={sim_port}", *sim],
            "sim_env": {"BACKEND_CTL": "1", "BACKEND_CTL_PORT": "{sim_port}", "PYTHONUTF8": "1"},
            "proto_cmd": [
                "python",
                fake,
                "proto",
                ev,
                "{out}",
                "port={proto_port}",
                "letter_robot_sim",
                "--autostart",
                *proto,
            ],
            "proto_env": {"BACKEND_CTL": "1", "PYTHONUTF8": "1", "INSPECTOR_LOG_DIR": "{log_dir}"},
            "sim_commands": [],
            "collect_cmd": [
                "python",
                fake,
                "collect",
                ev,
                "{out}",
                "dir={out}/collect",
                "sim={sim_port}",
                "proto={proto_port}",
                *collect,
            ],
            "alpha_cmd": [
                "python",
                fake,
                "alpha",
                ev,
                "{out}",
                "sim={sim_port}",
                "proto={proto_port}",
                *alpha,
            ],
            "audit_cmd": [
                "python",
                fake,
                "audit",
                ev,
                "{out}",
                "sim={sim_port}",
                "proto={proto_port}",
                *audit,
            ],
        }
        cfg.update(over)
        return cfg

    def write(self, cfg: dict) -> Path:
        self.config_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return self.config_path

    # -- запуск CLI --------------------------------------------------------
    def run(
        self, *extra, config: str | None = "default", tree: bool = True, out: bool = True, timeout: float = 90
    ) -> Result:
        assert SCRIPT.is_file(), f"скрипта запуска нет: {SCRIPT} не создан (ожидаемый RED до реализации)"
        cmd = [sys.executable, str(SCRIPT)]
        if config == "default":
            cmd += ["--config", str(self.config_path)]
        elif config is not None:
            cmd += ["--config", config]
        if tree:
            cmd += ["--tree", str(REPO_ROOT)]
        if out:
            cmd += ["--out-root", str(self.out_root)]
        cmd += list(extra)
        env = dict(os.environ)
        env["PATH"] = "/usr/bin:/bin"  # голого `python` в PATH нет: только sys.executable
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        t0 = time.monotonic()
        proc = subprocess.Popen(
            cmd,
            cwd=self.base,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            o, e = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()
            pytest.fail(f"CLI завис: не завершился за {timeout} с (убит вместе с группой)")
        elapsed = time.monotonic() - t0
        res = Result(
            proc.returncode,
            o.decode("utf-8", "replace"),
            e.decode("utf-8", "replace"),
            elapsed,
        )
        res.alive = [(r, p) for (r, p) in self._launched() if self._is_ours_alive(p)]
        res.ports_open = [p for p in (self.sim_port, self.proto_port, self.extra_port) if port_open(p)]
        return res

    # -- журнал, уборка ----------------------------------------------------
    def events(self) -> list[dict]:
        if not self.events_path.exists():
            return []
        return [json.loads(line) for line in self.events_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def started(self, role: str) -> list[dict]:
        return [e for e in self.events() if e["role"] == role and e["event"] == "start"]

    def roles_started(self) -> set[str]:
        return {e["role"] for e in self.events() if e["event"] == "start"}

    def _launched(self) -> list[tuple[str, int]]:
        return [(e["role"], e["pid"]) for e in self.events() if e["event"] == "start"]

    def _is_ours_alive(self, pid: int) -> bool:
        if not pid_alive(pid):
            return False
        r = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True)
        return str(self.fake) in r.stdout  # защита от переиспользованного pid

    def close(self) -> None:
        for _role, pid in self._launched():
            if self._is_ours_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    # -- чтение результатов прогона ---------------------------------------
    def run_dirs(self) -> list[Path]:
        return sorted(p for p in self.out_root.glob("*/run*") if p.is_dir())

    def run_dir(self, k: int) -> Path:
        found = [p for p in self.run_dirs() if p.name == f"run{k}"]
        assert found, f"нет каталога run{k} под {self.out_root}: {self.run_dirs()}"
        return found[0]

    def verdict(self, k: int = 1) -> str:
        path = self.run_dir(k) / "verdict.md"
        assert path.is_file(), f"нет {path}"
        return path.read_text(encoding="utf-8")

    def summaries(self) -> list[Path]:
        return sorted(self.out_root.glob("*/summary.md"))

    def mark_json(self, k: int, name: str) -> dict:
        return json.loads((self.run_dir(k) / name).read_text(encoding="utf-8"))

    def mark_text(self, k: int, name: str) -> str:
        return (self.run_dir(k) / name).read_text(encoding="utf-8")


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path / "w")
    yield e
    e.close()


class _CleanRun:
    """Один чистый прогон на модуль; исключение (RED) кэшируется и повторяется в каждом тесте."""

    def __init__(self, base: Path):
        self.env = Env(base)
        self._res: Result | None = None
        self._exc: BaseException | None = None

    def get(self) -> tuple[Env, Result]:
        if self._exc is not None:
            raise self._exc
        if self._res is None:
            try:
                self.env.write(self.env.cfg())
                self._res = self.env.run()
            except BaseException as exc:  # noqa: BLE001 - повторяем в каждом тесте
                self._exc = exc
                raise
        return self.env, self._res


@pytest.fixture(scope="module")
def clean(tmp_path_factory):
    c = _CleanRun(tmp_path_factory.mktemp("clean"))
    yield c
    c.env.close()


# ===========================================================================
# (а) все фейки отработали: PASS, код 0, verdict.md и summary.md созданы
# ===========================================================================
def test_a_clean_run_exit_code_is_0(clean):
    e, res = clean.get()
    assert res.code == 0, res.text


def test_a_clean_run_writes_verdict_md_with_mechanism_pass(clean):
    e, res = clean.get()
    assert MECH_PASS.search(e.verdict(1))


def test_a_clean_run_prints_the_verdict(clean):
    e, res = clean.get()
    assert MECH_PASS.search(res.stdout), res.stdout


def test_a_clean_run_writes_summary_md_next_to_run_dir(clean):
    e, res = clean.get()
    sums = e.summaries()
    assert len(sums) == 1, sums
    assert sums[0].parent == e.run_dir(1).parent
    assert "PASS" in sums[0].read_text(encoding="utf-8")


def test_a_clean_run_leaves_nothing_alive_and_ports_free(clean):
    e, res = clean.get()
    assert res.alive_ours == []
    assert res.ports_open == []


def test_a_clean_run_captures_step_output_in_files(clean):
    e, res = clean.get()
    d = e.run_dir(1)
    for name in ("sim.out", "proto.out", "collect.out", "alpha.out", "audit.out"):
        assert (d / name).is_file(), f"нет {name}"
    alpha_out = (d / "alpha.out").read_text(encoding="utf-8")
    assert "МЕХАНИЗМ: PASS" in alpha_out
    assert "ИТОГ: проверок 9, нарушений 0" in (d / "audit.out").read_text(encoding="utf-8")


def test_a_every_stage_was_started_once_cold(clean):
    e, res = clean.get()
    for role in ("sim", "proto", "collect", "alpha", "audit"):
        assert len(e.started(role)) == 1, role


# ---- поля verdict.md (п. 4) ------------------------------------------------
def test_verdict_has_a_timestamp(clean):
    e, res = clean.get()
    assert str(datetime.now(timezone.utc).year) in e.verdict(1)


def test_verdict_names_headless_mode(clean):
    e, res = clean.get()
    assert "headless" in e.verdict(1).lower()


def test_verdict_lists_run_file_paths(clean):
    e, res = clean.get()
    text = e.verdict(1)
    for name in ("sim.out", "proto.out", "collect.out", "alpha.out", "audit.out"):
        assert name in text, name


def test_verdict_has_audit_itog_line_verbatim(clean):
    e, res = clean.get()
    assert "ИТОГ: проверок 9, нарушений 0" in e.verdict(1)


def test_verdict_has_alpha_accuracy_line_verbatim(clean):
    e, res = clean.get()
    assert "ТОЧНОСТЬ: прогон 1" in e.verdict(1)


# ===========================================================================
# (б) МЕХАНИЗМ: FAIL у α -> код 1, причина alpha
# ===========================================================================
@pytest.mark.parametrize("alpha_code", ["0", "1"])
def test_b_alpha_mechanism_fail_gives_exit_1_and_reason_alpha(env, alpha_code):
    env.write(env.cfg(alpha=["result=fail", f"code={alpha_code}"]))
    res = env.run()
    assert res.code == 1, res.text
    text = env.verdict(1)
    assert MECH_FAIL.search(text)
    assert reasons(text) == {"alpha"}


def test_b_alpha_without_any_mechanism_line_is_fail_alpha(env):
    env.write(env.cfg(alpha=["result=none"]))
    res = env.run()
    assert res.code == 1, res.text
    assert reasons(env.verdict(1)) == {"alpha"}


def test_b_alpha_exit_code_1_with_mechanism_pass_still_passes(env):
    env.write(env.cfg(alpha=["result=pass", "code=1"]))
    res = env.run()
    assert res.code == 0, res.text
    assert MECH_PASS.search(env.verdict(1))


# ===========================================================================
# (в) аудит код 1 -> код 1, причина audit
# ===========================================================================
def test_c_audit_exit_1_gives_exit_1_and_reason_audit(env):
    env.write(env.cfg(audit=["code=1"]))
    res = env.run()
    assert res.code == 1, res.text
    text = env.verdict(1)
    assert MECH_FAIL.search(text)
    assert reasons(text) == {"audit"}


# ===========================================================================
# (г) после остановки порт из free_after занят чужим -> код 1, причина «порты»
# ===========================================================================
def test_d_foreign_listener_after_stop_gives_exit_1_and_reason_ports(env):
    env.write(
        env.cfg(
            alpha=[f"foreign={env.extra_port}"],
            free_after=[env.sim_port, env.proto_port, env.extra_port],
        )
    )
    res = env.run()
    assert res.code == 1, res.text
    text = env.verdict(1)
    assert MECH_FAIL.search(text)
    assert reasons(text) == {"порты"}


def test_d_foreign_listener_is_not_killed(env):
    env.write(
        env.cfg(
            alpha=[f"foreign={env.extra_port}"],
            free_after=[env.sim_port, env.proto_port, env.extra_port],
        )
    )
    res = env.run()
    foreign = [pid for role, pid in res.alive if role == "foreign"]
    assert len(foreign) == 1, f"чужой слушатель убит или не запускался: {res.alive}"
    assert env.extra_port in res.ports_open


def test_d_own_processes_are_still_stopped_when_foreign_holds_a_port(env):
    env.write(
        env.cfg(
            alpha=[f"foreign={env.extra_port}"],
            free_after=[env.sim_port, env.proto_port, env.extra_port],
        )
    )
    res = env.run()
    assert res.alive_ours == []


# ===========================================================================
# (д) порт из free_after занят ДО старта -> код 3, ничего не запущено
# ===========================================================================
def test_e_port_busy_before_start_gives_exit_3_and_nothing_started(env):
    holder = socket.socket()
    holder.bind(("127.0.0.1", env.extra_port))
    holder.listen(4)
    try:
        env.write(env.cfg(free_after=[env.sim_port, env.proto_port, env.extra_port]))
        res = env.run()
        assert res.code == 3, res.text
        assert env.events() == [], "при занятом порте не должно стартовать ни одного фейка"
        assert port_open(env.extra_port), "чужой слушатель должен остаться нетронутым"
    finally:
        holder.close()


def test_e_port_busy_before_start_prints_a_message(env):
    holder = socket.socket()
    holder.bind(("127.0.0.1", env.extra_port))
    holder.listen(4)
    try:
        env.write(env.cfg(free_after=[env.extra_port]))
        res = env.run()
        assert res.code == 3, res.text
        assert res.text.strip() != ""
    finally:
        holder.close()


# ===========================================================================
# (е) сим/прототип не открыл порт за backends_up -> код 3, уборка
# ===========================================================================
@pytest.mark.parametrize("bad", ["sim", "proto"])
def test_f_backend_not_up_in_time_gives_exit_3(env, bad):
    kwargs = {bad: ["mode=noport"]}
    env.write(env.cfg(timeouts={"backends_up": 2}, **kwargs))
    res = env.run(timeout=60)
    assert res.code == 3, res.text
    assert res.elapsed < 45, f"ожидание {res.elapsed:.1f} с: backends_up=2 не соблюдён"


@pytest.mark.parametrize("bad", ["sim", "proto"])
def test_f_backend_not_up_cleans_up_everything_started(env, bad):
    kwargs = {bad: ["mode=noport"]}
    env.write(env.cfg(timeouts={"backends_up": 2}, **kwargs))
    res = env.run(timeout=60)
    assert res.alive_ours == []
    assert res.ports_open == []
    assert env.started(bad), "фейк, не открывший порт, должен был стартовать"


@pytest.mark.parametrize("bad", ["sim", "proto"])
def test_f_backend_not_up_never_starts_collector_alpha_audit(env, bad):
    kwargs = {bad: ["mode=noport"]}
    env.write(env.cfg(timeouts={"backends_up": 2}, **kwargs))
    env.run(timeout=60)
    assert env.roles_started().isdisjoint({"collect", "alpha", "audit"})


# ===========================================================================
# (ж) ТОЧНОСТЬ: ... дословно в verdict.md, на код не влияет
# ===========================================================================
@pytest.mark.parametrize(
    "line",
    ["ТОЧНОСТЬ: 7 трудных", "ТОЧНОСТЬ: FAIL все 7 пропущены"],
)
def test_g_accuracy_line_goes_into_verdict_verbatim_and_not_into_exit_code(env, line):
    env.write(env.cfg(alpha=[f"accuracy={line}"]))
    res = env.run()
    assert res.code == 0, res.text
    assert line in env.verdict(1)
    assert MECH_PASS.search(env.verdict(1))


# ===========================================================================
# (з) --gui не добавляет --headless к proto_cmd; без --gui добавляет
# ===========================================================================
def test_h_without_gui_flag_headless_is_added_once(env):
    env.write(env.cfg())
    res = env.run()
    assert res.code == 0, res.text
    argv = env.mark_json(1, "proto.json")["argv"]
    assert argv.count("--headless") == 1, argv
    assert "letter_robot_sim" in argv and "--autostart" in argv


def test_h_with_gui_flag_headless_is_not_added(env):
    env.write(env.cfg())
    res = env.run("--gui")
    assert res.code == 0, res.text
    argv = env.mark_json(1, "proto.json")["argv"]
    assert "--headless" not in argv, argv
    assert "letter_robot_sim" in argv and "--autostart" in argv


def test_h_gui_run_verdict_does_not_claim_headless(env):
    env.write(env.cfg())
    env.run("--gui")
    text = env.verdict(1).lower()
    assert "gui" in text
    assert "headless" not in text


# ===========================================================================
# (и) --runs 3: три каталога run1..run3 и один summary.md
# ===========================================================================
def test_i_runs_3_makes_three_run_dirs_with_verdicts(env):
    env.write(env.cfg())
    res = env.run("--runs", "3", timeout=120)
    assert res.code == 0, res.text
    assert [p.name for p in env.run_dirs()] == ["run1", "run2", "run3"]
    for k in (1, 2, 3):
        assert MECH_PASS.search(env.verdict(k)), k


def test_i_runs_3_makes_one_label_dir_and_one_summary(env):
    env.write(env.cfg())
    env.run("--runs", "3", timeout=120)
    labels = [p for p in env.out_root.iterdir() if p.is_dir()]
    assert len(labels) == 1, labels
    assert len(env.summaries()) == 1


def test_i_runs_3_summary_has_a_row_per_run_with_mechanism_and_accuracy(env):
    env.write(env.cfg())
    env.run("--runs", "3", timeout=120)
    lines = env.summaries()[0].read_text(encoding="utf-8").splitlines()
    for k in (1, 2, 3):
        rows = [ln for ln in lines if re.search(rf"run{k}\b", ln)]
        assert len(rows) == 1, (k, rows)
        assert "PASS" in rows[0], rows[0]
        assert f"ТОЧНОСТЬ: прогон {k}" in rows[0], rows[0]


def test_i_runs_3_each_run_is_a_full_cold_start(env):
    env.write(env.cfg())
    env.run("--runs", "3", timeout=120)
    for role in ("sim", "proto", "collect", "alpha", "audit"):
        pids = {e["pid"] for e in env.started(role)}
        assert len(pids) == 3, (role, pids)


def test_i_runs_3_leaves_nothing_alive(env):
    env.write(env.cfg())
    res = env.run("--runs", "3", timeout=120)
    assert res.alive_ours == []
    assert res.ports_open == []


def test_i_runs_default_is_one_run(env):
    env.write(env.cfg())
    env.run()
    assert [p.name for p in env.run_dirs()] == ["run1"]


def test_i_failing_second_run_gives_exit_1_and_fail_verdict_for_run2(env):
    env.write(env.cfg(alpha=["fail_runs=2"]))
    res = env.run("--runs", "3", timeout=120)
    assert res.code == 1, res.text
    assert MECH_PASS.search(env.verdict(1))
    assert MECH_FAIL.search(env.verdict(2))


# ===========================================================================
# (к) неизвестный/пропущенный ключ конфига и ошибки аргументов -> код 2, без значений
# ===========================================================================
LEAK = "LEAKCHK-secret-4417"


def _leaky_cfg(env: Env, **over) -> dict:
    cfg = env.cfg(**over)
    cfg["sim_env"]["LEAKCHK_ENV"] = LEAK + "-env"
    cfg["recipe"] = LEAK + "-recipe"
    return cfg


def test_k_unknown_config_key_gives_exit_2_without_values(env):
    cfg = _leaky_cfg(env)
    cfg["zzz_unknown_key"] = LEAK + "-unknown"
    env.write(cfg)
    res = env.run()
    assert res.code == 2, res.text
    assert LEAK not in res.text
    assert "Traceback" not in res.text
    assert res.text.strip() != ""
    assert env.events() == []


@pytest.mark.parametrize("key", ALL_REQUIRED_KEYS)
def test_k_missing_required_key_gives_exit_2_without_values(env, key):
    cfg = _leaky_cfg(env)
    del cfg[key]
    env.write(cfg)
    res = env.run()
    assert res.code == 2, res.text
    assert LEAK not in res.text
    assert "Traceback" not in res.text
    assert res.text.strip() != ""
    assert env.events() == []


def test_k_bad_runs_value_gives_exit_2_without_the_value(env):
    env.write(env.cfg())
    res = env.run("--runs", "zzz-bad-value-91")
    assert res.code == 2, res.text
    assert "zzz-bad-value-91" not in res.text
    assert env.events() == []


def test_k_unknown_cli_flag_gives_exit_2(env):
    env.write(env.cfg())
    res = env.run("--bogus-flag-xyz")
    assert res.code == 2, res.text
    assert env.events() == []


def test_k_missing_config_file_gives_exit_2_without_the_path(env):
    res = env.run(config=str(env.base / "no_such_LEAKCHKDIR" / "chain_check.yaml"))
    assert res.code == 2, res.text
    assert "LEAKCHKDIR" not in res.text
    assert env.events() == []


# ===========================================================================
# (л) порядок шагов
# ===========================================================================
def test_l_collector_and_alpha_start_only_after_both_ports_answer(env):
    env.write(env.cfg())
    env.run()
    assert env.mark_json(1, "collect.ports_open.json") == {"sim": True, "proto": True}
    obs = env.mark_json(1, "alpha.observed.json")
    assert obs["sim_port_open"] is True
    assert obs["proto_port_open"] is True


def test_l_collector_is_running_before_alpha_does_its_work(env):
    env.write(env.cfg(alpha=["delay=1.0"]))
    res = env.run()
    assert res.code == 0, res.text
    obs = env.mark_json(1, "alpha.observed.json")
    assert obs["collect_started_ns"] is not None, "сборщик не был запущен к работе α"
    assert int(obs["collect_started_ns"]) < obs["alpha_ns"]


def test_l_failed_sim_command_stops_before_collector_and_alpha(env):
    # ответ без success: фейк-сим принимает соединение и сразу его закрывает
    cmds = [{"target": "camera", "command": "scene.defect_rate", "args": {"probability": 0.0}}]
    env.write(env.cfg(sim=["mode=close_conn"], sim_commands=cmds))
    res = env.run()
    assert res.code == 3, res.text
    assert env.roles_started().isdisjoint({"collect", "alpha", "audit"})
    assert res.alive_ours == []
    assert res.ports_open == []


def test_l_audit_runs_only_after_everything_is_stopped_and_ports_are_free(env):
    env.write(env.cfg())
    env.run()
    seen = env.mark_json(1, "audit.seen.json")
    assert seen == {
        "sim_alive": False,
        "proto_alive": False,
        "collect_alive": False,
        "alpha_alive": False,
        "sim_port_open": False,
        "proto_port_open": False,
    }


# ===========================================================================
# (м) уборка при падении α: исключение и таймаут alpha
# ===========================================================================
@pytest.mark.parametrize("how", ["crash", "hang"])
def test_m_alpha_failure_cleans_up_everything(env, how):
    env.write(env.cfg(alpha=[f"{how}=1"], timeouts={"alpha": 3}))
    res = env.run(timeout=60)
    assert res.alive_ours == [], res.alive_ours
    assert res.ports_open == []


@pytest.mark.parametrize("how", ["crash", "hang"])
def test_m_alpha_failure_writes_verdict_with_reason_alpha(env, how):
    env.write(env.cfg(alpha=[f"{how}=1"], timeouts={"alpha": 3}))
    res = env.run(timeout=60)
    assert res.code in (1, 3), res.text
    text = env.verdict(1)
    assert MECH_FAIL.search(text)
    assert "alpha" in reasons(text)


def test_m_alpha_hang_is_bounded_by_alpha_timeout(env):
    env.write(env.cfg(alpha=["hang=1"], timeouts={"alpha": 3, "stop": 5}))
    res = env.run(timeout=60)
    assert res.elapsed < 45, f"прогон длился {res.elapsed:.1f} с при alpha=3"


def test_m_alpha_failure_still_stops_collector_and_runs_audit(env):
    env.write(env.cfg(alpha=["crash=1"]))
    env.run(timeout=60)
    assert env.mark_text(1, "audit.md").startswith("ИТОГ:")
    assert env.mark_text(1, "collect.stop_seen_ns")


# ===========================================================================
# (н) STOP-файл сборщику создаётся после α, не раньше
# ===========================================================================
def test_n_stop_file_does_not_exist_while_alpha_is_running(env):
    env.write(env.cfg(alpha=["run_s=1.5"]))
    res = env.run()
    assert res.code == 0, res.text
    assert env.mark_json(1, "alpha.end.json")["stop_exists"] is False


def test_n_collector_sees_stop_only_after_alpha_has_finished(env):
    env.write(env.cfg(alpha=["run_s=1.5"]))
    env.run()
    finished = env.mark_json(1, "alpha.end.json")["finished_ns"]
    seen = int(env.mark_text(1, "collect.stop_seen_ns"))
    assert seen >= finished


def test_n_collector_exits_after_stop_file(env):
    env.write(env.cfg())
    res = env.run()
    assert res.code == 0, res.text
    assert [r for r, _ in res.alive if r == "collect"] == []
    assert any(e["event"] == "stop_seen" for e in env.events())


# ===========================================================================
# Остальные утверждения DESIGN (п. 2-3), однозначные по тексту
# ===========================================================================
def test_python_in_command_lists_is_replaced_by_sys_executable(env):
    env.write(env.cfg())
    env.run()
    for name in ("sim", "proto", "collect", "alpha", "audit"):
        assert env.mark_json(1, f"{name}.json")["prefix"] == sys.prefix, name


def test_substitutions_in_list_elements_and_cwd_of_sim_is_tree(env):
    placeholders = ["{tree}", "{out}", "{log_dir}", "{zone_max_mm}", "{proto_port}", "{sim_port}"]
    env.write(env.cfg(alpha=placeholders))
    res = env.run()
    assert res.code == 0, res.text
    run = env.run_dir(1)
    argv = env.mark_json(1, "alpha.json")["argv"][-6:]
    assert os.path.realpath(argv[0]) == os.path.realpath(REPO_ROOT)
    assert os.path.realpath(argv[1]) == os.path.realpath(run)
    assert os.path.realpath(argv[2]) == os.path.realpath(run / "logs_prototype")
    assert argv[3] == "600"
    assert argv[4] == str(env.proto_port)
    assert argv[5] == str(env.sim_port)
    sim = env.mark_json(1, "sim.json")
    assert os.path.realpath(sim["cwd"]) == os.path.realpath(REPO_ROOT)


def test_environment_substitutions_for_sim_and_proto(env):
    env.write(env.cfg())
    env.run()
    sim_env = env.mark_json(1, "sim.json")["env"]
    assert sim_env["BACKEND_CTL"] == "1"
    assert sim_env["BACKEND_CTL_PORT"] == str(env.sim_port)
    assert sim_env["PYTHONUTF8"] == "1"
    proto_env = env.mark_json(1, "proto.json")["env"]
    assert proto_env["BACKEND_CTL"] == "1"
    assert os.path.realpath(proto_env["INSPECTOR_LOG_DIR"]) == os.path.realpath(env.run_dir(1) / "logs_prototype")


@pytest.mark.skipif(shutil.which("git", path="/usr/bin:/bin") is None, reason="git вне /usr/bin:/bin")
def test_default_tree_is_git_toplevel_of_the_script_dir_not_cwd(env):
    env.write(env.cfg(alpha=["{tree}"]))
    res = env.run(tree=False)
    assert res.code == 0, res.text
    argv = env.mark_json(1, "alpha.json")["argv"]
    assert os.path.realpath(argv[-1]) == os.path.realpath(REPO_ROOT)


def test_alpha_stopping_the_prototype_itself_is_fine(env):
    env.write(env.cfg(alpha=["stop_proto=1"]))
    res = env.run()
    assert res.code == 0, res.text
    assert MECH_PASS.search(env.verdict(1))
    assert res.alive_ours == []


def test_cleanup_sends_sigterm_first_then_sigkills_a_stubborn_process(env):
    env.write(env.cfg(sim=["mode=ignore_term"], timeouts={"stop": 2}))
    res = env.run(timeout=60)
    assert res.alive_ours == [], "SIGKILL должен добить процесс, игнорирующий SIGTERM"
    assert env.mark_text(1, "sim.sigterm_ns"), "до SIGKILL должен быть послан SIGTERM"
    assert res.ports_open == []


def test_clean_run_layout_is_one_label_dir_with_run1_verdict_and_summary(env):
    env.write(env.cfg())
    env.run()
    labels = [p for p in env.out_root.iterdir() if p.is_dir()]
    assert len(labels) == 1
    assert (labels[0] / "run1" / "verdict.md").is_file()
    assert (labels[0] / "summary.md").is_file()
