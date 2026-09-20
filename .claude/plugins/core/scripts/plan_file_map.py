#!/usr/bin/env python3
"""plan_file_map.py — build the "shared file -> tasks -> owner" map by machine.

Why: a hand-built file-locality allocation missed exactly the intersection it
was designed to catch, on the very first wave where the rule was applied — Task
1.1 and Task 1.5 both touch `check_injections.py` (see
`docs/reviews/2026-09-10_wave-1-methodology.md` §1.2/§2.1, and
`.claude/memory/agent-allocation-by-file-locality.md`). Eyeballing a `**Files:**`
list across a dozen-plus tasks does not scale; this script parses it instead.

Reads a plan (`plans/<slug>/plan.md` + `phase-*.md`, or a single
`plans/<...>.md`), extracts every `**Files:**` line under each `### Task X.Y`
heading, normalizes the paths it finds there, and reports:

  - the default table: every file touched by 2+ tasks, sorted by task count
    (owner = lowest-numbered task, unless a project convention says otherwise —
    this script has no such convention table, it always picks lowest-numbered);
  - with `--check --wave A,B,C,...`: whether any file is shared by 2+ tasks
    *within that wave* — the machine version of "two writers do not sit on one
    file" (`_WORKTREE_PATTERN.md` "writer cap" section, and the allocation rule
    in project memory).

Normalization (exactly the three rules named in the task brief):
  1. Backtick-quoted spans on the Files line are the path candidates.
  2. `P/...` expands to `src/claude_kit_claude/template/plugins/...`.
  3. A trailing `:NN` or `:NN-NN` line-locator is stripped.
A backtick span that is not path-like (no `/`, no recognized file extension —
e.g. a bare function name like `` `check_seed_version` `` in a parenthetical
aside) is not treated as a file. Brace-expansion groups (`{a,b,c}.md`) are kept
as one literal token, not expanded — out of scope for this script (see the
implementation's own tests/report for the reasoning).

Usage:
    python plan_file_map.py <plan-dir-or-file> [--wave A,B,C,...] [--check] [--json]

Exit codes:
    0 — normal report, or --check found no in-wave collision.
    1 — --check found at least one file shared by 2+ tasks within --wave.
    2 — the given path does not exist.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from pathlib import Path

TASK_HEADER_RE = re.compile(r"^###\s+Task\s+(\d+)\.(\d+)\b", re.MULTILINE)
FILES_LINE_RE = re.compile(r"^\*\*Files:\*\*\s*(.*)$")
BACKTICK_RE = re.compile(r"`([^`]+)`")
LINE_SUFFIX_RE = re.compile(r":\d+(?:-\d+)?$")

_PATH_EXTENSIONS = (
    ".py",
    ".md",
    ".sh",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".txt",
    ".cfg",
)

_P_PREFIX = "P/"
_P_EXPANSION = "src/claude_kit_claude/template/plugins/"


def looks_like_path(token: str) -> bool:
    """A backtick token counts as a file path if it has a directory separator
    or ends with a recognized extension (optionally followed by a :line
    suffix) — this excludes bare identifiers like function/flag names that
    also get backtick-quoted in Files-line parentheticals."""
    token = token.strip()
    if not token:
        return False
    if "/" in token or "\\" in token:
        return True
    stem = LINE_SUFFIX_RE.sub("", token)
    return any(stem.endswith(ext) for ext in _PATH_EXTENSIONS)


def normalize_path(token: str) -> str:
    """Apply the three normalization rules: strip :line(-range) suffix, expand
    the P/ prefix. (Backtick-stripping happens in the caller, via BACKTICK_RE.)"""
    token = token.strip()
    token = LINE_SUFFIX_RE.sub("", token)
    if token.startswith(_P_PREFIX):
        token = _P_EXPANSION + token[len(_P_PREFIX) :]
    return token


def extract_backtick_tokens(line: str) -> list[str]:
    return BACKTICK_RE.findall(line)


def extract_tasks(text: str) -> list[dict]:
    """Split `text` on `### Task X.Y` headings; for each task body, find the
    first `**Files:**` line and extract its normalized, path-like tokens."""
    headers = list(TASK_HEADER_RE.finditer(text))
    tasks: list[dict] = []
    lines = text.splitlines()

    # Map each header match to (task_id, start_line_index).
    header_positions: list[tuple[str, tuple[int, int], int]] = []
    for m in headers:
        line_index = text.count("\n", 0, m.start())
        task_id = f"{m.group(1)}.{m.group(2)}"
        header_positions.append((task_id, (int(m.group(1)), int(m.group(2))), line_index))

    for i, (task_id, number, start) in enumerate(header_positions):
        end = header_positions[i + 1][2] if i + 1 < len(header_positions) else len(lines)
        body_lines = lines[start:end]

        files: list[str] = []
        for line in body_lines:
            fm = FILES_LINE_RE.match(line.strip())
            if fm is None:
                continue
            for raw_token in extract_backtick_tokens(fm.group(1)):
                if looks_like_path(raw_token):
                    normalized = normalize_path(raw_token)
                    if normalized not in files:
                        files.append(normalized)
            break  # only the first **Files:** line per task

        tasks.append({"id": task_id, "number": number, "files": files})

    return tasks


def build_file_map(tasks: list[dict]) -> dict[str, list[str]]:
    """path -> sorted list of task ids that touch it (numeric sort)."""
    file_map: dict[str, set[str]] = {}
    id_to_number = {t["id"]: t["number"] for t in tasks}
    for task in tasks:
        for f in task["files"]:
            file_map.setdefault(f, set()).add(task["id"])
    return {
        path: sorted(ids, key=lambda tid: id_to_number.get(tid, _parse_id(tid)))
        for path, ids in file_map.items()
    }


def _parse_id(task_id: str) -> tuple[int, int]:
    a, _, b = task_id.partition(".")
    return (int(a), int(b))


def owner_of(task_ids: list[str]) -> str:
    """The task with the lowest (phase, task) number — no project-specific
    ownership convention is encoded here, this is the documented default."""
    return min(task_ids, key=_parse_id)


def shared_files(file_map: dict[str, list[str]]) -> list[tuple[str, list[str]]]:
    """Files touched by 2+ tasks, sorted by task count desc then path asc."""
    shared = [(path, ids) for path, ids in file_map.items() if len(ids) >= 2]
    shared.sort(key=lambda item: (-len(item[1]), item[0]))
    return shared


def render_table(shared: list[tuple[str, list[str]]]) -> str:
    lines = ["| Файл | Задачи | Владелец |", "|------|--------|----------|"]
    for path, ids in shared:
        lines.append(f"| `{path}` | {', '.join(ids)} | {owner_of(ids)} |")
    return "\n".join(lines)


def check_wave_collisions(
    file_map: dict[str, list[str]], wave: list[str]
) -> list[tuple[str, list[str]]]:
    """Files shared by 2+ tasks that are BOTH in `wave` — the machine check of
    "two writers do not sit on one file" for a specific set of tasks about to
    be spawned together."""
    wave_set = set(wave)
    violations: list[tuple[str, list[str]]] = []
    for path, ids in file_map.items():
        in_wave = [i for i in ids if i in wave_set]
        if len(in_wave) >= 2:
            violations.append((path, sorted(in_wave, key=_parse_id)))
    violations.sort(key=lambda item: item[0])
    return violations


_PHASE_NUM_RE = re.compile(r"phase-(\d+)\.md$")


def discover_plan_files(path: Path) -> list[Path]:
    """`path` is either a single plan `.md` file, or a directory containing
    `plan.md` (+ optional `phase-N.md` files, sorted numerically)."""
    if not path.exists():
        raise FileNotFoundError(f"plan path does not exist: {path}")

    if path.is_file():
        # `plans/<slug>/plan.md` names the whole multi-phase plan: its tasks live
        # in the sibling phase-*.md files, and reading plan.md alone yields zero
        # tasks — i.e. a silent "no collision".
        if path.name != "plan.md":
            return [path]
        path = path.parent

    files: list[Path] = []
    plan_md = path / "plan.md"
    if plan_md.is_file():
        files.append(plan_md)

    phases = sorted(
        path.glob("phase-*.md"),
        key=lambda p: int(m.group(1)) if (m := _PHASE_NUM_RE.search(p.name)) else 0,
    )
    files.extend(phases)

    if not files:
        raise FileNotFoundError(f"no plan.md or phase-*.md found under: {path}")
    return files


def _emit(report: dict, as_json: bool, human_lines: list[str]) -> None:
    if as_json:
        print(json.dumps(report, indent=2))
        return
    for line in human_lines:
        print(line)


def _force_utf8_stdout() -> None:
    """Зафиксировать UTF-8 для stdout/stderr (Windows cp1251 fix) — the table
    header is Cyrillic (`Файл | Задачи | Владелец`); on a non-Cyrillic-codepage
    Windows console this would otherwise raise UnicodeEncodeError. Same fix as
    `lang-python/templates/scripts/link_check/link_check.py`."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(OSError, ValueError):
            reconfigure(encoding="utf-8")


def main(argv: list[str]) -> int:
    _force_utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan_path", help="plans/<slug>/ directory or a single plan .md file")
    parser.add_argument(
        "--wave",
        default=None,
        help="Comma-separated task ids (e.g. 1.1,1.4,1.5,1.6) to scope --check to",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any file is shared by 2+ tasks within --wave",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON on stdout only")
    args = parser.parse_args(argv)

    try:
        files = discover_plan_files(Path(args.plan_path))
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    tasks: list[dict] = []
    for f in files:
        tasks.extend(extract_tasks(f.read_text(encoding="utf-8")))

    file_map = build_file_map(tasks)
    shared = shared_files(file_map)
    wave = [w.strip() for w in args.wave.split(",")] if args.wave else None

    if args.check:
        if wave is None:
            print("error: --check requires --wave", file=sys.stderr)
            return 2
        known = {t["id"] for t in tasks}
        missing = [w for w in wave if w not in known]
        if missing:
            print(
                f"error: task(s) not found in plan: {', '.join(missing)}",
                file=sys.stderr,
            )
            return 2
        violations = check_wave_collisions(file_map, wave)
        ok = not violations
        report = {
            "wave": wave,
            "check": True,
            "violations": [{"path": p, "tasks": ids} for p, ids in violations],
            "ok": ok,
        }
        human = [f"Wave: {', '.join(wave)}"]
        if violations:
            human.append("VIOLATIONS (2+ tasks in this wave share a file):")
            for p, ids in violations:
                human.append(f"  {p} — {', '.join(ids)}")
        else:
            human.append("OK — no shared file within this wave")
        _emit(report, args.json, human)
        return 0 if ok else 1

    if wave is not None:
        file_map = {
            path: [i for i in ids if i in set(wave)]
            for path, ids in file_map.items()
        }
        file_map = {path: ids for path, ids in file_map.items() if ids}
        shared = shared_files(file_map)

    report = {
        "wave": wave,
        "check": False,
        "shared_files": [
            {"path": p, "tasks": ids, "owner": owner_of(ids)} for p, ids in shared
        ],
    }
    human = [render_table(shared)] if shared else ["(no file touched by 2+ tasks)"]
    _emit(report, args.json, human)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
