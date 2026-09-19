#!/usr/bin/env python3
"""worktree_preflight.py — executable form of the venv false-green / false-red trap.

Why: `core/agents/_WORKTREE_PATTERN.md` ("uv / venv (false-green / false-red
trap)") documents that a fresh git worktree starts without its own `.venv` and
that `uv run <anything>` can silently resolve outside the worktree — the
package import goes green (editable install resolves fine) while the *runner*
(pytest) still resolves to the main tree's `.venv`, so a "passing" test run
proves nothing. That mitigation lived only as a paragraph agents were expected
to paste into every spawn prompt; on 2026-09-10 three agents independently
re-discovered the trap within one hour because none of them found the
paragraph. This script is the callable the paragraph should have been.

How the check works: importing `<package>` and `<runner>` from *this very
process* is exactly the "uv run python -c 'import <pkg> as m, pytest;
print(m.__file__); print(pytest.__file__)'" one-liner the doc prescribes —
just wrapped in a script. It only proves anything when this script itself is
invoked the way you intend to invoke your real commands, e.g.
`uv run python worktree_preflight.py`; running it with a bare `python` that
happens to resolve to the wrong interpreter reproduces the exact failure mode
this script exists to catch (that's the point, not a bug).

Usage:
    python worktree_preflight.py [--package NAME] [--runner NAME] [--json]

    --package NAME   Import name to verify (default: `[project].name` from
                      pyproject.toml at the worktree root, hyphens normalized
                      to underscores; falls back to the worktree root's
                      directory name if pyproject.toml is absent or has no
                      [project].name). Pass explicitly whenever the project
                      name does not map 1:1 to an importable top-level module
                      (e.g. a monorepo shipping several packages under one
                      project name).
    --runner NAME    Import name of the test runner to verify (default: pytest).
    --json           Emit the report as JSON on stdout only (agent contract) —
                      no other prose goes to stdout in this mode.

Exit codes:
    0 — not a worktree (nothing to check), or both package and runner resolve
        inside the worktree root.
    1 — at least one of package/runner resolves outside the worktree root, or
        cannot be imported at all (dev extra not synced).
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path


def run_git(args: list[str], cwd: Path | None = None) -> str | None:
    """Run ``git <args>``, return stripped stdout, or None if git/repo unavailable."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def detect_worktree(
    cwd: Path | None = None, *, git_runner=run_git
) -> tuple[bool, Path | None]:
    """Return (is_worktree, worktree_root).

    A linked git worktree has a ``--git-dir`` that differs from its
    ``--git-common-dir`` (the common dir always points at the main repo's
    ``.git``; the git-dir of a linked worktree points at
    ``<main>/.git/worktrees/<name>``). Equal means either the main checkout or
    not a worktree at all.
    """
    base = cwd or Path.cwd()
    common_dir = git_runner(["rev-parse", "--git-common-dir"], cwd=base)
    git_dir = git_runner(["rev-parse", "--git-dir"], cwd=base)
    if common_dir is None or git_dir is None:
        return False, None

    common_abs = (base / common_dir).resolve()
    git_abs = (base / git_dir).resolve()
    if common_abs == git_abs:
        return False, None

    toplevel = git_runner(["rev-parse", "--show-toplevel"], cwd=base)
    if toplevel is None:
        return False, None
    return True, Path(toplevel).resolve()


def _first_src_package(worktree_root: Path) -> str | None:
    """First importable package under ``src/`` (sorted), or None.

    A monorepo's root ``[project].name`` (``claude-kit``) is often not an import
    name at all — the importable packages live under ``src/<pkg>/``. Any one of
    them proves where the editable install points, so the first is enough.
    """
    src = worktree_root / "src"
    if not src.is_dir():
        return None
    for init in sorted(src.glob("*/__init__.py")):
        return init.parent.name
    return None


def _src_package_pick_note(worktree_root: Path, name: str) -> str | None:
    """Human note for the monorepo auto-pick, or None when nothing was
    actually "picked" among alternatives.

    ``resolve_package_name_with_origin`` silently chose the alphabetically
    first package under ``src/`` when ``[project].name`` was not importable —
    with several packages present (this repo has four), an agent had no way
    to tell that a choice was made at all versus there being exactly one
    candidate. Only worth surfacing when there was more than one.
    """
    n = len(list((worktree_root / "src").glob("*/__init__.py")))
    if n > 1:
        return f"auto-picked {name!r} (first of {n} packages under src/)"
    return None


def resolve_package_name_with_origin(
    explicit: str | None, worktree_root: Path
) -> tuple[str, str]:
    """Package/import name to check, plus the reason it was picked.

    Origin is one of:
      * ``"explicit"``  — the ``--package`` flag.
      * ``"pyproject"`` — ``[project].name`` (hyphens normalized to
        underscores), either confirmed importable by a matching
        ``src/<name>/`` or ``<name>/`` directory, or used as a last-resort
        literal fallback when neither that match nor any ``src/`` package
        was found.
      * ``"src-scan"``  — ``[project].name`` was not importable (the
        monorepo case), so the first importable package under ``src/`` was
        used instead.
      * ``"dirname"``   — no pyproject.toml / no ``[project].name`` / no
        ``src/`` packages at all: the worktree root's own directory name.
    """
    if explicit:
        return explicit, "explicit"

    pyproject = worktree_root / "pyproject.toml"
    if pyproject.is_file():
        try:
            import tomllib

            with pyproject.open("rb") as f:
                data = tomllib.load(f)
            name = data.get("project", {}).get("name")
            if name:
                candidate = str(name).replace("-", "_")
                if (worktree_root / "src" / candidate).is_dir() or (
                    worktree_root / candidate
                ).is_dir():
                    return candidate, "pyproject"
                src_pick = _first_src_package(worktree_root)
                if src_pick:
                    return src_pick, "src-scan"
                return candidate, "pyproject"
        except (OSError, ValueError, tomllib.TOMLDecodeError):
            pass

    src_pick = _first_src_package(worktree_root)
    if src_pick:
        return src_pick, "src-scan"
    return worktree_root.name.replace("-", "_"), "dirname"


def resolve_package_name(explicit: str | None, worktree_root: Path) -> str:
    """Package/import name to check: explicit arg > pyproject [project].name
    (hyphens normalized to underscores; if no ``src/<name>/`` or ``<name>/``
    directory exists but ``src/`` holds packages, the first of those — the
    monorepo case where ``[project].name`` is not importable) > worktree root
    directory name.

    Thin wrapper over ``resolve_package_name_with_origin`` for callers (and
    ``pre_report_gate.py``) that only need the name, not the origin.
    """
    return resolve_package_name_with_origin(explicit, worktree_root)[0]


def resolve_module(name: str) -> tuple[Path | None, str | None]:
    """Import ``name`` from the CURRENT interpreter. Returns (resolved path, error).

    This is deliberately an in-process import (not a subprocess) — the whole
    point is to observe what *this* interpreter resolves, because that is
    exactly what a real `pytest`/application run under this same invocation
    would resolve too.
    """
    try:
        mod = importlib.import_module(name)
    except Exception as e:  # noqa: BLE001 — any import failure is a reportable result
        return None, f"{type(e).__name__}: {e}"

    file = getattr(mod, "__file__", None)
    if file is not None:
        return Path(file).resolve(), None

    paths = list(getattr(mod, "__path__", []) or [])
    if paths:
        return Path(paths[0]).resolve(), None

    return None, f"{name!r} has no __file__/__path__ (builtin or namespace package?)"


def _is_inside(path: Path, root: Path) -> bool:
    try:
        return path.is_relative_to(root)
    except ValueError:
        return False


def evaluate(
    *,
    worktree_root: Path,
    package_name: str,
    package_path: Path | None,
    package_error: str | None,
    runner_name: str,
    runner_path: Path | None,
    runner_error: str | None,
) -> tuple[bool, list[str]]:
    """Pure decision logic — no I/O. Returns (ok, problem messages).

    Checks BOTH the package and the runner, independently — this is the "half
    that was missing" per _WORKTREE_PATTERN.md: checking only the package
    import goes green even when the runner still resolves outside the worktree.
    """
    problems: list[str] = []
    for label, path, error in (
        (package_name, package_path, package_error),
        (runner_name, runner_path, runner_error),
    ):
        if error is not None:
            problems.append(
                f"{label}: cannot be imported ({error}) — "
                f"run `uv sync --extra dev` in this worktree, then re-invoke via `uv run python`"
            )
        elif not _is_inside(path, worktree_root):
            problems.append(
                f"{label}: resolves OUTSIDE the worktree ({path}) — "
                f"run `uv sync --extra dev` inside {worktree_root} and re-invoke via `uv run python`"
            )
    return (not problems), problems


def _emit(report: dict, as_json: bool, human_summary: str) -> None:
    if as_json:
        print(json.dumps(report, indent=2))
        return
    print(f"worktree_root: {report.get('worktree_root')}")
    print(f"sys.executable: {report.get('sys_executable')}")
    print(f"VIRTUAL_ENV: {report.get('virtual_env')}")
    package = report.get("package")
    if package:
        print(f"package {package['name']!r}: {package['resolved'] or package['error']}")
    package_pick = report.get("package_pick")
    if package_pick:
        print(f"package_pick: {package_pick}")
    runner = report.get("runner")
    if runner:
        print(f"runner {runner['name']!r}: {runner['resolved'] or runner['error']}")
    for problem in report.get("problems", []):
        print(f"PROBLEM: {problem}")
    print(human_summary)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package",
        default=None,
        help="Import name to verify (default: pyproject [project].name, fallback dir name)",
    )
    parser.add_argument(
        "--runner", default="pytest", help="Runner module to verify (default: pytest)"
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON on stdout only (agent contract)"
    )
    args = parser.parse_args(argv)

    sys_executable = sys.executable
    virtual_env = os.environ.get("VIRTUAL_ENV")

    # Pass the module-level `run_git` explicitly (rather than relying on
    # detect_worktree's own default parameter) so a caller that monkeypatches
    # this module's `run_git` attribute is honored: a `def f(x=name)` default
    # binds to the function object `name` pointed to at *def time*, not at
    # call time, so it would be immune to a later `module.run_git = fake`.
    is_worktree, worktree_root = detect_worktree(git_runner=run_git)

    if not is_worktree:
        report = {
            "is_worktree": False,
            "worktree_root": None,
            "sys_executable": sys_executable,
            "virtual_env": virtual_env,
            "ok": True,
            "note": "not a worktree",
        }
        _emit(report, args.json, "OK (not a worktree)")
        return 0

    package_name, package_origin = resolve_package_name_with_origin(
        args.package, worktree_root
    )
    package_path, package_error = resolve_module(package_name)
    runner_path, runner_error = resolve_module(args.runner)

    ok, problems = evaluate(
        worktree_root=worktree_root,
        package_name=package_name,
        package_path=package_path,
        package_error=package_error,
        runner_name=args.runner,
        runner_path=runner_path,
        runner_error=runner_error,
    )

    report = {
        "is_worktree": True,
        "worktree_root": str(worktree_root),
        "package": {
            "name": package_name,
            "resolved": str(package_path) if package_path else None,
            "error": package_error,
        },
        "runner": {
            "name": args.runner,
            "resolved": str(runner_path) if runner_path else None,
            "error": runner_error,
        },
        "sys_executable": sys_executable,
        "virtual_env": virtual_env,
        "ok": ok,
        "problems": problems,
    }
    if package_origin == "src-scan":
        pick_note = _src_package_pick_note(worktree_root, package_name)
        if pick_note:
            report["package_pick"] = pick_note
    _emit(report, args.json, "OK" if ok else "NOT OK")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
