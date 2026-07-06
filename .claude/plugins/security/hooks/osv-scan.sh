#!/bin/bash
# OSV-Scanner dependency CVE gate (OPT-IN — pre-push / CI use, NOT PostToolUse).
# Wraps `osv-scanner` over the project's lockfiles and propagates its exit code
# so a pre-push hook or CI job fails when a known-vulnerable dependency is found.
# Skip-if-absent: if osv-scanner is not installed this is a no-op (exit 0), so
# day-1 projects and CI stay green until the binary is added.
#
# Wire into a pre-push hook or call directly:
#   bash .claude/plugins/security/hooks/osv-scan.sh
#   bash .claude/plugins/security/hooks/osv-scan.sh --format json

# Skip silently if osv-scanner is not installed.
if ! command -v osv-scanner &>/dev/null; then
    echo "osv-scan: osv-scanner not installed — skipping CVE gate (exit 0)." >&2
    echo "  Install: brew install osv-scanner" >&2
    exit 0
fi

# Recursive scan of the working tree (auto-detects supported lockfiles).
# Exit code propagates: 0 = clean, 1 = vulnerabilities found (gate fails).
exec osv-scanner --recursive "$@" .
