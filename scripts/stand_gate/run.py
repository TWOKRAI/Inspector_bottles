"""Живой прогон стенд-гейта: один кейс → JSON `stand5`-формата (перенос `stand5.py`, Task 5.6).

Отличия от `docs/reviews/2026-10-03_phase5-stand-w2/stand5.py`:
  * дренаж P10 — по ``introspect_queues(processor).chain_queue.size``: возврат к медиане трёх опросов
    до паузы, ОДИН вызов на опрос, шаг ≤ 20 мс (:func:`measure_drain`); в JSON ``pause.drain_s`` и
    ``pause.drain_poll_period_s`` (наибольший интервал между соседними опросами);
  * журнал — только ``messages.log``, выбор «самого полного» файла по ПУТИ, а не по имени
    (у stand5 все файлы звались ``messages.log`` и складывались в один);
  * замок ``stand.lock`` проверяется до старта (:func:`check_stand_lock`).
Стенд поднимает только лид под замком; тесты зовут CLI с ``--from-json``.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import yaml

from . import thresholds as T

WARMUP_S = 10
WINDOW_S = 30
PAUSE_AFTER_S = 5
PAUSE_SECS = 10
DRAIN_CAP_S = 30.0
PROCS = ["camera_0", "processor", "renderer", "inspector", "storage", "gui"]
CYC_KEYS = (
    "lag_dropped_items",
    "lag_dropped_total",
    "not_inspected_lag",
    "not_inspected_stale_restore",
    "not_inspected_stale_exec",
    "not_inspected_handled",
    "queue_wait_ms",
    "effective_hz",
    "cycles",
)
RS_KEYS = (
    "frame_stale_drops",
    "frame_torn_reads",
    "frame_restore_failures",
    "door_drops",
    "not_inspected_door",
    "queue_data_evicted",
    "frame_loan_exhausted",
    "errors_delivery_failed",
    "deferred_closes",
)
#: Кейсы профиля quick: (метка, transit_ms, пауза исполнителя processor).
QUICK_CASES: tuple[tuple[str, int, bool], ...] = (("E", 0, False), ("D100", 100, False), ("P10", 0, True))


class StandRunError(Exception):
    """Стенд не поднялся / замок чужой — код выхода 2."""


# --- замок ------------------------------------------------------------------------
def default_lock_path(tree: Path) -> Path:
    """``<основной checkout>/.claude/stand.lock`` — общий для всех worktree."""
    git = tree / ".git"
    if git.is_file():  # worktree: «gitdir: <main>/.git/worktrees/<имя>»
        text = git.read_text(encoding="utf-8").strip()
        gitdir = Path(text.split(":", 1)[1].strip())
        return gitdir.parents[2] / ".claude" / "stand.lock"
    return tree / ".claude" / "stand.lock"


def check_stand_lock(lock: Path, token: str | None) -> None:
    """Замок держит лид руками. Нет файла → код 2 (стенд не занят нами); ``token`` задан и не найден
    в файле → замок чужой, код 2."""
    if not lock.is_file():
        raise StandRunError(f"замок {lock} не взят — возьмите stand.lock до прогона")
    if token and token not in lock.read_text(encoding="utf-8", errors="replace"):
        raise StandRunError(f"замок {lock} чужой (нет токена {token!r})")


# --- рецепт -----------------------------------------------------------------------
def render(tree: Path, out_dir: Path, transit_ms: int) -> Path:
    """`stand.yaml` → 1080p@100, ``extras.overflow: every`` на processor и inspector, ``transit_ms``."""
    r = yaml.safe_load((tree / "scripts/capacity_bench/recipes/stand.yaml").read_text(encoding="utf-8"))
    for p in r["processes"]:
        name = p["process_name"]
        for pl in p.get("plugins") or []:
            cls = str(pl.get("plugin_class", ""))
            if cls.endswith("CameraServicePlugin"):
                pl["resolution_width"], pl["resolution_height"] = 1920, 1080
                p["source_target_fps"] = 100
            if cls.endswith("RobotControlPlugin"):
                pl["reject_delay_ms"] = 0
                if transit_ms:
                    pl["transit_ms"] = transit_ms
            if "db_path" in pl:
                pl["db_path"] = str(out_dir / Path(pl["db_path"]).name)
        if name in T.EVERY_PROCESSES:
            p.setdefault("extras", {})["overflow"] = "every"
    obs = r.setdefault("observability", {}).setdefault("processes", {}).setdefault("inspector", {})
    obs["events"] = {"first_n": 1, "every_mth": 1}
    out = out_dir / "stand_gate_recipe.yaml"
    out.write_text(yaml.safe_dump(r, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out


# --- снимки -----------------------------------------------------------------------
def _payload(resp: Any) -> dict | None:
    """Ответ драйвера бывает обёрнут; ищем dict с ключом workers/router_stats."""
    if isinstance(resp, dict):
        if "workers" in resp or "router_stats" in resp:
            return resp
        for v in resp.values():
            got = _payload(v)
            if got is not None:
                return got
    return None


def chain_queue_size(resp: Any) -> int | None:
    """``chain_queue.size`` из ответа ``introspect_queues`` (на любой глубине)."""
    if isinstance(resp, dict):
        cq = resp.get("chain_queue")
        if isinstance(cq, dict) and isinstance(cq.get("size"), int):
            return cq["size"]
        for v in resp.values():
            got = chain_queue_size(v)
            if got is not None:
                return got
    return None


def snap(drv: Any, procs: list[str]) -> dict:
    out = {}
    for name in procs:
        rec: dict[str, Any] = {"workers": {}, "rs": {}}
        try:
            st = _payload(drv.introspect_status(name)) or {}
            for wn, ws in (st.get("workers") or {}).items():
                if isinstance(ws, dict):
                    rec["workers"][wn] = {k: ws[k] for k in CYC_KEYS if k in ws}
                    rec["workers"][wn]["_keys"] = sorted(k for k in ws if "inspect" in k or "lag" in k)
            rs = (_payload(drv.introspect_router_stats(name)) or {}).get("router_stats") or {}
            rec["rs"] = {k: rs[k] for k in RS_KEYS if k in rs}
            rec["rs_all"] = {k: v for k, v in rs.items() if isinstance(v, (int, float)) and v}
            rec["queues"] = drv.introspect_queues(name)
        except Exception as exc:  # noqa: BLE001 — снимок неполон, причина в JSON
            rec["error"] = f"{type(exc).__name__}: {exc}"
        out[name] = rec
    return out


# --- дренаж -----------------------------------------------------------------------
def measure_drain(
    poll: Callable[[], int | None],
    baseline: float,
    *,
    step_s: float = T.DRAIN_POLL_STEP_S,
    cap_s: float = DRAIN_CAP_S,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Опрос ``poll()`` (ОДИН вызов драйвера) с шагом ``step_s`` до ``size <= baseline`` или ``cap_s``.

    Возвращает ``drain_s`` (от старта до первого опроса, где очередь вернулась; ``None`` — не вернулась
    за ``cap_s``), ``drain_poll_period_s`` (наибольший интервал между соседними опросами — худший шаг,
    по нему судится доказуемость порога) и ``drain_trace``.
    """
    t0 = clock()
    last = t0
    period = 0.0
    trace: list[tuple[float, int | None]] = []
    while True:
        t_call = clock()
        size = poll()
        t_done = clock()
        period = max(period, t_done - last)
        last = t_done
        elapsed = t_done - t0
        trace.append((round(elapsed, 4), size))
        if size is not None and size <= baseline:
            return {"drain_s": round(elapsed, 4), "drain_poll_period_s": round(period, 4), "drain_trace": trace[:200]}
        if elapsed >= cap_s:
            return {"drain_s": None, "drain_poll_period_s": round(period, 4), "drain_trace": trace[:200]}
        sleep(max(0.0, step_s - (clock() - t_call)))


def pause_executor(drv: Any, res: dict, secs: float) -> bool:
    st = _payload(drv.introspect_status("processor")) or {}
    names = [w for w in (st.get("workers") or {}) if "exec" in w.lower() or "pipeline" in w.lower()]
    res["pause_worker_names"] = list(st.get("workers") or {})
    if not names:
        res["pause_error"] = "executor worker not found"
        return False
    worker = names[0]
    import psutil

    def _poll() -> int | None:
        return chain_queue_size(drv.introspect_queues("processor"))

    pre = [s for s in (_poll() for _ in range(3)) if s is not None]
    baseline = statistics.median(pre) if pre else 0
    pid = st.get("pid")
    rss0 = psutil.Process(pid).memory_info().rss if pid else None
    t = time.perf_counter()
    res["pause_stop"] = drv.send_command("processor", "worker.stop", {"worker_name": worker}, timeout=10)
    time.sleep(secs)
    res["pause_mid"] = snap(drv, ["processor"])
    rss1 = psutil.Process(pid).memory_info().rss if pid else None
    res["pause_start"] = drv.send_command("processor", "worker.start", {"worker_name": worker}, timeout=10)
    t_res = time.perf_counter()
    drain = measure_drain(_poll, baseline)
    res["pause"] = {
        "worker": worker,
        "stopped_s": round(t_res - t, 1),
        "rss0": rss0,
        "rss1": rss1,
        "drain_baseline": baseline,
        "drain_pre_polls": pre,
        **drain,
        "after": snap(drv, PROCS),
    }
    return True


# --- журнал -----------------------------------------------------------------------
EV = re.compile(r"event inspection: (\S+): (.*?) trace=(\S+)")
FEEDER_RELEASE = "отпуск фидер"  # подстрока строки отпуска фидера (число — в отчёт, без порога)


def journal(log_dir: Path) -> dict:
    """Журнал по файлам ``messages.log`` (никогда ``observability.db``: бинарный SQLite даёт ложные дубли)."""
    rows: list[tuple[str, str, str, str]] = []
    feeder = 0
    for f in Path(log_dir).rglob("messages.log"):
        if not f.is_file():
            continue
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(f.relative_to(log_dir))
        feeder += txt.count(FEEDER_RELEASE)
        for m in EV.finditer(txt):
            rows.append((rel, m.group(1), m.group(2)[:80], m.group(3)))
    by_file: dict[str, int] = {}
    for fn, *_ in rows:
        by_file[fn] = by_file.get(fn, 0) + 1
    # Одна строка может лежать в нескольких файлах (каналы scope BUSINESS) — берём самый полный файл.
    best = max(by_file, key=lambda k: by_file[k]) if by_file else None
    sel = [r for r in rows if r[0] == best]
    traces = [r[3] for r in sel]
    markers = [r for r in sel if "не проверен" in r[2]]
    return {
        "files": by_file,
        "file": best,
        "rows": len(sel),
        "distinct": len(set(traces)),
        "dup": len(traces) - len(set(traces)),
        "markers": len(markers),
        "verdicts": len(sel) - len(markers),
        "feeder_release_lines": feeder,
    }


def _rc(drv: Any) -> Any:
    try:
        return drv.send_command("inspector", "get_stats", {}, timeout=10)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


# --- кейс -------------------------------------------------------------------------
def run_case(tree: Path, tag: str, transit_ms: int, pause: bool, port: int) -> dict:
    """Один кейс профиля quick → dict JSON. Сбой подъёма → :class:`StandRunError`."""
    for k in [k for k in os.environ if k.startswith("FW_SHM_")]:
        del os.environ[k]
    from backend_ctl.harness import BackendHarness

    case_dir = Path(tempfile.mkdtemp(prefix=f"stand_gate_{tag}_"))
    log_dir = case_dir / "logs"
    log_dir.mkdir()
    recipe = render(tree, case_dir, transit_ms)
    res: dict[str, Any] = {
        "tag": tag,
        "overflow": "every",
        "secs": WINDOW_S,
        "reject_delay_ms": 0,
        "transit_ms": transit_ms,
        "case_dir": str(case_dir),
    }
    harness = BackendHarness(recipe=recipe, port=port, ready_timeout=90, log_dir=log_dir)
    t_boot = time.perf_counter()
    try:
        drv = harness.start()
    except Exception as exc:  # noqa: BLE001
        raise StandRunError(f"стенд не поднялся: {type(exc).__name__}: {exc}") from exc
    res["start_s"] = round(time.perf_counter() - t_boot, 2)
    try:
        t_ready = time.perf_counter()
        first = None
        while time.perf_counter() - t_ready < 5:
            try:
                st = _payload(drv.introspect_status("camera_0")) or {}
                cyc = sum(
                    int(ws.get("cycles") or 0) for ws in (st.get("workers") or {}).values() if isinstance(ws, dict)
                )
            except Exception:  # noqa: BLE001
                cyc = 0
            if cyc > 0:
                first = round(time.perf_counter() - t_ready, 3)
                break
            time.sleep(0.02)
        res["first_frame_after_ready_s"] = first
        time.sleep(max(0.0, WARMUP_S - (time.perf_counter() - t_ready)))
        res["s0"] = snap(drv, PROCS)
        t0 = time.perf_counter()
        hz: dict[str, list[float]] = {p: [] for p in PROCS}
        paused = None
        while time.perf_counter() - t0 < WINDOW_S:
            if pause and paused is None and time.perf_counter() - t0 > PAUSE_AFTER_S:
                paused = pause_executor(drv, res, PAUSE_SECS)
            ov = drv.system_overview(timeout=5)
            for p in PROCS:
                v = ov.get("processes", {}).get(p, {}).get("hz")
                if isinstance(v, (int, float)):
                    hz[p].append(float(v))
            time.sleep(2)
        res["window_s"] = round(time.perf_counter() - t0, 2)
        res["s1"] = snap(drv, PROCS)
        res["rc_s1"] = _rc(drv)
        res["hz_median"] = {p: (statistics.median(v) if v else None) for p, v in hz.items()}
        # После worker.pause_all камера не отвечает на introspect — F снимается ДО паузы.
        res["camera_before_pause"] = snap(drv, ["camera_0"])["camera_0"]
        res["camera_pause"] = drv.send_command("camera_0", "worker.pause_all", timeout=10)
        prev = None
        cur: dict = {}
        for _ in range(30):
            time.sleep(1)
            cur = snap(drv, PROCS)
            sig = json.dumps({p: (v["workers"], v["rs"]) for p, v in cur.items()}, sort_keys=True, default=str)
            if sig == prev:
                break
            prev = sig
        res["s2"] = cur
        res["rc_s2"] = _rc(drv)
    finally:
        harness.stop()
    res["journal"] = journal(log_dir)
    res["feeder_release_lines"] = res["journal"]["feeder_release_lines"]
    return res
