"""CLI бенча ёмкости: `python -m scripts.capacity_bench [--profile quick|full] [--tests] [--baseline SHA] ...`.

Оркестрация: паспорт -> самопроверка часов -> (опц.) тесты -> матрица кейсов -> отчёт.
Каждый кейс — отдельный процесс `run_case.py` с cwd/PYTHONPATH = меряемое дерево
(текущее — `candidate`, `--baseline` — временный worktree на нужном sha — `baseline`).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

from . import matrix
from .cpu_probe import clock_selfcheck
from .passport import collect_passport
from .recipe import render_recipe
from .report import write_report

PKG_DIR = Path(__file__).resolve().parent
REPO = PKG_DIR.parents[1]
TEST_DIRS = (
    "multiprocess_framework/modules/shared_resources_module/tests",
    "multiprocess_framework/modules/process_module/tests",
    "scripts/capacity_bench/tests",
)
CASE_TIMEOUT_MARGIN_S = 180
TESTS_TIMEOUT_S = 900


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.capacity_bench", description=__doc__.splitlines()[0])
    ap.add_argument(
        "--profile", choices=("quick", "full"), default="quick", help="матрица кейсов (по умолчанию %(default)s)"
    )
    ap.add_argument("--tests", action="store_true", help="перед замером прогнать pytest по трём каталогам")
    ap.add_argument(
        "--baseline", metavar="SHA", help="A/B: для каждого кейса сначала этот коммит, потом текущее дерево"
    )
    ap.add_argument("--port", type=int, default=8775, help="порт backend_ctl стенда (по умолчанию %(default)s)")
    ap.add_argument("--out", default="reports/bench", help="каталог отчёта (по умолчанию %(default)s)")
    ap.add_argument(
        "--dry-run", action="store_true", help="паспорт, самопроверка, список кейсов, отчёт; стенд не поднимается"
    )
    return ap


def _git_head(tree: Path) -> str | None:
    proc = subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _parse_pytest_summary(text: str) -> tuple[int, int]:
    """(passed, failed) из итоговой строки pytest; нет строки -> (0, 0)."""
    for line in reversed(text.strip().splitlines()):
        if " passed" in line or " failed" in line or " error" in line:
            passed = re.search(r"(\d+) passed", line)
            failed = re.search(r"(\d+) failed", line)
            return int(passed.group(1)) if passed else 0, int(failed.group(1)) if failed else 0
    return 0, 0


def _kill_tree(proc: subprocess.Popen) -> None:
    """Потомки первыми (снимок дерева, пока родитель жив), потом сам процесс."""
    with contextlib.suppress(psutil.Error):
        for child in psutil.Process(proc.pid).children(recursive=True):
            with contextlib.suppress(psutil.Error):
                child.kill()
    proc.kill()


def _run_tree(cmd: list, *, cwd: Path, env: dict, timeout: float) -> tuple[int, str, str]:
    """(rc, stdout, stderr). Таймаут и Ctrl+C убивают ВСЁ дерево, не только прямого потомка.

    `subprocess.run` по таймауту убивает лишь прямой процесс (на Windows-venv — редиректор), а стенд
    внутри живёт дальше и держит унаследованный pipe: `communicate()` после kill ждёт его выхода.
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except BaseException:  # TimeoutExpired и KeyboardInterrupt: одинаково добить дерево и пробросить
        _kill_tree(proc)
        with contextlib.suppress(subprocess.TimeoutExpired):  # сирота вне дерева не должен повесить нас снова
            proc.communicate(timeout=10)
        raise
    return proc.returncode, out, err


def run_tests(repo: Path) -> dict:
    """Итог pytest; сбой запуска (в т.ч. таймаут) не отменяет замер: rc=None и `error`."""
    t0 = time.perf_counter()
    try:
        rc, out, _ = _run_tree(
            [sys.executable, "-m", "pytest", *TEST_DIRS, "-q"],
            cwd=repo,
            env=dict(os.environ, PYTHONPATH=str(repo)),
            timeout=TESTS_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 — замер важнее тестов; ошибка уходит в отчёт
        duration = round(time.perf_counter() - t0, 1)
        return {
            "rc": None,
            "passed": None,
            "failed": None,
            "duration_s": duration,
            "error": f"{type(exc).__name__}: {exc}",
        }
    passed, failed = _parse_pytest_summary(out)
    return {"rc": rc, "passed": passed, "failed": failed, "duration_s": round(time.perf_counter() - t0, 1)}


def run_one(tree: Path, label: str, height: int, fps: int, secs: int, port: int) -> dict:
    """Один кейс на одном дереве: рендер рецепта -> `run_case.py` в чужом cwd -> JSON."""
    with tempfile.TemporaryDirectory(prefix="bench_case_", ignore_cleanup_errors=True) as tmp:
        recipe = render_recipe(height, fps, Path(tmp))
        out = Path(tmp) / "case.json"
        rc, _, stderr = _run_tree(
            [
                sys.executable,
                str(PKG_DIR / "run_case.py"),
                "--recipe",
                str(recipe),
                "--secs",
                str(secs),
                "--port",
                str(port),
                "--out",
                str(out),
            ],
            cwd=tree,
            env=dict(os.environ, PYTHONPATH=str(tree), PYTHONIOENCODING="utf-8"),
            timeout=secs + CASE_TIMEOUT_MARGIN_S,
        )
        if rc != 0:
            raise RuntimeError(f"run_case rc={rc} ({label}, {height}p@{fps}): {stderr[-1500:]}")
        data = json.loads(out.read_text(encoding="utf-8"))
    return {"height": height, "fps": fps, "secs": secs, "sha": _git_head(tree), "tree": label, **data}


@contextlib.contextmanager
def _baseline_worktree(sha: str | None):
    """Временный `git worktree --detach` на `sha` (None -> без базы); удаляется в `finally`."""
    if sha is None:
        yield None
        return
    with tempfile.TemporaryDirectory(prefix="bench_baseline_", ignore_cleanup_errors=True) as tmp:
        tree = Path(tmp) / "tree"
        subprocess.run(
            ["git", "-C", str(REPO), "worktree", "add", "--detach", str(tree), sha],
            check=True,
            capture_output=True,
            timeout=120,
        )
        try:
            yield tree
        finally:
            proc = subprocess.run(
                ["git", "-C", str(REPO), "worktree", "remove", "--force", str(tree)], capture_output=True, timeout=120
            )
            if proc.returncode != 0:  # иначе в .git/worktrees остаётся запись о каталоге, которого уже нет
                print(f"capacity_bench: не удалось убрать worktree {tree}: rc={proc.returncode}", file=sys.stderr)
                subprocess.run(["git", "-C", str(REPO), "worktree", "prune"], capture_output=True, timeout=120)


def run_matrix(profile: str, baseline: str | None, port: int, cases_out: list) -> None:
    """Дописывает результаты в `cases_out` по мере готовности: упавший кейс не теряет прежние."""
    with _baseline_worktree(baseline) as base_tree:
        for height, fps, secs in matrix.cases(profile):
            if base_tree is not None:
                cases_out.append(run_one(base_tree, "baseline", height, fps, secs, port))
            cases_out.append(run_one(REPO, "candidate", height, fps, secs, port))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # консоль Windows cp1251: путь с кириллицей не должен ронять печать
        sys.stdout.reconfigure(errors="replace")
    result = {
        "passport": collect_passport(REPO),
        "selfcheck": clock_selfcheck(),
        "tests": run_tests(REPO) if args.tests else None,
        "profile": args.profile,
        "cases": [],
    }
    rc = 0
    if not args.dry_run:
        try:
            run_matrix(args.profile, args.baseline, args.port, result["cases"])
        except Exception as exc:  # noqa: BLE001 — отчёт пишется всегда, ошибка уходит в rc и stderr
            print(f"capacity_bench: замер прерван: {exc}", file=sys.stderr)
            rc = 1
    md_path, json_path = write_report(result, Path(args.out))
    print(md_path)
    print(json_path)
    return rc


if __name__ == "__main__":
    sys.exit(main())
