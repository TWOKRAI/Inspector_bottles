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
import subprocess
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
LOCK_MODE_MEASURE = "measure"


def default_lock_path(tree: Path) -> Path:
    """``<родитель основного дерева>/stand.lock`` (ред. 4): путь от ``git rev-parse --git-common-dir``,
    а не от worktree — один файл протокола на все деревья (сегодня ``D:\\PROJECT_INNOTECH\\Inspector_vision``)."""
    proc = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"], cwd=tree, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise StandRunError(f"git rev-parse --git-common-dir не ответил в {tree}: {proc.stderr.strip()}")
    common = Path(proc.stdout.strip())
    if not common.is_absolute():
        common = tree / common
    return common.resolve().parent.parent / "stand.lock"


def check_stand_lock(lock: Path, token: str | None) -> None:
    """Замок протокола: строки ``сессия | время | режим | SHA | порты``. Код 2 (:class:`StandRunError`),
    если токена нет, файла нет, ни одна строка не принадлежит сессии ``token`` (сравнение поля, не
    подстроки) или режим этой строки не ``measure``."""
    if not token:
        raise StandRunError("живой режим требует --lock-token <сессия>")
    if not lock.is_file():
        raise StandRunError(f"замок {lock} не взят — возьмите stand.lock до прогона")
    rows = [
        [f.strip() for f in line.split("|")]
        for line in lock.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    ours = [r for r in rows if r and r[0] == token]
    if not ours:
        raise StandRunError(f"замок {lock} чужой: нет строки сессии {token!r}")
    mode = ours[-1][2] if len(ours[-1]) > 2 else ""
    if mode != LOCK_MODE_MEASURE:
        raise StandRunError(f"замок {lock}: режим {mode!r}, нужен {LOCK_MODE_MEASURE!r}")


def require_pause(ordered: bool, paused: bool | None, res: dict) -> None:
    """Заказанная пауза обязана состояться: иначе P10 без ``pause`` анализировался бы как кейс E."""
    if ordered and paused is not True:
        raise StandRunError(f"пауза исполнителя заказана, но не состоялась: {res.get('pause_error', paused)}")


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
def executor_cycles(resp: Any, worker: str) -> int | None:
    """``cycles`` воркера ``worker`` из ответа ``introspect_status`` (обёртка драйвера снимается)."""
    ws = ((_payload(resp) or {}).get("workers") or {}).get(worker)
    cycles = ws.get("cycles") if isinstance(ws, dict) else None
    return cycles if isinstance(cycles, int) and not isinstance(cycles, bool) else None


def measure_drain(
    poll: Callable[[], int | None],
    target: int,
    t0: float,
    *,
    step_s: float = T.DRAIN_POLL_STEP_S,
    cap_s: float = DRAIN_CAP_S,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> dict:
    """Опрос ``poll()`` (ОДИН вызов ``introspect_status``, возвращает ``cycles`` исполнителя) с шагом
    ``step_s``, пока ``cycles`` не дойдёт до ``target`` или не пройдёт ``cap_s`` от ``t0``.

    ``t0`` — момент ДО отправки ``worker.start`` (ред. 4): задержка ответа на команду входит в дренаж.
    ``drain_s`` — от ``t0`` до конца опроса, увидевшего ``target`` (верхняя граница; ``None`` — не дошёл
    за ``cap_s``). ``drain_poll_period_s`` — наибольший интервал между соседними опросами, первый
    интервал считается от ``t0``: это неопределённость момента, по ней судится доказуемость порога.
    Часы — ``time.perf_counter`` модуля на момент вызова (подменяемы в тестах).
    """
    clock = clock or time.perf_counter
    sleep = sleep or time.sleep
    last = t0
    period = 0.0
    trace: list[tuple[float, int | None]] = []
    while True:
        t_call = clock()
        cycles = poll()
        t_done = clock()
        period = max(period, t_done - last)
        last = t_done
        elapsed = t_done - t0
        trace.append((round(elapsed, 4), cycles))
        if cycles is not None and cycles >= target:
            return {"drain_s": round(elapsed, 4), "drain_poll_period_s": round(period, 4), "drain_trace": trace[:200]}
        if elapsed >= cap_s:
            return {"drain_s": None, "drain_poll_period_s": round(period, 4), "drain_trace": trace[:200]}
        sleep(max(0.0, step_s - (clock() - t_call)))


def pause_executor(drv: Any, res: dict, secs: float) -> bool:
    """Пауза исполнителя processor на ``secs`` и дренаж: ``backlog = chain_queue.size`` в ``pause_mid``,
    ``drain_s`` — пока ``cycles`` исполнителя не вырастет на ``backlog + 1`` относительно ``pause_mid``."""
    st = _payload(drv.introspect_status("processor")) or {}
    names = [w for w in (st.get("workers") or {}) if "exec" in w.lower() or "pipeline" in w.lower()]
    res["pause_worker_names"] = list(st.get("workers") or {})
    if not names:
        res["pause_error"] = "executor worker not found"
        return False
    worker = names[0]
    import psutil

    pid = st.get("pid")
    rss0 = psutil.Process(pid).memory_info().rss if pid else None
    t = time.perf_counter()
    res["pause_stop"] = drv.send_command("processor", "worker.stop", {"worker_name": worker}, timeout=10)
    time.sleep(secs)
    res["pause_mid"] = snap(drv, ["processor"])
    mid = res["pause_mid"]["processor"]
    backlog = chain_queue_size(mid.get("queues"))
    cycles_mid = (mid.get("workers") or {}).get(worker, {}).get("cycles")
    rss1 = psutil.Process(pid).memory_info().rss if pid else None
    t0 = time.perf_counter()  # ДО отправки: задержка ответа на worker.start входит в дренаж
    res["pause_start"] = drv.send_command("processor", "worker.start", {"worker_name": worker}, timeout=10)
    if backlog is None or not isinstance(cycles_mid, int):
        # Воркер уже запущен обратно; без backlog/cycles дренаж не измерим — прогон сорван (код 2).
        res["pause_error"] = f"pause_mid без chain_queue.size/cycles: backlog={backlog} cycles={cycles_mid}"
        return False
    drain = measure_drain(
        lambda: executor_cycles(drv.introspect_status("processor"), worker), cycles_mid + backlog + 1, t0
    )
    res["pause"] = {
        "worker": worker,
        "stopped_s": round(t0 - t, 1),
        "rss0": rss0,
        "rss1": rss1,
        "backlog": backlog,
        "cycles_mid": cycles_mid,
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
                require_pause(True, paused, res)
            ov = drv.system_overview(timeout=5)
            for p in PROCS:
                v = ov.get("processes", {}).get(p, {}).get("hz")
                if isinstance(v, (int, float)):
                    hz[p].append(float(v))
            time.sleep(2)
        require_pause(pause, paused, res)  # окно кончилось раньше паузы — тоже сорванный P10
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
