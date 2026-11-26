# -*- coding: utf-8 -*-
"""Приёмка стенда камер через backend_ctl: опрос камерных плагинов, таблица, JSON, код выхода.

Бэкенд поднимается отдельно (``BACKEND_CTL=1 ... --headless --autostart``), скрипт только читает::

    python -m backend_ctl.probes.camera_stand_probe --port 8765 --processes p1,p2 \
        [--plugins n1,n2] --seconds 60 --interval 5 --out stand.json

Каждые ``--interval`` секунд на каждый плагин: блок ``processes.<p>.state.plugins.<n>`` командой
``state.get`` и уровни ``introspect.telemetry`` (опрос, публикацию телеметрии скрипт не включает).
Опрос удачен, только если пришли оба ответа; прошлые числа вместо неудачного не подставляются.

Код 0 означает «каждый процесс из ``--processes`` дал хотя бы один камерный плагин, каждый плагин
наблюдался и его ``frames`` росли». Код 1 — причины лежат в ``failures`` плагина и в ``errors``
отчёта. Код 2 — неверные аргументы. Набор плагинов определяется дважды, в начале и в конце:
плагин, появившийся только в конце, получает ``no_samples``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from typing import Any

from backend_ctl import BackendDriver
from backend_ctl.protocol import unwrap

_TIMEOUT_S = 5.0
# Метрики, без которых вердикт не выносится.
_REQUIRED = ("frames", "dropped", "errors")
# Метрики, которые уходят в JSON значением последнего удачного опроса.
_LAST_METRICS = (
    "frames",
    "dropped",
    "errors",
    "param_errors_count",
    "lost_frames",
    "incomplete",
    "lost_packets",
    "trigger_missed",
)
_COLUMNS = (
    "samples",
    "failed_polls",
    "fps_mean",
    "fps_min",
    "frames",
    "dropped",
    "errors",
    "state",
    "link_state",
    "link_outages",
)

# Один удачный опрос: (блок state, уровни плагина).
type Sample = tuple[dict, dict]


def _dig(node: Any, *keys: str) -> dict | None:
    """Вложенный dict по ключам; нет ключа или не dict — ``None``."""
    for key in keys:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else None


def _num(value: Any) -> float | None:
    """Конечное число или ``None``: NaN прошёл бы проверку ``> 0`` как «потерь нет»."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def _ask(call: Callable[[], Any], what: str) -> dict:
    """Ответ драйвера, развёрнутый до нагрузки; исключение — в stderr и пустой dict (неудачный опрос)."""
    try:
        return unwrap(call(), leaf=True)
    except Exception as exc:  # noqa: BLE001 — отказ вызова считается неудачным опросом, не роняет отчёт
        print(f"[camera_stand] {what}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return {}


def _state_value(drv: Any, path: str) -> dict | None:
    leaf = _ask(
        lambda: drv.send_command("ProcessManager", "state.get", {"path": path}, timeout=_TIMEOUT_S),
        f"state.get {path}",
    )
    return _dig(leaf, "value") if leaf.get("status") == "ok" else None


def _plugin_levels(drv: Any, process: str) -> dict:
    """``levels.state.plugins`` процесса; нет ответа или ``levels`` — пустой dict."""
    leaf = _ask(lambda: drv.introspect_telemetry(process, timeout=_TIMEOUT_S), f"introspect.telemetry {process}")
    return _dig(leaf, "levels", "state", "plugins") or {}


def _detect(drv: Any, process: str, wanted: list[str] | None) -> list[str] | None:
    """Камерные плагины процесса (или запрошенные из ``wanted``); ``None`` — дерево не прочиталось."""
    blocks = _state_value(drv, f"processes.{process}.state.plugins")
    if blocks is None:
        return None
    if wanted is not None:
        return [n for n in wanted if isinstance(blocks.get(n), dict)]
    return [n for n, b in blocks.items() if isinstance(b, dict) and "device_held" in b and "link" in b]


def _summarize(samples: list[Sample], failed_polls: int) -> dict:
    """Строка отчёта плагина с кодами причин отказа в ``failures``."""
    block, metrics = samples[-1] if samples else ({}, {})
    link = _dig(block, "link") or {}
    fps = [v for _, m in samples if (v := _num(m.get("fps"))) is not None]
    frames = [_num(m.get("frames")) for _, m in samples]
    errors = [v for _, m in samples if (v := _num(m.get("errors"))) is not None]
    last = {name: _num(metrics.get(name)) for name in _LAST_METRICS}

    failures: list[str] = []
    if not samples:
        failures.append("no_samples")
    elif len(samples) == 1:
        failures.append("too_few_samples")
    if failed_polls:
        failures.append("failed_poll")
    if samples:
        failures += [f"missing_metric:{name}" for name in _REQUIRED if last[name] is None]
        if block.get("state") != "grabbing":
            failures.append("state_not_grabbing")
        if last["dropped"] is not None and last["dropped"] > 0:
            failures.append("dropped")
        if link.get("state") == "lost":
            failures.append("link_lost")
        if last["errors"] is not None and last["errors"] > errors[0]:
            failures.append("errors_grew")
    if len(samples) > 1:
        # Положительное доказательство: оба числа есть и последнее больше предпоследнего.
        prev, cur = frames[-2], frames[-1]
        if prev is None or cur is None or not cur > prev:
            failures.append("frames_stalled")
        if any(b < a for a, b in pairwise(f for f in frames if f is not None)):
            failures.append("frames_reset")

    return {
        "failures": failures,
        "failed_polls": failed_polls,
        "samples": len(samples),
        "fps_mean": sum(fps) / len(fps) if fps else None,
        "fps_min": min(fps) if fps else None,
        **last,
        "state": block.get("state"),
        "link_state": link.get("state"),
        "link_outages": link.get("outages"),
        "link_attempts": link.get("attempts"),
        "identity_serial": (_dig(block, "identity") or {}).get("serial"),
    }


def _observe(drv: Any, args: argparse.Namespace, report: dict) -> None:
    """Опросить стенд и заполнить ``report``."""
    processes: list[str] = args.processes
    names = {p: _detect(drv, p, args.plugins) or [] for p in processes}
    samples: dict[tuple[str, str], list[Sample]] = {(p, n): [] for p in processes for n in names[p]}
    failed = dict.fromkeys(samples, 0)

    ticks = int(args.seconds / args.interval + 1e-9) + 1
    start = time.monotonic()
    for tick in range(ticks if samples else 0):
        time.sleep(max(0.0, start + tick * args.interval - time.monotonic()))
        for p in processes:
            if not names[p]:
                continue
            blocks = {n: _state_value(drv, f"processes.{p}.state.plugins.{n}") for n in names[p]}
            levels = _plugin_levels(drv, p)
            for n, block in blocks.items():
                metrics = _dig(levels, n)
                if block is None or metrics is None:
                    failed[(p, n)] += 1
                else:
                    samples[(p, n)].append((block, metrics))

    # Повторное определение набора: плагин, которого не было в начале, не наблюдался — это не зелёный.
    for p in processes:
        late = _detect(drv, p, args.plugins)
        if late is None:
            report["errors"].append(f"detect_failed:{p}")
            late = []
        for n in late:
            if n not in names[p]:
                names[p].append(n)
                samples[(p, n)], failed[(p, n)] = [], 0

    for p in processes:
        if not names[p]:
            report["errors"].append(f"no_camera_plugin:{p}")
        report["processes"][p] = {"plugins": {n: _summarize(samples[(p, n)], failed[(p, n)]) for n in names[p]}}
    for n in args.plugins or []:
        if not any(n in names[p] for p in processes):
            report["errors"].append(f"plugin_not_found:{n}")


def _passed(report: dict, processes: list[str]) -> bool:
    """Положительный вердикт: ошибок нет, у каждого процесса есть плагины и ни у одного нет причин отказа."""
    if report["errors"]:
        return False
    for p in processes:
        plugins = report["processes"].get(p, {}).get("plugins")
        if not plugins or any(row["failures"] for row in plugins.values()):
            return False
    return True


def _print_table(report: dict) -> None:
    rows: list[tuple[str, ...]] = [("process", "plugin", *_COLUMNS, "failures")]
    for p, entry in report["processes"].items():
        for n, row in entry["plugins"].items():
            cells = [
                f"{v:.1f}" if isinstance(v, float) else "-" if v is None else str(v) for v in map(row.get, _COLUMNS)
            ]
            rows.append((p, n, *cells, ",".join(row["failures"]) or "ok"))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip())
    for error in report["errors"]:
        print(f"ERROR {error}")


def _names(text: str) -> list[str]:
    names = list(dict.fromkeys(part.strip() for part in text.split(",") if part.strip()))
    if not names:
        raise argparse.ArgumentTypeError("пустой список")
    return names


def _seconds(text: str) -> float:
    value = float(text)
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("нужно конечное число >= 0")
    return value


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="camera_stand_probe", description="Приёмка стенда камер через backend_ctl.")
    parser.add_argument("--port", type=int, default=None, help="порт backend_ctl (по умолчанию env или 8765)")
    parser.add_argument("--processes", type=_names, required=True, help="процессы через запятую")
    parser.add_argument("--plugins", type=_names, default=None, help="плагины через запятую (иначе все камерные)")
    parser.add_argument("--seconds", type=_seconds, default=60.0)
    parser.add_argument("--interval", type=_seconds, default=5.0)
    parser.add_argument("--out", type=Path, required=True, help="файл JSON-отчёта")
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval должен быть > 0")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    args.out.unlink(missing_ok=True)  # отчёт прошлого прогона не должен читаться как этот
    report: dict = {"processes": {}, "errors": []}
    try:
        with BackendDriver(port=args.port) as drv:
            _observe(drv, args, report)
    except Exception as exc:  # noqa: BLE001 — нет соединения и т.п.: отчёт с причиной и код 1
        print(f"[camera_stand] {type(exc).__name__}: {exc}", file=sys.stderr)
        report["errors"].append(f"driver:{type(exc).__name__}: {exc}")

    code = 0 if _passed(report, args.processes) else 1
    report["exit_code"] = code
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_table(report)
    return code


if __name__ == "__main__":
    sys.exit(main())
