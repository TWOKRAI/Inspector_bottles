"""Generate a CycloneDX SBOM (Software Bill of Materials) for the project.

Wraps an external SBOM generator and emits CycloneDX JSON — the lingua-franca a
downstream CVE scanner (``osv-scanner``, Dependency-Track, GitHub dependency
review) consumes. Generation is opt-in (the artifact is only useful when you
ship/audit it), but the command stays available so producing one is a single
call.

Generator preference (first one found on PATH wins):
  1. ``syft``   — Anchore, broad ecosystem coverage, ``-o cyclonedx-json``.
  2. ``cdxgen`` — CycloneDX project, ``-t <type>`` autodetect, native CycloneDX.

⚠️ Trivy is intentionally NOT used as a generator here. The ``trivy`` npm/CI
supply chain was compromised in Feb–Mar 2026 (malicious post-install payloads in
mirrored releases); until provenance is re-established prefer ``syft`` / ``cdxgen``
whose release artifacts were unaffected. If you must use Trivy, pin a known-good
digest and verify its signature out-of-band.

Skip-if-absent: if no generator is installed the command is a no-op (exit 0 with
a stderr notice) so day-1 projects and CI stay green.

Exit codes:
- 0 — SBOM written (or no generator installed → skipped)
- 2 — generator ran but failed (real error)

Run::

    python .claude/plugins/security/scripts/sbom_gen.py                 # -> sbom.cdx.json
    python .claude/plugins/security/scripts/sbom_gen.py --output -      # -> stdout
    python .claude/plugins/security/scripts/sbom_gen.py --root . --output build/sbom.json
"""

from __future__ import annotations

import argparse
import contextlib
import shutil
import subprocess
import sys
from pathlib import Path


# (binary, argv-builder) in preference order. Each builder returns the argv that
# writes CycloneDX JSON for ``root`` to ``out`` ('-' means stdout).
def _syft_cmd(binary: str, root: Path, out: str) -> list[str]:
    target = f"cyclonedx-json={out}" if out != "-" else "cyclonedx-json"
    return [binary, "scan", str(root), "-o", target, "-q"]


def _cdxgen_cmd(binary: str, root: Path, out: str) -> list[str]:
    cmd = [binary, "-r", str(root)]
    if out != "-":
        cmd += ["-o", out]
    return cmd


_GENERATORS: tuple[tuple[str, object], ...] = (
    ("syft", _syft_cmd),
    ("cdxgen", _cdxgen_cmd),
)


def _force_utf8_stdout() -> None:
    """Pin UTF-8 for stdout/stderr (Windows cp1251 fix)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(OSError, ValueError):
            reconfigure(encoding="utf-8")


def _resolve_generator() -> tuple[str, str, object] | None:
    """Return (name, binary_path, argv_builder) for the first generator found."""
    for name, builder in _GENERATORS:
        binary = shutil.which(name)
        if binary:
            return name, binary, builder
    return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sbom_gen",
        description="Generate a CycloneDX SBOM via syft/cdxgen (Trivy avoided — see docstring).",
    )
    p.add_argument("--root", type=Path, default=Path("."))
    p.add_argument(
        "--output",
        default="sbom.cdx.json",
        help="Output file, or '-' for stdout (default: sbom.cdx.json).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    args = build_parser().parse_args(argv)

    resolved = _resolve_generator()
    if resolved is None:
        print(
            "sbom_gen: no SBOM generator installed — skipping (exit 0).\n"
            "  Install one: brew install syft  |  npm install -g @cyclonedx/cdxgen\n"
            "  (Trivy intentionally avoided — Feb–Mar 2026 supply-chain compromise.)",
            file=sys.stderr,
        )
        return 0

    if not args.root.exists():
        print(f"error: root not found: {args.root}", file=sys.stderr)
        return 2

    name, binary, builder = resolved
    cmd = builder(binary, args.root, args.output)  # type: ignore[operator]
    proc = subprocess.run(cmd, text=True, encoding="utf-8")
    if proc.returncode != 0:
        print(f"error: {name} exited {proc.returncode}", file=sys.stderr)
        return 2

    if args.output != "-":
        print(
            f"SBOM written: {args.output} (CycloneDX JSON, via {name})", file=sys.stderr
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
