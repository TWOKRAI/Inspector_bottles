"""CLI стенд-гейта фазы 5 (Task 5.6).

``python -m scripts.stand_gate [--profile quick] [--runs N] [--from-json PATH ...] [--no-throughput-gate]
[--out-dir reports/stand]``

Коды выхода: 0 — все пороги зелёные; 1 — нарушен хотя бы один порог (строка ``FAIL <имя>: <факт> vs <порог>``);
2 — сбой прогона (стенд не поднялся, нет обязательного ключа JSON, замок занят).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analyze import CaseResult, GateInputError, analyze
from .report import stdout_lines, write_report

EXIT_OK, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.stand_gate", description=__doc__.splitlines()[0])
    ap.add_argument("--profile", choices=("quick",), default="quick")
    ap.add_argument("--runs", type=int, default=1, help="прогонов каждого кейса (живой режим)")
    ap.add_argument("--from-json", nargs="+", metavar="PATH", help="проверить готовые JSON, стенд не поднимать")
    ap.add_argument("--no-throughput-gate", action="store_true", help="выключить ТОЛЬКО порог lag processor")
    ap.add_argument("--out-dir", default="reports/stand")
    ap.add_argument("--port", type=int, default=8775, help="порт драйвера живого стенда")
    ap.add_argument(
        "--lock", default=None, help="путь stand.lock (по умолчанию <родитель основного дерева>/stand.lock)"
    )
    ap.add_argument("--lock-token", default=None, help="сессия в строке замка (обязательна в живом режиме)")
    ap.add_argument("--json-dir", default=None, help="куда класть JSON живых кейсов (по умолчанию --out-dir)")
    return ap


def _from_json(paths: list[str]) -> list[tuple[str, dict]]:
    cases = []
    for p in paths:
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GateInputError(f"{p}: {type(exc).__name__}: {exc}") from exc
        cases.append((Path(p).name, data))
    return cases


def _live(args: argparse.Namespace) -> list[tuple[str, dict]]:
    from . import run

    tree = Path.cwd()
    lock = Path(args.lock) if args.lock else run.default_lock_path(tree)
    run.check_stand_lock(lock, args.lock_token)
    json_dir = Path(args.json_dir or args.out_dir)
    json_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    for i in range(1, args.runs + 1):
        for tag, transit, pause in run.QUICK_CASES:
            data = run.run_case(tree, tag, transit, pause, args.port)
            out = json_dir / f"{tag}_{i}.json"
            out.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            print(f"stand_gate: {tag} run {i} -> {out}", flush=True)
            cases.append((f"{tag}_{i}", data))
    return cases


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.from_json:
            cases = _from_json(args.from_json)
        else:
            cases = _live(args)
        results: list[CaseResult] = [
            analyze(data, label=label, throughput_gate=not args.no_throughput_gate) for label, data in cases
        ]
    except Exception as exc:  # noqa: BLE001 — любой сбой прогона/входа = код 2, причина в stderr
        print(f"ERROR stand_gate: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR
    for line in stdout_lines(results):
        print(line)
    code = EXIT_FAIL if any(r.failed for r in results) else EXIT_OK
    path = write_report(results, Path(args.out_dir), exit_code=code, command=" ".join(sys.argv))
    print(f"RESULT exit={code} report={path}")
    return code


if __name__ == "__main__":
    sys.exit(main())
