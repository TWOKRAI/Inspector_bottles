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

## security-guidance (a separate, CONSUME plugin — Task 4.2)

`security-guidance` is the official Anthropic marketplace plugin for **edit-time**
regex/substring reminders plus optional model-backed end-of-turn/commit review
(docs: <https://code.claude.com/docs/en/security-guidance>). It is a **different
plugin id** in `enabled.yaml` (`security-guidance: source:
"security-guidance@claude-plugins-official"`) from this `security` plugin (SAST/
CVE/SBOM CLIs) — CONSUME, so Claude Code installs and wires it; this seed ships
**no** `plugins/security-guidance/` folder for it (verified empirically: a bare
lockfile entry with no local plugin directory resolves to `plugin doctor`/`plugin
list` status `external`, never `missing`/`broken` — see
`compose/collect.py`'s `consume_external` pass). The one file it needs —
`templates/security-patterns.template.json`, this plugin's per-edit pattern seed
(three starter rules: `hardcoded_secret_prefix`, `skip_commit_hooks`,
`edit_knowledge_raw`) — lives here because it is thematically part of the
`security` domain, not because `security-guidance` has a plugin folder of its
own. `init` copies it once to `.claude/security-patterns.json` (idempotent —
never overwrites an owner's edits, like `commit-layers.txt`).

For the model-backed layers, add `.claude/claude-security-guidance.md` with your
project's threat model (per-project — not shipped here, see docs above).
