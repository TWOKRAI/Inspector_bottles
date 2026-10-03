"""Пороги стенд-гейта над JSON одного кейса (перенос `analyze5.py`, Task 5.6).

Чистые функции: вход — dict JSON `stand5`-формата, выход — :class:`CaseResult` со списком проверок.
Сбой входа (нет обязательного ключа) — :class:`GateInputError`, CLI превращает его в код 2.
Определения (born/drops/own_in/handled, F, I, N, V) — литералы «Определения» Task 5.6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import thresholds as T

PASS = "PASS"
FAIL = "FAIL"
NOT_MEASURED = "NOT_MEASURED"
REPORT = "REPORT"

#: Ключи верхнего уровня, без которых пороги не считаются (код 2).
REQUIRED_KEYS: tuple[str, ...] = ("s0", "s1", "s2", "rc_s2", "camera_before_pause", "journal")
#: Процессы, без которых формулы не считаются (код 2).
REQUIRED_PROCESSES: tuple[str, ...] = ("processor", "inspector", "renderer")
#: Ключи статуса воркера, которые не являются счётчиками и в суммы не идут.
_NOT_COUNTERS = ("queue_wait_ms", "effective_hz")


class GateInputError(Exception):
    """Вход не годится для порогов (нет ключа, не JSON) — код выхода 2."""


@dataclass
class Check:
    name: str
    status: str  # PASS | FAIL | NOT_MEASURED | REPORT
    fact: str
    threshold: str = ""

    def line(self) -> str:
        if self.status == NOT_MEASURED:
            return f"FAIL {self.name}: NOT_MEASURED {self.fact} vs {self.threshold}"
        if self.status == REPORT:
            return f"REPORT {self.name}: {self.fact}"
        return f"{self.status} {self.name}: {self.fact} vs {self.threshold}"

    @property
    def failed(self) -> bool:
        return self.status in (FAIL, NOT_MEASURED)


@dataclass
class CaseResult:
    label: str
    case: str
    checks: list[Check] = field(default_factory=list)
    numbers: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return any(c.failed for c in self.checks)


# --- определения -------------------------------------------------------------------
def w(rec: dict, key: str) -> int | float:
    """Σ по воркерам числового ключа ``key`` (воркеры без ключа не участвуют)."""
    total: int | float = 0
    if key in _NOT_COUNTERS:
        return total
    for ws in (rec.get("workers") or {}).values():
        v = ws.get(key) if isinstance(ws, dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            total += v
    return total


def _rs(rec: dict, key: str) -> int:
    return int((rec.get("rs") or {}).get(key, 0) or 0)


def own_in(rec: dict) -> int | float:
    return w(rec, "not_inspected_lag") + w(rec, "not_inspected_stale_restore") + w(rec, "not_inspected_stale_exec")


def born(rec: dict) -> int | float:
    return own_in(rec) + _rs(rec, "not_inspected_door")


def drops(rec: dict) -> int | float:
    return (
        w(rec, "lag_dropped_items")
        + _rs(rec, "frame_stale_drops")
        + _rs(rec, "frame_torn_reads")
        + _rs(rec, "frame_restore_failures")
    )


def handled(rec: dict) -> int | float:
    return w(rec, "not_inspected_handled")


def find_dict_with(obj: Any, key: str) -> dict | None:
    """Вложенный dict с ключом ``key`` на любой глубине (ответ драйвера обёрнут)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj
        for v in obj.values():
            got = find_dict_with(v, key)
            if got is not None:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = find_dict_with(v, key)
            if got is not None:
                return got
    return None


def detect_case(data: dict) -> str:
    """``pause`` → P10; иначе ``transit_ms > 0`` → D100; иначе E."""
    if "pause" in data:
        return "P10"
    if (data.get("transit_ms") or 0) > 0:
        return "D100"
    return "E"


def _fmt(x: float) -> str:
    return f"{x:g}" if isinstance(x, float) else str(x)


# --- вход ---------------------------------------------------------------------------
def _require(data: Any) -> None:
    if not isinstance(data, dict):
        raise GateInputError("JSON кейса — не объект")
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise GateInputError(f"нет обязательных ключей: {missing}")
    for snap in ("s0", "s1", "s2"):
        absent = [p for p in REQUIRED_PROCESSES if p not in (data[snap] or {})]
        if absent:
            raise GateInputError(f"в {snap} нет процессов {absent}")
    if detect_case(data) == "P10":
        pause = data["pause"] or {}
        need = [k for k in ("rss0", "rss1", "drain_s", "drain_poll_period_s", "after") if k not in pause]
        if need:
            raise GateInputError(f"P10: в pause нет ключей {need}")


def _frames(data: dict) -> int:
    cam = data["camera_before_pause"] or {}
    cycles = [ws.get("cycles") for ws in (cam.get("workers") or {}).values() if isinstance(ws, dict)]
    cycles = [c for c in cycles if isinstance(c, int) and not isinstance(c, bool)]
    if not cycles:
        raise GateInputError("camera_before_pause: нет ни одного счётчика cycles — F не определён")
    return sum(cycles)


def _solver(data: dict) -> dict:
    rc = find_dict_with(data["rc_s2"], "total_inspected")
    if rc is None or "total_not_inspected" not in rc:
        raise GateInputError("rc_s2: нет dict с total_inspected/total_not_inspected")
    return rc


# --- пороги -------------------------------------------------------------------------
def _zero_counter(name: str, sites: list[tuple[str, dict]]) -> Check:
    bad = [f"{label}.{proc}={_rs(rec, name)}" for label, snap in sites for proc, rec in snap.items() if _rs(rec, name)]
    if bad:
        return Check(name, FAIL, ", ".join(bad), "== 0")
    return Check(name, PASS, "0 at " + "+".join(label for label, _ in sites), "== 0")


def analyze(data: Any, *, label: str = "case", throughput_gate: bool = True) -> CaseResult:
    """Все пороги Task 5.6 над одним кейсом. ``throughput_gate=False`` выключает ТОЛЬКО lag processor."""
    _require(data)
    case = detect_case(data)
    res = CaseResult(label=label, case=case)
    checks = res.checks
    s0, s1, s2 = data["s0"], data["s1"], data["s2"]
    frames = _frames(data)
    rc = _solver(data)
    inspected, not_inspected = int(rc["total_inspected"]), int(rc["total_not_inspected"])
    journal = data["journal"] or {}

    # rs.queue_data_evicted == 0 и rs.errors_delivery_failed == 0: s0, s2 (+ pause.after у P10).
    sites = [("s0", s0), ("s2", s2)]
    if case == "P10":
        sites.append(("pause.after", data["pause"]["after"]))
    checks.append(_zero_counter("queue_data_evicted", sites))
    checks.append(_zero_counter("errors_delivery_failed", sites))

    # Формула по процессу.
    for proc in T.FORMULA_PROCESSES:
        b, d = born(s2[proc]), drops(s2[proc])
        status = PASS if b - d == 0 else FAIL
        checks.append(Check(f"formula born-drops[{proc}]", status, f"born={b} drops={d} diff={b - d}", "== 0"))

    # Формула соседей processor.
    born_p = born(s2["processor"])
    for nb in T.NEIGHBOR_PROCESSES:
        h, o = handled(s2[nb]), own_in(s2[nb])
        diff = h - o - born_p
        checks.append(
            Check(
                f"neighbor handled-own_in-born(processor)[{nb}]",
                PASS if diff == 0 else FAIL,
                f"handled={h} own_in={o} born(processor)={born_p} diff={diff}",
                "== 0",
            )
        )

    # Учёт решателя.
    ledger = inspected + not_inspected - frames
    upper = T.LEDGER_UPPER_FRACTION * frames
    checks.append(
        Check(
            "solver ledger (I+N)-F",
            PASS if T.LEDGER_LOWER <= ledger <= upper else FAIL,
            f"{ledger} (I={inspected} N={not_inspected} F={frames})",
            f"{T.LEDGER_LOWER}..{_fmt(upper)}",
        )
    )

    dup = int(journal.get("dup", 0) or 0)
    checks.append(Check("journal dup trace_id", PASS if dup <= T.JOURNAL_DUP_MAX else FAIL, str(dup), "== 0"))

    stale_restore = sum(w(rec, "not_inspected_stale_restore") for rec in s2.values() if isinstance(rec, dict))
    limit = T.STALE_RESTORE_FRACTION * frames
    checks.append(
        Check("stale_restore", PASS if stale_restore <= limit else FAIL, str(stale_restore), f"<= {_fmt(limit)}")
    )

    lag_p = w(s2["processor"], "lag_dropped_items")
    lag_limit = T.PROCESSOR_LAG_FRACTION * frames
    if throughput_gate:
        status = PASS if lag_p <= lag_limit else FAIL
        checks.append(Check("lag processor lag_dropped_items", status, str(lag_p), f"<= {_fmt(lag_limit)}"))
    else:
        checks.append(Check("lag processor lag_dropped_items", REPORT, f"{lag_p} (порог {_fmt(lag_limit)} выключен)"))

    if case == "D100":
        verdicts = int(journal.get("verdicts", 0) or 0)
        floor = T.VERDICT_FLOOR_FRACTION * (frames - not_inspected)
        checks.append(Check("verdicts V", PASS if verdicts >= floor else FAIL, str(verdicts), f">= {_fmt(floor)}"))
        win = w(s1["inspector"], "not_inspected_lag") - w(s0["inspector"], "not_inspected_lag")
        status = PASS if win <= T.INSPECTOR_WINDOW_LAG_MAX else FAIL
        checks.append(Check("lag@inspector window s1-s0", status, str(win), f"<= {T.INSPECTOR_WINDOW_LAG_MAX}"))

    if case == "P10":
        pause = data["pause"]
        growth = int(pause["rss1"]) - int(pause["rss0"])
        status = PASS if growth <= T.PAUSE_RSS_GROWTH_MAX_BYTES else FAIL
        checks.append(Check("pause rss growth", status, f"{growth} B", f"<= {T.PAUSE_RSS_GROWTH_MAX_BYTES} B"))
        checks.append(_drain_check(pause))

    for proc, rec in s0.items():
        n = _rs(rec, "frame_stale_drops") if isinstance(rec, dict) else 0
        if proc in T.EVERY_PROCESSES:
            status = PASS if n <= T.START_STALE_DROPS_MAX else FAIL
            checks.append(Check(f"start frame_stale_drops[{proc}]", status, str(n), "== 0"))
        else:
            checks.append(Check(f"start frame_stale_drops[{proc}]", REPORT, f"{n} (latest, без порога)"))

    res.numbers = _numbers(data, rc, frames, lag_p)
    return res


def _drain_check(pause: dict) -> Check:
    period, drain = pause["drain_poll_period_s"], pause["drain_s"]
    if period is None or float(period) > T.DRAIN_POLL_PERIOD_MAX_S:
        return Check(
            "drain", NOT_MEASURED, f"poll period {period} s, drain_s={drain}", f"poll <= {T.DRAIN_POLL_PERIOD_MAX_S} s"
        )
    if drain is None:
        return Check("drain", FAIL, "очередь не вернулась к медиане до паузы", f"<= {T.DRAIN_MAX_S} s")
    status = PASS if float(drain) <= T.DRAIN_MAX_S else FAIL
    return Check("drain", status, f"{drain} s (poll {period} s)", f"<= {T.DRAIN_MAX_S} s")


def _numbers(data: dict, rc: dict, frames: int, lag_p: Any) -> dict[str, Any]:
    """Числа «в отчёте, без порога» (5.2, 5.4, справочные)."""
    journal = data.get("journal") or {}
    out: dict[str, Any] = {
        "F (camera cycles)": frames,
        "I total_inspected": rc.get("total_inspected"),
        "N total_not_inspected": rc.get("total_not_inspected"),
        "V verdicts": journal.get("verdicts"),
        "journal rows / markers": f"{journal.get('rows')} / {journal.get('markers')}",
        "lag processor": lag_p,
        "start_s": data.get("start_s"),
        "first_frame_after_ready_s": data.get("first_frame_after_ready_s"),
    }
    for key in (
        "actuation_fired_items",
        "actuation_missed_items",
        "actuation_late_fires",
        "actuation_unscheduled_items",
    ):
        out[key] = rc.get(key)
    if "pause" in data:
        pause = data["pause"]
        out["pause.drain_s"] = pause.get("drain_s")
        out["pause.drain_poll_period_s"] = pause.get("drain_poll_period_s")
    if data.get("feeder_release_lines") is not None:
        out["feeder release lines"] = data["feeder_release_lines"]
    return out
