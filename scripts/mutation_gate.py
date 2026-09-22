"""mutation_gate.py — mutation probe over the files a Task changed (pipeline §3).

Mutates only the source files changed since *base* and runs only the Task's tests
against each mutant (mutmut). A surviving mutant is a behaviour change no test noticed.

Pre: run from the repo root inside the project env with mutmut available —
     `uv run --with mutmut python scripts/mutation_gate.py --tests <test files>`;
     no `setup.cfg` and no `[tool.mutmut]` in pyproject.toml (the gate owns the config)
Post: exit 0 — no survivors, nothing to mutate, or SKIP (no fork on this platform);
      exit 1 — survivors listed (REVIEW) or the clean test run failed (BLOCK);
      `setup.cfg` is removed again in every case
Stability: lite

Why a throwaway setup.cfg: mutmut 3 takes test selection from config only, and it runs
tests from a copy under `mutants/` — a suite that reaches outside source+tests fails there,
so the selection has to be the Task's own test files, which change per Task.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

_CFG = Path("setup.cfg")
_MAX_DIFFS = 10  # the rest are named; rerun after killing the first batch


def _changed_sources(base: str, source: str) -> list[str]:
    out = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=d",
            f"{base}...HEAD",
            "--",
            source,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [p for p in out.splitlines() if p.endswith(".py")]


def _mutmut(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mutmut", *args], capture_output=True, text=True
    )


def run(base: str, source: str, tests: list[str]) -> int:
    if not hasattr(os, "fork"):
        print("VERDICT: SKIP\nReason: mutmut needs fork — on Windows run it under WSL")
        return 0
    # a dangling symlink passes exists() and write_text would follow it out of the project;
    # rmtree refuses a symlinked mutants/ silently and mutmut would then write through it
    if _CFG.is_symlink() or Path("mutants").is_symlink():
        print(
            "VERDICT: BLOCK\nReason: setup.cfg or mutants/ is a symlink — refusing to write through it"
        )
        return 1
    if _CFG.exists() or "[tool.mutmut]" in Path("pyproject.toml").read_text(
        encoding="utf-8"
    ):
        print(
            "VERDICT: BLOCK\nReason: mutmut config already present — the gate writes its own setup.cfg"
        )
        return 1
    changed = _changed_sources(base, source)
    if not changed:
        print(f"VERDICT: PASS\nReason: no .py changed under {source}/ since {base}")
        return 0

    lines = lambda items: "".join(f"\n    {i}" for i in items)  # noqa: E731
    _CFG.write_text(
        f"[mutmut]\nsource_paths={source}\nonly_mutate={lines(changed)}\n"
        f"pytest_add_cli_args_test_selection={lines(tests)}\n",
        encoding="utf-8",
    )
    try:
        shutil.rmtree("mutants", ignore_errors=True)  # stale results of another Task
        ran = _mutmut("run")
        if ran.returncode != 0:
            print(
                "VERDICT: BLOCK\nReason: mutmut run failed — a test fails from the copy under mutants/ "
                "(pass only tests that need nothing outside source+tests), or no selected test "
                "reaches the mutated code; mutmut's own words below"
            )
            print((ran.stdout + ran.stderr)[-1500:])
            return 1
        # every status, not only "survived": a mutant with "no tests" / "timeout" was never
        # judged, and counting survivors alone would call that a PASS
        statuses = [
            ln.strip().rsplit(": ", 1)
            for ln in _mutmut("results", "--all", "true").stdout.splitlines()
            if ": " in ln
        ]
        survived = [name for name, status in statuses if status == "survived"]
        unjudged = [
            f"{name}: {status}"
            for name, status in statuses
            if status not in ("survived", "killed")
        ]
        killed = len(statuses) - len(survived) - len(unjudged)
        # diffs while the config still exists — `mutmut show` cannot find the source without it
        diffs = [
            "\n".join(
                ln for ln in _mutmut("show", name).stdout.splitlines() if ln[:1] in "+-"
            )
            for name in survived[:_MAX_DIFFS]
        ]
    finally:
        _CFG.unlink(missing_ok=True)

    if not survived and not unjudged:
        print(
            f"VERDICT: PASS\nKilled: {killed} of {len(statuses)}\nMutated: {', '.join(changed)}"
        )
        return 0
    print(
        f"VERDICT: REVIEW\nKilled: {killed} of {len(statuses)}; survived: {len(survived)}; "
        f"never judged: {len(unjudged)} — kill each with a test or name it equivalent in the report"
    )
    print("\n".join(unjudged + survived))
    print(f"--- first {len(diffs)} diffs ---")
    print("\n\n".join(diffs))
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mutation probe over the files changed since --base."
    )
    parser.add_argument(
        "--tests",
        nargs="+",
        required=True,
        metavar="PATH",
        help="The Task's test files.",
    )
    parser.add_argument("--base", default="main", help="Diff base (default: main).")
    parser.add_argument(
        "--source", default="src", help="Source root to mutate (default: src)."
    )
    args = parser.parse_args()
    sys.exit(run(args.base, args.source, args.tests))


if __name__ == "__main__":
    main()
