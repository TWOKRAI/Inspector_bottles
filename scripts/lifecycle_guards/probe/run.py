"""Проба abort: живая ось (``axis``) и прогон набора с пробой (``run``).

``axis`` — проверка, что на этой машине фатальный путь вообще воспроизводится: репродуктор
``axis_chain.py`` в режиме ``thread`` обязан упасть, в режиме ``main`` — выжить. Если ось мертва,
зелёный прогон набора ничего не доказывает, и ``run`` отказывается его запускать.

``run`` — pytest в подпроцессе с плагином ``crashprobe`` N раз; исход каждого прогона:

* ``crashed`` — признак падения интерпретатора в выводе или код возврата из ``CRASH_CODES``;
* ``not-triggered`` — проба не сработала (в журнале нет строки ``at first logger test``);
* ``failed`` — иной ненулевой код (код 3 pytest, ``INTERNAL_ERROR``, — это ``failed``);
* ``survived`` — код 0 и проба сработала.

Код возврата ``run`` 0 только при ``survived == runs``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PROBE_DIR = Path(__file__).resolve().parent
AXIS_SCRIPT = PROBE_DIR / "axis_chain.py"
DEFAULT_CWD = REPO_ROOT / "multiprocess_framework" / "modules"
DEFAULT_TARGETS = (
    "frontend_module/tests",
    "frontend_module/graph/tests",
    "logger_module/tests/test_channels_extra.py",
    "logger_module/tests/test_console_backpressure.py",
)

# Windows: access violation, stack buffer overrun и т. п.; POSIX: SIGABRT/SIGSEGV (шелл 128+n и -n).
CRASH_CODES = frozenset({134, 139, -6, -11, 3221225477, 3221225725, 3221226505})
CRASH_TEXTS = ("fatal python error", "access violation")

AXIS_TIMEOUT_S = 300
RUN_TIMEOUT_S = 900

type Outcome = str  # "survived" | "crashed" | "failed" | "not-triggered"


def _is_crash(returncode: int | None, output: str) -> bool:
    if returncode in CRASH_CODES:
        return True
    low = output.lower()
    return any(text in low for text in CRASH_TEXTS)


def classify_run(returncode: int | None, output: str, log_text: str, mode: str) -> Outcome:
    """Исход прогона пробы; порядок проверки задан контрактом (crashed → not-triggered → failed → survived)."""
    if _is_crash(returncode, output):
        return "crashed"
    if f"[{mode}] at first logger test" not in log_text:
        return "not-triggered"
    if returncode != 0:
        return "failed"
    return "survived"


def _exec(cmd: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> tuple[int | None, str]:
    """Прогон подпроцесса; по сроку — код ``None`` и накопленный вывод."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
        err = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
        return None, f"{out}{err}\n[timeout {timeout}s]"
    return proc.returncode, proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# Ось
# ---------------------------------------------------------------------------


def check_axis(runs: int, script: Path | None = None) -> tuple[bool | None, str]:
    """Проверка оси: ``(True|False|None, строка)``; ``None`` — не проверялась (не ``win32`` без ``--script``)."""
    if script is None and sys.platform != "win32":
        return None, "axis: unchecked (not win32)"
    target = script or AXIS_SCRIPT
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONUTF8": "1"}
    thread_crashed = 0
    main_survived = 0
    for _ in range(runs):
        rc, out = _exec([sys.executable, str(target), "thread"], cwd=target.parent, env=env, timeout=AXIS_TIMEOUT_S)
        thread_crashed += _is_crash(rc, out)
    for _ in range(runs):
        rc, out = _exec([sys.executable, str(target), "main"], cwd=target.parent, env=env, timeout=AXIS_TIMEOUT_S)
        main_survived += rc == 0 and "SURVIVED main" in out and not _is_crash(rc, out)
    if thread_crashed == runs and main_survived == runs:
        return True, "axis: alive"
    return False, f"axis: dead (thread crashed {thread_crashed}/{runs}, main survived {main_survived}/{runs})"


# ---------------------------------------------------------------------------
# Набор
# ---------------------------------------------------------------------------


def _wrappers(log_text: str, mode: str) -> str:
    match = re.search(rf"\[{re.escape(mode)}\] at first logger test: .* = (\d+)", log_text)
    return match.group(1) if match else "n/a"


def run_probe(
    *,
    mode: str,
    runs: int,
    targets: Sequence[str],
    cwd: Path,
    no_conftest: bool,
) -> tuple[int, str]:
    """``runs`` прогонов pytest с плагином пробы; ``(код, итоговая строка)``."""
    outcomes: list[Outcome] = []
    secs: list[int] = []
    wrappers = "n/a"
    with tempfile.TemporaryDirectory(prefix="crashprobe-") as tmp:
        for index in range(runs):
            log = Path(tmp) / f"run{index + 1}.log"  # свежий файл на каждый прогон: чужой журнал не переиспользуется
            env = {
                **os.environ,
                "PYTHONPATH": str(REPO_ROOT),
                "QT_QPA_PLATFORM": "offscreen",
                "PYTHONUTF8": "1",
                "CRASHPROBE_MODE": mode,
                "CRASHPROBE_LOG": str(log),
                # проба измеряет abort, а не стражи: плагин lifecycle в её прогонах молчит
                "LIFECYCLE_G3": "off",
                "LIFECYCLE_G4": "off",
            }
            cmd = [
                sys.executable, "-m", "pytest", "-q", "--tb=line",
                "-p", "scripts.lifecycle_guards.probe.crashprobe", "-p", "no:cacheprovider",
                *(["--noconftest"] if no_conftest else []),
                *targets,
            ]  # fmt: skip
            started = time.monotonic()
            rc, out = _exec(cmd, cwd=cwd, env=env, timeout=RUN_TIMEOUT_S)
            secs.append(round(time.monotonic() - started))
            log_text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
            outcome = classify_run(rc, out, log_text, mode)
            outcomes.append(outcome)
            if index == 0:
                wrappers = _wrappers(log_text, mode)
            print(f"run {index + 1}/{runs}: {outcome} (rc={rc}, {secs[-1]}s)", flush=True)
            if outcome != "survived":
                print("\n".join(out.splitlines()[-15:]), flush=True)
    survived = outcomes.count("survived")
    summary = (
        f"probe {mode}: survived {survived}/{runs}, crashed {outcomes.count('crashed')}, "
        f"failed {outcomes.count('failed')}, not-triggered {outcomes.count('not-triggered')}, "
        f"wrappers {wrappers} (secs {'/'.join(str(s) for s in secs)})"
    )
    return (0 if survived == runs else 1), summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m scripts.lifecycle_guards.probe", description=__doc__.split("\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    axis = sub.add_parser("axis", help="проверить, что ось (падение при gc.collect вне главного потока) жива")
    axis.add_argument("--runs", type=int, default=3)
    axis.add_argument("--script", type=Path, default=None, help="подменить репродуктор (argv: main|thread)")

    run = sub.add_parser("run", help="прогнать набор с плагином crashprobe")
    run.add_argument("--mode", default="offmain_gc", choices=("census", "main_gc", "main_then_offmain", "offmain_gc"))
    run.add_argument("--runs", type=int, default=3)
    run.add_argument("--targets", nargs="+", default=list(DEFAULT_TARGETS))
    run.add_argument("--no-conftest", action="store_true", help="pytest --noconftest (без политики T1)")
    run.add_argument("--cwd", type=Path, default=DEFAULT_CWD)
    run.add_argument("--skip-axis", action="store_true")
    run.add_argument("--axis-script", type=Path, default=None, help="репродуктор оси для проверки внутри run")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.runs < 1:
        print("--runs должен быть >= 1", file=sys.stderr)
        return 2
    if args.command == "axis":
        alive, line = check_axis(args.runs, args.script)
        print(line, flush=True)
        return 2 if alive is False else 0
    if not args.skip_axis:
        alive, line = check_axis(args.runs, args.axis_script)
        print(line, flush=True)
        if alive is False:
            print("ось не живая — результат не доказывает отсутствие abort", flush=True)
            return 2
    code, summary = run_probe(
        mode=args.mode,
        runs=args.runs,
        targets=args.targets,
        cwd=args.cwd,
        no_conftest=args.no_conftest,
    )
    print(summary, flush=True)
    return code
