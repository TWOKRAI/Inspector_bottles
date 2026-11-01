# -*- coding: utf-8 -*-
# ruff: noqa: E501  (русские docstring/строки плана длиннее 120)
"""stand_c60.py - живой стенд C-60 (lifecycle-stop-ownership): сценарии S8 и S8w, A/B «база / после».

Вопрос стенда: получает ли плагин процесса весть о стопе (хук ``request_stop``) ДО ожидания долгой операции исполнителя.
Ребёнок ``c60`` (``stand_c60_child.py``): GenericProcess с исполнителем ``io`` (serial) и плагином-зондом; команда
``c60.slow_io`` (executor="io") ждёт ``L`` = 10,0 с; зонд пишет в файл-метку моменты ``request_stop``, ``shutdown`` и
конца операции (``time.monotonic()``; на Windows часы общие для процессов, шаг 15,6 мс).

Сценарий: ``c60.slow_io`` -> пауза 0,5 с -> ``t_send`` -> ``process.stop c60`` -> ответ -> метки. Бэкенд ведёт только
backend_ctl (BACKEND_CTL=1, сокет ProcessManager; тот же router-путь, что у GUI). Без psutil, без GUI, без qt-mcp.
Свежий бэкенд на каждый повтор. База (``--base-root``, da3febe8e) и «после» (``--root``) чередуются в одном запуске.

Запуск (в окне стенда; PYTHONPATH = корень дерева «после», python - основной .venv):
    bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" \
        heavy inspector-bottles-ca <python> <этот файл> --scenario S8 --base-root <worktree базы> \
        --out <scratchpad> --results-dir <каталог results/...>
Без бэкенда: ``--help``, ``--dry-run`` (печатает план, пороги и прогоняет самопроверку вердиктов на синтетике).

Вердикты PASS/FAIL - против ``THRESHOLDS`` (литералы записаны в бриф до прогона, plans/lifecycle-stop-ownership/tasks/
C-60.md, «Стенд S8»). Зависание - FAIL с затраченным временем; нет метки / нет ответа / не поднялась предпосылка -
FAIL с пометкой ``invalid``. Расхождение с литералом - результат, порог не подгоняется.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import subprocess  # nosec B404 — стенд запускает бэкенд с литеральными аргументами
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
L9_DIR_DEFAULT = HERE.parent / "2026-10-26_lifecycle-stop-ownership_1.9b-stand"

# --------------------------------------------------------------------------------------------------------------
# Пороги (литералы брифа C-60, «Стенд S8»). Не выводятся из кода под проверкой, после прогона не меняются.
# --------------------------------------------------------------------------------------------------------------
THRESHOLDS: dict[str, dict[str, Any]] = {
    "S8": {
        "L_s": 10.0,
        "pause_s": 0.5,
        "stop_process_timeout_s": 5.0,
        "base_n": 3,
        "after_n": 5,
        "base_shutdown_min_s": 3.0,  # W = 3,0 (shutdown_timeout не задан -> 5,0), Δ0 <= 0,6
        "base_shutdown_max_s": 3.6,
        "after_request_stop_max_s": 0.6,
        "after_shutdown_min_s": 3.0,
        "after_shutdown_max_s": 3.6,
        "reply_delta_max_s": 0.3,  # медиана ответа «после» − медиана «база»
    },
    "S8w": {
        "stop_window_s": 10.0,
        "max_stop_window_s": 12.0,  # W = 7,0
        "base_n": 1,
        "after_n": 1,
        "base_shutdown_min_s": 7.0,
        "base_shutdown_max_s": 7.6,
        "after_request_stop_max_s": 0.6,
    },
}
STOP_PROCESS_TIMEOUT_S = 5.0  # окно PM
SHUTDOWN_TIMEOUT_S = 5.0  # = system.stop_timeout дерева (system.yaml: 5.0) = умолчание -> W = 3,0
CHILD = "c60"
CHILD_CLASS = "stand_c60_child.C60Child"
COMMAND = "c60.slow_io"
DEFAULT_REPO_RECIPE = "multiprocess_prototype/recipes/region_pipeline.yaml"
SEQ_S8 = ["base", "after", "base", "after", "base", "after", "after", "after"]  # база 3, после 5, чередование
SEQ_S8W = ["base", "after"]  # база - справка к «после» (n = 1)
WARN_NEEDLE = "не остановлен к сроку"


# --------------------------------------------------------------------------------------------------------------
# Чистая часть: разбор меток, статистика, вердикты (проверяются --dry-run на синтетике)
# --------------------------------------------------------------------------------------------------------------
def parse_marks(text: str) -> dict[str, float]:
    """``<событие>\\t<monotonic>`` построчно -> ``{событие: первый момент}``."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        parts = line.strip().split("\t")
        if len(parts) != 2:
            continue
        try:
            out.setdefault(parts[0], float(parts[1]))
        except ValueError:
            continue
    return out


def rel(marks: dict[str, float], event: str, t_send: float) -> float | None:
    return round(marks[event] - t_send, 4) if event in marks else None


def spread(values: list[float | None]) -> dict[str, Any]:
    got = [float(v) for v in values if v is not None]
    return {
        "n": len(values),
        "none": len(values) - len(got),
        "min": min(got) if got else None,
        "median": statistics.median(got) if got else None,
        "max": max(got) if got else None,
    }


def run_invalid_reason(r: dict[str, Any]) -> str | None:
    """Причина «прогон не измерение» (предпосылка, нет ответа, нет метки shutdown) или None."""
    if not r.get("precondition_ok"):
        return f"предпосылка: {r.get('precondition_note', '?')}"
    if r.get("reply_s") is None:
        return f"нет ответа process.stop (ждали {r.get('waited_s')} с) - зависание"
    if r.get("shutdown_s") is None:
        return "нет метки shutdown"
    return None


def _check_runs(runs: list[dict[str, Any]], label: str, reasons: list[str]) -> tuple[list[dict[str, Any]], bool]:
    valid: list[dict[str, Any]] = []
    invalid = False
    for i, r in enumerate(runs, 1):
        why = run_invalid_reason(r)
        if why:
            reasons.append(f"{label} r{i}: {why}")
            invalid = True
        else:
            valid.append(r)
    return valid, invalid


def judge_s8(
    base: list[dict[str, Any]], after: list[dict[str, Any]], th: dict[str, Any] | None = None, partial_ok: bool = False
) -> dict[str, Any]:
    """S8: база (n=3) и после (n=5) против литералов брифа. ``partial_ok`` - дымовой прогон (меньше повторов)."""
    th = th or THRESHOLDS["S8"]
    reasons: list[str] = []
    if not partial_ok:
        if len(base) != th["base_n"]:
            reasons.append(f"база: {len(base)} прогонов вместо {th['base_n']}")
        if len(after) != th["after_n"]:
            reasons.append(f"после: {len(after)} прогонов вместо {th['after_n']}")
    base_ok, inv_b = _check_runs(base, "база", reasons)
    after_ok, inv_a = _check_runs(after, "после", reasons)
    # база: метки request_stop нет, shutdown в [3,0; 3,6]
    for i, r in enumerate(base_ok, 1):
        if r.get("request_stop_s") is not None:
            reasons.append(
                f"база r{i}: метка request_stop есть ({r['request_stop_s']} с) - на базе хука быть не должно"
            )
        s = r["shutdown_s"]
        if not th["base_shutdown_min_s"] <= s <= th["base_shutdown_max_s"]:
            reasons.append(
                f"база r{i}: shutdown-t_send={s} вне [{th['base_shutdown_min_s']}; {th['base_shutdown_max_s']}]"
            )
    # после: request_stop <= 0,6; операция идёт; shutdown в [3,0; 3,6]; 5 из 5
    for i, r in enumerate(after_ok, 1):
        rs = r.get("request_stop_s")
        if rs is None:
            reasons.append(f"после r{i}: метки request_stop нет")
        elif rs > th["after_request_stop_max_s"]:
            reasons.append(f"после r{i}: request_stop-t_send={rs} > {th['after_request_stop_max_s']}")
        if rs is not None and not r.get("op_running_at_request_stop"):
            reasons.append(
                f"после r{i}: в момент request_stop операция не идёт (op_start/op_end: {r.get('op_start_s')}/{r.get('op_end_s')})"
            )
        s = r["shutdown_s"]
        if not th["after_shutdown_min_s"] <= s <= th["after_shutdown_max_s"]:
            reasons.append(
                f"после r{i}: shutdown-t_send={s} вне [{th['after_shutdown_min_s']}; {th['after_shutdown_max_s']}]"
            )
    # ответ process.stop: outcome/success после = база; медиана ответа после − база <= 0,3
    delta = None
    if base_ok and after_ok:
        b_out = {(r.get("outcome"), r.get("success")) for r in base_ok}
        a_out = {(r.get("outcome"), r.get("success")) for r in after_ok}
        if len(b_out) != 1 or a_out != b_out:
            reasons.append(
                f"outcome/success: база {sorted(map(str, b_out))}, после {sorted(map(str, a_out))} - не совпали или база нестабильна"
            )
        delta = round(
            statistics.median(r["reply_s"] for r in after_ok) - statistics.median(r["reply_s"] for r in base_ok), 4
        )
        if delta > th["reply_delta_max_s"]:
            reasons.append(f"время ответа: медиана после − база = {delta} > {th['reply_delta_max_s']}")
    return {
        "verdict": "FAIL" if reasons else "PASS",
        "invalid": bool((inv_a or inv_b) and reasons),
        "reasons": reasons,
        "base": {k: spread([r.get(k) for r in base]) for k in ("request_stop_s", "shutdown_s", "op_end_s", "reply_s")},
        "after": {
            k: spread([r.get(k) for r in after]) for k in ("request_stop_s", "shutdown_s", "op_end_s", "reply_s")
        },
        "reply_median_delta_s": delta,
    }


def judge_s8w(
    base: list[dict[str, Any]], after: list[dict[str, Any]], th: dict[str, Any] | None = None, partial_ok: bool = False
) -> dict[str, Any]:
    """S8w (окно ребёнка 10 -> W = 7,0): после - request_stop <= 0,6 с; база (справка) - shutdown в [7,0; 7,6]."""
    th = th or THRESHOLDS["S8w"]
    reasons: list[str] = []
    if not partial_ok and (len(base) != th["base_n"] or len(after) != th["after_n"]):
        reasons.append(f"прогонов: база {len(base)}/{th['base_n']}, после {len(after)}/{th['after_n']}")
    base_ok, inv_b = _check_runs(base, "база", reasons)
    after_ok, inv_a = _check_runs(after, "после", reasons)
    for i, r in enumerate(base_ok, 1):
        s = r["shutdown_s"]
        if not th["base_shutdown_min_s"] <= s <= th["base_shutdown_max_s"]:
            reasons.append(
                f"база r{i}: shutdown-t_send={s} вне [{th['base_shutdown_min_s']}; {th['base_shutdown_max_s']}]"
            )
        if r.get("request_stop_s") is not None:
            reasons.append(f"база r{i}: метка request_stop есть ({r['request_stop_s']} с)")
    for i, r in enumerate(after_ok, 1):
        rs = r.get("request_stop_s")
        if rs is None:
            reasons.append(f"после r{i}: метки request_stop нет")
        elif rs > th["after_request_stop_max_s"]:
            reasons.append(f"после r{i}: request_stop-t_send={rs} > {th['after_request_stop_max_s']}")
    return {
        "verdict": "FAIL" if reasons else "PASS",
        "invalid": bool((inv_a or inv_b) and reasons),
        "reasons": reasons,
        "base": {k: spread([r.get(k) for r in base]) for k in ("request_stop_s", "shutdown_s", "reply_s")},
        "after": {k: spread([r.get(k) for r in after]) for k in ("request_stop_s", "shutdown_s", "reply_s")},
    }


def _synthetic(tree: str, rs: float | None, sd: float, reply: float = 3.3, out: str = "exited") -> dict[str, Any]:
    return {
        "tree": tree,
        "precondition_ok": True,
        "request_stop_s": rs,
        "shutdown_s": sd,
        "op_start_s": -0.5,
        "op_end_s": None,
        "op_running_at_request_stop": rs is not None,
        "reply_s": reply,
        "outcome": out,
        "success": True,
    }


def selfcheck() -> list[str]:
    """Самопроверка судей на синтетике: «хороший» набор -> PASS, каждое нарушение -> FAIL. Возврат - список провалов."""
    bad: list[str] = []
    base = [_synthetic("base", None, 3.2) for _ in range(3)]
    good = [_synthetic("after", 0.1, 3.2) for _ in range(5)]
    if judge_s8(base, good)["verdict"] != "PASS":
        bad.append("хороший набор не дал PASS")
    cases = {
        "request_stop поздно": [_synthetic("after", 0.9, 3.2)] * 5,
        "нет request_stop": [_synthetic("after", None, 3.2)] * 5,
        "shutdown рано": [_synthetic("after", 0.1, 0.4)] * 5,
        "ответ медленнее": [_synthetic("after", 0.1, 3.2, reply=3.9)] * 5,
        "другой outcome": [_synthetic("after", 0.1, 3.2, out="terminated")] * 5,
        "4 из 5": [_synthetic("after", 0.1, 3.2)] * 4,
    }
    for name, after in cases.items():
        if judge_s8(base, after)["verdict"] != "FAIL":
            bad.append(f"{name}: нет FAIL")
    hung = dict(_synthetic("after", 0.1, 3.2), reply_s=None, waited_s=40.0)
    v = judge_s8(base, [hung] * 5)
    if v["verdict"] != "FAIL" or not v["invalid"]:
        bad.append("зависание: нет FAIL/invalid")
    if judge_s8([_synthetic("base", 0.1, 3.2)] * 3, good)["verdict"] != "FAIL":
        bad.append("метка request_stop на базе: нет FAIL")
    w_base, w_after = [_synthetic("base", None, 7.2)], [_synthetic("after", 0.1, 7.2)]
    if judge_s8w(w_base, w_after)["verdict"] != "PASS":
        bad.append("S8w хороший набор не дал PASS")
    if judge_s8w(w_base, [_synthetic("after", 2.0, 7.2)])["verdict"] != "FAIL":
        bad.append("S8w поздний request_stop: нет FAIL")
    return bad


# --------------------------------------------------------------------------------------------------------------
# Живая часть
# --------------------------------------------------------------------------------------------------------------
class C60Ctx:
    """Параметры прогона для ``stand_l9.Backend`` (читает root/out/python/recipe/door/boot_timeout_s/default_windows)."""

    def __init__(self, args: argparse.Namespace, root: Path, out: Path) -> None:
        self.root = root
        self.out = out
        self.python = args.python
        self.recipe = args.recipe
        self.door = args.door
        self.boot_timeout_s = args.boot_timeout
        self.default_windows = False


def load_l9(l9_dir: Path) -> Any:
    sys.path.insert(0, str(l9_dir))
    import stand_l9  # type: ignore[import-not-found]

    stand_l9.STOP_PROCESS_TIMEOUT_S = STOP_PROCESS_TIMEOUT_S  # Backend читает константы модуля при создании/запуске
    stand_l9.SHUTDOWN_TIMEOUT_S = SHUTDOWN_TIMEOUT_S
    return stand_l9


def make_backend_class(l9: Any, l9_dir: Path) -> type:
    class C60Backend(l9.Backend):
        """Backend стенда L9 + каталог стенда C-60 в PYTHONPATH и env зонда (копия ``start`` - только ради этого)."""

        mark_path: Path
        slow_s: float = 10.0

        def start(self) -> Any:
            from backend_ctl.driver import BackendDriver

            self.workdir.mkdir(parents=True, exist_ok=True)
            (self.workdir / "data").mkdir(exist_ok=True)
            manifest = self._write_configs()
            env = dict(os.environ)
            env.update(
                {
                    "PYTHONUTF8": "1",
                    "PYTHONPATH": os.pathsep.join([str(self.ctx.root), str(HERE)]),
                    "BACKEND_CTL": "1",
                    "BACKEND_CTL_PORT": str(self.port),
                    "INSPECTOR_MANIFEST": str(manifest),
                    "INSPECTOR_HEADLESS": "1",
                    "MULTIPROCESS_PID_FILE": str(self.workdir / "pids.jsonl"),
                    "INSPECTOR_PID_FILE": str(self.workdir / "pids.jsonl"),
                    "STAND_STOP_PROCESS_TIMEOUT": str(self.stop_window_s),
                    "STAND_C60_MARK": str(self.mark_path),
                    "STAND_C60_L": str(self.slow_s),
                }
            )
            self.windows["stop_process_timeout"] = self.stop_window_s
            if self.ceiling_s is not None:
                env["STAND_MAX_STOP_WINDOW"] = str(self.ceiling_s)
            else:
                env.pop("STAND_MAX_STOP_WINDOW", None)
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            t0 = time.monotonic()
            out = open(self.stdout_path, "wb")
            self.proc = subprocess.Popen(  # nosec B603 — свой python и скрипт стенда L9
                [self.ctx.python, str(l9_dir / "stand_backend.py")],
                cwd=str(self.workdir),
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
            drv = BackendDriver(port=self.port)
            deadline = t0 + self.ctx.boot_timeout_s
            while True:
                if self.proc.poll() is not None:
                    raise RuntimeError(
                        f"бэкенд завершился при старте, код {self.proc.returncode}; см. {self.stdout_path}"
                    )
                try:
                    drv.connect()
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise RuntimeError(f"сокет backend_ctl не открылся за {self.ctx.boot_timeout_s} с")
                    time.sleep(0.25)
            while time.monotonic() < deadline:
                if self.supervision(drv).get("devices", {}).get("alive"):
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("devices не стал alive за срок старта")
            self.boot_s = round(time.monotonic() - t0, 2)
            self.drv = drv
            text = self.stdout_path.read_text(encoding="utf-8", errors="replace")
            self.override_seen = f"stop_process_timeout={self.stop_window_s}" in text
            if self.ceiling_s is not None:
                self.ceiling_seen = f"orchestrator_config.max_stop_window_s={self.ceiling_s}" in text
                self.windows["max_stop_window_s"] = self.ceiling_s
            return drv

    return C60Backend


def add_c60(l9: Any, drv: Any, extra: dict[str, Any] | None) -> dict[str, Any]:
    """Добавить ``c60`` через ``topology.apply`` (с ``topology.diff``-предохранителем), по образцу ``add_slow_fast``."""
    leaf, supervision = l9.leaf, l9.Backend.supervision
    desired = {
        "name": "stand_c60",
        "processes": [{"process_name": CHILD, "process_class": CHILD_CLASS, **(extra or {})}],
        "wires": [],
    }
    engine_deadline = time.monotonic() + 60.0
    while True:
        diff = leaf(drv.send_command("ProcessManager", "topology.diff", {"topology_dict": desired}, timeout=30.0))
        if diff.get("success") is True:
            break
        if time.monotonic() > engine_deadline:
            raise RuntimeError(f"topology.diff не стал успешным за 60 с: {diff}")
        time.sleep(0.5)
    touched = {c.get("process_name") for c in (diff.get("commands") or []) if isinstance(c, dict)}
    if "devices" in touched or "gui" in touched:
        raise RuntimeError(f"topology.diff трогает protected-процессы: {sorted(touched)}")
    t0 = time.monotonic()
    res = leaf(drv.send_command("ProcessManager", "topology.apply", {"topology_dict": desired}, timeout=120.0))
    if res.get("success") is not True:
        raise RuntimeError(f"topology.apply c60 не удался: {res}")
    end = time.monotonic() + 45.0
    while time.monotonic() < end and not supervision(drv, CHILD).get(CHILD, {}).get("alive"):
        time.sleep(0.25)
    if not supervision(drv, CHILD).get(CHILD, {}).get("alive"):
        raise RuntimeError("c60 не alive после topology.apply")
    time.sleep(1.5)  # плагин загружен, команда зарегистрирована, читатели очередей открыты
    return {"apply_s": round(time.monotonic() - t0, 2), "diff_commands": sorted(str(x) for x in touched)}


def read_marks(path: Path) -> dict[str, float]:
    try:
        return parse_marks(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}


def child_pids(snap: dict[str, Any]) -> list[int]:
    pid = snap.get("pid")
    return [pid] if isinstance(pid, int) else []


def run_one(
    l9: Any,
    backend_cls: type,
    ctx: C60Ctx,
    tree: str,
    root: Path,
    scenario: str,
    idx: int,
    window: dict[str, Any] | None,
) -> dict[str, Any]:
    """Один повтор: свежий бэкенд дерева ``tree``, ``c60.slow_io``, пауза, ``process.stop c60``, метки."""
    import copy

    tctx = copy.copy(ctx)
    tctx.root = root
    tag = f"{scenario.lower()}_{tree}_r{idx}"
    be = backend_cls(tctx, tag)
    be.mark_path = be.workdir / "c60.marks"
    be.slow_s = THRESHOLDS["S8"]["L_s"]
    be.stop_window_s = STOP_PROCESS_TIMEOUT_S
    if window:
        be.ceiling_s = window["max_stop_window_s"]
    be.workdir.mkdir(parents=True, exist_ok=True)
    be.mark_path.write_text("", encoding="utf-8")
    rec: dict[str, Any] = {
        "scenario": scenario,
        "tree": tree,
        "root": str(root),
        "run": idx,
        "precondition_ok": False,
        "window": window or {},
        "marks_file": str(be.mark_path),
    }
    pids: list[int] = []
    try:
        drv = be.start()
        rec["boot_s"] = be.boot_s
        rec["override_seen"] = be.override_seen
        rec["ceiling_seen"] = be.ceiling_seen
        extra = {"stop_window_s": window["stop_window_s"]} if window else None
        rec["apply"] = add_c60(l9, drv, extra)
        sup = be.supervision(drv, CHILD).get(CHILD, {})
        rec["child_before_stop"] = sup
        pids = child_pids(sup)
        rec["precondition_ok"] = bool(be.override_seen and (be.ceiling_seen if window else True))
        if not rec["precondition_ok"]:
            rec["precondition_note"] = (
                f"подмена окон PM не сработала: override={be.override_seen} ceiling={be.ceiling_seen}"
            )
        else:
            from multiprocess_framework.modules.message_module import build_command_message

            msg = build_command_message(CHILD, COMMAND, {}, sender=drv._sender, reply_to=drv._reply_to)
            t_cmd = time.monotonic()
            op = l9.send_async(drv, msg, 60.0)
            started = None
            while time.monotonic() - t_cmd < 5.0:
                if "op_start" in read_marks(be.mark_path):
                    started = time.monotonic() - t_cmd
                    break
                time.sleep(0.01)
            rec["op_start_delay_s"] = None if started is None else round(started, 3)
            if started is None:
                rec["precondition_ok"] = False
                rec["precondition_note"] = (
                    "метка op_start не появилась за 5 с после c60.slow_io (команда не дошла/плагин не загружен)"
                )
            else:
                rest = th_pause(t_cmd)
                rec["pause_slept_s"] = round(rest, 3)
                wall_send = time.time()
                p = l9.send_async(drv, l9.pm_msg("process.stop", {"process_name": CHILD}, ctx.door), 40.0)
                t_send = p.t_send
                p.ev.wait(40.0)
                rec["waited_s"] = round(time.monotonic() - t_send, 3)
                rec["reply_s"] = p.latency()
                rec["reply"] = l9.leaf(p.result) if p.result is not None else None
                rec["wall_send"] = wall_send
                time.sleep(0.3)
                marks = read_marks(be.mark_path)
                rec["marks_abs"] = marks
                rec["t_send"] = t_send
                for key, ev in (
                    ("request_stop_s", "request_stop"),
                    ("shutdown_s", "shutdown"),
                    ("op_start_s", "op_start"),
                    ("op_end_s", "op_end"),
                ):
                    rec[key] = rel(marks, ev, t_send)
                rs = rec["request_stop_s"]
                oe = rec["op_end_s"]
                rec["op_running_at_request_stop"] = bool(
                    rs is not None
                    and rec["op_start_s"] is not None
                    and rec["op_start_s"] < rs
                    and (oe is None or oe > rs)
                )
                reply = rec["reply"] if isinstance(rec["reply"], dict) else {}
                rec["outcome"] = reply.get("outcome", "<нет>")
                rec["success"] = reply.get("success")
                rec["op_reply_arrived"] = op.answered
    except Exception as exc:  # noqa: BLE001
        rec["error"] = repr(exc)
        rec["precondition_note"] = rec.get("precondition_note") or repr(exc)
    finally:
        be.stop()
    # уборка: только по PID этого прогона (бэкенд и ребёнок c60)
    leftovers = l9.pids_alive(([be.proc.pid] if be.proc else []) + pids)
    rec["leftover_pids_before_kill"] = leftovers
    if leftovers:
        l9.kill_pids(leftovers)
    rec["leftover_pids_after_kill"] = l9.pids_alive(leftovers) if leftovers else []
    rec.update(scan_warn(l9, be.log_root, rec.get("wall_send")))
    return rec


def th_pause(t_cmd: float) -> float:
    """Добить паузу до 0,5 с после отправки ``c60.slow_io`` (op_start мог прийти раньше). Возврат - сколько спали."""
    want = THRESHOLDS["S8"]["pause_s"] - (time.monotonic() - t_cmd)
    if want > 0:
        time.sleep(want)
        return want
    return 0.0


def scan_warn(l9: Any, log_root: Path, wall_send: float | None) -> dict[str, Any]:
    """Строки WARNING исполнителя «не остановлен к сроку» (keyed_executor.py) и их момент относительно ``wall_send``."""
    lines: list[dict[str, Any]] = []
    if log_root.exists():
        for p in sorted(log_root.rglob("*.log")):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for raw in text.splitlines():
                if WARN_NEEDLE in raw:
                    m = l9._LOG_LINE.match(raw.strip())
                    ts = l9.parse_log_ts(m.group(1)) if m else None
                    lines.append(
                        {
                            "file": str(p.relative_to(log_root)),
                            "rel_send_s": None if ts is None or wall_send is None else round(ts - wall_send, 3),
                            "text": raw.strip()[:200],
                        }
                    )
    return {"executor_warn": lines}


def run_sequence(
    l9: Any,
    backend_cls: type,
    ctx: C60Ctx,
    scenario: str,
    seq: list[str],
    roots: dict[str, Path],
    window: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    counters = {"base": 0, "after": 0}
    for tree in seq:
        counters[tree] += 1
        t0 = time.time()
        rec = run_one(l9, backend_cls, ctx, tree, roots[tree], scenario, counters[tree], window)
        rec["started_at"] = dt.datetime.fromtimestamp(t0).isoformat(timespec="seconds")
        runs.append(rec)
        print(
            f"[{scenario} {tree} r{counters[tree]}] request_stop={rec.get('request_stop_s')} shutdown={rec.get('shutdown_s')} "
            f"op_end={rec.get('op_end_s')} reply_s={rec.get('reply_s')} outcome={rec.get('outcome')} success={rec.get('success')} "
            f"precond={rec['precondition_ok']} err={rec.get('error')}",
            flush=True,
        )
    return runs


# --------------------------------------------------------------------------------------------------------------
# Отчёт
# --------------------------------------------------------------------------------------------------------------
def _f(x: Any, nd: int = 3) -> str:
    return "—" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def markdown(rows: dict[str, dict[str, Any]], raw: dict[str, list[dict[str, Any]]]) -> str:
    out = ["# C-60 / S8, S8w — числа прогона\n"]
    for name, verdict in rows.items():
        out.append(f"## {name}: **{verdict['verdict']}**{' (invalid)' if verdict['invalid'] else ''}\n")
        out.append(
            "| дерево | повтор | request_stop−t_send, с | shutdown−t_send, с | конец операции−t_send, с | op идёт при request_stop | outcome / success | ответ process.stop, с |"
        )
        out.append("|---|---|---|---|---|---|---|---|")
        for r in raw[name]:
            out.append(
                f"| {r['tree']} | {r['run']} | {_f(r.get('request_stop_s'))} | {_f(r.get('shutdown_s'))} | {_f(r.get('op_end_s'))} "
                f"| {r.get('op_running_at_request_stop')} | {r.get('outcome')} / {r.get('success')} | {_f(r.get('reply_s'))} |"
            )
        out.append("")
        for tree in ("base", "after"):
            sp = verdict[tree]
            out.append(
                f"- {tree}: "
                + "; ".join(
                    f"{k}: n={v['n']} none={v['none']} min={_f(v['min'])} med={_f(v['median'])} max={_f(v['max'])}"
                    for k, v in sp.items()
                )
            )
        if verdict.get("reply_median_delta_s") is not None:
            out.append(f"- медиана ответа после − база: {verdict['reply_median_delta_s']} с")
        out.append("")
        out.extend(f"- {reason}" for reason in verdict["reasons"]) if verdict["reasons"] else out.append(
            "- расхождений с литералами нет"
        )
        out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------------------------------------------
def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Стенд C-60: S8 / S8w, A/B база и после. Подробности - докстринг.")
    ap.add_argument("--scenario", default="S8", help="S8 | S8w | S8,S8w")
    ap.add_argument(
        "--root", default=str(HERE.parents[2]), help="корень дерева «после» (по умолчанию worktree со скриптом)"
    )
    ap.add_argument("--base-root", default=None, help="корень дерева базы (da3febe8e); без него только «после»")
    ap.add_argument(
        "--sequence", default=None, help="переопределить порядок деревьев: base,after,... (дымовой запуск: after)"
    )
    ap.add_argument("--python", default=sys.executable, help="интерпретатор для бэкенда (основной .venv)")
    ap.add_argument("--recipe", default=DEFAULT_REPO_RECIPE)
    ap.add_argument("--door", choices=("direct", "command"), default="direct")
    ap.add_argument("--out", default=None, help="каталог логов и сырых файлов прогона (scratchpad, не в git)")
    ap.add_argument("--results-dir", default=None, help="каталог raw.json + results.md (в git)")
    ap.add_argument("--l9-dir", default=str(L9_DIR_DEFAULT), help="каталог stand_l9.py / stand_backend.py")
    ap.add_argument("--boot-timeout", type=float, default=90.0)
    ap.add_argument("--dry-run", action="store_true", help="план, пороги, самопроверка вердиктов; бэкенд не трогать")
    return ap.parse_args(argv)


def plan(args: argparse.Namespace) -> list[str]:
    lines = []
    for sc in picked_of(args):
        seq = seq_of(args, sc)
        lines.append(f"{sc}: порядок деревьев {seq} (база {seq.count('base')}, после {seq.count('after')})")
    lines.append(
        f"окна PM: stop_process_timeout={STOP_PROCESS_TIMEOUT_S}, shutdown_timeout={SHUTDOWN_TIMEOUT_S} -> W = 3,0 с; S8w: stop_window_s=10, max_stop_window_s=12 -> W = 7,0 с"
    )
    lines.append(f"L = {THRESHOLDS['S8']['L_s']} с; пауза {THRESHOLDS['S8']['pause_s']} с между c60.slow_io и t_send")
    lines.append("пороги: " + json.dumps(THRESHOLDS, ensure_ascii=False))
    return lines


def picked_of(args: argparse.Namespace) -> list[str]:
    picked = [s.strip() for s in args.scenario.split(",") if s.strip()]
    bad = [s for s in picked if s not in ("S8", "S8w")]
    if bad:
        raise SystemExit(f"сценарии {bad} недоступны (S8, S8w)")
    return picked


def seq_of(args: argparse.Namespace, scenario: str) -> list[str]:
    if args.sequence:
        seq = [x.strip() for x in args.sequence.split(",") if x.strip()]
    else:
        seq = list(SEQ_S8 if scenario == "S8" else SEQ_S8W)
    if not args.base_root:
        seq = [x for x in seq if x == "after"]
    bad = [x for x in seq if x not in ("base", "after")]
    if bad:
        raise SystemExit(f"--sequence: недопустимо {bad}")
    return seq


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        rec = getattr(stream, "reconfigure", None)
        if callable(rec):
            rec(encoding="utf-8", errors="replace")
    args = parse_args(sys.argv[1:] if argv is None else argv)
    picked = picked_of(args)
    if args.dry_run:
        print("[dry-run] бэкенд не запускается. План:")
        for line in plan(args):
            print("  -", line)
        bad = selfcheck()
        print("[dry-run] самопроверка вердиктов:", "OK" if not bad else f"ПРОВАЛ: {bad}")
        return 1 if bad else 0

    out = (Path(args.out) if args.out else HERE / "results" / "_run" / time.strftime("%Y%m%d_%H%M%S")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    results_dir = Path(args.results_dir).resolve() if args.results_dir else out
    results_dir.mkdir(parents=True, exist_ok=True)
    roots = {"after": Path(args.root).resolve()}
    if args.base_root:
        roots["base"] = Path(args.base_root).resolve()
    l9_dir = Path(args.l9_dir).resolve()
    l9 = load_l9(l9_dir)
    backend_cls = make_backend_class(l9, l9_dir)
    ctx = C60Ctx(args, roots["after"], out)
    started = time.time()
    raw: dict[str, list[dict[str, Any]]] = {}
    rows: dict[str, dict[str, Any]] = {}
    for sc in picked:
        seq = seq_of(args, sc)
        window = THRESHOLDS["S8w"] if sc == "S8w" else None
        runs = run_sequence(l9, backend_cls, ctx, sc, seq, roots, window)
        raw[sc] = runs
        base = [r for r in runs if r["tree"] == "base"]
        after = [r for r in runs if r["tree"] == "after"]
        partial = bool(args.sequence) or not args.base_root
        rows[sc] = (judge_s8w if sc == "S8w" else judge_s8)(base, after, partial_ok=partial)
        (results_dir / "raw.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    summary = {
        "roots": {k: str(v) for k, v in roots.items()},
        "python": args.python,
        "thresholds": THRESHOLDS,
        "elapsed_s": round(time.time() - started, 1),
        "rows": rows,
    }
    (results_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    md = markdown(rows, raw)
    (results_dir / "results_run.md").write_text(md, encoding="utf-8")
    print(md)
    return 0 if all(v["verdict"] == "PASS" for v in rows.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
