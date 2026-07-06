# security — SAST + CVE + SBOM

Deterministic security gates that complement the LLM-only `/security-review`.
**No MCP server** — every tool is a CLI the wrappers shell out to (Semgrep's
`semgrep/mcp` is archived; OSV/Syft are CLIs). The plugin is **inert without the
tools installed**: each command/hook skips with a notice and exits 0, so day-1
projects and CI stay green until you add the binary.

## Commands

| Command | Wraps | Default |
|---|---|---|
| `/security:scan` | `scripts/sast_scan.py` → `semgrep --config auto` | on (command) |
| `/security:cve`  | `osv-scanner` (lockfile CVE scan) | on (ship/CI gate) |
| `/security:sbom` | `scripts/sbom_gen.py` → `syft`/`cdxgen` (CycloneDX) | off (opt-in artifact) |

## Hooks (opt-in — NOT registered by default)

The plugin ships hook scripts but does **not** wire them in `plugin.json`
(per-edit Semgrep is slow/noisy; CVE-on-every-edit is overkill). Opt in by adding
them to your project `.claude/settings.json`:

- `hooks/semgrep-scan.sh` — `PostToolUse` SAST on edited files (slow → opt-in).
- `hooks/osv-scan.sh` — lockfile CVE scan, suitable for a pre-push / CI gate.

Both follow the seed's skip-if-binary-absent contract and exit 0.

## Install the tools

```bash
pipx install semgrep                       # SAST
brew install osv-scanner                    # or: go install github.com/google/osv-scanner/cmd/osv-scanner@latest
brew install syft                           # SBOM (or: npm i -g @cyclonedx/cdxgen)
```

> **Trivy is intentionally avoided** as an SBOM generator (Feb–Mar 2026
> supply-chain compromise). Prefer `syft`/`cdxgen`; see `scripts/sbom_gen.py`.

## Permissions

`settings.partial.json` allow-lists `semgrep`, `osv-scanner`, `syft`, `cdxgen`
so the scans run without a confirmation prompt once the plugin is enabled.
