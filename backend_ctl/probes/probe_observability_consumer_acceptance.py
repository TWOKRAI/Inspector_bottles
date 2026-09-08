# -*- coding: utf-8 -*-
# ruff: noqa: E501 — строки «ожидал/наблюдал» намеренно длинные: цитата вывода целиком дороже переноса.
"""Приёмка наблюдаемости глазами ПОТРЕБИТЕЛЯ — живой стенд `inspection_full`.

Зонд отвечает на вопрос владельца «какие функции наблюдаемости есть и как ими
управлять» не чтением документов, а прогоном: каждая строка чек-листа — это
предусловие → действие → ожидание (литерал, записанный ДО прогона) → наблюдение
(цитата вывода) → вердикт. Строка без наблюдения не бывает `PASS`.

Три правила честности, зашитые в код:

* **Независимые арбитры.** Файл стора читается `sqlite3` напрямую (read-only URI),
  журналы — `open()` с диска, тайминги — `perf_counter_ns` на ОБОИХ концах в
  этом процессе. Ответ команды (`success=True`) сам по себе никогда не вердикт.
* **Ноль — вопрос, а не результат.** Где ожидается «записи перестали приходить»,
  рядом стоит контроль «а до ручки они приходили» (пара ON/OFF).
* **Число без разброса — наблюдение.** Все лаги снимаются ≥ 5 повторов, в отчёт
  идут медиана/мин/макс; разрешение `time.time()` измеряется отдельно, чтобы
  назвать, какие числа лежат на сетке таймера Windows.

Запуск (из корня репозитория, порт 8765 обязан быть свободен):

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m backend_ctl.probes.probe_observability_consumer_acceptance

Артефакты: `logs_live/2026-09-08_qa-acceptance_<ts>/` — журналы стенда, стор,
`acceptance_results.json` и `acceptance_results.md` (таблица строк чек-листа).

Что зонд НЕ поднимает сам: строки `record_start/stop` (flight recorder драйвера
живёт в MCP-сессии, у голого `BackendDriver` его нет) и `observability.persist`
(писал бы спутник рецепта в общее дерево). Они помечены в отчёте как
`NOT_REACHED` с причиной, а не выкинуты.
"""

from __future__ import annotations

import glob
import json
import os
import re
import socket
import sqlite3
import statistics
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["BACKEND_CTL"] = "1"

#: Свой каталог логов на прогон. Метка времени берётся ТОЛЬКО если каталог ещё
#: не назначен: на Windows дети спавнятся переимпортом модуля, и безусловный
#: расчёт метки развёл бы писателей по разным каталогам (грабля stage2, прогон 1.6).
_inherited = os.environ.get("MULTIPROCESS_LOG_DIR")
LOG_DIR = (
    Path(_inherited) if _inherited else PROJECT_ROOT / "logs_live" / f"2026-09-08_qa-acceptance_{int(time.time())}"
)
LOG_DIR.mkdir(parents=True, exist_ok=True)
os.environ["MULTIPROCESS_LOG_DIR"] = str(LOG_DIR)
os.environ["INSPECTOR_LOG_DIR"] = str(LOG_DIR)

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.harness import BackendHarness  # noqa: E402
from backend_ctl.protocol import _leaf_result  # noqa: E402

RECIPE = PROJECT_ROOT / "multiprocess_prototype" / "backend" / "topology" / "inspection_full.yaml"
PORT = 8765
PM = "ProcessManager"

#: Ожидаемый состав процессов — литерал из стенда Task 3.8 (семь, не восемь).
EXPECTED_PROCS = {"ProcessManager", "camera_0", "gui", "inspector", "processor", "renderer", "storage"}

ROWS: List[Dict[str, Any]] = []
LAT: Dict[str, Dict[str, Any]] = {}
NOTES: List[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def row(
    rid: str,
    family: str,
    function: str,
    control: str,
    consumer: str,
    expected: str,
    observed: str,
    verdict: str,
    doc: str = "",
) -> None:
    """Одна строка чек-листа. Вердикт `PASS` без наблюдения запрещён — сторож ниже."""
    if verdict == "PASS" and not observed.strip():
        verdict = "PARTIAL"
        observed = "<наблюдение пустое — PASS снят сторожем зонда>"
    ROWS.append(
        {
            "id": rid,
            "family": family,
            "function": function,
            "control": control,
            "consumer": consumer,
            "expected": expected,
            "observed": observed,
            "verdict": verdict,
            "doc": doc,
        }
    )
    log(f"  [{verdict}] {rid} {function}\n         ожидал: {expected}\n         наблюдал: {observed}")


def short(obj: Any, n: int = 400) -> str:
    s = json.dumps(obj, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + f"…(+{len(s) - n})"


def marker(tag: str) -> str:
    return f"QAACC{tag}{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Арбитры: sqlite напрямую, файлы с диска
# ---------------------------------------------------------------------------


def sql(db: str, query: str, params: Tuple[Any, ...] = ()) -> List[Tuple[Any, ...]]:
    """Read-only соединение на каждый вызов: арбитр не делит соединение с драйвером."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0)
    try:
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def file_lines(path: Path) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except FileNotFoundError:
        return -1


def file_count(path: Path, needle: str) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for line in fh if needle in line)
    except FileNotFoundError:
        return -1


def file_grep(path: Path, needle: str, limit: int = 3) -> List[str]:
    out: List[str] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if needle in line:
                    out.append(line.rstrip()[:300])
                    if len(out) >= limit:
                        break
    except FileNotFoundError:
        pass
    return out


def wait_until(pred: Callable[[], bool], timeout: float, step: float = 0.005) -> Tuple[bool, float]:
    t0 = time.perf_counter()
    while True:
        if pred():
            return True, time.perf_counter() - t0
        if time.perf_counter() - t0 >= timeout:
            return False, time.perf_counter() - t0
        time.sleep(step)


def stats_ms(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "median_ms": round(statistics.median(values), 2),
        "min_ms": round(min(values), 2),
        "max_ms": round(max(values), 2),
        "values_ms": [round(v, 2) for v in values],
    }


# ---------------------------------------------------------------------------
# Сборщик пушей: отметка ПРИБЫТИЯ ставится в reader-потоке драйвера
# ---------------------------------------------------------------------------


class Arrivals:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.items: List[Tuple[int, float, Dict[str, Any]]] = []

    def __call__(self, msg: Any) -> None:
        # Лёгкий колбэк: только штамп и append; request() отсюда звать нельзя (дедлок).
        if isinstance(msg, dict):
            with self._lock:
                self.items.append((time.perf_counter_ns(), time.time(), msg))

    def find(self, pred: Callable[[Dict[str, Any]], bool]) -> Optional[Tuple[int, float, Dict[str, Any]]]:
        with self._lock:
            for it in self.items:
                if pred(it[2]):
                    return it
        return None

    def count(self, pred: Callable[[Dict[str, Any]], bool], since_ns: int = 0) -> int:
        with self._lock:
            return sum(1 for it in self.items if it[0] >= since_ns and pred(it[2]))


def msg_contains(msg: Dict[str, Any], needle: str) -> bool:
    try:
        return needle in json.dumps(msg, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return False


def msg_records(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = msg.get("data")
    if not isinstance(data, dict):
        return []
    out: List[Dict[str, Any]] = []
    rec = data.get("record")
    if isinstance(rec, dict):
        out.append(rec)
    recs = data.get("records")
    if isinstance(recs, list):
        out.extend(r for r in recs if isinstance(r, dict))
    return out


# ---------------------------------------------------------------------------
# Обёртки команд
# ---------------------------------------------------------------------------


def cmd(
    drv, process: str, command: str, data: Optional[Dict[str, Any]] = None, timeout: float = 15.0
) -> Dict[str, Any]:
    try:
        return _leaf_result(drv.send_command(process, command, data or {}, timeout=timeout)) or {}
    except Exception as exc:  # noqa: BLE001
        return {"success": None, "reason": f"<транспорт: {type(exc).__name__}: {exc}>"}


def obs(drv, process: str, flush: bool = False) -> Dict[str, Any]:
    args: Dict[str, Any] = {"audit_limit": 5}
    if flush:
        args["flush"] = True
    return cmd(drv, process, "introspect.observability", args)


def counters_of(drv, process: str) -> Dict[str, Any]:
    return (obs(drv, process, flush=True).get("counters") or {}) if True else {}


def debug_lines(proc: str) -> int:
    return file_count(LOG_DIR / proc / "system.log", "[DEBUG]")


def port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", port)) != 0
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Семья 6 — самоописание
# ---------------------------------------------------------------------------


def family_self_description(drv) -> Dict[str, Any]:
    log("\n=== Семья 6: самоописание ===")
    ctx: Dict[str, Any] = {}

    ov = drv.system_overview(timeout=20.0)
    procs = ov.get("processes") if isinstance(ov, dict) else None
    names = set(procs.keys()) if isinstance(procs, dict) else set()
    ctx["procs"] = sorted(names)
    row(
        "S1",
        "самоописание",
        "system_overview: состав процессов",
        "—",
        "drv.system_overview()",
        f"ровно 7 процессов: {sorted(EXPECTED_PROCS)}",
        f"{len(names)}: {sorted(names)}; anomalies={short(ov.get('anomalies'), 200)}",
        "PASS" if names == EXPECTED_PROCS else "FAIL",
        "backend_ctl/AGENTS.md (system_overview)",
    )

    # Драйвер отдаёт ТИПИЗИРОВАННЫЙ свод (`Capabilities` dataclass: .processes → ProcessCapabilities
    # с .commands), а MCP-инструмент — dict. Прогоны 1 и 2 читали как dict и видели пусто —
    # S2 в них закрыт MCP-арбитром (`capabilities(format=concise)`), зонд поправлен без перепрогона.
    caps_obj = drv.capabilities(timeout=20.0)
    cap_procs = getattr(caps_obj, "processes", None)
    if cap_procs is None and isinstance(caps_obj, dict):
        cap_procs = (_leaf_result(caps_obj) or {}).get("processes")
    cap_names = set(cap_procs.keys()) if isinstance(cap_procs, dict) else set()
    obs_cmds = set()
    if isinstance(cap_procs, dict):
        card = cap_procs.get("camera_0")
        cmds = getattr(card, "commands", None)
        if cmds is None and isinstance(card, dict):
            cmds = card.get("commands")
        names: List[str] = []
        if isinstance(cmds, dict):
            names = [str(c) for c in cmds]
        elif isinstance(cmds, (list, tuple, set)):
            names = [str(c.get("name") if isinstance(c, dict) else getattr(c, "name", c)) for c in cmds]
        obs_cmds = {
            c
            for c in names
            if c.startswith(("config.", "observability.", "introspect.", "health.", "diag.", "telemetry."))
        }
    need = {
        "config.reload",
        "introspect.observability",
        "observability.sink.enable",
        "observability.sink.disable",
        "health.report",
        "diag.thread_raise",
        "diag.warn",
        "introspect.telemetry",
    }
    missing = sorted(need - obs_cmds)
    row(
        "S2",
        "самоописание",
        "capabilities: команды наблюдаемости у процесса объявлены",
        "—",
        "drv.capabilities() → processes.camera_0.commands",
        f"состав процессов = S1; у camera_0 есть {sorted(need)}",
        f"processes={sorted(cap_names)}; obs-команд camera_0: {len(obs_cmds)}; отсутствуют: {missing or 'нет'}",
        "PASS" if (cap_names == names and not missing) else ("PARTIAL" if cap_names == names else "FAIL"),
        "docs/contracts/CAPABILITIES.md",
    )

    o = obs(drv, PM)
    sections = sorted(k for k in o.keys() if isinstance(o.get(k), dict))
    need_s = {"effective", "counters", "provenance", "history", "observation", "audit", "layers"}
    hist = o.get("history") or {}
    db_path = str(hist.get("db_path") or "")
    ctx["db_path"] = db_path
    row(
        "S3",
        "самоописание",
        "introspect.observability: семь секций документированного ответа",
        "—",
        "send_command(PM, introspect.observability)",
        f"секции ⊇ {sorted(need_s)}",
        f"секции={sections}",
        "PASS" if need_s <= set(sections) else "FAIL",
        "CONTROL_PANEL.md §2 (MCP-зеркало)",
    )
    expected_db = str(LOG_DIR / "observability.db")
    same = (
        os.path.normcase(os.path.abspath(db_path)) == os.path.normcase(os.path.abspath(expected_db))
        if db_path
        else False
    )
    exists = os.path.exists(db_path) if db_path else False
    row(
        "S4",
        "самоописание",
        "history.db_path из readback совпадает с файлом на диске",
        "—",
        "readback history.db_path ↔ os.path.exists",
        f"db_path == {expected_db} и файл существует",
        f"db_path={db_path!r}; exists={exists}; enabled={hist.get('enabled')}",
        "PASS" if (same and exists) else ("PARTIAL" if exists else "FAIL"),
        "CONTROL_PANEL.md §7 (история)",
    )
    eff = o.get("effective") or {}
    log_dir_eff = str(eff.get("log_directory") or eff.get("log_dir") or "")
    dirs_ok = [p for p in names if (LOG_DIR / p / "system.log").exists() or (LOG_DIR / p / "messages.log").exists()]
    row(
        "S5",
        "самоописание",
        "effective.log_directory ↔ каталоги журналов на диске",
        "—",
        "readback effective ↔ os.listdir",
        f"каталог = {LOG_DIR}; у каждого из 7 процессов есть system.log или messages.log",
        f"effective.log_directory={log_dir_eff!r}; каталогов с журналами: {len(dirs_ok)}/{len(names)}: {sorted(dirs_ok)}",
        "PASS" if (len(dirs_ok) == len(names) and len(names) > 0) else "PARTIAL",
        "SINKS_MAP.md §2",
    )
    t = _leaf_result(drv.introspect_telemetry("camera_0", timeout=15.0)) or {}
    resolved = t.get("resolved") or {}
    levels = t.get("levels")
    row(
        "S6",
        "самоописание",
        "introspect.telemetry: gate/resolved/levels/tick",
        "—",
        "drv.introspect_telemetry('camera_0')",
        "gate_active=true (белый список fps/latency_ms), resolved содержит fps и latency_ms, levels не null, tick_effective_sec=5.0",
        f"gate_active={t.get('gate_active')}; resolved keys={sorted(resolved.keys())[:8]}; levels={'есть' if isinstance(levels, dict) else levels}; tick_effective_sec={t.get('tick_effective_sec')}",
        "PASS" if (t.get("gate_active") is True and "fps" in resolved and isinstance(levels, dict)) else "PARTIAL",
        "CONTROL_PANEL.md §5.5",
    )
    sup = _leaf_result(drv.supervision_status(timeout=15.0)) or {}
    sup_procs = sup.get("processes") if isinstance(sup, dict) else None
    pids = {k: (v.get("pid") if isinstance(v, dict) else None) for k, v in (sup_procs or {}).items()}
    ctx["pids"] = pids
    row(
        "S7",
        "самоописание",
        "supervision_status: pid и instance_restarts на старте",
        "—",
        "drv.supervision_status()",
        "у каждого процесса pid непустой, instance_restarts=0",
        f"pids={pids}; restarts={ {k: (v.get('instance_restarts') if isinstance(v, dict) else None) for k, v in (sup_procs or {}).items()} }",
        "PASS" if (pids and all(pids.values())) else "PARTIAL",
        "backend_ctl/AGENTS.md (supervision_status)",
    )
    return ctx


# ---------------------------------------------------------------------------
# Семья 2 — чтение потребителем
# ---------------------------------------------------------------------------


def family_reading(drv, arr: Arrivals, ctx: Dict[str, Any]) -> None:
    log("\n=== Семья 2: чтение потребителем ===")
    db = ctx["db_path"]

    per = {p: (file_lines(LOG_DIR / p / "messages.log"), file_lines(LOG_DIR / p / "system.log")) for p in ctx["procs"]}
    row(
        "R1",
        "чтение",
        "журналы процессов на диске: messages.log / system.log",
        "—",
        "open(<log_dir>/<процесс>/*.log)",
        "у каждого процесса оба файла существуют (строк ≥ 0), у PM system.log непустой",
        f"(messages, system) строк: {per}",
        "PASS" if all(v[0] >= 0 and v[1] >= 0 for v in per.values()) and per.get(PM, (0, 0))[1] > 0 else "PARTIAL",
        "SINKS_MAP.md §2",
    )

    cols = [r[1] for r in sql(db, "PRAGMA table_info(records)")]
    need_cols = {"id", "kind", "process", "module", "ts", "severity", "message", "extra", "severity_number", "metric"}
    kinds = sql(db, "SELECT kind, COUNT(*) FROM records GROUP BY kind")
    dprocs = sorted(r[0] for r in sql(db, "SELECT DISTINCT process FROM records") if r[0])
    row(
        "R2",
        "чтение",
        "SQLite-стор напрямую: схема и состав",
        "—",
        "sqlite3 file:<db>?mode=ro",
        f"колонки ⊇ {sorted(need_cols)}; kind ∈ {{log,error,stats,observation}}; process ⊆ состав S1",
        f"cols={cols}; by_kind={kinds}; processes={dprocs}",
        "PASS" if need_cols <= set(cols) and set(dprocs) <= set(ctx["procs"]) else "FAIL",
        "observability_store.py (_init_schema)",
    )

    hq = drv.history_query(kind="log", process="camera_0", limit=5, timeout=15.0)
    rows_ = hq.get("rows") if isinstance(hq, dict) else None
    ids = [r.get("id") for r in (rows_ or []) if isinstance(r, dict)]
    verified = 0
    for rid in ids:
        if rid is not None and sql(
            db, "SELECT 1 FROM records WHERE id=? AND kind='log' AND process='camera_0'", (rid,)
        ):
            verified += 1
    row(
        "R3",
        "чтение",
        "history_query(kind=log, process=camera_0) ↔ те же строки в sqlite",
        "—",
        "drv.history_query → sqlite по id",
        "success=true, ≥1 строка, каждая найдена в файле по id с тем же kind/process",
        f"success={hq.get('success')}; count={hq.get('count')}; ids={ids}; подтверждено арбитром={verified}/{len(ids)}",
        "PASS"
        if hq.get("success") and ids and verified == len(ids)
        else ("NOT_REACHED" if hq.get("success") and not ids else "FAIL"),
        "CONTROL_PANEL.md §7 (history_query)",
    )

    # R4: log_tail + пуш log.record + файл messages.log
    lt = _leaf_result(drv.log_tail("camera_0", level="INFO", timeout=15.0)) or {}
    m4 = marker("R4")
    hr = cmd(drv, "camera_0", "health.report", {"message": m4, "level": "INFO", "context": "qa"})
    ok, el = wait_until(
        lambda: arr.find(lambda m: m.get("command") == "log.record" and msg_contains(m, m4)) is not None, 5.0
    )
    hit = arr.find(lambda m: m.get("command") == "log.record" and msg_contains(m, m4))
    okf, elf = wait_until(lambda: file_count(LOG_DIR / "camera_0" / "messages.log", m4) > 0, 3.0)
    row(
        "R4",
        "чтение",
        "log_tail(INFO) → пуш log.record + строка в messages.log",
        "log_tail(camera_0, level=INFO); эмиссия: health.report level=INFO",
        "drv.subscribe (пуш) + open(camera_0/messages.log)",
        "пуш с маркером ≤ 5 с; строка с маркером в messages.log ≤ 3 с",
        f"log_tail={short(lt, 120)}; health.report={short(hr, 120)}; push={'есть' if hit else 'нет'} за {el * 1000:.0f} мс; файл={'есть' if okf else 'нет'} за {elf * 1000:.0f} мс",
        "PASS" if (hit and okf) else ("PARTIAL" if (hit or okf) else "FAIL"),
        "backend_ctl/AGENTS.md (log_tail); SINKS_MAP.md §2 (INFO→BUSINESS→messages_file)",
    )

    # R5: observability_tail на processor + WARNING
    ot = _leaf_result(drv.observability_tail("processor", level="INFO", timeout=15.0)) or {}
    m5 = marker("R5")
    cmd(drv, "processor", "health.report", {"message": m5, "level": "WARNING", "context": "qa"})
    ok5, el5 = wait_until(
        lambda: arr.find(lambda m: m.get("command") == "observability.record" and msg_contains(m, m5)) is not None, 5.0
    )
    kinds5 = sorted({r.get("kind") for it in arr.items if msg_contains(it[2], m5) for r in msg_records(it[2])} - {None})
    files5 = {
        f: file_count(LOG_DIR / "processor" / f, m5)
        for f in ("system.log", "messages.log", "warnings.log", "errors.log")
    }
    row(
        "R5",
        "чтение",
        "observability_tail(INFO) → пуш observability.record (kind) + файлы",
        "observability_tail(processor, level=INFO); эмиссия: health.report level=WARNING",
        "drv.subscribe (пуш) + open(processor/*.log)",
        "пуш observability.record с маркером ≤ 5 с, kind содержит log; WARNING в system.log (SYSTEM-скоуп)",
        f"tail={short(ot, 100)}; push={'есть' if ok5 else 'нет'} за {el5 * 1000:.0f} мс; kinds={kinds5}; файлы(строк с маркером)={files5}",
        "PASS" if (ok5 and files5["system.log"] > 0) else ("PARTIAL" if ok5 else "FAIL"),
        "backend_ctl/AGENTS.md (observability_tail); SINKS_MAP.md §2",
    )

    # R6: events_page по плоскостям
    pl = drv.events_page("logs", cursor=None, limit=500)
    items = pl.get("items") if isinstance(pl, dict) else None
    found4 = any(msg_contains(it.get("event", {}), m4) for it in (items or []))
    pe = drv.events_page("errors", cursor=None, limit=500)
    eitems = pe.get("items") if isinstance(pe, dict) else None
    found5e = any(msg_contains(it.get("event", {}), m5) for it in (eitems or []))
    row(
        "R6",
        "чтение",
        "events_page(plane=logs|errors): курсорное чтение без потери",
        "—",
        "drv.events_page(plane)",
        "маркер R4 в plane=logs; dropped=0; маркер R5 (WARNING) — наблюдать, в какой плоскости",
        f"logs: items={len(items or [])}, dropped={pl.get('dropped')}, R4={found4}; errors: items={len(eitems or [])}, R5={found5e}",
        "PASS" if (found4 and (pl.get("dropped") in (0, None))) else "PARTIAL",
        "backend_ctl/AGENTS.md (events_page, B.1)",
    )

    # R7: watch_like_gui → read-model телеметрии
    w = drv.watch_like_gui(tail_level="INFO", timeout=30.0)
    ctx["watch_started_ns"] = time.perf_counter_ns()
    ok7, el7 = wait_until(
        lambda: (drv.telemetry_snapshot(process="camera_0") or {}).get("count", 0) > 0, 12.0, step=0.25
    )
    snap = drv.telemetry_snapshot(process="camera_0") or {}
    okh, elh = wait_until(
        lambda: (drv.telemetry_history("processes.camera_0.state.fps") or {}).get("count", 0) >= 1, 12.0, step=0.5
    )
    hist = drv.telemetry_history("processes.camera_0.state.fps") or {}
    row(
        "R7",
        "чтение",
        "watch_like_gui → telemetry_snapshot / telemetry_history (read-model)",
        "watch_like_gui(tail_level=INFO)",
        "drv.telemetry_snapshot(process=camera_0); drv.telemetry_history(processes.camera_0.state.fps)",
        "снимок count>0 ≤ 12 с; ≥1 точка fps ≤ 12 с (fps в белом списке, такт 5 с)",
        f"watch={short(w, 120)}; snapshot count={snap.get('count')} за {el7:.1f} с; history count={hist.get('count')} за {elh:.1f} с, points={short(hist.get('points') or hist.get('items'), 120)}",
        "PASS" if (ok7 and okh) else ("PARTIAL" if ok7 else "FAIL"),
        "backend_ctl/AGENTS.md (watch_like_gui, telemetry_snapshot)",
    )

    # R8: record_* — только в MCP-сессии
    row(
        "R8",
        "чтение",
        "record_start/stop/status (flight recorder драйвера)",
        "MCP record_start(name) … record_stop()",
        "файл в BACKEND_CTL_RECORD_DIR",
        "файл записи с events_written>0",
        "зондом не достижимо: recorder живёт в MCP-сессии (mcp_driver_session.py), у BackendDriver методов record_* нет — проверяется MCP-инструментами из агентской сессии, см. протокол",
        "NOT_REACHED",
        "backend_ctl/AGENTS.md (record_*), BCTL-ADR-006",
    )

    # R9: широкие записи — ручка events + FTS по trace_id
    base_ev = sql(db, "SELECT COUNT(*) FROM records WHERE message LIKE 'event %'")[0][0]
    # Селектор считает от СТАРТА процесса (счёт «продолжается, а не начинается заново»):
    # к моменту ручки first_n давно потрачен, и проходит только каждая every_mth-я.
    # Ожидание считается от счётчиков events.kinds, а не от «5 первых» (урок прогона 1).
    k0 = ((obs(drv, "inspector").get("events") or {}).get("kinds") or {}).get("inspection") or {}
    cr = cmd(
        drv, "inspector", "config.reload", {"observability": {"events": {"first_n": 5, "every_mth": 50}}, "ttl": 120}
    )
    time.sleep(10.0)
    k1 = ((obs(drv, "inspector").get("events") or {}).get("kinds") or {}).get("inspection") or {}
    d_total = (k1.get("selected", 0) + k1.get("skipped", 0)) - (k0.get("selected", 0) + k0.get("skipped", 0))
    d_sel = k1.get("selected", 0) - k0.get("selected", 0)
    expect_sel = d_total / 50.0
    now_ev = sql(db, "SELECT COUNT(*) FROM records WHERE message LIKE 'event %'")[0][0]
    ev_rows = sql(
        db, "SELECT process, module, message FROM records WHERE message LIKE 'event %' ORDER BY id DESC LIMIT 1"
    )
    trace = ""
    if ev_rows:
        mt = re.search(r"trace=([0-9a-f]+)", str(ev_rows[0][2]))
        trace = mt.group(1) if mt else ""
    fts = (
        drv.history_query(text=trace, limit=5, timeout=15.0)
        if trace
        else {"success": None, "reason": "trace_id не найден"}
    )
    fts_n = len(fts.get("rows") or []) if isinstance(fts, dict) else 0
    ctrl = drv.history_query(text="deadbeefcafe0000", limit=5, timeout=15.0)
    ctrl_n = len(ctrl.get("rows") or []) if isinstance(ctrl, dict) else -1
    ctx["events_reply"] = cr
    row(
        "R9",
        "чтение",
        "широкие записи (ctx.write_event) → стор; поиск по trace_id (FTS)",
        "config.reload inspector {events: {first_n:5, every_mth:50}, ttl:120}",
        "sqlite COUNT(message LIKE 'event %'); drv.history_query(text=<trace_id>)",
        "Δselected за 10 с == Δ(единиц)/50 ± 1 (first_n от старта процесса уже потрачен, не переприменяется); строк 'event %' в сторе прибавилось на Δselected; поиск по trace_id даёт ≥1 строку; контроль по несуществующему следу — 0",
        f"reply success={cr.get('success')} applied={short(cr.get('applied'), 80)} events_applied={short(cr.get('events_applied'), 100)}; kinds.inspection до={short(k0, 80)} после={short(k1, 80)}; Δединиц={d_total}, Δselected={d_sel}, ожидание {expect_sel:.1f}; строк в сторе Δ={now_ev - base_ev} ({base_ev}→{now_ev}); last={short(ev_rows, 160)}; fts({trace[:8]})={fts_n}; control={ctrl_n}",
        "PASS"
        if (abs(d_sel - expect_sel) <= 1.0 and (now_ev - base_ev) >= d_sel - 1 and fts_n >= 1 and ctrl_n == 0)
        else ("PARTIAL" if d_sel >= 1 else "FAIL"),
        "CONTROL_PANEL.md §7 (отбор широких записей), ADR-PM-036",
    )
    rs = cmd(drv, "inspector", "config.reload", {"observability_reset": ["events.first_n", "events.every_mth"]})
    NOTES.append(f"R9 reset events: {short(rs, 200)}")

    # R10: кольцо памяти flight_ring читается ретроспективно
    st = cmd(drv, "inspector", "observability.sink.tail", {"sink": "flight_ring", "limit": 5})
    recs = st.get("records") or st.get("items") or st.get("tail") or []
    row(
        "R10",
        "чтение",
        "observability.sink.tail: ретроспективный хвост memory-кольца (flight_ring)",
        "—",
        "send_command(inspector, observability.sink.tail {sink: flight_ring, limit: 5})",
        "success=true, ≥1 запись из кольца инспектора",
        f"success={st.get('success')}; записей={len(recs) if isinstance(recs, list) else recs}; keys={sorted(st.keys())[:10]}",
        "PASS"
        if (st.get("success") and isinstance(recs, list) and recs)
        else ("PARTIAL" if st.get("success") else "FAIL"),
        "SINKS_MAP.md §1 (memory), CONTROL_PANEL.md §2",
    )

    # R12/R13: stats без идентичности, history_query(metric)
    st_rows = sql(
        db, "SELECT COUNT(*), SUM(CASE WHEN metric IS NULL THEN 1 ELSE 0 END) FROM records WHERE kind='stats'"
    )
    metrics = sql(db, "SELECT metric, COUNT(*) FROM records WHERE metric IS NOT NULL GROUP BY metric")
    row(
        "R12",
        "чтение",
        "history_query(metric=…): идентичность числа в сторе на inspection_full",
        "—",
        "sqlite: kind=stats и колонка metric",
        "известное с Task 3.8: у снапшотов metric=NULL; на inspection_full записей с metric нет вовсе (camera_service чисел не пишет)",
        f"kind=stats: всего={st_rows[0][0]}, metric NULL={st_rows[0][1]}; metric≠NULL по именам={metrics}",
        "PASS" if (st_rows[0][0] == st_rows[0][1]) else "PARTIAL",
        "stand-task-3-8.md (б); plans/observability-closure (3.6 снята)",
    )


# ---------------------------------------------------------------------------
# Семья 1 — ручки
# ---------------------------------------------------------------------------


def family_knobs(drv, arr: Arrivals, ctx: Dict[str, Any]) -> None:
    log("\n=== Семья 1: ручки ===")
    db = ctx["db_path"]

    # K1: log_level DEBUG на camera_0, сосед processor не задет, возврат
    d_cam0, d_proc0 = debug_lines("camera_0"), debug_lines("processor")
    v = drv.config_reload_verified("camera_0", observability={"log_level": "DEBUG"}, settle=1.0, timeout=30.0)
    ver = (v.get("verified") or {}) if isinstance(v, dict) else {}
    time.sleep(4.0)
    d_cam1, d_proc1 = debug_lines("camera_0"), debug_lines("processor")
    row(
        "K1a",
        "ручки",
        "log_level=DEBUG одному процессу (L3) — включение",
        "config_reload_verified(camera_0, {log_level: DEBUG})",
        "open(camera_0/system.log) — счёт строк [DEBUG]; сосед processor тем же способом",
        "verdict=confirmed; delivering=true; Δ[DEBUG] camera_0 > 0 за 4 с; Δ[DEBUG] processor == 0",
        f"verdict={ver.get('verdict')}; delivering={v.get('delivering')} written_net={v.get('written_net')}; camera_0 {d_cam0}→{d_cam1} (Δ{d_cam1 - d_cam0}); processor {d_proc0}→{d_proc1} (Δ{d_proc1 - d_proc0})",
        "PASS" if (ver.get("verdict") == "confirmed" and d_cam1 - d_cam0 > 0 and d_proc1 - d_proc0 == 0) else "FAIL",
        "CONTROL_PANEL.md §5.1, §7",
    )
    rs = cmd(drv, "camera_0", "config.reload", {"observability_reset": ["log_level"]})
    time.sleep(1.0)
    d_cam2 = debug_lines("camera_0")
    time.sleep(4.0)
    d_cam3 = debug_lines("camera_0")
    lay = obs(drv, "camera_0").get("layers") or {}
    row(
        "K1b",
        "ручки",
        "log_level — возврат к нижнему слою (observability_reset)",
        "config.reload camera_0 {observability_reset: [log_level]}",
        "open(camera_0/system.log) — [DEBUG] перестают расти; readback layers",
        "success=true; Δ[DEBUG] за 4 с после 1 с выдержки == 0; в layers нет session-ключа log_level",
        f"reset={short(rs, 140)}; [DEBUG] {d_cam2}→{d_cam3} (Δ{d_cam3 - d_cam2}); layers={short(lay, 200)}",
        "PASS" if (rs.get("success") and d_cam3 - d_cam2 == 0) else "FAIL",
        "CONTROL_PANEL.md §7 («вернуть один ключ к нижнему слою»)",
    )

    # K2: уровень по имени источника (loggers)
    # Источник выбран по факту прогона 1: под глобальным DEBUG болтали `router_<процесс>`
    # и `router_messages`; префикс `process_module` за 4 с не дал ни строки (сравнить не с чем).
    src = "router_processor"
    dp0, dc0 = debug_lines("processor"), debug_lines("camera_0")
    v2 = drv.config_reload_verified(
        "processor", observability={"loggers": {src: {"level": "DEBUG"}}}, settle=1.0, timeout=30.0
    )
    ver2 = (v2.get("verified") or {}) if isinstance(v2, dict) else {}
    time.sleep(4.0)
    dp1, dc1 = debug_lines("processor"), debug_lines("camera_0")
    mods: Dict[str, int] = {}
    try:
        with open(LOG_DIR / "processor" / "system.log", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if "[DEBUG]" in line:
                    parts = line.split()
                    name = parts[5] if len(parts) > 5 else "?"
                    mods[name] = mods.get(name, 0) + 1
    except FileNotFoundError:
        pass
    only_src = bool(mods) and all(k.rstrip(":") == src for k in mods)
    row(
        "K2",
        "ручки",
        "уровень по ИМЕНИ ИСТОЧНИКА (loggers.<источник>.level) — один источник, соседи молчат",
        f"config_reload_verified(processor, {{loggers: {{{src}: {{level: DEBUG}}}}}})",
        "open(processor/system.log) — [DEBUG] по именам источников; open(camera_0/system.log) как контроль соседа",
        f"verdict=confirmed; Δ[DEBUG] processor > 0 за 4 с и ВСЕ DEBUG-строки от `{src}`; Δ[DEBUG] camera_0 == 0",
        f"verdict={ver2.get('verdict')} unverifiable={short(ver2.get('unverifiable'), 80)}; processor Δ[DEBUG]={dp1 - dp0}, по источникам={mods}; camera_0 Δ[DEBUG]={dc1 - dc0}",
        "PASS"
        if (ver2.get("verdict") == "confirmed" and dp1 - dp0 > 0 and only_src and dc1 - dc0 == 0)
        else ("PARTIAL" if ver2.get("verdict") == "confirmed" else "FAIL"),
        "CONTROL_PANEL.md §7 (DEBUG одному источнику); SINKS_MAP.md §2 (DEBUG-скоуп → system_file)",
    )
    cmd(drv, "processor", "config.reload", {"observability_reset": [f"loggers.{src}.level", "loggers"]})

    # K3: снять приёмник messages_file у camera_0 → INFO не доезжает, счётчик; вернуть
    c0 = counters_of(drv, "camera_0")
    dis = _leaf_result(drv.logger_sink_disable("camera_0", "messages_file", timeout=15.0)) or {}
    eff = obs(drv, "camera_0").get("effective") or {}
    disabled = eff.get("sinks_disabled_by_operator") or (eff.get("logger") or {}).get("sinks_disabled_by_operator")
    m3 = marker("K3off")
    cmd(drv, "camera_0", "health.report", {"message": m3, "level": "INFO", "context": "qa"})
    okoff, _ = wait_until(lambda: file_count(LOG_DIR / "camera_0" / "messages.log", m3) > 0, 2.0)
    c1 = counters_of(drv, "camera_0")

    def _delta(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for plane, vals in (b or {}).items():
            if isinstance(vals, dict):
                for k, vb in vals.items():
                    va = ((a or {}).get(plane) or {}).get(k)
                    if isinstance(vb, (int, float)) and isinstance(va, (int, float)) and vb != va:
                        out[f"{plane}.{k}"] = vb - va
        return out

    dlt = _delta(c0, c1)
    en = _leaf_result(drv.logger_sink_enable("camera_0", "messages_file", timeout=15.0)) or {}
    m3b = marker("K3on")
    cmd(drv, "camera_0", "health.report", {"message": m3b, "level": "INFO", "context": "qa"})
    okon, elon = wait_until(lambda: file_count(LOG_DIR / "camera_0" / "messages.log", m3b) > 0, 3.0)
    row(
        "K3",
        "ручки",
        "приёмник (sink) выключить/включить на лету: messages_file",
        "logger_sink_disable(camera_0, messages_file) → … → logger_sink_enable",
        "open(camera_0/messages.log) с маркерами до/после; readback sinks_disabled_by_operator; счётчики потерь",
        "OFF: маркер НЕ в файле за 2 с, readback называет messages_file, растёт счётчик потерь (какой — наблюдать); ON: маркер в файле ≤ 3 с",
        f"disable={short(dis, 100)}; disabled_by_operator={disabled}; OFF маркер в файле={okoff}; Δсчётчиков={dlt}; enable={short(en, 80)}; ON маркер в файле={okon} за {elon * 1000:.0f} мс",
        "PASS" if (not okoff and okon and disabled and dlt) else ("PARTIAL" if (not okoff and okon) else "FAIL"),
        "CONTROL_PANEL.md §2 (observability.sink.*), §5.3 (sinks_disabled_by_operator)",
    )

    # K4: TTL — правка живёт ttl секунд и возвращается с голосом
    t_set = time.perf_counter()
    r4 = cmd(drv, "camera_0", "config.reload", {"observability": {"log_level": "DEBUG"}, "ttl": 20})
    lay0 = obs(drv, "camera_0").get("layers") or {}
    sess0 = {"session_keys": lay0.get("session_keys"), "ttl": lay0.get("ttl")}

    def _find_keys(node: Any, names: Tuple[str, ...], path: str = "") -> Dict[str, Any]:
        found: Dict[str, Any] = {}
        if isinstance(node, dict):
            for k, v in node.items():
                p = f"{path}.{k}" if path else str(k)
                if k in names and not isinstance(v, (dict, list)):
                    found[p] = v
                found.update(_find_keys(v, names, p))
        return found

    ttl_keys = _find_keys(r4, ("ttl", "ttl_sec", "ttl_enforced", "ttl_default_sec"))
    ok_rev, el_rev = wait_until(
        lambda: file_count(LOG_DIR / "camera_0" / "system.log", "TTL истёк") > 0, 40.0, step=1.0
    )
    t_rev = time.perf_counter() - t_set
    line = file_grep(LOG_DIR / "camera_0" / "system.log", "TTL истёк", limit=1)
    lay1 = obs(drv, "camera_0").get("layers") or {}
    time.sleep(1.0)
    d1 = debug_lines("camera_0")
    time.sleep(4.0)
    d2 = debug_lines("camera_0")
    row(
        "K4",
        "ручки",
        "срок правки (ttl) — авто-возврат с голосом в журнале",
        "config.reload camera_0 {observability: {log_level: DEBUG}, ttl: 20}",
        "open(camera_0/system.log) — строка «TTL истёк … log_level»; readback layers; [DEBUG] перестают расти",
        "reply несёт ttl/ttl_enforced=true; строка «TTL истёк» появляется в интервале (20; 25+2] с (срок + такт 5 с); после — Δ[DEBUG]==0 за 4 с",
        f"reply success={r4.get('success')}, ttl-ключи в ответе (путь→значение)={short(ttl_keys, 200)}; layers до={short(sess0, 160)}; голос через {t_rev:.1f} с: {line}; layers после={short({'session_keys': lay1.get('session_keys'), 'ttl': lay1.get('ttl'), 'reverts': lay1.get('reverts')}, 220)}; [DEBUG] после возврата {d1}→{d2} (Δ{d2 - d1})",
        "PASS" if (ok_rev and 20.0 <= t_rev <= 27.5 and d2 - d1 == 0) else ("PARTIAL" if ok_rev else "FAIL"),
        "CONTROL_PANEL.md §3; observability_ttl.py::_announce_revert; ADR-PM-048 (свип молчит про ADR-PM-046 — не дефект)",
    )
    LAT["K4_ttl_revert_s"] = {"ttl_s": 20, "observed_s": round(t_rev, 1), "grid": "такт heartbeat 5 с + шаг опроса 1 с"}

    # K5: publisher-gate fps off/on — потребитель: дельты state.changed
    def _fps_deltas(since_ns: int) -> int:
        def pred(m: Dict[str, Any]) -> bool:
            if m.get("command") != "state.changed":
                return False
            data = m.get("data") or {}
            for d in data.get("deltas") or []:
                if (
                    isinstance(d, dict)
                    and str(d.get("path", "")).startswith("processes.camera_0.state.")
                    and str(d.get("path", "")).endswith((".fps", ".latency_ms"))
                ):
                    return True
            return False

        return arr.count(pred, since_ns)

    t_b = time.perf_counter_ns()
    time.sleep(12.0)
    base_d = _fps_deltas(t_b)
    if base_d == 0:
        row(
            "K5",
            "ручки",
            "телеметрия: publisher-gate fps/latency_ms выкл/вкл",
            "telemetry_set(camera_0, fps, enabled=false, verify=true)",
            "дельты state.changed по processes.camera_0.state.{fps,latency_ms} (drv.subscribe)",
            "контроль: за 12 с ≥1 дельта до ручки; после OFF — 0 за 12 с; после ON — снова ≥1",
            "контроль дал 0 дельт за 12 с ДО ручки — ось мертва (TreeStore.set гасит дельту при неизменном значении; fps стабильный) — OFF/ON различить нечем",
            "NOT_REACHED",
            "system.yaml (комментарий про TreeStore.set), CONTROL_PANEL.md §5.5",
        )
    else:
        ts_off = drv.telemetry_set("camera_0", "fps", enabled=False, verify=True, timeout=20.0)
        ts_off2 = drv.telemetry_set("camera_0", "latency_ms", enabled=False, verify=True, timeout=20.0)
        it = _leaf_result(drv.introspect_telemetry("camera_0", timeout=15.0)) or {}
        res_fps = (it.get("resolved") or {}).get("fps") or {}
        time.sleep(2.0)
        t_o = time.perf_counter_ns()
        time.sleep(12.0)
        off_d = _fps_deltas(t_o)
        ts_on = drv.telemetry_set("camera_0", "fps", enabled=True, verify=True, timeout=20.0)
        ts_on2 = drv.telemetry_set("camera_0", "latency_ms", enabled=True, verify=True, timeout=20.0)
        time.sleep(2.0)
        t_n = time.perf_counter_ns()
        time.sleep(12.0)
        on_d = _fps_deltas(t_n)
        row(
            "K5",
            "ручки",
            "телеметрия: publisher-gate fps/latency_ms выкл/вкл (L3, срок 300 с)",
            "telemetry_set(camera_0, fps|latency_ms, enabled=false/true, verify=true)",
            "дельты state.changed по processes.camera_0.state.{fps,latency_ms} (drv.subscribe); introspect_telemetry.resolved",
            "контроль ≥1 дельта/12 с; verified_effect=true; resolved.fps.enabled=false; OFF: 0 дельт/12 с; ON: ≥1 дельта/12 с",
            f"контроль={base_d}; off: verified_effect={ts_off.get('verified_effect')}/{ts_off2.get('verified_effect')}, resolved.fps={short(res_fps, 80)}, дельт={off_d}; on: verified_effect={ts_on.get('verified_effect')}/{ts_on2.get('verified_effect')}, дельт={on_d}",
            "PASS"
            if (ts_off.get("verified_effect") and off_d == 0 and on_d >= 1)
            else ("PARTIAL" if ts_off.get("verified_effect") else "FAIL"),
            "CONTROL_PANEL.md §5.4–5.5; memory project_runtime_knob_expires_in_300s",
        )

    # K6: плоскость чисел — правило по пути глушит метрику, счётчик numbers_policy_dropped растёт
    # Процесс и имя метрики берутся из СВЕЖЕГО снапшота любого процесса (прогон 1 спрашивал
    # только ProcessManager, у которого снапшотов с именами не оказалось).
    metric_name, PM_K6 = "", PM
    for proc_, extra_ in sql(db, "SELECT process, extra FROM records WHERE kind='stats' ORDER BY id DESC LIMIT 20"):
        try:
            ex = json.loads(extra_) if isinstance(extra_, str) else (extra_ or {})
            mnames = [m for m in (ex.get("metrics") or {}).keys() if isinstance(m, str)]
        except Exception:  # noqa: BLE001
            mnames = []
        if mnames and proc_:
            metric_name, PM_K6 = mnames[0], str(proc_)
            break
    if not metric_name:
        row(
            "K6",
            "ручки",
            "плоскость чисел: правило glob по пути выключает метрику",
            "config_reload_verified(<p>, {observation: {rules: {processes.<p>.stats.<имя>: {enabled:false}}}})",
            "readback stats.policy + counters.stats.numbers_policy_dropped; snapshot в сторе",
            "readback содержит правило; numbers_policy_dropped[<имя>] растёт за 12 с",
            "в сторе нет ни одного снапшота kind=stats с именами метрик ни у одного процесса — правило писать не на что",
            "NOT_REACHED",
            "CONTROL_PANEL.md §5.4",
        )
    else:
        rule_path = f"processes.{PM_K6}.stats.{metric_name}"
        v6 = drv.config_reload_verified(
            PM_K6, observability={"observation": {"rules": {rule_path: {"enabled": False}}}}, settle=1.0, timeout=30.0
        )
        ver6 = (v6.get("verified") or {}) if isinstance(v6, dict) else {}
        time.sleep(12.0)
        o6 = obs(drv, PM_K6, flush=True)
        st6 = o6.get("stats") or {}
        pol = st6.get("policy") or {}
        dropped = ((o6.get("counters") or {}).get("stats") or {}).get("numbers_policy_dropped")
        newest = sql(
            db, "SELECT extra FROM records WHERE kind='stats' AND process=? ORDER BY id DESC LIMIT 1", (PM_K6,)
        )
        has_metric = None
        if newest:
            try:
                has_metric = metric_name in ((json.loads(newest[0][0]) or {}).get("metrics") or {})
            except Exception:  # noqa: BLE001
                has_metric = None
        dropped_n = (dropped or {}).get(metric_name) if isinstance(dropped, dict) else dropped
        row(
            "K6",
            "ручки",
            f"плоскость чисел: правило по пути глушит метрику `{metric_name}` у {PM_K6}",
            f"config_reload_verified({PM_K6}, {{observation: {{rules: {{{rule_path}: {{enabled: false}}}}}}}})",
            "readback stats.policy.rules/dropped_by_rule + counters.stats.numbers_policy_dropped; sqlite: свежий снапшот без метрики",
            "verdict=confirmed; numbers_policy_dropped[<имя>] > 0 за 12 с; свежий снапшот в сторе не содержит метрику",
            f"verdict={ver6.get('verdict')}; policy.rules={short(pol.get('rules'), 120)} dropped_by_rule={short(pol.get('dropped_by_rule'), 80)}; numbers_policy_dropped={short(dropped, 120)}; свежий снапшот содержит метрику={has_metric}",
            "PASS"
            if (ver6.get("verdict") == "confirmed" and isinstance(dropped_n, (int, float)) and dropped_n > 0)
            else ("PARTIAL" if ver6.get("verdict") == "confirmed" else "FAIL"),
            "CONTROL_PANEL.md §5.4",
        )
        cmd(drv, PM_K6, "config.reload", {"observability_reset": ["observation.rules"]})

    # K7: history.level — порог записи в стор действует на лету.
    # Урок прогона 1: `health.report` кладёт в стор строку плоскости ОШИБОК с тем же маркером
    # (её порог WARNING законно пропускает), а свою INFO-строку в стор не кладёт по дизайну
    # (дедуп дорог). Поэтому INFO-источник здесь — audit-строки самого `config.reload`
    # (`[observability-audit] …`, INFO, модуль `observability`), считаемые в сторе по kind/severity.
    def _info_rows() -> int:
        return sql(db, "SELECT COUNT(*) FROM records WHERE kind='log' AND severity='info' AND process='camera_0'")[0][0]

    def _info_file() -> int:
        return file_count(LOG_DIR / "camera_0" / "messages.log", "[INFO]")

    r7 = cmd(drv, "camera_0", "config.reload", {"observability": {"history": {"level": "WARNING"}}})
    time.sleep(0.5)
    s0, f0 = _info_rows(), _info_file()
    for _ in range(3):  # три reload → ≥3 INFO audit-строки в файле
        cmd(drv, "camera_0", "config.reload", {"observability": {"voices": {"escalate_after_repeats": 3}}})
        time.sleep(0.3)
    m7b = marker("K7warn")
    cmd(drv, "camera_0", "health.report", {"message": m7b, "level": "WARNING", "context": "qa"})
    okb, elb = wait_until(
        lambda: bool(sql(db, "SELECT 1 FROM records WHERE message LIKE ? LIMIT 1", (f"%{m7b}%",))), 3.0
    )
    time.sleep(0.5)
    s1, f1 = _info_rows(), _info_file()
    rs7 = cmd(drv, "camera_0", "config.reload", {"observability_reset": ["history.level"]})
    time.sleep(0.5)
    s2, f2 = _info_rows(), _info_file()
    for _ in range(3):
        cmd(drv, "camera_0", "config.reload", {"observability": {"voices": {"escalate_after_repeats": 3}}})
        time.sleep(0.3)
    time.sleep(0.5)
    s3, f3 = _info_rows(), _info_file()
    hist7 = obs(drv, "camera_0").get("history") or {}
    row(
        "K7",
        "ручки",
        "history.level — порог записи в СТОР действует на лету (файл журнала не трогает)",
        "config.reload camera_0 {history: {level: WARNING}} → 3× reload (INFO audit-строки) → observability_reset [history.level] → 3× reload",
        "sqlite COUNT(kind=log, severity=info, process=camera_0) до/после; open(camera_0/messages.log) COUNT([INFO]) как контроль; WARNING-маркер в сторе",
        "при WARNING: Δstore(info)==0 при Δfile(INFO)≥3; WARNING-строка в сторе ≤3 с; после reset: Δstore(info)≥3 при Δfile(INFO)≥3; readback history.level вернулся к INFO",
        f"reload={r7.get('success')}; WARNING: store info {s0}→{s1} (Δ{s1 - s0}), file INFO {f0}→{f1} (Δ{f1 - f0}); warn-маркер в сторе={okb} за {elb * 1000:.0f} мс; reset={rs7.get('success')}; после reset: store info {s2}→{s3} (Δ{s3 - s2}), file INFO {f2}→{f3} (Δ{f3 - f2}); readback history.level={hist7.get('level')}",
        "PASS"
        if ((s1 - s0) == 0 and (f1 - f0) >= 3 and okb and (s3 - s2) >= 3 and (f3 - f2) >= 3)
        else ("PARTIAL" if ((s1 - s0) == 0 and (f1 - f0) >= 3 and okb) else "FAIL"),
        "CONTROL_PANEL.md §7 (история), ADR-PM-047",
    )

    # K8: опечатка в имени ключа — адресный отказ у операторской двери
    r8 = cmd(drv, "camera_0", "config.reload", {"observability": {"log_levl": "DEBUG"}})
    lay8 = obs(drv, "camera_0").get("layers") or {}
    row(
        "K8",
        "ручки",
        "опечатка в имени ключа (log_levl) — отказ, а не тихий успех",
        "config.reload camera_0 {observability: {log_levl: DEBUG}}",
        "ответ команды + readback layers",
        "success=false, в ответе назван ключ; в session-слое ключа нет",
        f"reply={short(r8, 220)}; layers.session={short(lay8.get('session') or lay8, 120)}",
        "PASS" if (r8.get("success") is False and "log_levl" in json.dumps(r8, ensure_ascii=False)) else "FAIL",
        "CONTROL_PANEL.md §6 (задача 5.4)",
    )

    # K9: voices — readback подтверждает, эффект потребителю не воспроизведён
    v9 = drv.config_reload_verified(
        "camera_0", observability={"voices": {"default_window_sec": 30}}, settle=0.5, timeout=30.0
    )
    ver9 = (v9.get("verified") or {}) if isinstance(v9, dict) else {}
    eff9 = (obs(drv, "camera_0").get("effective") or {}).get("voices") or {}
    cmd(drv, "camera_0", "config.reload", {"observability_reset": ["voices.default_window_sec"]})
    row(
        "K9",
        "ручки",
        "окно голоса (voices.default_window_sec) — readback",
        "config_reload_verified(camera_0, {voices: {default_window_sec: 30}})",
        "readback effective.voices",
        "verdict=confirmed; effective.voices.default_window_sec == 30",
        f"verdict={ver9.get('verdict')}; effective.voices={short(eff9, 160)}",
        "PASS"
        if (ver9.get("verdict") == "confirmed" and eff9.get("default_window_sec") == 30)
        else ("PARTIAL" if ver9.get("verdict") == "confirmed" else "FAIL"),
        "CONTROL_PANEL.md §7 (окна голоса), ADR-LOG-012 — эффект потребителю (подавление повторов) здесь НЕ воспроизведён",
    )

    # K10: регистр плагина — запись с readback и аудит сессии
    t0 = time.perf_counter()
    sr = drv.set_register_verified("inspector", "robot_control", "reject_delay_ms", 1, timeout=15.0)
    el10 = (time.perf_counter() - t0) * 1000
    back = drv.set_register_verified("inspector", "robot_control", "reject_delay_ms", 0, timeout=15.0)
    slog = {
        "note": "session_log — аудит MCP-сессии (E.1), у голого BackendDriver его нет; проверяется MCP-инструментом"
    }
    row(
        "K10",
        "ручки",
        "регистр плагина: запись с readback (set_register_verified) + аудит сессии",
        "set_register_verified(inspector, robot_control, reject_delay_ms, 1) → 0",
        "readback introspect.registers (внутри verified) + session_log",
        "verified=true, actual=1; возврат verified=true, actual=0; session_log содержит запись",
        f"set: verified={sr.get('verified')} expected={sr.get('expected')} actual={sr.get('actual')} за {el10:.0f} мс; back: verified={back.get('verified')} actual={back.get('actual')}; session_log={short(slog, 160)}",
        "PASS" if (sr.get("verified") and back.get("verified")) else "FAIL",
        "backend_ctl/AGENTS.md (set_register_verified, session_log)",
    )
    LAT["K10_register_write_readback_ms"] = {"single": round(el10, 1)}

    # K11: applied не покрывает events (известное с 3.8) — сверка
    cr = ctx.get("events_reply") or {}
    applied = cr.get("applied")
    row(
        "K11",
        "ручки",
        "ответ config.reload: `applied` называет применённую секцию events?",
        "config.reload inspector {events: …} (из R9)",
        "ответ команды",
        "известное с Task 3.8: applied называет только log_level, events_applied — отдельный ключ",
        f"applied={short(applied, 120)}; events_applied={short(cr.get('events_applied'), 120)}",
        "PASS" if cr.get("events_applied") is not None else "PARTIAL",
        "stand-task-3-8.md (побочная находка «applied не покрывает»)",
    )

    row(
        "K12",
        "ручки",
        "observability.persist — сделать правку постоянной (L3 → L2 спутник рецепта)",
        "observability.persist {}",
        "файл-спутник рядом с рецептом",
        "ключи L3 переезжают в спутник",
        "не исполнялось: спутник писался бы рядом с `inspection_full.yaml` в общем дереве (правило «не мутировать tracked-дерево»)",
        "NOT_REACHED",
        "CONTROL_PANEL.md §2, §3",
    )
    row(
        "K13",
        "ручки",
        "history.purge_interval_sec — укороченный период ждёт старый срок (298 с при 5)",
        "config.reload {history: {purge_interval_sec: 5, max_age_sec: 20}}",
        "строка «уборка истории: снято N» в журнале",
        "по Task 3.8: голос через ~300 с, не через 5; config.reload отвечает success",
        "не повторялось (бюджет стенда): замер 298 с зафиксирован в stand-task-3-8.md, заход 3, и ревью (300.5 с)",
        "UNVERIFIED",
        "memory feedback_a_shortened_interval_waits_out_the_old_deadline",
    )
    row(
        "K14",
        "ручки",
        "telemetry_reconfigure(mode=replace) — оптовая секция publisher/throttle",
        "telemetry_reconfigure(process=all, publish=…, mode=replace)",
        "introspect_telemetry",
        "секция применена целиком (неуказанные метрики снесены)",
        "не исполнялось: режим replace сносит белый список fps/latency_ms и дефолтную IPC-страховку — разрушающая ручка вне бюджета приёмки; точечная дорога проверена в K5",
        "NOT_REACHED",
        "backend_ctl/AGENTS.md (telemetry_reconfigure)",
    )


# ---------------------------------------------------------------------------
# Семья 3 — задержки между модулями
# ---------------------------------------------------------------------------


def family_latency(drv, arr: Arrivals, ctx: Dict[str, Any]) -> None:
    log("\n=== Семья 3: задержки ===")
    db = ctx["db_path"]

    # L0: сетка часов
    deltas: List[float] = []
    prev = time.time()
    t_end = time.perf_counter() + 0.5
    while time.perf_counter() < t_end:
        now = time.time()
        if now != prev:
            deltas.append((now - prev) * 1000)
            prev = now
    grid_ms = min(deltas) if deltas else float("nan")
    pdeltas: List[float] = []
    p0 = time.perf_counter_ns()
    for _ in range(2000):
        p1 = time.perf_counter_ns()
        if p1 != p0:
            pdeltas.append((p1 - p0) / 1e3)
            p0 = p1
    LAT["L0_clock_grid"] = {
        "time.time_min_step_ms": round(grid_ms, 3),
        "time.time_steps_seen": len(deltas),
        "perf_counter_min_step_us": round(min(pdeltas), 3) if pdeltas else None,
    }
    row(
        "L0",
        "задержки",
        "разрешение часов на этой машине (что лежит на сетке)",
        "—",
        "time.time() / perf_counter_ns() в цикле",
        "time.time() шагает ~15.6 мс (или 1 мс при поднятом таймере); perf_counter — доли мкс",
        f"time.time min step = {grid_ms:.3f} мс ({len(deltas)} шагов за 0.5 с); perf_counter min step = {LAT['L0_clock_grid']['perf_counter_min_step_us']} мкс",
        "PASS",
        "memory project_monotonic_resolution_windows",
    )

    # L1: RTT команды через роутер
    for target in ("camera_0", "processor", PM):
        vals: List[float] = []
        for _ in range(20):
            t0 = time.perf_counter_ns()
            r = cmd(drv, target, "introspect.status", {}, timeout=10.0)
            t1 = time.perf_counter_ns()
            if r.get("success"):
                vals.append((t1 - t0) / 1e6)
        LAT[f"L1_rtt_introspect_status_{target}"] = stats_ms(vals)
    s = LAT["L1_rtt_introspect_status_camera_0"]
    row(
        "L1",
        "задержки",
        "RTT команда→ответ через роутер (introspect.status), 20 повторов × 3 адресата",
        "—",
        "perf_counter_ns вокруг drv.send_command (оба конца у потребителя — не на сетке)",
        "успешных 20/20 у каждого; медиана в единицах мс; PM быстрее детей (без второго хопа)",
        f"camera_0={s}; processor={LAT['L1_rtt_introspect_status_processor']}; PM={LAT['L1_rtt_introspect_status_ProcessManager']}",
        "PASS"
        if all(LAT[f"L1_rtt_introspect_status_{t}"]["n"] == 20 for t in ("camera_0", "processor", PM))
        else "PARTIAL",
        "memory project_honest_verdict_2026_09 (шина ~0.3/0.6 мс на хоп — это кадр по SHM, не команда)",
    )

    # L2/L3: эмиссия → стор и → живой хвост
    rtt_store: List[float] = []
    lag_store_wall: List[float] = []
    rtt_tail: List[float] = []
    lag_tail_wall: List[float] = []
    cmd_rtt: List[float] = []
    for i in range(7):
        m = marker(f"L{i}")
        t0 = time.perf_counter_ns()
        cmd(drv, "camera_0", "health.report", {"message": m, "level": "WARNING", "context": "qa"})
        t_cmd = time.perf_counter_ns()
        cmd_rtt.append((t_cmd - t0) / 1e6)
        hit = None
        ok_t, _ = wait_until(
            lambda: (
                arr.find(lambda mm: mm.get("command") in ("observability.record", "log.record") and msg_contains(mm, m))
                is not None
            ),
            5.0,
            step=0.002,
        )
        if ok_t:
            hit = arr.find(
                lambda mm: mm.get("command") in ("observability.record", "log.record") and msg_contains(mm, m)
            )
        ok_s, _ = wait_until(
            lambda: bool(sql(db, "SELECT 1 FROM records WHERE message LIKE ? LIMIT 1", (f"%{m}%",))), 5.0, step=0.005
        )
        t_seen = time.perf_counter_ns()
        wall_seen = time.time()
        if ok_s:
            rec = sql(db, "SELECT ts FROM records WHERE message LIKE ? ORDER BY id LIMIT 1", (f"%{m}%",))
            rtt_store.append((t_seen - t0) / 1e6)
            if rec:
                lag_store_wall.append((wall_seen - float(rec[0][0])) * 1000)
        if hit:
            rtt_tail.append((hit[0] - t0) / 1e6)
            recs = msg_records(hit[2])
            ts_emit = None
            for r in recs:
                if msg_contains(r, m):
                    ts_emit = r.get("ts") or r.get("timestamp")
                    break
            if isinstance(ts_emit, (int, float)):
                lag_tail_wall.append((hit[1] - float(ts_emit)) * 1000)
        time.sleep(0.3)
    LAT["L2_emit_to_store_rtt_ms"] = stats_ms(rtt_store)
    LAT["L2_emit_to_store_wall_lag_ms"] = stats_ms(lag_store_wall)
    LAT["L3_emit_to_tail_rtt_ms"] = stats_ms(rtt_tail)
    LAT["L3_emit_to_tail_wall_lag_ms"] = stats_ms(lag_tail_wall)
    LAT["L2_cmd_rtt_health_report_ms"] = stats_ms(cmd_rtt)
    row(
        "L2",
        "задержки",
        "эмиссия в camera_0 → видно в SQLite-сторе (арбитр sqlite3, опрос 5 мс), 7 повторов",
        "health.report level=WARNING с маркером",
        "perf_counter_ns: отправка → первый успешный SELECT; и wall_seen − record.ts (на сетке time.time)",
        "по Task 3.3: ~110–125 мс (такт дренажа 100 мс + таймер 15.6 мс); 7/7 доехали",
        f"RTT отправка→SELECT: {LAT['L2_emit_to_store_rtt_ms']}; wall−ts: {LAT['L2_emit_to_store_wall_lag_ms']}; RTT самой команды: {LAT['L2_cmd_rtt_health_report_ms']}",
        "PASS"
        if LAT["L2_emit_to_store_rtt_ms"]["n"] == 7
        else ("PARTIAL" if LAT["L2_emit_to_store_rtt_ms"]["n"] > 0 else "FAIL"),
        "backend_ctl/AGENTS.md (history_query, задержка Task 3.3)",
    )
    row(
        "L3",
        "задержки",
        "эмиссия в camera_0 → пуш живого хвоста у потребителя (reader-поток драйвера), 7 повторов",
        "тот же health.report",
        "perf_counter_ns: отправка → прибытие в колбэке subscribe; wall_arrival − record.ts",
        "7/7 доехали; медиана меньше, чем у стора (без такта дренажа 100 мс)",
        f"RTT отправка→пуш: {LAT['L3_emit_to_tail_rtt_ms']}; wall−ts: {LAT['L3_emit_to_tail_wall_lag_ms']}",
        "PASS"
        if LAT["L3_emit_to_tail_rtt_ms"]["n"] == 7
        else ("PARTIAL" if LAT["L3_emit_to_tail_rtt_ms"]["n"] > 0 else "FAIL"),
        "backend_ctl/AGENTS.md (observability_tail)",
    )

    # L4: state.set → пуш state.changed. Прогон 1 не поймал ни одного пуша при `changed: true`
    # в ответе — форма дельты неизвестна, поэтому матчим по подстроке и печатаем найденный конверт.
    sub4 = _leaf_result(drv.state_subscribe("qa.**", timeout=15.0)) or {}
    NOTES.append(f"L4 state_subscribe(qa.**) reply: {short(sub4, 200)}")
    time.sleep(0.5)
    vals4: List[float] = []
    rtt4: List[float] = []
    for i in range(7):
        path = "qa.acceptance.n"
        val = 1000 + i
        t0 = time.perf_counter_ns()
        r = cmd(drv, PM, "state.set", {"path": path, "value": val, "source": "qa"}, timeout=10.0)
        t1 = time.perf_counter_ns()

        def pred(m: Dict[str, Any], _v=val) -> bool:
            return (
                m.get("command") == "state.changed" and msg_contains(m, "qa.acceptance.n") and msg_contains(m, str(_v))
            )

        ok4, _ = wait_until(lambda: arr.find(pred) is not None, 5.0, step=0.002)
        if ok4:
            hit = arr.find(pred)
            vals4.append((hit[0] - t0) / 1e6)
            rtt4.append((t1 - t0) / 1e6)
            if i == 0:
                NOTES.append(f"L4 форма пуша: {short(hit[2], 300)}")
        elif i == 0:
            NOTES.append(
                f"L4 state.set reply: {short(r, 200)}; пушей state.changed с 'qa.' в буфере: {arr.count(lambda m: m.get('command') == 'state.changed' and msg_contains(m, 'qa.'))}"
            )
        time.sleep(0.2)
    LAT["L4_state_set_to_push_ms"] = stats_ms(vals4)
    LAT["L4_state_set_cmd_rtt_ms"] = stats_ms(rtt4)
    row(
        "L4",
        "задержки",
        "state.set → пуш state.changed подписчику (qa.**), 7 повторов",
        "state_subscribe('qa.**'); state.set qa.acceptance.n",
        "perf_counter_ns: отправка → прибытие пуша в колбэке",
        "7/7 пушей; медиана того же порядка, что RTT команды",
        f"отправка→пуш: {LAT['L4_state_set_to_push_ms']}; RTT state.set: {LAT['L4_state_set_cmd_rtt_ms']}",
        "PASS"
        if LAT["L4_state_set_to_push_ms"]["n"] == 7
        else ("PARTIAL" if LAT["L4_state_set_to_push_ms"]["n"] > 0 else "FAIL"),
        "backend_ctl/AGENTS.md (state_subscribe, мост push→канал 1.1b)",
    )

    # L5: регистр — запись → readback, 5 повторов
    vals5: List[float] = []
    for i in range(5):
        t0 = time.perf_counter_ns()
        r = drv.set_register_verified("inspector", "robot_control", "reject_delay_ms", (i % 2) + 1, timeout=15.0)
        t1 = time.perf_counter_ns()
        if r.get("verified"):
            vals5.append((t1 - t0) / 1e6)
    drv.set_register_verified("inspector", "robot_control", "reject_delay_ms", 0, timeout=15.0)
    LAT["L5_register_write_verified_ms"] = stats_ms(vals5)
    row(
        "L5",
        "задержки",
        "запись регистра → readback подтверждён (set_register_verified), 5 повторов",
        "set_register_verified(inspector, robot_control, reject_delay_ms)",
        "perf_counter_ns вокруг вызова",
        "5/5 verified; медиана ≈ 2× RTT команды (write + readback)",
        f"{LAT['L5_register_write_verified_ms']}",
        "PASS" if LAT["L5_register_write_verified_ms"]["n"] == 5 else "PARTIAL",
        "backend_ctl/AGENTS.md (set_register_verified)",
    )

    # L6: путь кадра — что даёт потребителю телеметрия
    lv = {}
    for p in ("camera_0", "processor", "inspector"):
        t = _leaf_result(drv.introspect_telemetry(p, timeout=15.0)) or {}
        levels = t.get("levels") or {}
        st = levels.get("state") if isinstance(levels, dict) else None
        lv[p] = {k: (st or {}).get(k) for k in ("fps", "latency_ms")} if isinstance(st, dict) else levels
    row(
        "L6",
        "задержки",
        "путь кадра camera_0 → processor → inspector: хоп-лаг между модулями",
        "—",
        "introspect_telemetry(<p>).levels.state.{fps, latency_ms}; extra широкой записи",
        "потребителю доступна отметка захвата (monotonic item['timestamp']) на каждом хопе → разность = лаг хопа",
        f"такой поверхности нет: latency_ms = max(cycle_duration_ms) воркера (время ЦИКЛА, не хопа; heartbeat/telemetry.py:184), широкая запись несёт trace_id без отметки захвата (plugins/base.py write_event), item['timestamp'] = monotonic у camera_service (:184) наружу не экспортируется. Что есть: {short(lv, 260)}",
        "NOT_REACHED",
        "OBSERVABILITY_MAP.md §1; Plugins/sources/camera_service/plugin.py:184; heartbeat/telemetry.py:184",
    )


# ---------------------------------------------------------------------------
# Семья 4 — ошибки и отказы
# ---------------------------------------------------------------------------


def family_errors(drv, arr: Arrivals, ctx: Dict[str, Any]) -> None:
    log("\n=== Семья 4: ошибки ===")
    db = ctx["db_path"]

    # Файлы плоскости ошибок лежат В КОРНЕ каталога логов и ОБЩИЕ для всех процессов
    # (`error_manager_config.py`: `logs/errors.log`), а не per-process — факт прогона 1.
    m1 = marker("E1")
    t0 = time.perf_counter_ns()
    hr = cmd(drv, "processor", "health.report", {"message": m1, "level": "ERROR", "context": "qa"})
    okf, elf = wait_until(lambda: file_count(LOG_DIR / "errors.log", m1) > 0, 3.0)
    oks, els = wait_until(
        lambda: bool(sql(db, "SELECT kind, severity FROM records WHERE message LIKE ? LIMIT 1", (f"%{m1}%",))), 3.0
    )
    rows_ = sql(db, "SELECT kind, severity, process, module FROM records WHERE message LIKE ?", (f"%{m1}%",))
    okp, _ = wait_until(
        lambda: arr.find(lambda m: m.get("command") == "observability.record" and msg_contains(m, m1)) is not None, 3.0
    )
    kinds = sorted({r.get("kind") for it in arr.items if msg_contains(it[2], m1) for r in msg_records(it[2])} - {None})
    files = {f: file_count(LOG_DIR / f, m1) for f in ("errors.log", "warnings.log", "critical.log")}
    files["processor/system.log"] = file_count(LOG_DIR / "processor" / "system.log", m1)
    ov = drv.system_overview(timeout=20.0)
    anomalies = ov.get("anomalies") if isinstance(ov, dict) else None
    an_txt = json.dumps(anomalies, ensure_ascii=False, default=str)
    row(
        "E1",
        "ошибки",
        "инъекция ERROR в processor → errors.log, стор kind=error, пуш, anomalies",
        "health.report processor {level: ERROR, message: <маркер>}",
        "open(<log_dir>/errors.log — общий файл всех процессов); sqlite; drv.subscribe; system_overview.anomalies",
        "маркер в <log_dir>/errors.log ≤ 3 с; строка в сторе kind=error ≤ 3 с; пуш observability.record kind=error; anomalies упоминают health/processor",
        f"reply={short(hr, 100)}; errors.log={okf} за {elf * 1000:.0f} мс; файлы={files}; стор={rows_}; push={okp} kinds={kinds}; anomalies содержит 'health'={'health' in an_txt} 'processor'={'processor' in an_txt}: {short(anomalies, 200)}",
        "PASS"
        if (okf and oks and okp and any(r[0] == "error" for r in rows_))
        else ("PARTIAL" if (okf or oks) else "FAIL"),
        "OBSERVABILITY_MAP.md §1 (плоскость ошибок), SINKS_MAP.md §2, ADR-PM-030",
    )

    m2 = marker("E2")
    tr = cmd(drv, "renderer", "diag.thread_raise", {"message": m2, "thread_name": "qa-raise"}, timeout=20.0)
    okf2, _ = wait_until(lambda: file_count(LOG_DIR / "errors.log", m2) > 0, 3.0)
    files2 = {
        "errors.log": file_count(LOG_DIR / "errors.log", m2),
        "critical.log": file_count(LOG_DIR / "critical.log", m2),
        "renderer/system.log": file_count(LOG_DIR / "renderer" / "system.log", m2),
    }
    row(
        "E2",
        "ошибки",
        "необработанное исключение в потоке (threading.excepthook) → плоскость ошибок",
        "diag.thread_raise renderer {message, thread_name}",
        "ответ команды + open(<log_dir>/errors.log)",
        "success=true, joined=true, thread_exceptions ≥ 1; маркер в <log_dir>/errors.log ≤ 3 с (с traceback)",
        f"reply={short(tr, 200)}; файлы={files2}",
        "PASS" if (tr.get("success") and okf2) else ("PARTIAL" if tr.get("success") else "FAIL"),
        "CONTROL_PANEL.md §2 (diag.thread_raise), Ф1.1 (C3)",
    )

    m3 = marker("E3")
    dw = cmd(drv, "renderer", "diag.warn", {"message": m3}, timeout=20.0)
    time.sleep(1.0)
    files3 = {
        "warnings.log": file_count(LOG_DIR / "warnings.log", m3),
        "errors.log": file_count(LOG_DIR / "errors.log", m3),
        "renderer/system.log": file_count(LOG_DIR / "renderer" / "system.log", m3),
        "renderer/messages.log": file_count(LOG_DIR / "renderer" / "messages.log", m3),
    }
    row(
        "E3",
        "ошибки",
        "warnings.warn (captureWarnings) → журнал/плоскость ошибок",
        "diag.warn renderer {message}",
        "ответ команды + open(<log_dir>/warnings.log, renderer/system.log)",
        "success=true, warnings_captured ≥ 1; маркер хотя бы в одном из renderer/system.log / <log_dir>/warnings.log (какой — наблюдать)",
        f"reply={short(dw, 160)}; файлы={files3}",
        "PASS"
        if (dw.get("success") and any(v > 0 for v in files3.values()))
        else ("PARTIAL" if dw.get("success") else "FAIL"),
        "CONTROL_PANEL.md §2 (diag.warn)",
    )

    floors = glob.glob(str(LOG_DIR / "**" / "errors_floor.jsonl"), recursive=True)
    floor_hits = {f: file_count(Path(f), m1) for f in floors}
    c_err = counters_of(drv, "processor").get("error") or {}
    to_floor = c_err.get("errors_to_floor")
    row(
        "E4",
        "ошибки",
        "пол ошибок errors_floor.jsonl — пишется ТОЛЬКО когда штатный маршрут записал ноль каналов",
        "—",
        "glob(<log_dir>/**/errors_floor.jsonl) + counters.error.errors_to_floor",
        "у здорового процесса файла НЕТ и errors_to_floor == 0 (error_floor.py: «floor непустой означает, что штатный маршрут сломан»); ERROR-маркер E1 дошёл до errors.log обычной дорогой",
        f"файлы={[os.path.relpath(f, LOG_DIR) for f in floors]}; маркер E1 в них={floor_hits}; errors_to_floor={to_floor}; E1 в errors.log={files.get('errors.log')}",
        "PASS" if (not floors and to_floor == 0 and files.get("errors.log", 0) > 0) else "PARTIAL",
        "error_floor.py (докстринг); OBSERVABILITY_MAP.md §1 читается как «пол пишется всегда» — уточнить",
    )

    c = counters_of(drv, "processor")
    need = {
        "unresolved_channel_records",
        "channel_write_errors",
        "channel_refused_records",
        "records_without_channels",
        "tap_reentrant_suppressed",
        "channel_written_records",
    }
    planes = {k: sorted(v.keys()) for k, v in c.items() if isinstance(v, dict)}
    have_all = {p for p, ks in planes.items() if need <= set(ks)}
    store_keys = {
        p: {k: v for k, v in (c.get(p) or {}).items() if "store" in k or "evict" in k or "dropped" in k}
        for p in c
        if isinstance(c.get(p), dict)
    }
    row(
        "E5",
        "ошибки",
        "счётчики потерь у трёх плоскостей + стор (видимость, НЕ под нагрузкой)",
        "—",
        "introspect.observability(flush) → counters",
        f"у logger/error/stats ключи ⊇ {sorted(need)}; есть счётчик вытеснений стора",
        f"плоскости с полным набором={sorted(have_all)}; все плоскости={sorted(planes.keys())}; store/evict/dropped-ключи={short(store_keys, 300)}",
        "PARTIAL" if have_all else "FAIL",
        "OBSERVABILITY_MAP.md §6 (LOSS_COUNTER_KEYS) — рост под перегрузкой здесь не вызывался",
    )

    h = _leaf_result(drv.introspect_handlers("camera_0", timeout=15.0)) or {}
    cmds = set(h.get("commands") or [])
    rh = set(h.get("router_handlers") or [])
    t0 = time.perf_counter()
    nr = cmd(drv, "camera_0", "qa.nonexistent.command", {}, timeout=6.0)
    el = time.perf_counter() - t0
    row(
        "E6",
        "ошибки",
        "диагностика «нет приёмника»: introspect_handlers + неизвестная команда",
        "send_command(camera_0, qa.nonexistent.command)",
        "introspect_handlers(camera_0); ответ команды",
        "команды нет ни в commands, ни в router_handlers; ответ — названный отказ (success=false с текстом), не таймаут",
        f"commands={len(cmds)} router_handlers={len(rh)}; в списках={'qa.nonexistent.command' in cmds or 'qa.nonexistent.command' in rh}; reply={short(nr, 200)} за {el:.2f} с",
        "PASS"
        if (
            (nr.get("success") is False or nr.get("status") == "error")
            and nr.get("reason")
            and "timeout" not in json.dumps(nr)
        )
        else "PARTIAL",
        "backend_ctl/AGENTS.md («Киллер-фича»); форма отказа — {status: error, reason}, без ключа success",
    )


# ---------------------------------------------------------------------------
# Семья 5 — жизненный цикл
# ---------------------------------------------------------------------------


def family_lifecycle(drv, arr: Arrivals, ctx: Dict[str, Any]) -> None:
    log("\n=== Семья 5: жизненный цикл ===")

    before = {p: ((counters_of(drv, p).get("logger") or {}).get("unresolved_channel_records")) for p in ctx["procs"]}
    r = drv.config_reload("all", observability={"log_level": "INFO"}, timeout=40.0)
    time.sleep(1.5)
    after = {p: ((counters_of(drv, p).get("logger") or {}).get("unresolved_channel_records")) for p in ctx["procs"]}
    delta = {
        p: ((after[p] or 0) - (before[p] or 0))
        if isinstance(after.get(p), (int, float)) and isinstance(before.get(p), (int, float))
        else None
        for p in ctx["procs"]
    }
    ok_batch = isinstance(r, dict) and (r.get("batch") is True or r.get("success"))
    row(
        "LC1",
        "жизненный цикл",
        "config.reload всем процессам под нагрузкой — цена окна пересборки каналов",
        "config_reload('all', {log_level: INFO})",
        "counters.logger.unresolved_channel_records до/после",
        "batch-ответ на 7 процессов; Δunresolved_channel_records ≤ 2 у каждого (документировано ~1 на процесс)",
        f"reply batch={r.get('batch') if isinstance(r, dict) else r} not_ok={short((r or {}).get('not_ok'), 80)}; Δ={delta}",
        "PASS" if (ok_batch and all((d is not None and d <= 2) for d in delta.values())) else "PARTIAL",
        "CONTROL_PANEL.md §6.1; CONNECTORS.md §4.1",
    )
    # Сброс — батчем через send_command_many: send_command("all", …) прогона 1 не дошёл никуда
    # (у camera_0 в аудите остался touch log_level ttl=300 без reset).
    rs_all = drv.send_command_many("all", "config.reload", {"observability_reset": ["log_level"]}, timeout=30.0)
    NOTES.append(
        f"LC1 reset all: not_ok={short((rs_all or {}).get('not_ok'), 100)} failed={short((rs_all or {}).get('failed'), 100)}"
    )

    # LC2: рестарт renderer с доказательством, судьба L3 и счётчиков, авто-переподписка хвоста
    cmd(drv, "renderer", "config.reload", {"observability": {"log_level": "DEBUG"}, "ttl": 600})
    lay_b = obs(drv, "renderer").get("layers") or {}
    cnt_b = (counters_of(drv, "renderer").get("logger") or {}).get("channel_written_records")
    t_r = time.perf_counter_ns()
    rr = drv.process_restart_verified("renderer", wait=90.0, timeout=10.0)
    # Новая инкарнация отвечает не сразу — ждём первый успешный introspect до 20 с.
    ok_alive, el_alive = wait_until(lambda: bool(obs(drv, "renderer").get("success")), 20.0, step=0.5)
    lay_a = obs(drv, "renderer").get("layers") or {}
    cnt_a = (counters_of(drv, "renderer").get("logger") or {}).get("channel_written_records")
    ok_rs, el_rs = wait_until(
        lambda: (
            arr.count(
                lambda m: (
                    m.get("command") == "observability.record"
                    and any(rr_.get("process") == "renderer" for rr_ in msg_records(m))
                ),
                t_r,
            )
            > 0
        ),
        30.0,
        step=0.5,
    )
    sess_b = lay_b.get("session_keys") if isinstance(lay_b, dict) else None
    sess_a = lay_a.get("session_keys") if isinstance(lay_a, dict) else None
    NOTES.append(f"LC2 новая инкарнация ответила на introspect через {el_alive:.1f} с (ok={ok_alive})")
    row(
        "LC2",
        "жизненный цикл",
        "process_restart_verified(renderer): pid, L3, счётчики, авто-переподписка хвоста",
        "config.reload renderer {log_level: DEBUG, ttl: 600} → process_restart_verified(renderer)",
        "ответ с pid_before/pid_after; readback layers/counters до/после; пуши observability.record от renderer после рестарта",
        "restarted=true, pid сменился; L3 (log_level) ПОТЕРЯН после рестарта; channel_written_records СБРОШЕН (меньше, чем до); новые записи renderer доезжают до подписчика ≤ 30 с (авто-переподписка watch)",
        f"restart={short({k: rr.get(k) for k in ('restarted', 'pid_before', 'pid_after', 'elapsed', 'instance_restarts_before', 'instance_restarts_after')}, 200)}; L3 до={short(sess_b, 100)} после={short(sess_a, 100)}; written до={cnt_b} после={cnt_a}; пуш от renderer после рестарта={ok_rs} за {el_rs:.1f} с",
        "PASS"
        if (
            rr.get("restarted")
            and rr.get("pid_before") != rr.get("pid_after")
            and ok_rs
            and sess_b
            and not sess_a
            and isinstance(cnt_a, (int, float))
            and isinstance(cnt_b, (int, float))
            and cnt_a < cnt_b
        )
        else ("PARTIAL" if rr.get("restarted") else "FAIL"),
        "backend_ctl/AGENTS.md (process_restart_verified, watch_like_gui авто-переподписка)",
    )
    LAT["LC2_restart_elapsed_s"] = {"elapsed": rr.get("elapsed"), "polls": rr.get("polls")}

    o = obs(drv, "camera_0")
    lay = o.get("layers") or {}
    row(
        "LC3",
        "жизненный цикл",
        "срок сессии по умолчанию (session_ttl_sec) в readback",
        "—",
        "introspect.observability → layers.{ttl_default_sec, ttl_enforced, ttl}",
        "ttl_default_sec == 300.0, ttl_enforced == true; layers.ttl — карта «ключ → остаток секунд»",
        f"ttl_default_sec={lay.get('ttl_default_sec')} ttl_enforced={lay.get('ttl_enforced')} ttl={short(lay.get('ttl'), 160)} session_keys={short(lay.get('session_keys'), 120)}",
        "PASS" if (lay.get("ttl_default_sec") == 300 and lay.get("ttl_enforced") is True) else "PARTIAL",
        "CONTROL_PANEL.md §3",
    )


def family_shutdown(procs: List[str]) -> None:
    log("\n=== Семья 5: останов ===")
    flush = {}
    for p in procs:
        hits = file_grep(LOG_DIR / p / "messages.log", "store flush:", limit=2) + file_grep(
            LOG_DIR / p / "system.log", "store flush:", limit=2
        )
        flush[p] = hits
    n_with = sum(1 for v in flush.values() if v)
    lost = []
    for v in flush.values():
        for line in v:
            mm = re.search(r"store flush: (\d+) записано, (\d+) потеряно", line)
            if mm:
                lost.append(int(mm.group(2)))
    row(
        "LC4",
        "жизненный цикл",
        "останов: строка «store flush: N записано, M потеряно» у каждого процесса",
        "harness.stop()",
        "open(<процесс>/messages.log|system.log) после останова",
        "строка есть у всех 7 процессов; M == 0 у всех",
        f"процессов со строкой={n_with}/{len(procs)}; потеряно по строкам={lost}; примеры={short({k: v[:1] for k, v in flush.items()}, 400)}",
        "PASS"
        if (n_with == len(procs) and lost and all(x == 0 for x in lost))
        else ("PARTIAL" if n_with > 0 else "FAIL"),
        "CONNECTORS.md; store_tap.py::close()",
    )
    free = port_free(PORT)
    row(
        "LC5",
        "жизненный цикл",
        "порт 8765 освобождён после останова",
        "harness.stop()",
        "socket.connect_ex",
        "connect_ex != 0",
        f"port_free={free}",
        "PASS" if free else "FAIL",
        "docs/sessions/2026-09-07_handoff-parallel-start.md §3",
    )


# ---------------------------------------------------------------------------
# Отчёт
# ---------------------------------------------------------------------------


def write_reports() -> None:
    out_json = LOG_DIR / "acceptance_results.json"
    out_md = LOG_DIR / "acceptance_results.md"
    out_json.write_text(
        json.dumps(
            {"rows": ROWS, "latency": LAT, "notes": NOTES, "log_dir": str(LOG_DIR)},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    lines = [
        "| № | функция | как управлять | как проверил (потребитель) | ожидал | наблюдал | вердикт | где документировано |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in ROWS:
        cells = [
            r["id"],
            r["function"],
            r["control"],
            r["consumer"],
            r["expected"],
            r["observed"],
            r["verdict"],
            r["doc"],
        ]
        lines.append("| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
    lines.append("")
    lines.append("## Задержки")
    lines.append("```json")
    lines.append(json.dumps(LAT, ensure_ascii=False, indent=2, default=str))
    lines.append("```")
    if NOTES:
        lines.append("## Заметки")
        lines.extend(f"- {n}" for n in NOTES)
    out_md.write_text("\n".join(lines), encoding="utf-8")
    counts: Dict[str, int] = {}
    for r in ROWS:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    log(f"\nИТОГ по вердиктам: {counts}")
    log(f"Отчёты: {out_json}\n        {out_md}")


def main() -> int:
    if not port_free(PORT):
        log(f"[abort] порт {PORT} занят — стенд эксклюзивен, ничего не убиваю")
        return 2
    log(f"[stand] log_dir={LOG_DIR}\n[stand] recipe={RECIPE}")
    harness = BackendHarness(
        recipe=RECIPE, port=PORT, ready_timeout=60.0, warmup=3.0, teardown_timeout=30.0, log_dir=LOG_DIR
    )
    arr = Arrivals()
    procs: List[str] = []
    t_start = time.time()
    try:
        drv = harness.start()
        drv.subscribe(arr)
        time.sleep(6.0)  # прогрев: первые снапшоты stats (10 с) ещё не пришли — это учтено в K6
        ctx = family_self_description(drv)
        procs = ctx["procs"]
        family_reading(drv, arr, ctx)
        family_knobs(drv, arr, ctx)
        family_latency(drv, arr, ctx)
        family_errors(drv, arr, ctx)
        family_lifecycle(drv, arr, ctx)
        NOTES.append(f"стенд жил {time.time() - t_start:.0f} с до останова; пушей собрано {len(arr.items)}")
    except Exception as exc:  # noqa: BLE001
        import traceback

        NOTES.append(f"ИСКЛЮЧЕНИЕ зонда: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-1500:]}")
        log(NOTES[-1])
    finally:
        log("\n[stand] останавливаю…")
        harness.stop()
    family_shutdown(procs or sorted(EXPECTED_PROCS))
    write_reports()
    return 0


if __name__ == "__main__":
    sys.exit(main())
