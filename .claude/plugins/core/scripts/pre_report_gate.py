#!/usr/bin/env python3
"""pre_report_gate.py -- self-check a writing agent runs on itself before reporting done.

Purpose:
    Catch, in seconds and inside the agent's own worktree, the finding
    classes reviewers paid dearly for in wave A of system-to-eight phase 2
    (exec bit lost on a delivered script, a new public script shipped
    without a module-contract-lite docstring/__all__, ruff-red code, a red
    unit test) -- the same checks a reviewer runs first, so the reviewer
    spends context on semantics and injected bugs instead.

Public API:
    - GateResult -- one gate outcome: ok, and on failure a code/path/output,
                    plus base_degraded / lint_skipped when either is true
                    and, on failure only, the base ref that scoped it
    - run_gate    -- the fail-fast checks against one working tree
    - main        -- CLI entry point (--json, --tests PATH [PATH ...], --base REF)

Stability: lite

Checks run in this order, each stopping the gate at its first finding
(fail-fast -- a worktree resolving outside itself is cheaper to see than a
red test suite):

  1. worktree      - a worktree whose package/runner resolves outside
                      itself (reuses worktree_preflight.py by dynamic
                      import when the core plugin is materialized under
                      .claude/plugins/core/scripts/).
  2. exec-bit      - a changed or untracked file with a shebang that has
                      no exec bit (git mode 100644, or the filesystem bit
                      itself when the file is not yet tracked at all).
  3. contract-lite - a newly added public .py script missing __all__ or a
                      Purpose: line in its module docstring. A path under a
                      template/ directory is checked only when its parent
                      directory is named scripts -- other template/ content
                      (starter files, fixtures) is out of scope.
  4. lint          - ruff check red on the changed .py files (--force-exclude,
                      so a pyproject.toml extend-exclude is honoured even
                      though files are passed explicitly). Ruff missing from
                      the interpreter does not fail the gate -- it sets
                      lint_skipped and the remaining checks still run.
  5. tests         - the configured test paths (default tests) red.
                      pytest missing from the interpreter is not a red
                      test -- ok with code no-runner.

Interpreter: the hook runs this script with the python3 on ITS PATH (the
main session's venv, or a system python), so when the working tree has its
own .venv the gate re-runs itself under that interpreter first -- lint,
tests and the worktree check then see the tree's own environment.

Scope is always the CALLER's diff against a resolved base plus its
untracked files (git ls-files --others --exclude-standard), never the whole
tree. The base is the first of --base (if given), @{upstream}, origin/HEAD,
main, master whose `git merge-base HEAD <ref>` succeeds; when none
resolves, the gate falls back to comparing against HEAD alone (the
caller's uncommitted changes only) and sets base_degraded.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

__all__ = ["GateResult", "main", "run_gate"]

DEFAULT_TEST_PATHS = ["tests"]
_TEST_TIMEOUT = 240
_LINT_TIMEOUT = 60
_TAIL_LINES = 10
_BASE_CANDIDATES = ["@{upstream}", "origin/HEAD", "main", "master"]
_REEXEC_ENV = "PRE_REPORT_GATE_REEXEC"
_VENV_PYTHONS = [".venv/bin/python", ".venv/Scripts/python.exe"]


@dataclass(frozen=True)
class GateResult:
    ok: bool
    code: str | None = None
    path: str | None = None
    output: list[str] | None = None
    base_degraded: bool = False
    lint_skipped: bool = False
    base: str | None = None

    def to_json(self) -> dict:
        payload: dict = {"ok": self.ok}
        if self.code:
            payload["code"] = self.code
        if self.path:
            payload["path"] = self.path
        if self.output:
            payload["output"] = self.output
        if self.base_degraded:
            payload["base_degraded"] = True
        if self.lint_skipped:
            payload["lint_skipped"] = True
        if self.base and not self.ok:
            payload["base"] = self.base
        return payload


def _git(cwd: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _untracked_files(cwd: Path) -> list[str]:
    out = _git(cwd, "ls-files", "--others", "--exclude-standard")
    return [line.strip() for line in out.splitlines() if line.strip()]


def _changed_files(cwd: Path, diff_filter: str, diff_target: str) -> list[str]:
    out = _git(cwd, "diff", "--name-only", f"--diff-filter={diff_filter}", diff_target)
    files = [line.strip() for line in out.splitlines() if line.strip()]
    if "A" in diff_filter:
        # an untracked file is, for gate purposes, an addition the caller
        # has not staged yet -- git diff ... <diff_target> never lists it.
        for rel in _untracked_files(cwd):
            if rel not in files:
                files.append(rel)
    return files


def _resolve_base(cwd: Path, base: str | None) -> tuple[str | None, bool, str | None]:
    """Resolve the diff base. Returns (sha, base_degraded, ref that resolved)."""
    candidates = ([base] if base else []) + _BASE_CANDIDATES
    for ref in candidates:
        sha = _git(cwd, "merge-base", "HEAD", ref).strip()
        if sha:
            return sha, False, ref
    return None, True, None


def check_exec_bit(cwd: Path, changed: list[str]) -> GateResult | None:
    for rel in changed:
        path = cwd / rel
        if not path.is_file():
            continue
        try:
            first_line = path.open("rb").readline()
        except OSError:
            continue
        if not first_line.startswith(b"#!"):
            continue
        mode_line = _git(cwd, "ls-files", "-s", "--", rel)
        # untracked -- git records no mode yet, so check the filesystem bit.
        no_exec = mode_line[:6] == "100644" if mode_line else not path.stat().st_mode & stat.S_IXUSR
        if no_exec:
            return GateResult(False, "exec-bit", path=rel)
    return None


def check_contract_lite(cwd: Path, added: list[str]) -> GateResult | None:
    for rel in added:
        if not rel.endswith(".py") or rel.startswith("tests/"):
            continue
        if Path(rel).name.startswith("_"):
            continue
        parts = Path(rel).parts
        if "template" in parts and Path(rel).parent.name != "scripts":
            # template/ content other than a delivered plugins/<id>/scripts
            # script (starter files, fixtures) is out of scope.
            continue
        path = cwd / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "__all__" not in text or "Purpose:" not in text:
            return GateResult(False, "contract-lite", path=rel)
    return None


def check_lint(cwd: Path, changed: list[str]) -> tuple[GateResult | None, bool]:
    """Returns (finding_or_None, lint_skipped) -- lint_skipped is True only
    when ruff itself could not run (module missing from the interpreter),
    in which case the caller keeps going rather than failing the gate."""
    py_files = [f for f in changed if f.endswith(".py") and (cwd / f).is_file()]
    if not py_files:
        return None, False
    cmd = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--no-fix",
        "--force-exclude",
        *py_files,
    ]
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=_LINT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None, False
    if result.returncode == 0:
        return None, False
    if "No module named" in result.stderr:
        return None, True
    tail = (result.stdout + result.stderr).splitlines()[-_TAIL_LINES:]
    return GateResult(False, "lint", output=tail), False


def _load_worktree_preflight(cwd: Path):
    # .claude/plugins/ is gitignored, so a fresh worktree lacks it: fall back
    # to the copy shipped next to this script.
    candidates = [
        cwd / ".claude" / "plugins" / "core" / "scripts" / "worktree_preflight.py",
        Path(__file__).resolve().parent / "worktree_preflight.py",
    ]
    path = next((c for c in candidates if c.is_file()), None)
    if path is None:
        return None
    try:
        spec = importlib.util.spec_from_file_location("_worktree_preflight_for_gate", path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def check_worktree(cwd: Path) -> GateResult | None:
    preflight = _load_worktree_preflight(cwd)
    if preflight is None:
        return None
    try:
        is_worktree, root = preflight.detect_worktree(cwd)
        if not is_worktree:
            return None
        pkg = preflight.resolve_package_name(None, root)
        pkg_path, pkg_error = preflight.resolve_module(pkg)
        run_path, run_error = preflight.resolve_module("pytest")
        ok, problems = preflight.evaluate(
            worktree_root=root,
            package_name=pkg,
            package_path=pkg_path,
            package_error=pkg_error,
            runner_name="pytest",
            runner_path=run_path,
            runner_error=run_error,
        )
    except Exception:  # an old interpreter (no tomllib) must not crash the gate
        return None
    if pkg_error is not None:
        # the name is a guess ([project].name); a mono-repo ships other
        # packages, so only a package that resolves OUTSIDE the tree counts.
        problems = [x for x in problems if not x.startswith(f"{pkg}: cannot be imported")]
        ok = not problems
    if not ok:
        return GateResult(False, "worktree", output=problems[:_TAIL_LINES])
    return None


def check_tests(cwd: Path, test_paths: list[str]) -> GateResult:
    existing = [p for p in test_paths if (cwd / p).exists()]
    if not existing:
        return GateResult(True, code="no-tests")

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-x",
        "--tb=short",
        "-p",
        "no:cacheprovider",
        *existing,
    ]
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=_TEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        return GateResult(
            False,
            "tests",
            output=[f"timeout after {_TEST_TIMEOUT}s -- narrow pre_report_gate_tests"],
        )
    except OSError as exc:
        return GateResult(False, "tests", output=[str(exc)])
    if result.returncode == 0:
        return GateResult(True)
    if not result.stdout.strip() and result.stderr.strip().endswith("No module named pytest"):
        return GateResult(True, code="no-runner")
    tail = (result.stdout + result.stderr).splitlines()[-_TAIL_LINES:]
    return GateResult(False, "tests", output=tail)


def _finalize(
    result: GateResult,
    base_degraded: bool,
    lint_skipped: bool,
    base_ref: str | None = None,
) -> GateResult:
    base = base_ref if not result.ok else None
    if not base_degraded and not lint_skipped and base is None:
        return result
    return replace(result, base_degraded=base_degraded, lint_skipped=lint_skipped, base=base)


def run_gate(cwd: Path, test_paths: list[str] | None = None, base: str | None = None) -> GateResult:
    base_sha, base_degraded, base_ref = _resolve_base(cwd, base)
    diff_target = base_sha or "HEAD"
    changed = _changed_files(cwd, "ACMR", diff_target)
    added = _changed_files(cwd, "A", diff_target)

    worktree_result = check_worktree(cwd)
    if worktree_result is not None:
        return _finalize(worktree_result, base_degraded, False, base_ref)

    for result in (check_exec_bit(cwd, changed), check_contract_lite(cwd, added)):
        if result is not None:
            return _finalize(result, base_degraded, False, base_ref)

    lint_result, lint_skipped = check_lint(cwd, changed)
    if lint_result is not None:
        return _finalize(lint_result, base_degraded, lint_skipped, base_ref)

    tests_result = check_tests(cwd, test_paths or DEFAULT_TEST_PATHS)
    return _finalize(tests_result, base_degraded, lint_skipped, base_ref)


def _project_python(cwd: Path) -> Path | None:
    return next((cwd / rel for rel in _VENV_PYTHONS if (cwd / rel).is_file()), None)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="emit the report as JSON on stdout only"
    )
    parser.add_argument(
        "--tests",
        nargs="+",
        default=None,
        metavar="PATH",
        help="test paths to run (default: tests)",
    )
    parser.add_argument(
        "--base",
        default=None,
        metavar="REF",
        help="diff base ref, tried before @{upstream}/origin/HEAD/main/master",
    )
    args = parser.parse_args(argv)

    venv_python = _project_python(Path.cwd())
    if venv_python is not None and not os.environ.get(_REEXEC_ENV):
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        env[_REEXEC_ENV] = "1"
        script = str(Path(__file__).resolve())
        return subprocess.run([str(venv_python), script, *argv], env=env).returncode

    result = run_gate(Path.cwd(), args.tests, args.base)

    if args.json:
        print(json.dumps(result.to_json()))
    else:
        print("OK" if result.ok else f"NOT OK: {result.code} {result.path or ''}".strip())
        for line in result.output or []:
            print(line)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
