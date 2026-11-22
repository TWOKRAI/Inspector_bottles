"""Тесты автора ``run_chain_check.py`` (Task 4a): опасности — порядок шагов, уборка при любой ошибке, таймауты.

Приёмочные тесты слепого tester лежат рядом (``test_run_chain_check_acceptance.py``, через CLI). Здесь скрипт
вызывается в процессе (``main`` с подставным клиентом сима) в daemon-потоке с дедлайном: зависший вызов роняет
тест, а не прогон. Фейки — маленький скрипт ``fake.py`` в ``tmp_path``; уборка по pid-файлам после каждого теста.
Один тест поднимает настоящий менеджер рецептов, один — два настоящих безвредных подпроцесса.
"""

import importlib.util
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="группы процессов и SIGTERM/SIGKILL: POSIX")

HERE = Path(__file__).resolve().parent
RECIPE_DIR = HERE.parent
REPO_ROOT = HERE.parents[4]
RECIPES_DIR = REPO_ROOT / "multiprocess_prototype" / "recipes"
DEADLINE_S = 90.0


def _load_script():
    spec = importlib.util.spec_from_file_location("run_chain_check_under_test", RECIPE_DIR / "run_chain_check.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass с отложенными аннотациями ищет модуль по имени
    spec.loader.exec_module(module)
    return module


rcc = _load_script()

FAKE_SRC = r"""
import os, socket, sys, time

role, pidfile = sys.argv[1], sys.argv[2]
with open(pidfile, "w") as f:
    f.write(str(os.getpid()))
end = time.time() + 60  # страховка: сирота уходит сам
if role == "listen":
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", int(sys.argv[3])))
    s.listen(8)
    while time.time() < end:
        time.sleep(0.05)
elif role == "collect":
    directory = sys.argv[3]
    os.makedirs(directory, exist_ok=True)
    stop = os.path.join(directory, "STOP")
    if len(sys.argv) > 4 and sys.argv[4] == "erase_stale_stop":
        time.sleep(0.8)  # как collect.py: при старте стирает «старый» STOP
        if os.path.exists(stop):
            os.remove(stop)
    while not os.path.exists(stop) and time.time() < end:
        time.sleep(0.05)
elif role == "alpha":
    print("МЕХАНИЗМ: PASS")
elif role == "audit":
    print("ИТОГ: проверок 1, нарушений 0")
"""


def _free_ports(n: int) -> list[int]:
    socks = [socket.socket() for _ in range(n)]
    for s in socks:
        s.bind(("127.0.0.1", 0))
    ports = [s.getsockname()[1] for s in socks]
    for s in socks:
        s.close()
    return ports


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _call(fn, deadline: float = DEADLINE_S):
    """Вызов в daemon-потоке с join-дедлайном: зависание = красный тест, а не зависший pytest."""
    box: dict = {}

    def target():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["exc"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(deadline)
    assert not thread.is_alive(), f"вызов завис дольше {deadline} с"
    if "exc" in box:
        raise box["exc"]
    return box["value"]


class FakeClient:
    """Клиент сима: пишет вызовы в журнал, отвечает заданным словарём или бросает исключение."""

    def __init__(self, journal: list, reply=None, connect_exc: BaseException | None = None, on_send=None):
        self.journal, self.reply, self.connect_exc, self.on_send = journal, reply, connect_exc, on_send
        self.closed = False

    def connect(self, timeout=None):
        if self.connect_exc is not None:
            raise self.connect_exc

    def send_command(self, target, command, args=None, *, timeout=None):
        if self.on_send is not None:
            self.on_send()
        self.journal.append((target, command, args))
        return self.reply

    def close(self):
        self.closed = True


class Rig:
    def __init__(self, base: Path):
        base.mkdir(parents=True, exist_ok=True)
        self.base = base
        self.fake = base / "fake.py"
        self.fake.write_text(FAKE_SRC, encoding="utf-8")
        self.config_path = base / "chain_check.yaml"
        self.out_root = base / "out"
        self.sim_port, self.proto_port, self.extra_port = _free_ports(3)

    def cfg(
        self, *, sim=None, alpha=None, audit=None, collect_extra=(), timeouts=None, free_after=None, commands=()
    ) -> dict:
        fake = str(self.fake)
        return {
            "recipe": "letter_robot_sim",
            "words": ["А", "Б"],
            "zone_max_mm": 600,
            "ports": {
                "sim": self.sim_port,
                "proto": self.proto_port,
                "free_after": free_after if free_after is not None else [self.sim_port, self.proto_port],
            },
            "timeouts_s": {"backends_up": 10, "alpha": 30, "stop": 5, **(timeouts or {})},
            "sim_cmd": sim or ["python", fake, "listen", "{out}/sim.pid", "{sim_port}"],
            "sim_env": {"PYTHONUTF8": "1"},
            "proto_cmd": ["python", fake, "listen", "{out}/proto.pid", "{proto_port}"],
            "proto_env": {"INSPECTOR_LOG_DIR": "{log_dir}"},
            "sim_commands": list(commands),
            "collect_cmd": ["python", fake, "collect", "{out}/collect.pid", "{out}/collect", *collect_extra],
            "alpha_cmd": alpha or ["python", fake, "alpha", "{out}/alpha.pid"],
            "audit_cmd": audit or ["python", fake, "audit", "{out}/audit.pid"],
        }

    def run(self, cfg: dict, *extra: str, client_factory=None, deadline: float = DEADLINE_S) -> int:
        self.config_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
        argv = ["--config", str(self.config_path), "--tree", str(REPO_ROOT), "--out-root", str(self.out_root), *extra]
        return _call(lambda: rcc.main(argv, client_factory=client_factory), deadline)

    def run_dir(self, k: int = 1) -> Path:
        labels = sorted(p for p in self.out_root.iterdir() if p.is_dir())
        assert len(labels) == 1, labels
        return labels[0] / f"run{k}"

    def pids(self, k: int = 1) -> dict[str, int]:
        found = {p.stem: int(p.read_text()) for p in self.run_dir(k).glob("*.pid") if p.read_text().strip()}
        return found

    def kill_survivors(self) -> None:
        for path in self.base.rglob("*.pid"):
            try:
                pid = int(path.read_text())
                os.killpg(pid, signal.SIGKILL)
            except (ValueError, OSError):
                pass


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path / "w")
    yield r
    r.kill_survivors()


def _ports_free(*ports: int) -> bool:
    return not any(rcc.port_open(p) for p in ports)


# ---------------------------------------------------------------------------------------------------------------------
# Настоящий менеджер рецептов и настоящие подпроцессы
# ---------------------------------------------------------------------------------------------------------------------
def test_real_recipe_manager_does_not_list_chain_check():
    from multiprocess_framework.modules.recipe.service import RecipeService

    class _Hook:
        def normalize(self, body):
            return dict(body)

        def validate(self, body):
            return []

        def to_topology(self, body):
            return dict(body)

    service = RecipeService(
        recipes_dir=RECIPES_DIR,
        hook=_Hook(),
        apply_topology=lambda args: {"success": True},
        persist_active=lambda path: None,
        read_active=lambda: None,
    )
    reply = service.list({})
    assert reply["success"] is True
    # парная проверка достижимости: настоящий рецепт в списке есть, значит отсутствие chain_check не вхолостую
    assert "letter_robot_sim" in reply["names"]
    assert "chain_check" not in reply["names"]
    assert (RECIPE_DIR / "chain_check.yaml").is_file()
    assert list((RECIPES_DIR / "chain_checks").glob("*.yaml")) == []  # менеджер берёт только файлы каталога рецептов


def test_cleanup_stops_two_real_subprocesses_including_one_that_ignores_sigterm(tmp_path):
    ready = tmp_path / "stubborn.ready"
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    stubborn = [
        sys.executable,
        "-c",
        f"import signal, time, pathlib; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"pathlib.Path({str(ready)!r}).write_text('x'); time.sleep(60)",
    ]
    items = [
        rcc._launch("sleeper", sleeper, dict(os.environ), tmp_path, tmp_path / "a.out"),
        rcc._launch("stubborn", stubborn, dict(os.environ), tmp_path, tmp_path / "b.out"),
    ]
    try:
        end = time.monotonic() + 20
        while not ready.exists() and time.monotonic() < end:
            time.sleep(0.05)
        assert ready.exists(), "упрямый подпроцесс не успел поставить игнор SIGTERM"
        t0 = time.monotonic()
        forced = _call(lambda: rcc.stop_items(items, 1.0), 30)
        assert time.monotonic() - t0 < 15
        assert forced == ["stubborn"]  # SIGTERM хватило sleeper-у, упрямого добил SIGKILL
        assert all(item.proc.poll() is not None for item in items)
        assert not any(rcc._group_alive(item) for item in items)
    finally:
        for item in items:
            if item.proc.poll() is None:
                item.proc.kill()
                item.proc.wait(5)


# ---------------------------------------------------------------------------------------------------------------------
# Порядок шагов
# ---------------------------------------------------------------------------------------------------------------------
def test_sim_commands_go_out_before_collector_and_alpha_and_land_in_verdict(rig):
    journal: list = []
    seen: dict = {}

    def snapshot():
        runs = list(rig.out_root.glob("*/run1"))
        seen["collect_out_exists"] = bool(runs) and (runs[0] / "collect.out").exists()
        seen["alpha_out_exists"] = bool(runs) and (runs[0] / "alpha.out").exists()
        seen["ports_open"] = [rcc.port_open(rig.sim_port), rcc.port_open(rig.proto_port)]

    cmd = {"target": "camera", "command": "scene.defect_rate", "args": {"probability": 0.0}}
    client = FakeClient(journal, reply={"result": {"status": "ok"}}, on_send=snapshot)
    ports_asked: list[int] = []

    def factory(port):
        ports_asked.append(port)
        return client

    code = rig.run(rig.cfg(commands=[cmd]), client_factory=factory)
    assert code == 0
    assert journal == [("camera", "scene.defect_rate", {"probability": 0.0})]
    assert ports_asked == [rig.sim_port]
    assert seen == {"collect_out_exists": False, "alpha_out_exists": False, "ports_open": [True, True]}
    assert client.closed is True
    assert "# дефекты сима: defect_rate 0.0" in (rig.run_dir() / "verdict.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "reply",
    [{"result": {"status": "error", "message": "нет"}}, {"success": False}, None, "строка"],
    ids=["status-error", "success-false", "none", "not-a-dict"],
)
def test_rejected_sim_command_cleans_up_and_never_starts_collector(rig, reply):
    cmd = {"target": "camera", "command": "scene.defect_rate", "args": {"probability": 0.0}}
    code = rig.run(rig.cfg(commands=[cmd]), client_factory=lambda port: FakeClient([], reply=reply))
    assert code == 3
    run = rig.run_dir()
    assert not (run / "collect.out").exists() and not (run / "alpha.out").exists()
    pids = rig.pids()
    assert set(pids) == {"sim", "proto"}
    assert not any(_pid_alive(pid) for pid in pids.values())
    assert _ports_free(rig.sim_port, rig.proto_port)


def test_interrupt_inside_the_chain_still_cleans_up(rig):
    cmd = {"target": "camera", "command": "scene.defect_rate", "args": {"probability": 0.0}}
    client = FakeClient([], connect_exc=KeyboardInterrupt())
    code = rig.run(rig.cfg(commands=[cmd]), client_factory=lambda port: client)
    assert code == 3
    assert not any(_pid_alive(pid) for pid in rig.pids().values())
    assert _ports_free(rig.sim_port, rig.proto_port)
    assert client.closed is True


# ---------------------------------------------------------------------------------------------------------------------
# Уборка и вердикт при падении шагов
# ---------------------------------------------------------------------------------------------------------------------
def test_alpha_that_cannot_be_launched_is_fail_alpha_with_cleanup_and_audit(rig):
    cfg = rig.cfg(alpha=[str(rig.base / "no_such_binary")])
    code = rig.run(cfg)
    assert code == 1
    text = (rig.run_dir() / "verdict.md").read_text(encoding="utf-8")
    assert "МЕХАНИЗМ: FAIL" in text
    assert [ln for ln in text.splitlines() if ln.startswith("причина:")] == ["причина: alpha"]
    assert (rig.run_dir() / "audit.out").read_text(encoding="utf-8").startswith("ИТОГ:")
    assert not any(_pid_alive(pid) for pid in rig.pids().values())
    assert _ports_free(rig.sim_port, rig.proto_port)


def test_collector_that_erases_a_stale_stop_file_is_still_stopped(rig):
    # α отработала мгновенно: STOP создан раньше, чем сборщик успел стереть «старый» STOP при старте
    code = rig.run(rig.cfg(collect_extra=["erase_stale_stop"], timeouts={"stop": 10}))
    assert code == 0
    assert not _pid_alive(rig.pids()["collect"])


def test_dead_sim_is_reported_at_once_not_after_backends_up(rig):
    sim = [sys.executable, "-c", "raise SystemExit(7)"]
    t0 = time.monotonic()
    code = rig.run(rig.cfg(sim=sim, timeouts={"backends_up": 60}), deadline=40)
    assert code == 3
    assert time.monotonic() - t0 < 30  # не ждали 60 с
    assert not (rig.run_dir() / "collect.out").exists()
    assert not _pid_alive(rig.pids()["proto"])


def test_busy_port_before_start_launches_nothing_and_a_rerun_on_freed_port_passes(rig):
    holder = socket.socket()
    holder.bind(("127.0.0.1", rig.extra_port))
    holder.listen(4)
    cfg = rig.cfg(free_after=[rig.sim_port, rig.proto_port, rig.extra_port])
    try:
        assert rig.run(cfg) == 3
        assert not list(rig.run_dir().glob("*.pid"))  # ни один фейк не запущен
        assert rcc.port_open(rig.extra_port), "чужой слушатель не тронут"
    finally:
        holder.close()
    assert rig.run(cfg) == 0  # повторный запуск после освобождения порта
    assert _ports_free(rig.sim_port, rig.proto_port, rig.extra_port)


# ---------------------------------------------------------------------------------------------------------------------
# Конфиг, подстановки, ответ команды
# ---------------------------------------------------------------------------------------------------------------------
def _good_config(rig: Rig) -> dict:
    return rig.cfg()


@pytest.mark.parametrize(
    ("path", "bad"),
    [("ports", "ports_extra"), ("timeouts_s", "stop_extra")],
)
def test_unknown_nested_config_key_is_named_but_its_value_is_not_printed(rig, path, bad):
    cfg = _good_config(rig)
    cfg[path][bad] = "LEAKCHK-4417"
    with pytest.raises(rcc.ConfigError) as caught:
        rcc.parse_config(cfg)
    assert bad in str(caught.value) and "LEAKCHK" not in str(caught.value)


@pytest.mark.parametrize("key", ["backends_up", "alpha", "stop"])
def test_missing_nested_timeout_is_config_error(rig, key):
    cfg = _good_config(rig)
    del cfg["timeouts_s"][key]
    with pytest.raises(rcc.ConfigError, match=key):
        rcc.parse_config(cfg)


def test_command_list_substitutions_and_python_replacement():
    values = {"out": "/o", "words": "А,Б", "sim_port": "1"}
    argv = rcc._argv(["python", "-c", "{out}/x {words} python", "{sim_port}"], values)
    assert argv == [sys.executable, "-c", "/o/x А,Б python", "1"]  # `python` заменяется только первым элементом


@pytest.mark.parametrize(
    ("reply", "ok"),
    [
        ({"result": {"status": "ok"}}, True),
        ({"result": {"success": True}}, True),
        ({"status": "ok", "applied": False}, True),
        ({"result": {"status": "error"}}, False),
        ({"result": {"success": False}}, False),
        ({}, False),
        (None, False),
    ],
)
def test_reply_ok(reply, ok):
    assert rcc._reply_ok(reply) is ok


def test_script_does_not_import_alpha_sim():
    source = (RECIPE_DIR / "run_chain_check.py").read_text(encoding="utf-8")
    assert "alpha_sim" not in source
    assert "import scripts" not in source and "from scripts" not in source


def test_cli_exit_codes_via_subprocess_for_bad_arguments(tmp_path):
    result = subprocess.run(
        [sys.executable, str(RECIPE_DIR / "run_chain_check.py"), "--runs", "0"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------------------------------------------------------
# stages.json: этапы прогона для читателя снаружи
# ---------------------------------------------------------------------------------------------------------------------
STAGE_IDS = [
    "ports_free_before",
    "sim_start",
    "proto_start",
    "backends_up",
    "sim_commands",
    "collector_start",
    "alpha",
    "collector_stop",
    "stop_processes",
    "ports_free_after",
    "audit",
    "verdict",
]
STAMP = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}")


def _stages(rig: Rig, k: int = 1) -> dict:
    return json.loads((rig.run_dir(k) / "stages.json").read_text(encoding="utf-8"))


def _statuses(doc: dict) -> dict[str, str]:
    return {item["id"]: item["status"] for item in doc["stages"]}


def test_stages_json_form_and_order_after_a_clean_run(rig):
    assert rig.run(rig.cfg()) == 0
    doc = _stages(rig)
    assert set(doc) == {"recipe", "run", "mode", "stages"}
    assert (doc["recipe"], doc["run"], doc["mode"]) == ("letter_robot_sim", 1, "headless")
    assert [item["id"] for item in doc["stages"]] == STAGE_IDS
    previous = ""
    for item in doc["stages"]:
        assert set(item) == {"id", "title", "status", "started", "finished", "note"}
        assert item["title"].strip() and item["status"] == "pass", item
        assert STAMP.fullmatch(item["started"]) and STAMP.fullmatch(item["finished"]), item
        assert item["started"] >= previous and item["finished"] >= item["started"], item  # порядок шагов DESIGN п. 3
        previous = item["started"]
    assert not (rig.run_dir() / "stages.json.tmp").exists()


def test_stages_json_mode_gui(rig):
    assert rig.run(rig.cfg(), "--gui") == 0
    assert _stages(rig)["mode"] == "gui"


def test_stage_log_is_created_all_pending_and_never_seen_torn_by_a_reader(tmp_path):
    log = rcc.StageLog(tmp_path, "r", 1, False)
    assert set(_statuses(json.loads((tmp_path / "stages.json").read_text(encoding="utf-8"))).values()) == {"pending"}
    stop = threading.Event()
    seen = {"reads": 0, "broken": []}

    def reader():
        while not stop.is_set():
            try:
                json.loads((tmp_path / "stages.json").read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:  # битый JSON или исчезнувший файл
                seen["broken"].append(type(exc).__name__)
            seen["reads"] += 1

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        for _ in range(300):
            for sid in STAGE_IDS:
                log.update(sid, "running")
                log.update(sid, "pass", "п" * 200)
    finally:
        stop.set()
        thread.join(10)
    assert not thread.is_alive()
    assert seen["reads"] > 50 and seen["broken"] == []


def test_stages_are_running_while_alpha_works_then_all_pass(rig):
    slow_alpha = [sys.executable, "-c", "import time; time.sleep(2); print('МЕХАНИЗМ: PASS')"]
    snapshots: list[dict[str, str]] = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            for path in rig.out_root.glob("*/run1/stages.json"):
                try:
                    snapshots.append(_statuses(json.loads(path.read_text(encoding="utf-8"))))
                except (ValueError, OSError) as exc:
                    snapshots.append({"broken": type(exc).__name__})
            time.sleep(0.02)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        assert rig.run(rig.cfg(alpha=slow_alpha)) == 0
    finally:
        stop.set()
        thread.join(10)
    assert not any("broken" in snap for snap in snapshots)
    mid = [snap for snap in snapshots if snap.get("alpha") == "running"]
    assert mid, "читатель не увидел alpha в статусе running"
    assert all(snap["collector_start"] == "pass" and snap["collector_stop"] == "pending" for snap in mid)
    assert snapshots[0]["ports_free_before"] in ("pending", "running", "pass")
    assert set(_statuses(_stages(rig)).values()) == {"pass"}


def test_failed_step_skips_the_rest_but_cleanup_is_reported(rig):
    cmd = {"target": "camera", "command": "scene.defect_rate", "args": {"probability": 0.0}}
    code = rig.run(rig.cfg(commands=[cmd]), client_factory=lambda port: FakeClient([], reply={"status": "error"}))
    assert code == 3
    doc = _stages(rig)
    assert _statuses(doc) == {
        "ports_free_before": "pass",
        "sim_start": "pass",
        "proto_start": "pass",
        "backends_up": "pass",
        "sim_commands": "fail",
        "collector_start": "skipped",
        "alpha": "skipped",
        "collector_stop": "skipped",
        "stop_processes": "pass",
        "ports_free_after": "skipped",
        "audit": "skipped",
        "verdict": "skipped",
    }
    by_id = {item["id"]: item for item in doc["stages"]}
    assert "scene.defect_rate" in by_id["sim_commands"]["note"]
    assert by_id["collector_start"]["started"] is None and by_id["collector_start"]["finished"] is None


def test_busy_port_before_start_is_fail_with_everything_else_skipped(rig):
    holder = socket.socket()
    holder.bind(("127.0.0.1", rig.extra_port))
    holder.listen(4)
    try:
        assert rig.run(rig.cfg(free_after=[rig.extra_port])) == 3
    finally:
        holder.close()
    doc = _stages(rig)
    statuses = _statuses(doc)
    assert statuses["ports_free_before"] == "fail"
    assert {v for sid, v in statuses.items() if sid != "ports_free_before"} == {"skipped"}
    assert str(rig.extra_port) in doc["stages"][0]["note"]


def test_alpha_note_carries_accuracy_verbatim_and_failed_mechanism_fails_alpha_and_verdict(rig):
    alpha = [sys.executable, "-c", "print('МЕХАНИЗМ: FAIL'); print('ТОЧНОСТЬ: 7 трудных')"]
    assert rig.run(rig.cfg(alpha=alpha)) == 1
    by_id = {item["id"]: item for item in _stages(rig)["stages"]}
    assert by_id["alpha"]["status"] == "fail" and "ТОЧНОСТЬ: 7 трудных" in by_id["alpha"]["note"]
    assert by_id["verdict"]["status"] == "fail" and by_id["verdict"]["note"] == "alpha"
    assert by_id["stop_processes"]["status"] == by_id["audit"]["status"] == "pass"


def test_alpha_note_on_a_passing_run_still_has_the_accuracy_line(rig):
    alpha = [sys.executable, "-c", "print('МЕХАНИЗМ: PASS'); print('ТОЧНОСТЬ: FAIL все 7 пропущены')"]
    assert rig.run(rig.cfg(alpha=alpha)) == 0
    by_id = {item["id"]: item for item in _stages(rig)["stages"]}
    assert by_id["alpha"]["status"] == "pass" and by_id["alpha"]["note"] == "ТОЧНОСТЬ: FAIL все 7 пропущены"


def test_every_run_of_a_series_gets_its_own_stages_json(rig):
    assert rig.run(rig.cfg(), "--runs", "2") == 0
    first, second = _stages(rig, 1), _stages(rig, 2)
    assert (first["run"], second["run"]) == (1, 2)
    assert set(_statuses(first).values()) == set(_statuses(second).values()) == {"pass"}
    assert first["stages"][0]["started"] < second["stages"][0]["started"]


# ---------------------------------------------------------------------------------------------------------------------
# «НЕ ПРОВЕРЕН» (сценарий не дошёл) отличается от FAIL (дошёл, проверка красная)
# ---------------------------------------------------------------------------------------------------------------------


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def _verdict(rig: Rig) -> str:
    return (rig.run_dir() / "verdict.md").read_text(encoding="utf-8")


def test_alpha_precondition_exit_3_is_not_checked_not_fail_and_exit_code_3(rig):
    alpha = _py("import sys; print('предусловие: нет ни одной строки диска'); sys.exit(3)")
    assert rig.run(rig.cfg(alpha=alpha)) == 3
    text = _verdict(rig)
    assert "МЕХАНИЗМ: НЕ ПРОВЕРЕН (сценарий не дошёл: α вышла по предусловию, код 3)" in text
    assert "МЕХАНИЗМ: FAIL" not in text
    summary = (rig.run_dir().parent / "summary.md").read_text(encoding="utf-8")
    assert "НЕ ПРОВЕРЕН" in summary


def test_audit_exit_2_is_not_checked_with_its_last_line_as_reason(rig):
    audit = _py("import sys; print('число слов --words не равно ... в журнале диска строк слова 0'); sys.exit(2)")
    alpha = _py("print('МЕХАНИЗМ: PASS')")
    assert rig.run(rig.cfg(alpha=alpha, audit=audit)) == 3
    text = _verdict(rig)
    assert "МЕХАНИЗМ: НЕ ПРОВЕРЕН (сценарий не дошёл: аудит отказал по входу, код 2: " in text
    assert "в журнале диска строк слова 0)" in text
    assert "МЕХАНИЗМ: FAIL" not in text


def test_no_disk_rows_in_the_run_is_not_checked_even_when_audit_and_alpha_pass(rig):
    audit = _py("print('ИТОГ: PASS (взятий 0, заданий 0, FAIL 0, пропусков 0, повторов 0, предупреждений 0)')")
    alpha = _py("print('МЕХАНИЗМ: PASS')")
    assert rig.run(rig.cfg(alpha=alpha, audit=audit)) == 3
    text = _verdict(rig)
    assert "МЕХАНИЗМ: НЕ ПРОВЕРЕН (сценарий не дошёл: в прогоне нет ни одной строки диска" in text


def test_reached_scenario_with_red_audit_is_still_fail_exit_1(rig):
    audit = _py("import sys; print('ИТОГ: FAIL (взятий 13, заданий 13, FAIL 3, пропусков 9, повторов 0)'); sys.exit(1)")
    alpha = _py("print('МЕХАНИЗМ: PASS')")
    assert rig.run(rig.cfg(alpha=alpha, audit=audit)) == 1
    text = _verdict(rig)
    assert "МЕХАНИЗМ: FAIL" in text and "НЕ ПРОВЕРЕН" not in text
    assert "причина: audit" in text


def test_skips_only_run_with_disk_rows_is_not_mistaken_for_no_disk_rows(rig):
    audit = _py("print('ИТОГ: PASS (взятий 0, заданий 0, FAIL 0, пропусков 4, повторов 0, предупреждений 0)')")
    alpha = _py("print('МЕХАНИЗМ: PASS')")
    assert rig.run(rig.cfg(alpha=alpha, audit=audit)) == 0
    assert "МЕХАНИЗМ: PASS" in _verdict(rig)


# ---------------------------------------------------------------------------------------------------------------------
# Сбой уборки перекрывает «не проверен»
# ---------------------------------------------------------------------------------------------------------------------


def test_cleanup_failure_stays_fail_over_not_checked(rig):
    """α вышла по предусловию (код 3), но оставила порт `free_after` занятым: FAIL, не «не проверен»."""
    port = rig.extra_port
    holder = "import socket, time; s = socket.socket(); s.bind(('127.0.0.1', %d)); s.listen(100); time.sleep(15)" % port
    alpha = _py(
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {holder!r}], start_new_session=True)\n"
        "import socket\n"
        "for _ in range(100):  # держатель порта поднялся, прежде чем α выйдет\n"
        f"    try: socket.create_connection(('127.0.0.1', {port}), 0.2).close(); break\n"
        "    except OSError: time.sleep(0.1)\n"
        "sys.exit(3)"
    )
    cfg = rig.cfg(alpha=alpha, free_after=[rig.sim_port, rig.proto_port, port])
    assert rig.run(cfg) == 1
    text = _verdict(rig)
    assert "причина: порты" in text and "МЕХАНИЗМ: FAIL" in text
    assert "НЕ ПРОВЕРЕН" not in text


# ---------------------------------------------------------------------------------------------------------------------
# Две мягкие STOP_REQ при остановке из running: информативно (PASS~), любое иное сочетание — FAIL
# ---------------------------------------------------------------------------------------------------------------------

_STOP_INFO_PREFIX = "СТОП α: информативно (2 мягких STOP_REQ: пауза + выключение;"


def _stop_alpha(alpha_stops, exchange_stops, *, disconnect=True, extra_red=False):
    """α печатает вывод в формате живого прогона; журнал обмена пишется в `{log_dir}/devices/`."""
    shown = ", ".join(str(n) for n in alpha_stops)
    mech = "МЕХАНИЗМ: FAIL (B jobs.count, СТОП stop)" if extra_red else "МЕХАНИЗМ: FAIL (СТОП stop)"
    out = [
        f"СТОП stop: STOP_REQ [{shown}], строк после seq 652: 13 | отброшено строк 513 "
        f"→ FAIL: STOP_REQ строк {len(alpha_stops)} ≠ 1",
        "класс СТОП stop: МЕХАНИЗМ",
        *(["класс B jobs.count: МЕХАНИЗМ"] if extra_red else []),
        mech,
        "ТОЧНОСТЬ: 6 трудных (B #7)",
    ]
    stamp = "2026-11-22 18:11:47,296 [INFO] S.d.d.e.robot_main:"
    log = [f"#1 {stamp} #1  connect ok"]
    log += [f"#{i + 2} {stamp} #{i + 2} in W STOP_REQ = {n}" for i, n in enumerate(exchange_stops)]
    if disconnect:
        log.append(f"#99 {stamp} #99  disconnect")
    code = (
        "import sys, pathlib\n"
        "d = pathlib.Path(sys.argv[1]) / 'devices'; d.mkdir(parents=True, exist_ok=True)\n"
        f"(d / 'robot_exchange.log').write_text({chr(10).join(log)!r}, encoding='utf-8')\n"
        f"print({chr(10).join(out)!r})\n"
        "sys.exit(1)"
    )
    return [sys.executable, "-c", code, "{log_dir}"]


def test_two_soft_stop_req_after_pause_is_pass_tilde_with_info_line(rig):
    assert rig.run(rig.cfg(alpha=_stop_alpha([5, 9], [5, 9]))) == 0
    text = _verdict(rig)
    assert "МЕХАНИЗМ: PASS~" in text and _STOP_INFO_PREFIX in text
    assert "sim-audit-stop-req-diagnosis.md" in text and "причина:" not in text
    by_id = {item["id"]: item for item in _stages(rig)["stages"]}
    assert by_id["alpha"]["status"] == "pass" and _STOP_INFO_PREFIX in by_id["alpha"]["note"]
    assert "PASS~" in (rig.run_dir().parent / "summary.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("kwargs", "case"),
    [
        (dict(alpha_stops=[5, 9, 13], exchange_stops=[5, 9, 13]), "три записи"),
        (dict(alpha_stops=[5, 10], exchange_stops=[5, 10]), "не мягкая запись n % 4 != 1"),
        (dict(alpha_stops=[5, 9], exchange_stops=[5, 9], extra_red=True), "ещё один красный пункт"),
        (dict(alpha_stops=[5, 9], exchange_stops=[5, 9], disconnect=False), "нет disconnect после записей"),
        (dict(alpha_stops=[5, 9], exchange_stops=[5, 9, 13]), "журнал обмена не совпал с выводом α"),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_any_other_stop_combination_stays_fail(rig, kwargs, case):
    assert rig.run(rig.cfg(alpha=_stop_alpha(**kwargs))) == 1, case
    text = _verdict(rig)
    assert "МЕХАНИЗМ: FAIL" in text and "причина: alpha" in text
    assert "PASS~" not in text and "СТОП α: информативно" not in text


def test_soft_stop_pair_does_not_hide_a_red_audit(rig):
    audit = _py("import sys; print('ИТОГ: FAIL (взятий 13, заданий 13, FAIL 3, пропусков 9)'); sys.exit(1)")
    assert rig.run(rig.cfg(alpha=_stop_alpha([5, 9], [5, 9]), audit=audit)) == 1
    text = _verdict(rig)
    assert "МЕХАНИЗМ: FAIL" in text and "причина: audit" in text and "причина: alpha" not in text


# ---------------------------------------------------------------------------------------------------------------------
# Окно съёма α: выход за окно не дальше 5 мм — информативно (PASS~); образец — B #4 прогона 3 серии
# ---------------------------------------------------------------------------------------------------------------------

_WINDOW_INFO_PREFIX = "ОКНО α: информативно ("


def _window_alpha(items, fail_texts, *, stops=None, exchange_stops=None, disconnect=True):
    """α с красными пунктами: items — имена в скобках МЕХАНИЗМ, fail_texts — тексты FAIL пунктов `<кейс> #n`."""
    out = []
    for item, text in fail_texts.items():
        out.append(f"{item} вход И 60.0° → наблюдение: диск 'И' 63.2° → ячейка 5 | Δугла +3.2° | RES=1 → FAIL: {text}")
    if stops:
        out.append(
            f"СТОП stop: STOP_REQ [{', '.join(map(str, stops))}], строк после seq 652: 13 "
            f"→ FAIL: STOP_REQ строк {len(stops)} ≠ 1"
        )
    out += [f"класс {item}: МЕХАНИЗМ" for item in items]
    out += [f"МЕХАНИЗМ: FAIL ({', '.join(items)})", "ТОЧНОСТЬ: 6 трудных (B #12)"]
    stamp = "2026-11-22 18:11:47,296 [INFO] S.d.d.e.robot_main:"
    log = [f"#1 {stamp} #1  connect ok"]
    log += [f"#{i + 2} {stamp} #{i + 2} in W STOP_REQ = {n}" for i, n in enumerate(exchange_stops or [])]
    if disconnect:
        log.append(f"#99 {stamp} #99  disconnect")
    code = (
        "import sys, pathlib\n"
        "d = pathlib.Path(sys.argv[1]) / 'devices'; d.mkdir(parents=True, exist_ok=True)\n"
        f"(d / 'robot_exchange.log').write_text({chr(10).join(log)!r}, encoding='utf-8')\n"
        f"print({chr(10).join(out)!r})\n"
        "sys.exit(1)"
    )
    return [sys.executable, "-c", code, "{log_dir}"]


_WIN_4617 = "pick (461.7, -343.1) вне окна x(454.9, 461.5) y(-344.0, -342.0); ARGS[2] 4617 ≠ 4549…4615"
_WIN_4666 = "pick (466.6, -343.1) вне окна x(454.9, 461.5) y(-344.0, -342.0); ARGS[2] 4666 ≠ 4549…4615"
_WIN_Y = "pick (460.0, -349.0) вне окна x(454.9, 461.5) y(-344.0, -342.0); ARGS[3] 62046 ≠ 62096…62116"


def test_window_item_within_margin_is_pass_tilde_with_info_line(rig):
    alpha = _window_alpha(["B #4"], {"B #4": _WIN_4617})
    assert rig.run(rig.cfg(alpha=alpha)) == 0
    text = _verdict(rig)
    assert "МЕХАНИЗМ: PASS~" in text
    assert "ОКНО α: информативно (1 заданий вне окна съёма ≤ 5 мм: B #4 на 0.2 мм; шум центроида сети" in text
    assert "причина:" not in text and "СТОП α" not in text


def test_window_item_together_with_two_soft_stops_gives_two_info_lines(rig):
    alpha = _window_alpha(["B #4", "СТОП stop"], {"B #4": _WIN_4617}, stops=[5, 9], exchange_stops=[5, 9])
    assert rig.run(rig.cfg(alpha=alpha)) == 0
    text = _verdict(rig)
    assert "МЕХАНИЗМ: PASS~" in text and _WINDOW_INFO_PREFIX in text and "СТОП α: информативно" in text


def test_window_item_on_y_within_margin_is_pass_tilde(rig):
    assert rig.run(rig.cfg(alpha=_window_alpha(["D #2"], {"D #2": _WIN_Y}))) == 0
    assert "D #2 на 5.0 мм" in _verdict(rig)


@pytest.mark.parametrize(
    ("alpha_kwargs", "case"),
    [
        (dict(items=["B #4"], fail_texts={"B #4": _WIN_4666}), "дальше 5 мм"),
        (dict(items=["B #4"], fail_texts={"B #4": _WIN_4617 + "; rz"}), "окно плюс ещё причина"),
        (dict(items=["B #4"], fail_texts={"B #4": "слово ARGS[7] 1100 ≠ 1101"}), "не про окно"),
        (
            dict(items=["B #4", "B #5"], fail_texts={"B #4": _WIN_4617, "B #5": "слово ARGS[7] 1100 ≠ 1101"}),
            "второй пункт не про окно",
        ),
        (
            dict(
                items=["B #4", "СТОП stop"],
                fail_texts={"B #4": _WIN_4617},
                stops=[5, 9, 13],
                exchange_stops=[5, 9, 13],
            ),
            "окно плюс стоп с тремя записями",
        ),
        (dict(items=["B #4", "B jobs.count"], fail_texts={"B #4": _WIN_4617}), "красный пункт без текста окна"),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_window_deviations_stay_fail(rig, alpha_kwargs, case):
    assert rig.run(rig.cfg(alpha=_window_alpha(**alpha_kwargs))) == 1, case
    text = _verdict(rig)
    assert "МЕХАНИЗМ: FAIL" in text and "PASS~" not in text and "ОКНО α" not in text


def test_window_item_does_not_hide_a_red_audit(rig):
    audit = _py("import sys; print('ИТОГ: FAIL (взятий 13, заданий 13, FAIL 3, пропусков 9)'); sys.exit(1)")
    assert rig.run(rig.cfg(alpha=_window_alpha(["B #4"], {"B #4": _WIN_4617}), audit=audit)) == 1
    text = _verdict(rig)
    assert "МЕХАНИЗМ: FAIL" in text and "причина: audit" in text and "причина: alpha" not in text
