"""capture_baseline.py — pre-implementation baseline snapshot for S7 integration gate.

Captures coverage% and optionally sentrux cycle count BEFORE implementation starts.
Integrator reads .sentrux/baseline.json to compute delta in integration.md JSON block.

Pre: pytest available; .sentrux/ writable; sentrux optional
Post: .sentrux/baseline.json exists with at minimum coverage_pct field (may be null)
Stability: lite
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path


def _capture_coverage(repo_root: Path) -> float | None:
    """Run pytest --cov and return the coverage percent, or None on failure.

    Uses a bare ``--cov`` (no path) so coverage honours the project's
    ``[tool.coverage.run] source`` from pyproject.toml — portable across both
    src-layout and flat-layout projects, rather than a hardcoded ``--cov=src``.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--cov",
            "--cov-report=json",
            "-q",
            "--tb=no",
        ],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    coverage_json = repo_root / "coverage.json"
    if not coverage_json.exists():
        combined = (proc.stdout or "") + (proc.stderr or "")
        if (
            "unrecognized arguments: --cov" in combined
            or "No module named pytest_cov" in combined
        ):
            warnings.warn(
                "pytest-cov is not installed — '--cov' was rejected by pytest. "
                "Add 'pytest-cov' to your dev dependencies so the S7 integration "
                "gate can compute a coverage delta; coverage_pct will be null.",
                stacklevel=2,
            )
        else:
            warnings.warn(
                "coverage.json not found after pytest --cov run; coverage_pct will be null.",
                stacklevel=2,
            )
        return None
    try:
        data = json.loads(coverage_json.read_text(encoding="utf-8"))
        return float(data["totals"]["percent_covered"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        warnings.warn(
            f"Failed to read coverage.json totals: {exc}; coverage_pct will be null.",
            stacklevel=2,
        )
        return None


def _capture_sentrux() -> tuple[bool, int | None]:
    """Check sentrux availability and return (available, cycles_count)."""
    sentrux_bin = shutil.which("sentrux")
    if sentrux_bin is None:
        return False, None
    try:
        result = subprocess.run(
            ["sentrux", "cycles", "--count"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            cycles_text = result.stdout.strip()
            cycles = int(cycles_text) if cycles_text.isdigit() else None
            return True, cycles
        return True, None
    except Exception:
        return False, None


def capture_baseline(out_path: Path, repo_root: Path) -> None:
    """Capture baseline metrics and write them to out_path as JSON."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Step 1: coverage
    coverage_pct = _capture_coverage(repo_root)

    # Step 2: sentrux (optional)
    sentrux_available, cycles_count = _capture_sentrux()

    payload = {
        "coverage_pct": coverage_pct,
        "cycles_count": cycles_count,
        "sentrux_available": sentrux_available,
        "ts": datetime.now(tz=timezone.utc).isoformat(),
    }

    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Baseline written to {out_path}")
    if coverage_pct is None:
        print("WARNING: coverage_pct is null — no coverage data available.")
    if not sentrux_available:
        print(
            "INFO: sentrux unavailable — S7 integration gate will run in advisory mode."
        )


def main(argv: list[str] | None = None) -> None:
    """Entry point — always exits 0 (partial baseline beats crashing)."""
    parser = argparse.ArgumentParser(
        description="Capture pre-implementation baseline for S7 integration gate."
    )
    parser.add_argument(
        "--out",
        default=".sentrux/baseline.json",
        help="Output path for baseline JSON (default: .sentrux/baseline.json)",
    )
    args = parser.parse_args(argv)

    repo_root = Path.cwd()
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo_root / out_path

    try:
        capture_baseline(out_path, repo_root)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: baseline capture failed unexpectedly: {exc}", file=sys.stderr)
        print(
            "WARNING: .sentrux/baseline.json may not have been written.",
            file=sys.stderr,
        )

    # Always exit 0 — partial baseline beats crashing
    sys.exit(0)


if __name__ == "__main__":
    main()
