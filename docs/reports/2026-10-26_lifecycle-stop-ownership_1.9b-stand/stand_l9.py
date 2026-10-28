# -*- coding: utf-8 -*-
# ruff: noqa: E501  (русские docstring/строки плана длиннее 120)
"""stand_l9.py - живой стенд Task 1.9b (lifecycle-stop-ownership): сценарии S1-S5 и контроль.

Печатает числа, а не прилагательные. Бэкенд ведёт только через backend_ctl (сокет ProcessManager, BACKEND_CTL=1):
тот же router-путь, что у GUI. Без psutil, без GUI, без qt-mcp.

Запуск (в окне стенда):
    bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" \
        heavy inspector-bottles-90 \
        <корень main>/.venv/Scripts/python.exe <этот файл> --scenario all --out <каталог>
    PYTHONPATH=<корень worktree>, PYTHONUTF8=1 ставит оболочка запуска (скрипт ставит PYTHONPATH детям сам).
Без бэкенда: ``--help``, ``--dry-run``.

Вердикты: PASS / FAIL против порогов «ПОСЛЕ» из plans/lifecycle-stop-ownership/tasks/T1.9b_tests.md («Стенд»),
пороги - литералы в ``THRESHOLDS``. Зависание - FAIL с затраченным временем (дефект старого скрипта: ``verdict: OK``
у зависших). Нет ответа, нет сигнала доставки, не поднялась предпосылка (медленный ребёнок не добавлен, роботы не
подключились) - тоже FAIL, с пометкой ``invalid``.

Часы: интервалы - ``time.monotonic()`` одного процесса (отправка и приход в reader-потоке сокета);
сравнение со строками логов - ``time.time()`` против штампа строки (мс, местное время).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import socket
import statistics
import subprocess  # nosec B404 — стенд: запускает бэкенд, git и tasklist с литеральными аргументами
import sys
import threading
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

# --------------------------------------------------------------------------------------------------------------
# Пороги «ПОСЛЕ» (литералы из T1.9b_tests.md, «Стенд») и «ДО» для контроля. Не выводятся из кода под проверкой.
# --------------------------------------------------------------------------------------------------------------
THRESHOLDS: dict[str, dict[str, Any]] = {
    "S1": {"reply_min_s": 0.85, "reply_max_s": 1.20, "hang_s": 4.5, "max_hangs": 0, "max_lost": 0},
    "S2": {"max_latency_s": 0.5, "p99_s": 0.150, "min_samples_per_stop": 20, "min_stop_reply_s": 2.5},
    "S3": {"max_delivery_s": 0.5, "max_relay_reply_s": 0.5, "min_stop_reply_s": 2.5},
    "S4": {"max_shutdown_line_s": 1.2, "max_pm_exit_s": 4.5, "max_dns": 0},
    "S5": {"max_restart_s": 5.0, "max_tree_exit_s": 2.0, "max_activate_s": 5.0, "shutdown_runs": 10},
    # T1.10: медленный стоп 6,0 с при окне 5,0 с -> terminate; ответ с окном (5,0-5,3 с), 3 из 3.
    "S6": {"outcome": "terminated", "success": True, "reply_min_s": 5.0, "reply_max_s": 5.3, "pass_runs": 3},
    # T1.11: стоп 6,0 с, окно ребёнка 10,0 (stop_window_s), потолок 12,0, окно PM 5,0 -> slow выходит сам; ответ 6,0-6,6 с.
    "S7": {"outcome": "exited", "success": True, "reply_min_s": 6.0, "reply_max_s": 6.6, "pass_runs": 3},
    # Контроль S7 (--s7-control): тот же стенд без ключа stop_window_s -> поведение T1.10 (terminate по окну PM 5,0 с).
    # Не приёмка, а различитель: exited здесь = стенд не различает, S7 не засчитывать.
    "S7_control": {"outcome": "terminated", "success": True, "reply_min_s": 5.0, "reply_max_s": 5.3, "pass_runs": 1},
}
#: Нижние границы «ДО» (main/И1): контроль обязан их вернуть, иначе стенд не различает.
CONTROL_FLOORS: dict[str, float] = {"S2_max_latency_s": 2.0, "S3_delivery_s": 2.0, "S4_shutdown_line_s": 3.0}

REPEATS = {"S1": 10, "S2": 10, "S3": 10, "S4": 5, "S5": 10, "S6": 3, "S7": 3}
STOP_PROCESS_TIMEOUT_S = 8.0
SHUTDOWN_TIMEOUT_S = 8.0


def stop_windows(default_windows: bool) -> dict[str, Any]:
    """Окна остановки прогона: ``override`` (8,0/8,0 - под медленного ребёнка 3,0 с, S1-S5 и R2-A/R2-B) или ``default`` (R2-C,
    исходный метод Task 1.1: ни ``stop_process_timeout`` в orchestrator_config, ни ``stop_timeout`` во временном system.yaml -
    значения кода и system.yaml дерева). Пишется в JSON каждого сеанса."""
    if default_windows:
        return {"mode": "default", "stop_process_timeout": None, "shutdown_timeout": None}
    return {
        "mode": "override",
        "stop_process_timeout": STOP_PROCESS_TIMEOUT_S,
        "shutdown_timeout": SHUTDOWN_TIMEOUT_S,
    }


SLOW = "slow"
FAST = "fast"
SLOW_CLASS = "stand_slow_child.SlowChild"
S6_SLOW_CLASS = "stand_slow_child.S6SlowChild"
S6_SLOW_STOP_S = 6.0  # --s6-slow-stop-s: хук остановки slow в S6
S6_WINDOW_S = 5.0  # --s6-window-s: stop_process_timeout в S6
S7_SLOW_STOP_S = 6.0  # --s7-slow-stop-s: хук остановки slow (S6SlowChild) в S7
S7_WINDOW_S = 10.0  # --s7-window-s: ключ stop_window_s в записи slow
S7_CEILING_S = 12.0  # --s7-ceiling-s: max_stop_window_s в orchestrator_config PM
S7_PM_WINDOW_S = 5.0  # stop_process_timeout в S7: окно PM как в S6 (ключ ребёнка его перекрывает)
FAST_CLASS = "stand_slow_child.FastChild"
WAIT_RELAY_AT_S = 1.0  # S3/S4: момент действия после отправки process.stop slow
SAMPLE_PERIOD_S = 0.1  # S2
DEFAULT_REPO_RECIPE = "multiprocess_prototype/recipes/region_pipeline.yaml"


# --------------------------------------------------------------------------------------------------------------
# Чистая часть: статистика, разбор логов, вердикты (юнит-тест: test_stand_l9_verdict.py)
# --------------------------------------------------------------------------------------------------------------
def percentile_nearest_rank(values: list[float], p: float) -> float | None:
    """Перцентиль по ближайшему рангу: ``sorted[ceil(p/100*n)-1]``; пусто -> None."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100.0 * len(ordered)))
    return ordered[rank - 1]


def stats(values: list[float | None]) -> dict[str, Any]:
    """min/median/max/p99 по ответившим; ``unanswered`` - число None (оно же зависание)."""
    got = [float(v) for v in values if v is not None]
    return {
        "n": len(values),
        "unanswered": len(values) - len(got),
        "min": min(got) if got else None,
        "median": statistics.median(got) if got else None,
        "max": max(got) if got else None,
        "p99": percentile_nearest_rank(got, 99.0),
    }


def is_hung(reply_s: float | None, status: str | None = None, lost: int = 0, hang_s: float = 4.5) -> bool:
    """Зависание S1 (правило из stand_report L-9): нет ответа, ответ >= hang_s, статус crashed или lost > 0."""
    if reply_s is None or reply_s >= hang_s:
        return True
    return status == "crashed" or lost > 0


_LOG_LINE = re.compile(r"^#\d+ (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) \[(\w+)\] (.*)$")
_NEEDLES = {
    "dns": "did not stop in",
    "lost": "not reported/lost",
    "terminating": "terminating",
    "survived": ("всё ещё жив после kill", "ВЫЖИЛИ"),
}
_SHUTDOWN_LINE = "System shutdown requested"


def parse_log_ts(text: str) -> float:
    """``2026-08-26 08:40:42,349`` (местное время) -> epoch."""
    return dt.datetime.strptime(text, "%Y-%m-%d %H:%M:%S,%f").timestamp()


def scan_log_texts(texts: dict[str, str]) -> dict[str, Any]:
    """Подсчёт строк по набору ``{относительный путь: текст}``.

    Одна запись журнала лежит в нескольких файлах (messages.log и system.log) - считаем уникальные
    ``(штамп, сообщение)``. ``shutdown_ts`` - самая ранняя строка ``System shutdown requested``.
    """
    seen: set[tuple[str, str]] = set()
    counts = {"dns": 0, "lost": 0, "terminating": 0, "survived": 0}
    dns_by_dir: dict[str, int] = {}
    shutdown_ts: float | None = None
    for path, text in texts.items():
        for raw in text.splitlines():
            m = _LOG_LINE.match(raw.strip())
            if not m:
                continue
            stamp, _level, message = m.groups()
            key = (stamp, message)
            if key in seen:
                continue
            seen.add(key)
            for name, needle in _NEEDLES.items():
                needles = needle if isinstance(needle, tuple) else (needle,)
                if any(n in message for n in needles):
                    counts[name] += 1
                    if name == "dns":
                        top = path.replace("\\", "/").split("/")[0]
                        dns_by_dir[top] = dns_by_dir.get(top, 0) + 1
            if _SHUTDOWN_LINE in message:
                ts = parse_log_ts(stamp)
                shutdown_ts = ts if shutdown_ts is None else min(shutdown_ts, ts)
    return {**counts, "dns_by_dir": dns_by_dir, "shutdown_ts": shutdown_ts}


def scan_log_dir(root: Path) -> dict[str, Any]:
    texts: dict[str, str] = {}
    if root.exists():
        for p in sorted(root.rglob("*.log")):
            try:
                texts[str(p.relative_to(root))] = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return scan_log_texts(texts)


def _verdict(reasons: list[str], invalid: bool = False) -> dict[str, Any]:
    return {"verdict": "FAIL" if reasons else "PASS", "reasons": reasons, "invalid": bool(invalid and reasons)}


def judge_s1(runs: list[dict[str, Any]], th: dict[str, float | int] | None = None) -> dict[str, Any]:
    """S1: 0 зависаний из N, ответ в [0,85; 1,20] с, ``not reported/lost`` = 0. Прогон: reply_s, status, lost, ok."""
    th = th or THRESHOLDS["S1"]
    reasons: list[str] = []
    invalid = False
    hangs = 0
    for i, r in enumerate(runs, 1):
        if not r.get("precondition_ok", True):
            reasons.append(f"r{i}: предпосылка не выполнена ({r.get('precondition_note', '')})")
            invalid = True
            continue
        if is_hung(r.get("reply_s"), r.get("status"), int(r.get("lost", 0)), float(th["hang_s"])):
            hangs += 1
            elapsed = r.get("reply_s")
            reasons.append(
                f"r{i}: ЗАВИСАНИЕ reply_s={'нет ответа' if elapsed is None else elapsed} "
                f"status={r.get('status')} lost={r.get('lost', 0)}"
            )
            continue
        rs = float(r["reply_s"])
        if not float(th["reply_min_s"]) <= rs <= float(th["reply_max_s"]):
            reasons.append(f"r{i}: reply_s={rs} вне [{th['reply_min_s']}; {th['reply_max_s']}]")
    if hangs > int(th["max_hangs"]):
        reasons.append(f"зависаний {hangs} из {len(runs)} (порог {th['max_hangs']})")
    if len(runs) != REPEATS["S1"] and not runs:
        reasons.append("нет ни одного прогона")
    # T1.10: outcome стопа - наблюдение, на вердикт не влияет (прогноз лида: exited 10 из 10).
    return {
        **_verdict(reasons, invalid),
        "hangs": hangs,
        "stats": stats([r.get("reply_s") for r in runs]),
        "outcomes": outcome_counts(runs),
    }


def outcome_counts(runs: list[dict[str, Any]]) -> dict[str, int]:
    """Счёт ``outcome`` из ответов стопа: ``{"exited": n, ...}``; нет ответа или ключа - ``"<нет>"``."""
    counts: dict[str, int] = {}
    for r in runs:
        key = str(_outcome_of(r.get("reply")))
        counts[key] = counts.get(key, 0) + 1
    return counts


def judge_s6(runs: list[dict[str, Any]], th: dict[str, Any] | None = None) -> dict[str, Any]:
    """S6 (T1.10): ``process.stop slow`` (стоп 6,0 с, окно 5,0 с): ``outcome == terminated``, ``success is True``,
    ответ 5,0-5,3 с; все прогоны (полный прогон - 3 из 3). Прогон: reply_s (None = нет ответа), reply (dict)."""
    th = th or THRESHOLDS["S6"]
    reasons: list[str] = []
    invalid = False
    if not runs:
        return {**_verdict(["нет ни одного прогона"], True), "stats": stats([]), "outcomes": {}}
    passed = 0
    for i, r in enumerate(runs, 1):
        if not r.get("precondition_ok", True):
            reasons.append(f"r{i}: предпосылка не выполнена ({r.get('precondition_note', '')})")
            invalid = True
            continue
        rs = r.get("reply_s")
        reply = r.get("reply")
        if rs is None or not isinstance(reply, dict):
            reasons.append(f"r{i}: нет ответа reply_s={rs} reply={reply}")
            continue
        bad: list[str] = []
        if reply.get("outcome") != th["outcome"]:
            bad.append(f"outcome={reply.get('outcome')!r} != {th['outcome']!r}")
        if reply.get("success") is not th["success"]:
            bad.append(f"success={reply.get('success')!r}")
        if not float(th["reply_min_s"]) <= float(rs) <= float(th["reply_max_s"]):
            bad.append(f"reply_s={rs} вне [{th['reply_min_s']}; {th['reply_max_s']}]")
        if bad:
            reasons.append(f"r{i}: " + "; ".join(bad))
        else:
            passed += 1
    if passed != len(runs):
        reasons.append(
            f"прошло {passed} из {len(runs)} (нужны все; полный прогон {th['pass_runs']} из {th['pass_runs']})"
        )
    return {
        **_verdict(reasons, invalid),
        "stats": stats([r.get("reply_s") for r in runs]),
        "outcomes": outcome_counts(runs),
    }


def judge_s7(runs: list[dict[str, Any]], th: dict[str, Any] | None = None) -> dict[str, Any]:
    """S7 (T1.11): ``process.stop slow`` (стоп 6,0 с, окно ребёнка 10,0 с, потолок 12,0 с): ``outcome == exited``,
    ``success is True``, ответ 6,0-6,6 с; 3 из 3. Проверка та же, что у S6 (``judge_s6``), другие литералы порогов."""
    return judge_s6(runs, th or THRESHOLDS["S7"])


def judge_s7_control(runs: list[dict[str, Any]], th: dict[str, Any] | None = None) -> dict[str, Any]:
    """Контроль S7 (``--s7-control``): тот же стенд без ключа ``stop_window_s``: ожидается поведение T1.10
    (``terminated``, ответ 5,0-5,3 с). ``distinguishes`` False - стенд не различает; ``exited`` без ключа = S7 не засчитывать."""
    res = judge_s6(runs, th or THRESHOLDS["S7_control"])
    distinguishes = res["verdict"] == "PASS"
    reasons = list(res["reasons"])
    if res["outcomes"].get("exited"):
        reasons.append("контроль дал exited без ключа stop_window_s: стенд не различает, S7 не засчитывать")
    return {**res, "reasons": reasons, "distinguishes": distinguishes}


def judge_s2(runs: list[dict[str, Any]], th: dict[str, float | int] | None = None) -> dict[str, Any]:
    """S2: каждый ответ ``supervision.status`` во время стопа <= 0,5 с, p99 <= 150 мс.

    Прогон: stop_reply_s (None = зависание), latencies (None = без ответа), stop_success.
    Предпосылки: стоп действительно длился (>= 2,5 с) и снято >= 20 проб на стоп.
    """
    th = th or THRESHOLDS["S2"]
    reasons: list[str] = []
    invalid = False
    flat: list[float | None] = []
    hangs = 0
    for i, r in enumerate(runs, 1):
        lat = list(r.get("latencies") or [])
        flat.extend(lat)
        sr = r.get("stop_reply_s")
        if sr is None:
            hangs += 1
            reasons.append(f"стоп {i}: ЗАВИСАНИЕ, ответа на process.stop нет за {r.get('waited_s')} с")
            invalid = True
            continue
        if sr < float(th["min_stop_reply_s"]):
            reasons.append(f"стоп {i}: stop_reply_s={sr} < {th['min_stop_reply_s']} - медленный стоп не воспроизведён")
            invalid = True
        if len(lat) < int(th["min_samples_per_stop"]):
            reasons.append(f"стоп {i}: проб {len(lat)} < {th['min_samples_per_stop']}")
            invalid = True
    st = stats(flat)
    if st["unanswered"]:
        reasons.append(f"проб без ответа: {st['unanswered']}")
    if st["max"] is not None and st["max"] > float(th["max_latency_s"]):
        reasons.append(f"max ответа {st['max']:.3f} с > {th['max_latency_s']}")
    if st["p99"] is not None and st["p99"] > float(th["p99_s"]):
        reasons.append(f"p99 {st['p99']:.3f} с > {th['p99_s']}")
    if not flat:
        reasons.append("нет ни одной пробы")
        invalid = True
    return {**_verdict(reasons, invalid), "hangs": hangs, "stats": st}


def judge_s3(runs: list[dict[str, Any]], th: dict[str, float | int] | None = None) -> dict[str, Any]:
    """S3: доставка (ответ ``devices`` на внутреннее сообщение) и ответ relay <= 0,5 с. None = нет сигнала -> FAIL."""
    th = th or THRESHOLDS["S3"]
    reasons: list[str] = []
    invalid = False
    hangs = 0
    for i, r in enumerate(runs, 1):
        if r.get("stop_reply_s") is None:
            hangs += 1
            reasons.append(f"повтор {i}: ЗАВИСАНИЕ стопа slow, ответа нет за {r.get('waited_s')} с")
            invalid = True
        elif r["stop_reply_s"] < float(th["min_stop_reply_s"]):
            reasons.append(f"повтор {i}: stop_reply_s={r['stop_reply_s']} < {th['min_stop_reply_s']}")
            invalid = True
        d, rr = r.get("delivery_s"), r.get("relay_reply_s")
        if d is None:
            reasons.append(f"повтор {i}: сигнал доставки не пришёл (devices не ответил на внутреннее сообщение)")
        elif d > float(th["max_delivery_s"]):
            reasons.append(f"повтор {i}: доставка {d:.3f} с > {th['max_delivery_s']}")
        if rr is None:
            reasons.append(f"повтор {i}: ответа relay нет")
        elif rr > float(th["max_relay_reply_s"]):
            reasons.append(f"повтор {i}: ответ relay {rr:.3f} с > {th['max_relay_reply_s']}")
    return {
        **_verdict(reasons, invalid),
        "hangs": hangs,
        "delivery_stats": stats([r.get("delivery_s") for r in runs]),
        "relay_reply_stats": stats([r.get("relay_reply_s") for r in runs]),
    }


def judge_s4(runs: list[dict[str, Any]], th: dict[str, float | int] | None = None) -> dict[str, Any]:
    """S4: строка ``System shutdown requested`` на <= +1,2 с, выход PM <= +4,5 с, 0 ``did not stop in``,
    ждущий в очереди - ``system_stopping``. Времена - от отправки ``process.stop slow``."""
    th = th or THRESHOLDS["S4"]
    reasons: list[str] = []
    invalid = False
    hangs = 0
    for i, r in enumerate(runs, 1):
        if not r.get("precondition_ok", True):
            reasons.append(f"повтор {i}: предпосылка не выполнена ({r.get('precondition_note', '')})")
            invalid = True
            continue
        line, ex = r.get("shutdown_line_s"), r.get("pm_exit_s")
        if ex is None:
            hangs += 1
            reasons.append(f"повтор {i}: ЗАВИСАНИЕ, PM не вышел за {r.get('waited_s')} с")
        elif ex > float(th["max_pm_exit_s"]):
            reasons.append(f"повтор {i}: выход PM на +{ex:.2f} с > {th['max_pm_exit_s']}")
        if line is None:
            reasons.append(f"повтор {i}: строки 'System shutdown requested' нет в логах")
        elif line > float(th["max_shutdown_line_s"]):
            reasons.append(f"повтор {i}: строка на +{line:.2f} с > {th['max_shutdown_line_s']}")
        if int(r.get("dns", 0)) > int(th["max_dns"]):
            reasons.append(f"повтор {i}: 'did not stop in' x{r.get('dns')}")
        if r.get("queued_error") != "system_stopping":
            reasons.append(
                f"повтор {i}: ответ ждущего в очереди = {r.get('queued_error')!r}, ожидалось 'system_stopping'"
            )
    return {
        **_verdict(reasons, invalid),
        "hangs": hangs,
        "shutdown_line_stats": stats([r.get("shutdown_line_s") for r in runs]),
        "pm_exit_stats": stats([r.get("pm_exit_s") for r in runs]),
    }


def judge_s5(runs: list[dict[str, Any]], th: dict[str, float | int] | None = None) -> dict[str, Any]:
    """S5: рестарт < 5,0 с; выход дерева < 2,0 с в 10 из 10; ответ recipe.activate < 5,0 с (строгие неравенства).

    Запись: ``{kind: restart|activate|shutdown, elapsed_s: float|None, ok: bool, target?}``.
    """
    th = th or THRESHOLDS["S5"]
    reasons: list[str] = []
    limits = {
        "restart": float(th["max_restart_s"]),
        "activate": float(th["max_activate_s"]),
        "shutdown": float(th["max_tree_exit_s"]),
    }
    invalid = False
    hangs = 0
    for i, r in enumerate(runs, 1):
        kind = r.get("kind")
        if kind not in limits:
            reasons.append(f"запись {i}: неизвестный kind {kind!r}")
            continue
        el = r.get("elapsed_s")
        if el is None:
            hangs += 1
            reasons.append(f"{kind} #{i} ({r.get('target', '')}): ЗАВИСАНИЕ, нет результата за {r.get('waited_s')} с")
        elif not el < limits[kind]:
            reasons.append(f"{kind} #{i} ({r.get('target', '')}): {el:.2f} с >= {limits[kind]}")
        if kind != "shutdown" and not r.get("ok", True):
            reasons.append(f"{kind} #{i} ({r.get('target', '')}): команда не подтвердила успех ({r.get('note', '')})")
        if r.get("survivors"):
            reasons.append(f"{kind} #{i}: после выхода живы PID {r['survivors']}")
    n_shutdown = sum(1 for r in runs if r.get("kind") == "shutdown")
    if n_shutdown != int(th["shutdown_runs"]):
        reasons.append(f"выходов дерева измерено {n_shutdown}, нужно {th['shutdown_runs']}")
        invalid = True
    return {
        **_verdict(reasons, invalid),
        "hangs": hangs,
        "restart_stats": stats([r.get("elapsed_s") for r in runs if r.get("kind") == "restart"]),
        "activate_stats": stats([r.get("elapsed_s") for r in runs if r.get("kind") == "activate"]),
        "tree_exit_stats": stats([r.get("elapsed_s") for r in runs if r.get("kind") == "shutdown"]),
    }


def judge_control(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Контроль (патч И1): стенд различает, если S2-S4 на И1 дают FAIL по ПОСЛЕ и достигают нижних границ «ДО».

    ``rows`` - результаты ``judge_*`` + ключи ``max_latency_s`` (S2), ``max_delivery_s`` (S3),
    ``min_shutdown_line_s`` (S4), посчитанные по контрольным прогонам.
    """
    reasons: list[str] = []
    for key in ("S2", "S3", "S4"):
        if rows.get(key, {}).get("verdict") != "FAIL":
            reasons.append(
                f"{key}: на И1 вердикт {rows.get(key, {}).get('verdict')!r}, ожидался FAIL (иначе стенд не различает)"
            )
    s2 = rows.get("S2", {}).get("max_latency_s")
    s3 = rows.get("S3", {}).get("max_delivery_s")
    s4 = rows.get("S4", {}).get("min_shutdown_line_s")
    if s2 is None or s2 < CONTROL_FLOORS["S2_max_latency_s"]:
        reasons.append(f"S2: max ответа на И1 = {s2}, ожидалось >= {CONTROL_FLOORS['S2_max_latency_s']}")
    if s3 is None or s3 < CONTROL_FLOORS["S3_delivery_s"]:
        reasons.append(f"S3: доставка на И1 = {s3}, ожидалось >= {CONTROL_FLOORS['S3_delivery_s']}")
    if s4 is None or s4 < CONTROL_FLOORS["S4_shutdown_line_s"]:
        reasons.append(f"S4: строка shutdown на И1 = +{s4}, ожидалось >= +{CONTROL_FLOORS['S4_shutdown_line_s']}")
    return {"distinguishes": not reasons, "reasons": reasons}


# --------------------------------------------------------------------------------------------------------------
# Живая часть. Всё ниже требует бэкенда; в --dry-run и юнит-тесте не вызывается.
# --------------------------------------------------------------------------------------------------------------
class Pending:
    """Один асинхронный запрос: момент отправки, момент прихода (reader-поток сокета), ответ."""

    def __init__(self) -> None:
        self.ev = threading.Event()
        self.t_send = 0.0
        self.t_arr: float | None = None
        self.result: Any = None

    @property
    def answered(self) -> bool:
        r = self.result
        if self.t_arr is None or not isinstance(r, dict):
            return False
        return r.get("error") not in ("timeout", "connection lost", "connection closed", "dropped", "not connected")

    def latency(self) -> float | None:
        return round(self.t_arr - self.t_send, 4) if self.answered and self.t_arr is not None else None


def leaf(res: Any) -> dict[str, Any]:
    from backend_ctl.protocol import unwrap

    out = unwrap(res, leaf=True)
    return out if isinstance(out, dict) else {}


def send_async(drv: Any, msg: dict[str, Any], timeout: float) -> Pending:
    p = Pending()

    def cb(res: Any) -> None:
        p.t_arr = time.monotonic()
        p.result = res
        p.ev.set()

    p.t_send = time.monotonic()
    drv.request_async(msg, cb, timeout=timeout)
    return p


def pm_msg(cmd: str, args: dict[str, Any] | None, door: str) -> dict[str, Any]:
    """Команда PM: ``direct`` - прямая дверь (target ProcessManager), ``command`` - ``process.command`` (дверь GUI)."""
    from multiprocess_framework.modules.message_module import build_command_message, build_system_command_message

    args = dict(args or {})
    if door == "command":
        return build_system_command_message({"cmd": cmd, **args}, sender="backend_ctl", reply_to="ProcessManager")
    return build_command_message("ProcessManager", cmd, args, sender="backend_ctl", reply_to="ProcessManager")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pids_alive(pids: list[int]) -> list[int]:
    """Какие из PID ещё есть в таблице процессов (``tasklist``, без psutil)."""
    if not pids:
        return []
    if sys.platform != "win32":
        alive = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except OSError:
                pass
        return alive
    # Вывод tasklist - в OEM-кодировке консоли (имена процессов бывают не-UTF-8): читаем байты, декодируем с заменой.
    raw = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, timeout=20).stdout  # nosec B603 B607 — литеральные аргументы, внешнего ввода нет
    out = raw.decode("utf-8", errors="replace")
    present = set()
    for line in out.splitlines():
        parts = [x.strip('"') for x in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            present.add(int(parts[1]))
    return [p for p in pids if p in present]


def kill_pids(pids: list[int]) -> None:
    for pid in pids:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=20)  # nosec B603 B607 — PID из supervision.status, аргументы литеральные
        else:
            try:
                os.kill(pid, 9)
            except OSError:
                pass


class Backend:
    """Бэкенд стенда: свой каталог запуска, временный манифест и system.yaml, свой порт; запуск и уборка."""

    def __init__(self, ctx: "Ctx", tag: str) -> None:
        self.ctx = ctx
        self.tag = tag
        self.workdir = ctx.out / "runs" / tag
        self.log_root = self.workdir / "logs"
        self.port = free_port()
        self.proc: subprocess.Popen | None = None
        self.drv: Any = None
        self.boot_s: float | None = None
        self.stdout_path = self.workdir / "backend.stdout.log"
        self.windows = stop_windows(bool(getattr(ctx, "default_windows", False)))
        self.stop_window_s = STOP_PROCESS_TIMEOUT_S  # S6 ставит своё (--s6-window-s) до start()
        self.slow_stop_s: float | None = None  # S6: STAND_S6_SLOW_STOP_S для S6SlowChild
        self.ceiling_s: float | None = None  # S7: STAND_MAX_STOP_WINDOW -> orchestrator_config.max_stop_window_s
        self.ceiling_seen: bool | None = None  # None - потолок не задан; иначе строка [stand] найдена в stdout

    # ---- конфиги этого запуска (закоммиченные файлы не трогаются) ----
    def _write_configs(self) -> Path:
        import yaml

        repo = self.ctx.root
        src_manifest = repo / "multiprocess_prototype" / "app.yaml"
        raw = yaml.safe_load(src_manifest.read_text(encoding="utf-8")) or {}
        base_dir = src_manifest.parent

        def absolutize(value: str) -> str:
            p = Path(value)
            return str(p if p.is_absolute() else (base_dir / p).resolve())

        sys_raw = yaml.safe_load(Path(absolutize(raw["system"])).read_text(encoding="utf-8")) or {}
        if self.windows["mode"] == "override":
            sys_raw.setdefault("system", {})["stop_timeout"] = (
                SHUTDOWN_TIMEOUT_S  # -> shutdown_timeout PM (spawner.py:90-92)
            )
        else:  # default: stop_timeout остаётся значением system.yaml дерева; запоминаем его в JSON
            self.windows["system_yaml_stop_timeout"] = (sys_raw.get("system") or {}).get("stop_timeout")
        sys_raw["system"]["log_dir"] = str(self.log_root)
        sys_raw.setdefault("backend_ctl", {}).update({"enabled": True, "port": self.port, "host": "127.0.0.1"})
        sys_path = self.workdir / "system.yaml"
        sys_path.write_text(yaml.safe_dump(sys_raw, allow_unicode=True, sort_keys=False), encoding="utf-8")

        raw["system"] = str(sys_path)
        raw["recipes"] = absolutize(raw["recipes"])
        raw["pipeline"] = str((repo / self.ctx.recipe).resolve())
        if isinstance(raw.get("styles"), dict) and raw["styles"].get("dir"):
            raw["styles"]["dir"] = absolutize(raw["styles"]["dir"])
        base = raw.get("base")
        if isinstance(base, str):
            raw["base"] = absolutize(base)
        elif isinstance(base, list):
            raw["base"] = [absolutize(x) for x in base]
        if raw.get("presentation"):
            raw["presentation"] = absolutize(raw["presentation"])
        manifest = self.workdir / "app.yaml"
        manifest.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return manifest

    def start(self) -> Any:
        from backend_ctl.driver import BackendDriver

        self.workdir.mkdir(parents=True, exist_ok=True)
        (self.workdir / "data").mkdir(exist_ok=True)  # registry_path data/devices.yaml - относительно cwd запуска
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
            }
        )
        if self.windows["mode"] == "override":
            env["STAND_STOP_PROCESS_TIMEOUT"] = str(self.stop_window_s)
            self.windows["stop_process_timeout"] = self.stop_window_s
        else:
            env.pop("STAND_STOP_PROCESS_TIMEOUT", None)  # R2-C: без подмены orchestrator_config
        if self.slow_stop_s is not None:
            env["STAND_S6_SLOW_STOP_S"] = str(self.slow_stop_s)
        if self.ceiling_s is not None:
            env["STAND_MAX_STOP_WINDOW"] = str(self.ceiling_s)
        else:
            env.pop("STAND_MAX_STOP_WINDOW", None)  # S1-S6: без потолка, чужой env не просачивается
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        t0 = time.monotonic()
        out = open(self.stdout_path, "wb")
        self.proc = subprocess.Popen(  # nosec B603 — свой python и свой скрипт стенда
            [self.ctx.python, str(HERE / "stand_backend.py")],
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
                raise RuntimeError(f"бэкенд завершился при старте, код {self.proc.returncode}; см. {self.stdout_path}")
            try:
                drv.connect()
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError(f"сокет backend_ctl не открылся за {self.ctx.boot_timeout_s} с")
                time.sleep(0.25)
        while time.monotonic() < deadline:
            snap = self.supervision(drv)
            if snap.get("devices", {}).get("alive"):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("devices не стал alive за срок старта")
        self.boot_s = round(time.monotonic() - t0, 2)
        self.drv = drv
        text = self.stdout_path.read_text(encoding="utf-8", errors="replace")
        self.override_seen = f"stop_process_timeout={self.stop_window_s}" in text
        self.windows["override_line_in_stdout"] = self.override_seen  # default: обязано быть False
        if self.ceiling_s is not None:
            self.ceiling_seen = f"orchestrator_config.max_stop_window_s={self.ceiling_s}" in text
            self.windows["max_stop_window_s"] = self.ceiling_s
            self.windows["ceiling_line_in_stdout"] = self.ceiling_seen
        return drv

    @staticmethod
    def supervision(drv: Any, name: str | None = None) -> dict[str, Any]:
        try:
            res = leaf(drv.supervision_status(name, timeout=5.0))
        except Exception:  # noqa: BLE001 - опрос готовности терпит моргание
            return {}
        procs = res.get("processes")
        return procs if isinstance(procs, dict) else {}

    def stop(self) -> None:
        """Погасить: system.shutdown, ждать выход; не вышел - kill дерева по PID (без psutil)."""
        if self.drv is not None:
            try:
                self.drv.system_shutdown(wait=False)
            except Exception:  # noqa: BLE001
                pass
            try:
                self.drv.close()
            except Exception:  # noqa: BLE001
                pass
            self.drv = None
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.wait(30)
            except subprocess.TimeoutExpired:
                kill_pids([self.proc.pid])
                self.proc.wait(10)

    def kill(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            kill_pids([self.proc.pid])


class Ctx:
    """Параметры прогона."""

    def __init__(self, args: argparse.Namespace, root: Path, out: Path) -> None:
        self.root = root
        self.out = out
        self.python = args.python
        self.recipe = args.recipe
        self.door = args.door
        self.boot_timeout_s = args.boot_timeout
        self.quick = args.quick
        self.default_windows = False  # R2-C: исходные окна остановки (без override 8,0)
        self.round2 = False  # R2-B: выход PM через WaitForSingleObject
        self.s6_slow_stop_s = float(getattr(args, "s6_slow_stop_s", S6_SLOW_STOP_S))
        self.s6_window_s = float(getattr(args, "s6_window_s", S6_WINDOW_S))
        self.s7_slow_stop_s = float(getattr(args, "s7_slow_stop_s", S7_SLOW_STOP_S))
        self.s7_window_s = float(getattr(args, "s7_window_s", S7_WINDOW_S))
        self.s7_ceiling_s = float(getattr(args, "s7_ceiling_s", S7_CEILING_S))
        self.s7_pm_window_s = S7_PM_WINDOW_S
        self.s7_control = bool(getattr(args, "s7_control", False))  # S7 без ключа stop_window_s, 1 повтор
        self.n = {k: (1 if args.quick else v) for k, v in REPEATS.items()}
        if self.s7_control:
            self.n["S7"] = 1


def write_run(ctx: Ctx, scenario: str, idx: int, data: dict[str, Any]) -> None:
    d = ctx.out / "json"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{scenario}_r{idx}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def revive(drv: Any, name: str, door: str, deadline_s: float = 45.0) -> dict[str, Any]:
    """Поднять ребёнка, если он мёртв (``process.restart`` мёртвого = старт), и дождаться ``alive``."""
    snap = Backend.supervision(drv, name).get(name, {})
    if snap.get("alive"):
        return snap
    p = send_async(drv, pm_msg("process.restart", {"process_name": name}, door), 60.0)
    p.ev.wait(60.0)
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        snap = Backend.supervision(drv, name).get(name, {})
        if snap.get("alive"):
            time.sleep(1.0)  # ребёнок успел открыть читателей очередей
            return snap
        time.sleep(0.25)
    raise RuntimeError(f"{name} не стал alive за {deadline_s} с")


def add_slow_fast(
    drv: Any, backend: Backend, slow_class: str = SLOW_CLASS, slow_extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Добавить ``slow`` и ``fast`` через ``topology.apply`` (с предварительным ``topology.diff``).

    ``slow_extra`` (S7): дополнительные ключи записи ``slow`` (``stop_window_s``); по умолчанию запись как в S1-S6.

    Что остаётся от рецепта: на первом ``topology.apply`` PM сносит все non-protected процессы
    (``process_manager_process.py:3988``: на boot ``_current_topology`` = None), protected (devices, gui) живут.
    Предохранитель: diff не должен трогать protected-процессы.
    """
    desired = {
        "name": "stand_l9",
        "processes": [
            {"process_name": SLOW, "process_class": slow_class, **(slow_extra or {})},
            {"process_name": FAST, "process_class": FAST_CLASS},
        ],
        "wires": [],
    }
    # Гонка старта (найдена в окне 10:14): движок топологии PM конфигурируется позже, чем devices становится alive.
    # Ждём, пока topology.diff начнёт отвечать успехом, а не "not configured".
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
        raise RuntimeError(f"topology.apply slow/fast не удался: {res}")
    for name in (SLOW, FAST):
        end = time.monotonic() + 45.0
        while time.monotonic() < end and not Backend.supervision(drv, name).get(name, {}).get("alive"):
            time.sleep(0.25)
        if not Backend.supervision(drv, name).get(name, {}).get("alive"):
            raise RuntimeError(f"{name} не alive после topology.apply")
    time.sleep(1.0)
    return {
        "apply_s": round(time.monotonic() - t0, 2),
        "diff_commands": sorted(str(x) for x in touched),
        "ready": res.get("ready"),
    }


# ---- S1 ---------------------------------------------------------------------------------------------------------
class Sims:
    """Два симулятора робота v2 в процессе стенда (TCP на свободных портах), как ``E2eRig``."""

    def __init__(self) -> None:
        self.servers: list[Any] = []
        self.ports: list[int] = []

    def start(self, n: int = 2) -> None:
        from Services.robot_comm.core.registers import ROBOT_UNIT_ID
        from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2
        from Services.robot_comm.server.sim_robot import SimRobotServer

        for _ in range(n):
            port = free_port()
            server = SimRobotServer("127.0.0.1", port, ROBOT_UNIT_ID, core=RobotSimCoreV2())
            server.start()
            self.servers.append(server)
            self.ports.append(port)
        self.unit = ROBOT_UNIT_ID

    def stop(self) -> None:
        for s in self.servers:
            try:
                s.stop()
            except Exception:  # noqa: BLE001
                pass


def connect_robots(drv: Any, sims: Sims, deadline_s: float = 25.0) -> tuple[bool, str]:
    for i, port in enumerate(sims.ports, 1):
        did = f"r{i}"
        up = leaf(
            drv.send_command(
                "devices",
                "device_upsert",
                {
                    "id": did,
                    "name": did,
                    "kind": "robot",
                    "protocol": "delta_v2",
                    "transport": {"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": sims.unit},
                },
                timeout=15.0,
            )
        )
        if up.get("status") != "ok":
            return False, f"device_upsert {did}: {up}"
        con = leaf(drv.send_command("devices", "device_connect", {"device_id": did}, timeout=15.0))
        if con.get("status") != "ok":
            return False, f"device_connect {did}: {con}"
    end = time.monotonic() + deadline_s
    pending = {f"r{i}" for i in range(1, len(sims.ports) + 1)}
    while pending and time.monotonic() < end:
        for did in sorted(pending):
            v = leaf(
                drv.send_command("ProcessManager", "state.get", {"path": f"devices.state.{did}.conn"}, timeout=5.0)
            )
            val = v.get("value")
            if v.get("status") == "ok" and isinstance(val, dict) and val.get("conn") == "connected":
                pending.discard(did)
        time.sleep(0.1)
    return (not pending), ("" if not pending else f"не connected: {sorted(pending)}")


def run_s1(ctx: Ctx) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    sims = Sims()
    sims.start(2)
    try:
        for i in range(1, ctx.n["S1"] + 1):
            be = Backend(ctx, f"s1_r{i}")
            rec: dict[str, Any] = {"run": i, "precondition_ok": False}
            try:
                drv = be.start()
                rec["boot_s"] = be.boot_s
                rec["override_seen"] = be.override_seen
                ok, note = connect_robots(drv, sims)
                rec["precondition_ok"], rec["precondition_note"] = ok, note
                if ok:
                    p = send_async(drv, pm_msg("process.stop", {"process_name": "devices"}, ctx.door), 20.0)
                    p.ev.wait(20.0)
                    rec["reply_s"] = p.latency()
                    rec["reply"] = p.result
                    rec["waited_s"] = round(time.monotonic() - p.t_send, 2)
                    time.sleep(3.0)
                    rec["status"] = (Backend.supervision(drv, "devices").get("devices") or {}).get("status")
            except Exception as exc:  # noqa: BLE001
                rec["error"] = repr(exc)
                rec["precondition_note"] = rec.get("precondition_note") or repr(exc)
            finally:
                be.stop()
            logs = scan_log_dir(be.log_root)
            rec.update({"lost": logs["lost"], "dns": logs["dns"], "dns_by_dir": logs["dns_by_dir"]})
            rec["hung"] = (
                is_hung(rec.get("reply_s"), rec.get("status"), rec["lost"]) if rec["precondition_ok"] else None
            )
            write_run(ctx, "S1", i, rec)
            runs.append(rec)
            print(
                f"[S1 r{i}] reply_s={rec.get('reply_s')} outcome={_outcome_of(rec.get('reply'))} status={rec.get('status')} "
                f"lost={rec['lost']} dns={rec['dns']} hung={rec['hung']}",
                flush=True,
            )
    finally:
        sims.stop()
    return runs


def _outcome_of(reply: Any) -> Any:
    """``outcome`` ответа стопа: S1 хранит весь конверт ``command.response`` (итог в ``result``), S6 - уже ``leaf``."""
    if not isinstance(reply, dict):
        return "<нет>"
    body = reply["result"] if isinstance(reply.get("result"), dict) else reply
    return body.get("outcome", "<нет>")


def run_s6(ctx: Ctx) -> list[dict[str, Any]]:
    """S6 (T1.10): свежий бэкенд на каждый повтор (как S1/S4/S5) - повтор не наследует ни запись stop_outcome, ни поток
    исполнителя предыдущего; цена - загрузка бэкенда на повтор."""
    runs: list[dict[str, Any]] = []
    for i in range(1, ctx.n["S6"] + 1):
        be = Backend(ctx, f"s6_r{i}")
        be.stop_window_s = ctx.s6_window_s
        be.slow_stop_s = ctx.s6_slow_stop_s
        rec: dict[str, Any] = {
            "run": i,
            "precondition_ok": False,
            "slow_stop_s": ctx.s6_slow_stop_s,
            "window_s": ctx.s6_window_s,
        }
        try:
            drv = be.start()
            rec["boot_s"] = be.boot_s
            rec["override_seen"] = be.override_seen
            rec["windows"] = be.windows
            rec["apply"] = add_slow_fast(drv, be, S6_SLOW_CLASS)
            rec["precondition_ok"] = bool(be.override_seen)
            if not be.override_seen:
                rec["precondition_note"] = "подмена stop_process_timeout не сработала (нет строки [stand] в stdout)"
            else:
                wait_s = ctx.s6_slow_stop_s + 30.0
                p = send_async(drv, pm_msg("process.stop", {"process_name": SLOW}, ctx.door), wait_s)
                p.ev.wait(wait_s)
                rec["reply_s"] = p.latency()
                rec["reply"] = leaf(p.result) if p.result is not None else None
                rec["reply_raw"] = p.result
                rec["waited_s"] = round(time.monotonic() - p.t_send, 2)
                rec["supervision_stop_outcome"] = (Backend.supervision(drv, SLOW).get(SLOW) or {}).get("stop_outcome")
        except Exception as exc:  # noqa: BLE001
            rec["error"] = repr(exc)
            rec["precondition_note"] = rec.get("precondition_note") or repr(exc)
        finally:
            be.stop()
        logs = scan_log_dir(be.log_root)
        rec.update({"lost": logs["lost"], "dns": logs["dns"], "dns_by_dir": logs["dns_by_dir"]})
        write_run(ctx, "S6", i, rec)
        runs.append(rec)
        print(
            f"[S6 r{i}] reply_s={rec.get('reply_s')} reply={rec.get('reply')} "
            f"supervision.stop_outcome={rec.get('supervision_stop_outcome')} dns={rec['dns']}",
            flush=True,
        )
    return runs


def run_s7(ctx: Ctx) -> list[dict[str, Any]]:
    """S7 (T1.11): окно стопа на ребёнка. Как S6 (свежий бэкенд на повтор, slow=S6SlowChild со стопом 6,0 с, окно PM 5,0 с),
    но запись ``slow`` в ``topology.apply`` несёт ``stop_window_s`` (10,0 с), а PM получает потолок ``max_stop_window_s``
    (12,0 с). Контроль (``ctx.s7_control``): ключа в записи нет, потолок тот же, 1 повтор."""
    scenario = "S7_control" if ctx.s7_control else "S7"
    runs: list[dict[str, Any]] = []
    for i in range(1, ctx.n["S7"] + 1):
        be = Backend(ctx, f"s7c_r{i}" if ctx.s7_control else f"s7_r{i}")
        be.stop_window_s = ctx.s7_pm_window_s
        be.slow_stop_s = ctx.s7_slow_stop_s
        be.ceiling_s = ctx.s7_ceiling_s
        slow_extra = None if ctx.s7_control else {"stop_window_s": ctx.s7_window_s}
        rec: dict[str, Any] = {
            "run": i,
            "precondition_ok": False,
            "control": ctx.s7_control,
            "slow_stop_s": ctx.s7_slow_stop_s,
            "pm_window_s": ctx.s7_pm_window_s,
            "child_window_s": None if ctx.s7_control else ctx.s7_window_s,
            "ceiling_s": ctx.s7_ceiling_s,
        }
        try:
            drv = be.start()
            rec["boot_s"] = be.boot_s
            rec["override_seen"] = be.override_seen
            rec["ceiling_seen"] = be.ceiling_seen
            rec["windows"] = be.windows
            rec["apply"] = add_slow_fast(drv, be, S6_SLOW_CLASS, slow_extra)
            rec["precondition_ok"] = bool(be.override_seen and be.ceiling_seen)
            if not rec["precondition_ok"]:
                rec["precondition_note"] = (
                    "подмена orchestrator_config не сработала (нет строки [stand] в stdout): "
                    f"stop_process_timeout={be.override_seen}, max_stop_window_s={be.ceiling_seen}"
                )
            else:
                wait_s = ctx.s7_slow_stop_s + 30.0
                p = send_async(drv, pm_msg("process.stop", {"process_name": SLOW}, ctx.door), wait_s)
                p.ev.wait(wait_s)
                rec["reply_s"] = p.latency()
                rec["reply"] = leaf(p.result) if p.result is not None else None
                rec["reply_raw"] = p.result
                rec["waited_s"] = round(time.monotonic() - p.t_send, 2)
                rec["supervision_stop_outcome"] = (Backend.supervision(drv, SLOW).get(SLOW) or {}).get("stop_outcome")
        except Exception as exc:  # noqa: BLE001
            rec["error"] = repr(exc)
            rec["precondition_note"] = rec.get("precondition_note") or repr(exc)
        finally:
            be.stop()
        logs = scan_log_dir(be.log_root)
        rec.update({"lost": logs["lost"], "dns": logs["dns"], "dns_by_dir": logs["dns_by_dir"]})
        write_run(ctx, scenario, i, rec)
        runs.append(rec)
        print(
            f"[{scenario} r{i}] reply_s={rec.get('reply_s')} reply={rec.get('reply')} "
            f"supervision.stop_outcome={rec.get('supervision_stop_outcome')} dns={rec['dns']}",
            flush=True,
        )
    return runs


# ---- S2 / S3 (один бэкенд на оба сценария) ------------------------------------------------------------------------
def run_s2_once(drv: Any, ctx: Ctx, idx: int) -> dict[str, Any]:
    revive(drv, SLOW, ctx.door)
    samples: list[Pending] = []
    halt = threading.Event()

    def sampler() -> None:
        while not halt.is_set():
            samples.append(send_async(drv, pm_msg("supervision.status", {}, "direct"), 5.0))
            halt.wait(SAMPLE_PERIOD_S)

    th = threading.Thread(target=sampler, name="s2-sampler", daemon=True)
    th.start()
    time.sleep(0.5)
    stop_p = send_async(drv, pm_msg("process.stop", {"process_name": SLOW}, ctx.door), 25.0)
    stop_p.ev.wait(25.0)
    time.sleep(0.3)
    halt.set()
    th.join(2.0)
    for p in samples:
        p.ev.wait(max(0.0, 6.0 - (time.monotonic() - p.t_send)))
    stop_end = stop_p.t_arr if stop_p.t_arr is not None else time.monotonic()
    during = [p for p in samples if stop_p.t_send <= p.t_send <= stop_end]
    lat = [p.latency() for p in during]
    rec = {
        "stop": idx,
        "stop_reply_s": stop_p.latency(),
        "waited_s": round(stop_end - stop_p.t_send, 2),
        "stop_reply": stop_p.result,
        "latencies": lat,
        "n_samples": len(during),
        "n_samples_total": len(samples),
        "stats": stats(lat),
    }
    write_run(ctx, "S2", idx, rec)
    s = rec["stats"]
    print(
        f"[S2 #{idx}] stop_reply_s={rec['stop_reply_s']} samples={rec['n_samples']} "
        f"max={s['max']} p99={s['p99']} unanswered={s['unanswered']}",
        flush=True,
    )
    return rec


def run_s3_once(drv: Any, ctx: Ctx, idx: int) -> dict[str, Any]:
    from multiprocess_framework.modules.message_module import build_command_message

    revive(drv, SLOW, ctx.door)
    # Сигнал доставки - ПОБОЧНЫЙ ЭФФЕКТ у получателя, а не ответ: ответ на request_id, которого PM не регистрировал,
    # до клиента не доезжает (окно 10:16/10:19, два quick: delivery_s=None при reply_to=PM и при адресе сессии).
    # Внутреннее сообщение - device_upsert записи-пустышки в реестр devices; доставка = момент, когда прямой
    # device_list от клиента впервые её показал (опрос без пауз, шаг - один оборот сокета).
    probe_id = f"relay_probe_{idx}"
    inner = build_command_message(
        "devices",
        "device_upsert",
        {
            "id": probe_id,
            "name": probe_id,
            "kind": "robot",
            "protocol": "delta_v2",
            "transport": {"type": "tcp", "host": "127.0.0.1", "port": 1, "unit_id": 2},
        },
        sender="backend_ctl",
    )
    stop_p = send_async(drv, pm_msg("process.stop", {"process_name": SLOW}, ctx.door), 25.0)
    while time.monotonic() - stop_p.t_send < WAIT_RELAY_AT_S:
        time.sleep(0.005)
    relay_p = send_async(
        drv, pm_msg("process.relay", {"target_process": "devices", "inner_message": inner}, "direct"), 15.0
    )
    delivered: float | None = None
    end = relay_p.t_send + 8.0
    while delivered is None and time.monotonic() < end:
        listing = drv.send_command("devices", "device_list", {}, timeout=3.0)
        if probe_id in json.dumps(listing, ensure_ascii=False, default=str):
            delivered = time.monotonic()
    relay_p.ev.wait(15.0)
    stop_p.ev.wait(25.0)
    if delivered is not None:
        drv.send_command("devices", "device_remove", {"id": probe_id, "device_id": probe_id}, timeout=5.0)
    rec = {
        "repeat": idx,
        "stop_reply_s": stop_p.latency(),
        "waited_s": round((stop_p.t_arr or time.monotonic()) - stop_p.t_send, 2),
        "relay_sent_at_s": round(relay_p.t_send - stop_p.t_send, 3),
        "relay_reply_s": relay_p.latency(),
        "relay_reply": relay_p.result,
        "delivery_s": round(delivered - relay_p.t_send, 4) if delivered is not None else None,
        "relay_inside_stop": stop_p.t_arr is None or relay_p.t_arr is None or relay_p.t_arr <= stop_p.t_arr,
    }
    write_run(ctx, "S3", idx, rec)
    print(
        f"[S3 #{idx}] relay_at=+{rec['relay_sent_at_s']} reply_s={rec['relay_reply_s']} "
        f"delivery_s={rec['delivery_s']} stop_reply_s={rec['stop_reply_s']}",
        flush=True,
    )
    return rec


def run_s23(ctx: Ctx, want: set[str]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"S2": [], "S3": []}
    be = Backend(ctx, "s23")
    try:
        drv = be.start()
        setup = add_slow_fast(drv, be)
        write_run(ctx, "setup", 23, {"boot_s": be.boot_s, "override_seen": be.override_seen, **setup})
        if "S2" in want:
            for i in range(1, ctx.n["S2"] + 1):
                out["S2"].append(run_s2_once(drv, ctx, i))
        if "S3" in want:
            for i in range(1, ctx.n["S3"] + 1):
                out["S3"].append(run_s3_once(drv, ctx, i))
    finally:
        be.stop()
    return out


# ---- S4 ---------------------------------------------------------------------------------------------------------
def run_s4_once(ctx: Ctx, idx: int) -> dict[str, Any]:
    be = Backend(ctx, f"s4_r{idx}")
    rec: dict[str, Any] = {"run": idx, "precondition_ok": False}
    try:
        drv = be.start()
        rec["boot_s"], rec["override_seen"] = be.boot_s, be.override_seen
        rec["windows"] = be.windows
        rec["setup"] = add_slow_fast(drv, be)
        revive(drv, SLOW, ctx.door)
        revive(drv, FAST, ctx.door)
        rec["precondition_ok"] = True
        pm_pid = None
        try:
            from backend_ctl.protocol import _find_payload

            got = _find_payload(drv.introspect_status("ProcessManager", timeout=5.0), "pid", "process").get("pid")
            pm_pid = got if isinstance(got, int) else None
        except Exception:  # noqa: BLE001 - нет PID PM: pm_exit_s будет равен выходу лаунчера
            pm_pid = None
        exit_box: dict[str, Any] = {}
        if ctx.round2:
            # Раунд 2: выход PM по дескриптору (OpenProcess+WaitForSingleObject), без tasklist в замере.
            if pm_pid is not None:
                watch_pid_exit(pm_pid, exit_box, "pm")
            proc_ref = be.proc
            threading.Thread(
                target=lambda: (proc_ref.wait(60), exit_box.__setitem__("launcher", time.monotonic())),
                daemon=True,
                name="s4-launcher-wait",
            ).start()
        t0_wall = time.time()
        stop_p = send_async(drv, pm_msg("process.stop", {"process_name": SLOW}, ctx.door), 25.0)
        time.sleep(0.1)
        queued_p = send_async(drv, pm_msg("process.restart", {"process_name": FAST}, ctx.door), 25.0)
        while time.monotonic() - stop_p.t_send < WAIT_RELAY_AT_S:
            time.sleep(0.005)
        sd_p = send_async(drv, pm_msg("system.shutdown", {"mode": "graceful"}, "command"), 15.0)
        rec["shutdown_sent_at_s"] = round(sd_p.t_send - stop_p.t_send, 3)
        wait_limit = 40.0
        end = stop_p.t_send + wait_limit
        pm_gone_t: float | None = None
        next_probe = 0.0
        while be.proc.poll() is None and time.monotonic() < end:
            now_t = time.monotonic()
            if not ctx.round2 and pm_pid is not None and pm_gone_t is None and now_t >= next_probe:
                next_probe = now_t + 0.25
                if not pids_alive([pm_pid]):
                    pm_gone_t = time.monotonic()
            time.sleep(0.02)
        t_exit = time.monotonic()
        exited = be.proc.poll() is not None
        # pm_exit_s - выход процесса ProcessManager (по PID, шаг опроса 0,25 с); launcher_exit_s - выход лаунчера
        # (он дольше PM на уборку). Нет PID PM - pm_exit_s = выход лаунчера.
        rec["launcher_exit_s"] = round(t_exit - stop_p.t_send, 3) if exited else None
        if ctx.round2:
            end_w = time.monotonic() + 5.0
            while time.monotonic() < end_w and ("pm" not in exit_box or "launcher" not in exit_box):
                time.sleep(0.01)
            rec["pm_exit_s"] = round(exit_box["pm"] - stop_p.t_send, 3) if "pm" in exit_box else None
            rec["launcher_exit_s"] = round(exit_box["launcher"] - stop_p.t_send, 3) if "launcher" in exit_box else None
            t_tl = time.monotonic()
            pids_alive([pm_pid] if pm_pid else [])
            rec["tasklist_call_s"] = round(time.monotonic() - t_tl, 3)
            rec["exit_probe"] = "WaitForSingleObject"
        elif pm_gone_t is not None:
            rec["pm_exit_s"] = round(pm_gone_t - stop_p.t_send, 3)
        else:
            rec["pm_exit_s"] = rec["launcher_exit_s"]
        rec["pm_pid"] = pm_pid
        rec["waited_s"] = round(t_exit - stop_p.t_send, 2)
        rec["shutdown_reply_s"] = sd_p.latency()
        rec["stop_slow_reply_s"] = stop_p.latency()
        rec["stop_slow_reply"] = stop_p.result
        q = leaf(queued_p.result) if queued_p.answered else {}
        rec["queued_reply_s"] = queued_p.latency()
        rec["queued_error"] = q.get("error") if queued_p.answered else None
        rec["queued_reply"] = queued_p.result
        rec["t0_wall"] = t0_wall
    except Exception as exc:  # noqa: BLE001
        rec["error"] = repr(exc)
        rec["precondition_note"] = repr(exc)
    finally:
        be.kill() if rec.get("pm_exit_s") is None else None
        be.stop()
    logs = scan_log_dir(be.log_root)
    rec.update(
        {
            "dns": logs["dns"],
            "dns_by_dir": logs["dns_by_dir"],
            "lost": logs["lost"],
            "terminating": logs["terminating"],
            "survived": logs["survived"],
        }
    )
    ts = logs["shutdown_ts"]
    rec["shutdown_line_s"] = round(ts - rec["t0_wall"], 3) if ts is not None and "t0_wall" in rec else None
    write_run(ctx, "S4", idx, rec)
    print(
        f"[S4 #{idx}] line=+{rec.get('shutdown_line_s')} pm_exit=+{rec.get('pm_exit_s')} "
        f"dns={rec['dns']} queued={rec.get('queued_error')!r}",
        flush=True,
    )
    return rec


def run_s4(ctx: Ctx) -> list[dict[str, Any]]:
    return [run_s4_once(ctx, i) for i in range(1, ctx.n["S4"] + 1)]


# ---- S5 ---------------------------------------------------------------------------------------------------------
def run_s5(ctx: Ctx, restart_targets: list[str]) -> list[dict[str, Any]]:
    """10 прогонов с нуля: system.shutdown без slow, замер выхода дерева; в прогоне 1 - рестарты и recipe.activate."""
    from backend_ctl.protocol import unwrap  # noqa: F401  (проверка доступности до старта)

    recs: list[dict[str, Any]] = []
    for i in range(1, ctx.n["S5"] + 1):
        be = Backend(ctx, f"s5_r{i}")
        try:
            drv = be.start()
            if i == 1:
                snap0 = Backend.supervision(drv)
                for target in restart_targets:
                    name, subst = target, False
                    if name not in snap0:
                        cands = [
                            n
                            for n, v in snap0.items()
                            if n not in ("devices", "gui", "ProcessManager") and v.get("alive")
                        ]
                        if not cands:
                            recs.append(
                                {
                                    "kind": "restart",
                                    "target": target,
                                    "elapsed_s": None,
                                    "ok": False,
                                    "note": "нет подходящего процесса",
                                    "waited_s": 0,
                                }
                            )
                            continue
                        name, subst = cands[0], True
                    for rep in (1, 2, 3):
                        t0 = time.monotonic()
                        res = drv.process_restart_verified(name, wait=30.0, timeout=30.0)
                        el = round(time.monotonic() - t0, 3)
                        recs.append(
                            {
                                "kind": "restart",
                                "target": f"{name}{' (вместо ' + target + ')' if subst else ''} #{rep}",
                                "elapsed_s": el,
                                "ok": bool(res.get("restarted")),
                                "note": res.get("reason", ""),
                                "waited_s": el,
                            }
                        )
                        print(f"[S5 restart {name} #{rep}] {el}s restarted={res.get('restarted')}", flush=True)
                p = send_async(drv, pm_msg("recipe.activate", {"name": Path(ctx.recipe).stem}, "direct"), 60.0)
                p.ev.wait(60.0)
                res_l = leaf(p.result)
                recs.append(
                    {
                        "kind": "activate",
                        "target": Path(ctx.recipe).stem,
                        "elapsed_s": p.latency(),
                        "ok": res_l.get("success") is True,
                        "note": str(res_l.get("error", "")),
                        "waited_s": round((p.t_arr or time.monotonic()) - p.t_send, 2),
                    }
                )
                print(f"[S5 recipe.activate] {p.latency()}s success={res_l.get('success')}", flush=True)
                time.sleep(2.0)
            snap = Backend.supervision(drv)
            pids = [v.get("pid") for v in snap.values() if isinstance(v.get("pid"), int)]
            try:
                from backend_ctl.protocol import _find_payload

                pm_pid = _find_payload(drv.introspect_status("ProcessManager", timeout=5.0), "pid", "process").get(
                    "pid"
                )
                if isinstance(pm_pid, int):
                    pids.append(pm_pid)
            except Exception:  # noqa: BLE001
                pass
            sd = send_async(drv, pm_msg("system.shutdown", {"mode": "graceful"}, "command"), 15.0)
            tree_gone: float | None = None
            end = sd.t_send + 30.0
            while time.monotonic() < end:
                if be.proc.poll() is not None:
                    left = pids_alive(pids)
                    if not left:
                        tree_gone = time.monotonic()
                        break
                    time.sleep(0.1)
                else:
                    time.sleep(0.02)
            survivors = pids_alive(pids) if tree_gone is None else []
            rec = {
                "kind": "shutdown",
                "target": f"run {i}",
                "elapsed_s": round(tree_gone - sd.t_send, 3) if tree_gone else None,
                "waited_s": round(time.monotonic() - sd.t_send, 2),
                "survivors": survivors,
                "n_pids": len(pids),
            }
            if survivors:
                kill_pids(survivors)
            recs.append(rec)
            print(
                f"[S5 shutdown run {i}] tree_exit_s={rec['elapsed_s']} pids={len(pids)} survivors={survivors}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            recs.append(
                {
                    "kind": "shutdown",
                    "target": f"run {i}",
                    "elapsed_s": None,
                    "waited_s": 0,
                    "note": repr(exc),
                    "survivors": [],
                }
            )
        finally:
            be.kill() if be.proc and be.proc.poll() is None and not recs[-1].get("elapsed_s") else None
            be.stop()
    for j, r in enumerate(recs, 1):
        write_run(ctx, "S5", j, r)
    return recs


# ---- контроль (И1) ----------------------------------------------------------------------------------------------
def git(root: Path, *a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, timeout=60)  # nosec B603 B607 — git с литеральными аргументами


class PatchedTree:
    """Контрольное дерево с патчем: ``git apply`` на входе, ``git apply -R`` и ``git diff --quiet`` на выходе."""

    def __init__(self, root: Path, patch: Path) -> None:
        self.root, self.patch = root, patch
        self.clean_after: bool | None = None

    def __enter__(self) -> "PatchedTree":
        if git(self.root, "diff", "--quiet").returncode != 0:
            raise RuntimeError(f"контрольное дерево {self.root} не чистое до патча")
        chk = git(self.root, "apply", "--check", str(self.patch))
        if chk.returncode != 0:
            raise RuntimeError(f"git apply --check: {chk.stderr.strip()}")
        ap = git(self.root, "apply", str(self.patch))
        if ap.returncode != 0:
            raise RuntimeError(f"git apply: {ap.stderr.strip()}")
        return self

    def __exit__(self, *exc: Any) -> None:
        rv = git(self.root, "apply", "-R", str(self.patch))
        self.clean_after = rv.returncode == 0 and git(self.root, "diff", "--quiet").returncode == 0
        if not self.clean_after:
            print(f"[control] ВНИМАНИЕ: дерево {self.root} не чистое после отката И1: {rv.stderr.strip()}", flush=True)


# --------------------------------------------------------------------------------------------------------------
# Раунд 2 (--round2): методика стенда по вердикту investigator (docs/reviews/2026-10-26_task-1.9b-stand-investigator.md)
#   R2-A  рестарт camera_0 и devices x3: ветка и main строго по очереди A/B/A/B, ответ против строки PM «restarted»;
#   R2-B  S4 x5 на ветке: выход PM через OpenProcess+WaitForSingleObject, без tasklist в замере;
#   R2-C  выход дерева исходным методом Task 1.1: полная загрузка + 2,0 с, метрика = выход процесса PM,
#         по 10 на ветке и на main строго по очереди; порог «< 2,0 с 10 из 10» - литерал, не ослаблен.
# Чистая часть (judge_*, check_alternation, scan_restarted_lines, pair_restart_records) - в юнит-тесте.
# --------------------------------------------------------------------------------------------------------------
R2_THRESHOLDS: dict[str, float | int] = {"max_restart_s": 5.0, "max_tree_exit_s": 2.0, "tree_runs_per_tree": 10}
R2_SESSIONS_PER_TREE = 3  # рестарт A/B: сеансов бэкенда на дерево (в каждом camera_0 x3 и devices x3)
R2_TREE_RECIPE = "multiprocess_prototype/backend/topology/inspection_full.yaml"  # как test_system_shutdown_live.py:42
R2_TARGETS = ("camera_0", "devices")
R2_REPS = 3
R2_TREE_WARMUP_S = 2.0  # после полной загрузки (test_system_shutdown_live.py:70)
EARLY_REPLY_TOL_S = 0.05  # допуск штампа лога (мс) и дрейфа часов: ответ раньше `restarted` больше чем на это = ранний
DEFAULT_MAIN_ROOT = "D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles"
_RESTARTED = re.compile(r"Process '([^']+)' restarted")


def check_alternation(order: list[str], trees: tuple[str, str] = ("branch", "main")) -> list[str]:
    """Строгое чередование A/B/A/B одиночными прогонами (не блоками) и равное число прогонов; пусто = порядок верный."""
    reasons: list[str] = []
    a, b = trees
    unknown = sorted({t for t in order if t not in trees})
    if unknown:
        reasons.append(f"неизвестные деревья в порядке: {unknown}")
    if order.count(a) != order.count(b):
        reasons.append(f"прогонов не поровну: {a}={order.count(a)}, {b}={order.count(b)}")
    for i in range(1, len(order)):
        if order[i] == order[i - 1]:
            reasons.append(f"не чередуется: прогоны {i} и {i + 1} оба {order[i]!r} (блок, а не A/B/A/B)")
            break
    return reasons


def scan_restarted_lines(text: str) -> dict[str, list[float]]:
    """Строки PM ``Process '<имя>' restarted`` -> ``{имя: [epoch, ...]}`` по возрастанию (уникальные по штампу и тексту)."""
    seen: set[tuple[str, str]] = set()
    out: dict[str, list[float]] = {}
    for raw in text.splitlines():
        m = _LOG_LINE.match(raw.strip())
        if not m:
            continue
        stamp, _level, message = m.groups()
        hit = _RESTARTED.search(message)
        if not hit or (stamp, message) in seen:
            continue
        seen.add((stamp, message))
        out.setdefault(hit.group(1), []).append(parse_log_ts(stamp))
    return {k: sorted(v) for k, v in out.items()}


def pair_restart_records(sent: list[dict[str, Any]], restarted: dict[str, list[float]]) -> list[dict[str, Any]]:
    """К каждому ``process.restart`` (``target``, ``t_send_wall``, ``t_reply_wall``) - первая строка PM ``restarted`` этого
    процесса не раньше отправки (минус допуск); ``reply_minus_restarted_s`` = ответ - строка; ``early`` = ответ раньше строки
    больше чем на ``EARLY_REPLY_TOL_S``. Нет строки - ``restarted_ts`` None, ``early`` None (нечем сравнить)."""
    used: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for rec in sent:
        rec = dict(rec)
        target = str(rec.get("target"))
        lines = restarted.get(target, [])
        ts = None
        for j in range(used.get(target, 0), len(lines)):
            if lines[j] >= float(rec["t_send_wall"]) - EARLY_REPLY_TOL_S:
                ts = lines[j]
                used[target] = j + 1
                break
        rec["restarted_ts"] = ts
        if ts is None or rec.get("t_reply_wall") is None or rec.get("request_error"):
            # request_error (timeout драйвера) - возврат без ответа PM: «раньше restarted» к нему не относится
            rec["reply_minus_restarted_s"] = None
            rec["early"] = None
        else:
            diff = float(rec["t_reply_wall"]) - ts
            rec["reply_minus_restarted_s"] = round(diff, 3)
            rec["early"] = diff < -EARLY_REPLY_TOL_S
        out.append(rec)
    return out


def judge_restart_ab(
    recs: list[dict[str, Any]], order: list[str], th: dict[str, float | int] | None = None
) -> dict[str, Any]:
    """R2-A. ``recs``: ``{tree, session, target, rep, elapsed_s, ok, request_error, early, ...}``; ``order`` - дерево каждого
    сеанса по порядку. FAIL: нарушено чередование/равенство; ранний ответ; ответ драйвера ``timeout``; рестарт не подтверждён;
    ветка не уложилась в ``max_restart_s`` строго (main - база, порог к нему не применяется, числа печатаются)."""
    th = th or R2_THRESHOLDS
    reasons = [f"порядок: {r}" for r in check_alternation(order)]
    for r in recs:
        who = f"{r.get('tree')} s{r.get('session')} {r.get('target')} #{r.get('rep')}"
        if r.get("request_error"):
            reasons.append(f"{who}: запрос драйвера завершился {r['request_error']!r} (не ответ PM)")
        if r.get("early") is True:
            reasons.append(f"{who}: ОТВЕТ РАНЬШЕ строки PM restarted на {-r['reply_minus_restarted_s']:.3f} с")
        if not r.get("ok", False):
            reasons.append(f"{who}: рестарт не подтверждён ({r.get('note', '')})")
        el = r.get("elapsed_s")
        if r.get("tree") == "branch":
            if el is None:
                reasons.append(f"{who}: ЗАВИСАНИЕ, нет результата")
            elif not el < float(th["max_restart_s"]):
                reasons.append(f"{who}: {el:.2f} с >= {th['max_restart_s']}")
    spread: dict[str, dict[str, Any]] = {}
    for tree in ("branch", "main"):
        for target in sorted({str(r.get("target")) for r in recs}):
            vals = [r.get("elapsed_s") for r in recs if r.get("tree") == tree and r.get("target") == target]
            spread[f"{tree}/{target}"] = stats(vals)
    return {
        **_verdict(reasons),
        "spread": spread,
        "unpaired": sum(1 for r in recs if r.get("early") is None),
        "n_early": sum(1 for r in recs if r.get("early") is True),
    }


def judge_tree_exit_ab(
    recs: list[dict[str, Any]], order: list[str], th: dict[str, float | int] | None = None
) -> dict[str, Any]:
    """R2-C. ``recs``: ``{tree, run, pm_exit_s}``; метрика = выход процесса PM от отправки ``system.shutdown``. Порог
    ``< max_tree_exit_s`` строго, по ``tree_runs_per_tree`` прогонов на КАЖДОМ дереве (и на main тоже - литерал)."""
    th = th or R2_THRESHOLDS
    reasons = [f"порядок: {r}" for r in check_alternation(order)]
    invalid = False
    spread: dict[str, dict[str, Any]] = {}
    for tree in ("branch", "main"):
        mine = [r for r in recs if r.get("tree") == tree]
        spread[tree] = stats([r.get("pm_exit_s") for r in mine])
        if len(mine) != int(th["tree_runs_per_tree"]):
            reasons.append(f"{tree}: прогонов {len(mine)}, нужно {th['tree_runs_per_tree']}")
            invalid = True
        for r in mine:
            el = r.get("pm_exit_s")
            if el is None:
                reasons.append(f"{tree} run {r.get('run')}: ЗАВИСАНИЕ, PM не вышел")
            elif not el < float(th["max_tree_exit_s"]):
                reasons.append(f"{tree} run {r.get('run')}: {el:.3f} с >= {th['max_tree_exit_s']}")
    return {**_verdict(reasons, invalid), "spread": spread}


# ---- живая часть раунда 2 ----------------------------------------------------------------------------------------
def watch_pid_exit(pid: int, box: dict[str, Any], key: str, limit_s: float = 60.0) -> threading.Thread:
    """Daemon-поток: ``box[key]`` = ``time.monotonic()`` выхода процесса ``pid`` (Windows: ``OpenProcess(SYNCHRONIZE)`` +
    ``WaitForSingleObject``, без tasklist). Процесса уже нет к открытию - ``box[key+'_already_gone']``. Не вышел за ``limit_s`` -
    ключ не ставится."""

    def run() -> None:
        if sys.platform != "win32":
            end = time.monotonic() + limit_s
            while time.monotonic() < end:
                try:
                    os.kill(pid, 0)
                except OSError:
                    box[key] = time.monotonic()
                    return
                time.sleep(0.01)
            return
        import ctypes

        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = k32.OpenProcess(0x00100000, 0, pid)  # SYNCHRONIZE
        if not handle:
            box[key + "_already_gone"] = True
            box[key] = time.monotonic()
            return
        try:
            if k32.WaitForSingleObject(handle, int(limit_s * 1000)) == 0:  # WAIT_OBJECT_0
                box[key] = time.monotonic()
        finally:
            k32.CloseHandle(handle)

    th = threading.Thread(target=run, daemon=True, name=f"exit-watch-{key}-{pid}")
    th.start()
    return th


def pm_pid_of(drv: Any) -> int | None:
    try:
        from backend_ctl.protocol import _find_payload

        got = _find_payload(drv.introspect_status("ProcessManager", timeout=5.0), "pid", "process").get("pid")
        return got if isinstance(got, int) else None
    except Exception:  # noqa: BLE001
        return None


def wait_full_boot(be: "Backend", timeout_s: float = 120.0) -> float:
    """Полная загрузка: в логе PM строка ``CommandManager 'ProcessManager' registration summary`` (investigator, шаг 1).
    Возврат - секунды ожидания; не дождались - RuntimeError."""
    t0 = time.monotonic()
    needle = "CommandManager 'ProcessManager' registration summary"
    pm_dir = be.log_root / "ProcessManager"
    while time.monotonic() - t0 < timeout_s:
        for p in pm_dir.glob("*.log") if pm_dir.exists() else []:
            try:
                if needle in p.read_text(encoding="utf-8", errors="replace"):
                    return round(time.monotonic() - t0, 2)
            except OSError:
                continue
        time.sleep(0.25)
    raise RuntimeError(f"строка PM 'registration summary' не появилась за {timeout_s} с")


def _tree_ctx(ctx: "Ctx", root: Path, recipe: str | None = None) -> "Ctx":
    import copy

    other = copy.copy(ctx)
    other.root = root
    if recipe is not None:
        other.recipe = recipe
    return other


def _restart_session(ctx: "Ctx", tree: str, session: int, seq: int) -> list[dict[str, Any]]:
    """Один сеанс R2-A: свежий бэкенд, полная загрузка, camera_0 x3 и devices x3 через ``process_restart_verified``.

    Запрос драйвера оборачивается (``drv.request``): момент отправки/возврата и ``error`` ответа (``timeout`` = собственное
    окно драйвера, не ответ PM). Возврат ``request()`` - пробуждение события reader-потока, расхождение с приходом - мс.
    """
    be = Backend(ctx, f"r2a_{tree}_{session}")
    sent: list[dict[str, Any]] = []
    try:
        drv = be.start()
        full_boot_s = wait_full_boot(be)
        original = drv.request
        current: dict[str, Any] = {}

        def spy(message: dict[str, Any], timeout: float | None = None) -> Any:
            data = message.get("data") if isinstance(message, dict) else None
            is_restart = isinstance(data, dict) and data.get("cmd") == "process.restart"
            t_send, t_send_wall = time.monotonic(), time.time()
            res = original(message, timeout=timeout)
            if is_restart:
                failed = isinstance(res, dict) and res.get("success") is False
                current.update(
                    {
                        "t_send_wall": t_send_wall,
                        "t_reply_wall": time.time(),
                        "request_s": round(time.monotonic() - t_send, 3),
                        "request_error": res.get("error") if failed else None,
                        "request_reply": res,
                    }
                )
            return res

        drv.request = spy  # type: ignore[method-assign]
        for target in R2_TARGETS:
            for rep in range(1, R2_REPS + 1):
                current.clear()
                res = drv.process_restart_verified(target, wait=30.0, timeout=30.0)
                sent.append(
                    {
                        "tree": tree,
                        "seq": seq,
                        "session": session,
                        "target": target,
                        "rep": rep,
                        "elapsed_s": res.get("elapsed"),
                        "ok": bool(res.get("restarted")),
                        "note": res.get("reason", ""),
                        "full_boot_wait_s": full_boot_s,
                        "windows": be.windows,
                        "res": res,
                        **current,
                    }
                )
                print(
                    f"[R2-A {tree} s{session} {target} #{rep}] elapsed={res.get('elapsed')} "
                    f"restarted={res.get('restarted')} request_s={current.get('request_s')} "
                    f"err={current.get('request_error')}",
                    flush=True,
                )
    except Exception as exc:  # noqa: BLE001
        sent.append(
            {
                "tree": tree,
                "seq": seq,
                "session": session,
                "target": "-",
                "rep": 0,
                "elapsed_s": None,
                "ok": False,
                "note": repr(exc),
                "t_send_wall": time.time(),
                "t_reply_wall": None,
            }
        )
    finally:
        be.stop()
    restarted: dict[str, list[float]] = {}
    pm_dir = be.log_root / "ProcessManager"
    if pm_dir.exists():
        text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sorted(pm_dir.glob("*.log")))
        restarted = scan_restarted_lines(text)
    paired = pair_restart_records([r for r in sent if r.get("target") != "-"], restarted)
    return paired + [r for r in sent if r.get("target") == "-"]


def run_r2_restart(ctx: "Ctx", main_root: Path, sessions: int) -> dict[str, Any]:
    ctxs = {"branch": ctx, "main": _tree_ctx(ctx, main_root)}
    order: list[str] = []
    recs: list[dict[str, Any]] = []
    for s in range(1, sessions + 1):
        for tree in ("branch", "main"):  # строго по одному: A, B, A, B
            order.append(tree)
            recs += _restart_session(ctxs[tree], tree, s, len(order))
    for j, r in enumerate(recs, 1):
        write_run(ctx, "R2A", j, r)
    return {"recs": recs, "order": order, "verdict": judge_restart_ab(recs, order)}


def _tree_exit_once(ctx: "Ctx", tree: str, run: int, seq: int) -> dict[str, Any]:
    """Один выход дерева методом Task 1.1: полная загрузка + 2,0 с, ``system.shutdown``, метрика = выход процесса PM."""
    be = Backend(ctx, f"r2c_{tree}_{run}")
    rec: dict[str, Any] = {"tree": tree, "run": run, "seq": seq, "pm_exit_s": None, "windows": be.windows}
    try:
        drv = be.start()
        rec["full_boot_wait_s"] = wait_full_boot(be)
        time.sleep(R2_TREE_WARMUP_S)
        pm_pid = pm_pid_of(drv)
        rec["pm_pid"] = pm_pid
        box: dict[str, Any] = {}
        if pm_pid is not None:
            watch_pid_exit(pm_pid, box, "pm")
        proc = be.proc
        assert proc is not None

        def wait_launcher() -> None:
            try:
                proc.wait(60)
                box["launcher"] = time.monotonic()
            except subprocess.TimeoutExpired:
                pass

        threading.Thread(target=wait_launcher, daemon=True, name="launcher-wait").start()
        sd = send_async(drv, pm_msg("system.shutdown", {"mode": "graceful"}, "command"), 15.0)
        end = sd.t_send + 40.0
        while time.monotonic() < end and ("pm" not in box or "launcher" not in box):
            time.sleep(0.01)
        rec["shutdown_reply_s"] = sd.latency()
        rec["pm_exit_s"] = round(box["pm"] - sd.t_send, 3) if "pm" in box else None
        rec["launcher_exit_s"] = round(box["launcher"] - sd.t_send, 3) if "launcher" in box else None
        rec["pm_already_gone_at_open"] = bool(box.get("pm_already_gone"))
        t0 = time.monotonic()
        pids_alive([pm_pid] if pm_pid else [])
        rec["tasklist_call_s"] = round(time.monotonic() - t0, 3)
    except Exception as exc:  # noqa: BLE001
        rec["error"] = repr(exc)
    finally:
        if be.proc is not None and be.proc.poll() is None and rec.get("pm_exit_s") is None:
            be.kill()
        be.stop()
    print(
        f"[R2-C {tree} #{run}] pm_exit_s={rec.get('pm_exit_s')} launcher_exit_s={rec.get('launcher_exit_s')} "
        f"tasklist_call_s={rec.get('tasklist_call_s')}",
        flush=True,
    )
    return rec


def run_r2_tree_exit(ctx: "Ctx", main_root: Path, runs: int) -> dict[str, Any]:
    ctxs = {"branch": _tree_ctx(ctx, ctx.root, R2_TREE_RECIPE), "main": _tree_ctx(ctx, main_root, R2_TREE_RECIPE)}
    for c in ctxs.values():
        c.default_windows = True  # R2-C: исходный метод Task 1.1 идёт на окнах по умолчанию
    order: list[str] = []
    recs: list[dict[str, Any]] = []
    for i in range(1, runs + 1):
        for tree in ("branch", "main"):
            order.append(tree)
            recs.append(_tree_exit_once(ctxs[tree], tree, i, len(order)))
    for j, r in enumerate(recs, 1):
        write_run(ctx, "R2C", j, r)
    th = dict(R2_THRESHOLDS)
    th["tree_runs_per_tree"] = runs
    return {"recs": recs, "order": order, "verdict": judge_tree_exit_ab(recs, order, th)}


def run_round2(args: argparse.Namespace, root: Path, out: Path) -> int:
    ctx = Ctx(args, root, out)
    ctx.round2 = False
    main_root = Path(args.main_root).resolve()
    parts = {p.strip() for p in args.round2_parts.split(",") if p.strip()}
    quick = args.quick
    started = time.time()
    summary: dict[str, Any] = {
        "mode": "round2",
        "branch_root": str(root),
        "main_root": str(main_root),
        "parts": sorted(parts),
        "thresholds": R2_THRESHOLDS,
        "started": started,
    }
    ok = True
    if "restart" in parts:
        r = run_r2_restart(ctx, main_root, 1 if quick else R2_SESSIONS_PER_TREE)
        summary["R2A"] = {"order": r["order"], "verdict": r["verdict"]}
        ok &= r["verdict"]["verdict"] == "PASS"
    if "s4" in parts:
        s4ctx = _tree_ctx(ctx, root)
        s4ctx.round2 = True
        runs = run_s4(s4ctx)
        summary["R2B"] = {"verdict": judge_s4(runs)}
        ok &= summary["R2B"]["verdict"]["verdict"] == "PASS"
    if "tree" in parts:
        r = run_r2_tree_exit(ctx, main_root, 1 if quick else int(R2_THRESHOLDS["tree_runs_per_tree"]))
        summary["R2C"] = {"order": r["order"], "verdict": r["verdict"]}
        ok &= r["verdict"]["verdict"] == "PASS"
    summary["elapsed_s"] = round(time.time() - started, 1)
    (out / "round2_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    lines = ["## Раунд 2", ""]
    for key in ("R2A", "R2B", "R2C"):
        if key in summary:
            v = summary[key]["verdict"]
            lines.append(f"- {key}: **{v['verdict']}**" + "".join(f"\n  - {x}" for x in v.get("reasons", [])))
            if "spread" in v:
                lines.append(f"  - разброс min/median/max: {json.dumps(v['spread'], ensure_ascii=False)}")
    (out / "results_round2.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if ok else 1


def round2_plan(args: argparse.Namespace) -> list[str]:
    q = args.quick
    sessions = 1 if q else R2_SESSIONS_PER_TREE
    runs = 1 if q else int(R2_THRESHOLDS["tree_runs_per_tree"])
    s4_runs = 1 if q else REPEATS["S4"]
    return [
        f"режим: РАУНД 2; части: {args.round2_parts}; quick={q}; ветка: {args.root}; main (только чтение): {args.main_root}",
        f"R2-A [окна: {stop_windows(False)['mode']} stop_process_timeout={STOP_PROCESS_TIMEOUT_S} "
        f"stop_timeout={SHUTDOWN_TIMEOUT_S}]: {sessions} сеанс(а) на дерево, строго A/B/A/B (ветка, main, ветка, main, ...); сеанс = свежий бэкенд, полная "
        f"загрузка (строка PM 'registration summary'), {', '.join(R2_TARGETS)} x{R2_REPS} через process_restart_verified; "
        "в JSON весь res, момент отправки/возврата запроса драйвера, error ('timeout' = окно драйвера, не ответ PM), "
        f"ответ против строки PM 'restarted'; порог: ранний ответ (> {EARLY_REPLY_TOL_S} с до 'restarted') = FAIL, "
        f"ветка < {R2_THRESHOLDS['max_restart_s']} с",
        f"R2-B [окна: {stop_windows(False)['mode']} stop_process_timeout={STOP_PROCESS_TIMEOUT_S} "
        f"stop_timeout={SHUTDOWN_TIMEOUT_S}]: S4 x{s4_runs} на ветке; выход PM через OpenProcess+WaitForSingleObject (ctypes), выход лаунчера и стоимость "
        "одного вызова tasklist пишутся отдельно; порог S4 прежний (строка <= +1,2 с, выход PM <= +4,5 с, dns 0)",
        f"R2-C [окна: {stop_windows(True)['mode']} - без stop_process_timeout, без stop_timeout во временном system.yaml "
        "(значения кода/system.yaml дерева)]: выход дерева методом Task 1.1 (test_system_shutdown_live.py:64-100): рецепт {R2_TREE_RECIPE}, полная загрузка "
        f"+ {R2_TREE_WARMUP_S} с, system.shutdown, метрика = выход процесса PM; {runs} на ветке и {runs} на main, строго по "
        f"очереди; порог < {R2_THRESHOLDS['max_tree_exit_s']} с, {runs} из {runs} на КАЖДОМ дереве (литерал)",
        "вывод: <out>/json/R2A_*.json, R2C_*.json, S4_r*.json, <out>/round2_summary.json, <out>/results_round2.md",
    ]


# --------------------------------------------------------------------------------------------------------------
# Таблицы, план, точка входа
# --------------------------------------------------------------------------------------------------------------
def _f(x: Any, nd: int = 3) -> str:
    return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def markdown_table(title: str, rows: dict[str, dict[str, Any]]) -> str:
    lines = [
        f"## {title}",
        "",
        "| сценарий | N | min | median | max | p99 | зависаний | not reported/lost | did not stop in "
        "| порог ПОСЛЕ | вердикт |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key, r in rows.items():
        st = r.get("primary_stats") or {}
        lines.append(
            f"| {key} | {st.get('n', '-')} | {_f(st.get('min'))} | {_f(st.get('median'))} | "
            f"{_f(st.get('max'))} | {_f(st.get('p99'))} | "
            f"{r.get('hangs', '-')} | {r.get('lost_lines', '-')} | {r.get('dns_lines', '-')} | "
            f"{r.get('threshold_text', '')} | "
            f"**{r['verdict']}**{' (invalid)' if r.get('invalid') else ''} |"
        )
    reasons = [f"- {k}: {why}" for k, r in rows.items() for why in r.get("reasons", [])]
    outcomes = [f"- {k}: {r['outcomes']}" for k, r in rows.items() if r.get("outcomes") is not None]
    if outcomes:
        lines += ["", "Итоги стопа (`outcome` из ответа; наблюдение, S1 - прогноз exited 10 из 10):"] + outcomes
    return "\n".join(lines + ([""] + ["Причины FAIL:"] + reasons if reasons else []) + [""])


THRESHOLD_TEXT = {
    "S1": "0 зависаний, ответ 0,85-1,20 с, lost 0",
    "S2": "каждый ответ <= 0,5 с, p99 <= 150 мс",
    "S3": "доставка и ответ <= 0,5 с",
    "S4": "строка <= +1,2 с, выход PM <= +4,5 с, dns 0, system_stopping",
    "S5": "рестарт < 5,0; выход дерева < 2,0 (10/10); activate < 5,0",
    "S6": "outcome terminated, success True, ответ 5,0-5,3 с; 3 из 3",
    "S7": "outcome exited, success True, ответ 6,0-6,6 с; 3 из 3",
    "S7-контроль": "без ключа: outcome terminated, ответ 5,0-5,3 с (exited = стенд не различает)",
}


def summarize(name: str, verdict: dict[str, Any], runs: list[dict[str, Any]], primary_key: str) -> dict[str, Any]:
    row = dict(verdict)
    row["primary_stats"] = verdict.get(primary_key)
    row["threshold_text"] = THRESHOLD_TEXT[name]
    row["lost_lines"] = sum(int(r.get("lost", 0)) for r in runs if isinstance(r, dict))
    row["dns_lines"] = sum(int(r.get("dns", 0)) for r in runs if isinstance(r, dict))
    return row


def build_plan(args: argparse.Namespace) -> list[str]:
    n = {k: (1 if args.quick else v) for k, v in REPEATS.items()}
    mode = "КОНТРОЛЬ (патч И1)" if args.control else "основной прогон"
    plan = [
        f"режим: {mode}; сценарии: {args.scenario}; quick={args.quick}",
        f"python: {args.python}",
        f"корень дерева: {args.control_root if args.control else args.root}",
        f"рецепт: {args.recipe} (headless, свой временный манифест INSPECTOR_MANIFEST, "
        "свой system.yaml, свой порт, свой cwd)",
        f"окна остановки: shutdown_timeout={SHUTDOWN_TIMEOUT_S} "
        "(system.yaml system.stop_timeout временной копии -> spawner.py:90-92), "
        f"stop_process_timeout={STOP_PROCESS_TIMEOUT_S} (stand_backend.py: orchestrator_config; иного пути в коде нет)",
        f"дверь команд process.*: {args.door}",
        f"S1 x{n['S1']}: свежий бэкенд на прогон, 2 sim-робота v2 (в процессе стенда), "
        "device_upsert+connect, process.stop devices, +3 с статус, логи PM",
        f"S2 x{n['S2']}: общий бэкенд S2+S3; topology.diff/apply (slow=SlowChild 3,0 с, fast); "
        f"supervision.status каждые {SAMPLE_PERIOD_S} с весь стоп slow",
        f"S3 x{n['S3']}: process.relay в devices (introspect.status, reply_to=PM) на +{WAIT_RELAY_AT_S} с стопа slow; "
        "доставка = ответ devices по request_id (push-слушатель)",
        f"S4 x{n['S4']}: свежий бэкенд; stop slow; +0,1 с process.restart fast (ждущий); "
        f"+{WAIT_RELAY_AT_S} с system.shutdown; строка лога, выход PM, dns, ответ ждущего",
        f"S6 x{n['S6']}: свежий бэкенд на повтор; slow=S6SlowChild (стоп {args.s6_slow_stop_s} с), "
        f"stop_process_timeout={args.s6_window_s}; process.stop slow: время и ответ целиком "
        "(outcome terminated, success True, 5,0-5,3 с)",
        (
            f"S7 x1 КОНТРОЛЬ: как S7, но в записи slow НЕТ ключа stop_window_s (потолок {args.s7_ceiling_s} остаётся); "
            "ожидается terminated, ответ 5,0-5,3 с; exited = стенд не различает, S7 не засчитывать"
            if args.s7_control
            else f"S7 x{n['S7']}: свежий бэкенд на повтор; slow=S6SlowChild (стоп {args.s7_slow_stop_s} с), "
            f"stop_process_timeout={S7_PM_WINDOW_S}, ключ slow stop_window_s={args.s7_window_s}, "
            f"max_stop_window_s={args.s7_ceiling_s} (stand_backend.py: orchestrator_config); process.stop slow: "
            "время и ответ целиком (outcome exited, success True, 6,0-6,6 с)"
        ),
        f"S5: свежий бэкенд x{n['S5']} (system.shutdown без slow, выход дерева по PID через tasklist); "
        f"в прогоне 1 ещё process_restart_verified x3 на {args.s5_restart} и recipe.activate",
        "пороги ПОСЛЕ (литералы THRESHOLDS): " + json.dumps(THRESHOLDS, ensure_ascii=False),
        "нижние границы ДО для контроля: " + json.dumps(CONTROL_FLOORS, ensure_ascii=False),
        "вывод: <out>/json/<сценарий>_rN.json, <out>/summary.json, <out>/results.md, "
        "<out>/runs/<tag>/ (логи и stdout бэкенда)",
    ]
    if args.control:
        plan.append(
            f"контроль: git apply {args.inj_patch} в {args.control_root}; S2-S4; git apply -R; git diff --quiet"
        )
    return plan


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Стенд T1.9b: S1-S5 и контроль (патч И1). Подробности: README.md и докстринг."
    )
    ap.add_argument(
        "--scenario",
        default="all",
        help="all (S1-S5) | список через запятую из S1..S7 (S6 - T1.10, S7 - T1.11, только явно)",
    )
    ap.add_argument("--out", default=None, help="каталог результатов (по умолчанию <каталог стенда>/results/<время>)")
    ap.add_argument(
        "--root", default=str(HERE.parents[2]), help="корень проверяемого дерева (по умолчанию worktree со скриптом)"
    )
    ap.add_argument("--python", default=sys.executable, help="интерпретатор для бэкенда (main .venv)")
    ap.add_argument("--recipe", default=DEFAULT_REPO_RECIPE, help="рецепт относительно корня дерева")
    ap.add_argument(
        "--door",
        choices=("direct", "command"),
        default="direct",
        help="дверь process.* : прямая (по умолчанию) или process.command",
    )
    ap.add_argument(
        "--s5-restart",
        default="renderer,devices",
        help="цели process_restart_verified; нет такого процесса - берётся первый non-protected, это пишется в JSON",
    )
    ap.add_argument("--s6-slow-stop-s", type=float, default=S6_SLOW_STOP_S, help="S6: стоп медленного ребёнка, с")
    ap.add_argument("--s6-window-s", type=float, default=S6_WINDOW_S, help="S6: stop_process_timeout, с")
    ap.add_argument("--s7-slow-stop-s", type=float, default=S7_SLOW_STOP_S, help="S7: стоп медленного ребёнка, с")
    ap.add_argument("--s7-window-s", type=float, default=S7_WINDOW_S, help="S7: ключ stop_window_s записи slow, с")
    ap.add_argument(
        "--s7-ceiling-s", type=float, default=S7_CEILING_S, help="S7: max_stop_window_s в orchestrator_config PM, с"
    )
    ap.add_argument(
        "--s7-control",
        action="store_true",
        help="контроль S7 (с --scenario S7): тот же стенд без ключа stop_window_s, 1 повтор; ждём terminated 5,0-5,3 с",
    )
    ap.add_argument("--boot-timeout", type=float, default=90.0)
    ap.add_argument(
        "--quick", action="store_true", help="по 1 повтору (проверка самого стенда в окне перед полным прогоном)"
    )
    ap.add_argument("--control", action="store_true", help="контроль: S2-S4 на дереве с патчем И1")
    ap.add_argument("--control-root", default=None, help="контрольное дерево (worktree lso-1.9b-inj)")
    ap.add_argument("--inj-patch", default=None, help="путь к I1.patch")
    ap.add_argument(
        "--round2", action="store_true", help="раунд 2: рестарт A/B, S4 с WaitForSingleObject, выход дерева main/ветка"
    )
    ap.add_argument("--main-root", default=DEFAULT_MAIN_ROOT, help="дерево main (только чтение) для A/B раунда 2")
    ap.add_argument("--round2-parts", default="restart,s4,tree", help="части раунда 2: restart,s4,tree")
    ap.add_argument("--dry-run", action="store_true", help="напечатать план и пороги, бэкенд не трогать")
    return ap.parse_args(argv)


def scenarios_of(args: argparse.Namespace) -> list[str]:
    allowed = ["S1", "S2", "S3", "S4", "S5"]
    if args.control:
        allowed = ["S2", "S3", "S4"]
    if args.scenario.lower() == "all":
        if args.s7_control:
            raise SystemExit("--s7-control работает только с --scenario S7 (S7 не входит в all)")
        return allowed
    picked = [s.strip().upper() for s in args.scenario.split(",") if s.strip()]
    valid = allowed if args.control else [*allowed, "S6", "S7"]  # S6 (T1.10), S7 (T1.11) не входят в all
    bad = [s for s in picked if s not in valid]
    if bad:
        raise SystemExit(f"сценарии {bad} недоступны в этом режиме (допустимы {valid})")
    if args.s7_control and picked != ["S7"]:
        raise SystemExit("--s7-control работает только с --scenario S7 (контроль не смешивается с другими сценариями)")
    return picked


def run_set(ctx: Ctx, picked: list[str], restart_targets: list[str]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    raw: dict[str, Any] = {}
    if "S1" in picked:
        runs = run_s1(ctx)
        raw["S1"] = runs
        rows["S1"] = summarize("S1", judge_s1(runs), runs, "stats")
    if "S2" in picked or "S3" in picked:
        out = run_s23(ctx, set(picked))
        if "S2" in picked:
            raw["S2"] = out["S2"]
            rows["S2"] = summarize("S2", judge_s2(out["S2"]), out["S2"], "stats")
            allv = [v for r in out["S2"] for v in r.get("latencies", [])]
            rows["S2"]["max_latency_s"] = max([v for v in allv if v is not None], default=None)
        if "S3" in picked:
            raw["S3"] = out["S3"]
            rows["S3"] = summarize("S3", judge_s3(out["S3"]), out["S3"], "delivery_stats")
            rows["S3"]["max_delivery_s"] = rows["S3"]["delivery_stats"]["max"]
    if "S4" in picked:
        runs = run_s4(ctx)
        raw["S4"] = runs
        rows["S4"] = summarize("S4", judge_s4(runs), runs, "shutdown_line_stats")
        rows["S4"]["min_shutdown_line_s"] = rows["S4"]["shutdown_line_stats"]["min"]
    if "S5" in picked:
        runs = run_s5(ctx, restart_targets)
        raw["S5"] = runs
        rows["S5"] = summarize("S5", judge_s5(runs), runs, "tree_exit_stats")
    if "S6" in picked:
        runs = run_s6(ctx)
        raw["S6"] = runs
        rows["S6"] = summarize("S6", judge_s6(runs), runs, "stats")
    if "S7" in picked:
        runs = run_s7(ctx)
        if ctx.s7_control:
            raw["S7_control"] = runs
            rows["S7-контроль"] = summarize("S7-контроль", judge_s7_control(runs), runs, "stats")
        else:
            raw["S7"] = runs
            rows["S7"] = summarize("S7", judge_s7(runs), runs, "stats")
    (ctx.out / "raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return rows


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        rec = getattr(stream, "reconfigure", None)
        if callable(rec):
            rec(encoding="utf-8", errors="replace")
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.control and not (args.control_root and args.inj_patch):
        raise SystemExit("--control требует --control-root и --inj-patch")
    picked = [] if args.round2 else scenarios_of(args)
    if args.dry_run and args.round2:
        print("[dry-run] бэкенд не запускается. План раунда 2:")
        for line in round2_plan(args):
            print("  -", line)
        return 0
    if args.dry_run:
        print("[dry-run] бэкенд не запускается. План:")
        for line in build_plan(args):
            head = line.split(" ", 1)[0].rstrip(":")
            if head in REPEATS and head not in picked:
                continue  # шаг сценария, которого нет в этом режиме/выборе
            print("  -", line)
        return 0

    # Абсолютный путь обязателен: cwd бэкенда - его каталог запуска, относительный --out ломал манифест и lock.
    out = (Path(args.out) if args.out else HERE / "results" / time.strftime("%Y%m%d_%H%M%S")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    root = Path(args.control_root if args.control else args.root).resolve()
    if args.round2:
        return run_round2(args, root, out)
    restart_targets = [x.strip() for x in args.s5_restart.split(",") if x.strip()]
    started = time.time()
    summary: dict[str, Any] = {
        "mode": "control" if args.control else "main",
        "root": str(root),
        "python": args.python,
        "stop_process_timeout": STOP_PROCESS_TIMEOUT_S,
        "shutdown_timeout": SHUTDOWN_TIMEOUT_S,
        "door": args.door,
        "thresholds": THRESHOLDS,
        "started": started,
    }
    if args.control:
        with PatchedTree(root, Path(args.inj_patch)) as tree:
            ctx = Ctx(args, root, out)
            rows = run_set(ctx, picked, restart_targets)
        summary["control_tree_clean_after"] = tree.clean_after
        if set(picked) >= {"S2", "S3", "S4"}:
            summary["control"] = judge_control(rows)
    else:
        ctx = Ctx(args, root, out)
        rows = run_set(ctx, picked, restart_targets)
    summary["rows"] = rows
    summary["elapsed_s"] = round(time.time() - started, 1)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md = markdown_table(
        "Контроль (И1): числа «ДО» обязаны вернуться" if args.control else "Основной прогон: числа «ПОСЛЕ»", rows
    )
    if "control" in summary:
        md += f"\nСтенд различает: **{summary['control']['distinguishes']}**\n" + "".join(
            f"- {r}\n" for r in summary["control"]["reasons"]
        )
        md += f"\nДерево после отката чистое: {summary['control_tree_clean_after']}\n"
    (out / ("results_control.md" if args.control else "results.md")).write_text(md, encoding="utf-8")
    print(md)
    if args.control:
        return 0 if summary.get("control", {}).get("distinguishes") and summary["control_tree_clean_after"] else 1
    return 0 if all(r["verdict"] == "PASS" for r in rows.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
