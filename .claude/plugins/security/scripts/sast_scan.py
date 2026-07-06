"""Static application security testing (SAST) wrapper around Semgrep.

Detects code-level vulnerabilities (injection, deserialization, path traversal,
hardcoded secrets, unsafe crypto, ...) by running the ``semgrep`` CLI under the
``auto`` ruleset and post-processing its JSON output. This is the deterministic
complement to the LLM-only ``/security-review``: a grep-on-AST gate that never
"forgets" to flag a known-bad pattern.

Why a wrapper (not raw ``semgrep``):
- Uniform CLI mirroring ``secrets_audit.py`` (``--format json|table``, exit
  0/1/2, inline suppression, path allowlist) so the whole security family feels
  the same and slots into the same pre-push / CI gates.
- Inline suppression ``# sast: ignore`` on the offending line (in addition to
  Semgrep's native ``# nosemgrep``) for project-local, reviewable exceptions.
- Skip-if-absent: if ``semgrep`` is not installed the scan is a no-op (exit 0
  with a stderr notice), so day-1 projects and CI stay green until the tool is
  added — the same "inert without the tool" contract the rest of the seed uses.

Exit codes:
- 0 — no findings (or semgrep not installed → skipped)
- 1 — findings present (under strict=true; for CI / pre-push gates)
- 2 — semgrep failed to run / produced unparseable output (real error)

Run::

    python .claude/plugins/security/scripts/sast_scan.py
    python .claude/plugins/security/scripts/sast_scan.py --format json
    python .claude/plugins/security/scripts/sast_scan.py --root src --config auto
    python .claude/plugins/security/scripts/sast_scan.py --no-strict   # report only

Inline suppression (same line as the finding)::

    os.system(user_input)  # sast: ignore  -- reviewed: input is a fixed constant
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

INLINE_SUPPRESS = "sast: ignore"

# Directories never worth scanning (vendored / generated / virtualenvs). Passed
# to semgrep as --exclude globs; extend per project via --exclude.
DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".venv",
    "venv",
    "node_modules",
    ".git",
    "dist",
    "build",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
)


@dataclass
class Finding:
    check_id: str
    file: str
    line: int
    severity: str
    message: str
    text: str


def _force_utf8_stdout() -> None:
    """Pin UTF-8 for stdout/stderr (Windows cp1251 fix; mirrors secrets_audit)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(OSError, ValueError):
            reconfigure(encoding="utf-8")


def _resolve_semgrep() -> str | None:
    """Return the semgrep executable path, or None if not installed."""
    return shutil.which("semgrep")


def run_semgrep(
    semgrep: str,
    root: Path,
    config: str,
    excludes: tuple[str, ...],
    timeout: int,
) -> tuple[int, str, str]:
    """Invoke semgrep --json; return (returncode, stdout, stderr)."""
    cmd = [
        semgrep,
        "--config",
        config,
        "--json",
        "--quiet",
        "--metrics=off",
        "--timeout",
        str(timeout),
    ]
    for pat in excludes:
        cmd += ["--exclude", pat]
    cmd.append(str(root))
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, proc.stdout, proc.stderr


def parse_findings(raw_json: str) -> list[Finding]:
    """Map semgrep JSON ``results`` to Finding objects, honoring inline suppression."""
    data = json.loads(raw_json)
    findings: list[Finding] = []
    for r in data.get("results", []):
        extra = r.get("extra", {})
        lines = extra.get("lines", "") or ""
        # Inline suppression on the matched source line(s).
        if INLINE_SUPPRESS in lines:
            continue
        text = lines.strip().splitlines()[0] if lines.strip() else ""
        if len(text) > 100:
            text = text[:99] + "…"
        findings.append(
            Finding(
                check_id=str(r.get("check_id", "?")),
                file=str(r.get("path", "?")),
                line=int(r.get("start", {}).get("line", 0)),
                severity=str(extra.get("severity", "INFO")),
                message=str(extra.get("message", "")).strip().splitlines()[0]
                if extra.get("message")
                else "",
                text=text,
            )
        )
    return findings


def render_table(findings: list[Finding]) -> str:
    if not findings:
        return "OK: SAST findings none.\n"
    headers = ["severity", "file:line", "check_id", "message"]
    data = [
        [
            f.severity,
            f"{f.file}:{f.line}",
            f.check_id.rsplit(".", 1)[-1],
            f.message[:80],
        ]
        for f in findings
    ]
    widths = [len(c) for c in headers]
    for row in data:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    out = io.StringIO()
    sep = "  "
    out.write(sep.join(h.ljust(widths[i]) for i, h in enumerate(headers)) + "\n")
    out.write(sep.join("-" * w for w in widths) + "\n")
    for row in data:
        out.write(
            sep.join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)) + "\n"
        )
    out.write(f"\nTotal: {len(findings)} finding(s)\n")
    return out.getvalue()


def render_json(findings: list[Finding]) -> str:
    return json.dumps(
        {
            "summary": {"total": len(findings)},
            "findings": [f.__dict__ for f in findings],
        },
        ensure_ascii=False,
        indent=2,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sast_scan",
        description="Run Semgrep SAST and report findings (deterministic gate).",
    )
    p.add_argument("--root", type=Path, default=Path("."))
    p.add_argument(
        "--config",
        default="auto",
        help="semgrep --config value (default: auto; or a ruleset/p/… or path).",
    )
    p.add_argument("--format", choices=["table", "json"], default="table")
    p.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Extra path glob to exclude (repeatable; added to defaults).",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Per-rule timeout in seconds (default: 30).",
    )
    p.add_argument(
        "--no-strict",
        action="store_true",
        help="Do not exit 1 on findings (report only).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    args = build_parser().parse_args(argv)

    semgrep = _resolve_semgrep()
    if semgrep is None:
        print(
            "sast_scan: semgrep not installed — skipping SAST (exit 0).\n"
            "  Install: pipx install semgrep  (or: uvx semgrep ...)",
            file=sys.stderr,
        )
        return 0

    if not args.root.exists():
        print(f"error: scan root not found: {args.root}", file=sys.stderr)
        return 2

    excludes = (*DEFAULT_EXCLUDES, *args.exclude)
    code, stdout, stderr = run_semgrep(
        semgrep, args.root, args.config, excludes, args.timeout
    )

    try:
        findings = parse_findings(stdout)
    except (json.JSONDecodeError, ValueError):
        print("error: could not parse semgrep output", file=sys.stderr)
        if stderr.strip():
            print(stderr.strip(), file=sys.stderr)
        return 2

    # semgrep exits 0 (clean) or 1 (findings); anything else with no parseable
    # results is a real failure (bad config, crash, ...).
    if code not in (0, 1) and not findings:
        print(f"error: semgrep exited {code}", file=sys.stderr)
        if stderr.strip():
            print(stderr.strip(), file=sys.stderr)
        return 2

    findings.sort(key=lambda f: (f.file, f.line))
    if args.format == "json":
        sys.stdout.write(render_json(findings))
    else:
        sys.stdout.write(render_table(findings))

    if findings and not args.no_strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
