---
description: Audit for secret leaks (API keys, JWT, private keys, hardcoded passwords) via regex
---

Run an audit of secret leaks in the sources:

```bash
uv run --no-project python scripts/secrets_audit/secrets_audit.py
```

What it catches: AWS / GCP / Azure keys, GitHub/GitLab PATs, OpenAI / Anthropic API keys, Stripe live keys, Slack / Telegram tokens, JWT, PEM/OpenSSH private keys, basic-auth in a URL, generic `password|secret|token = "..."` assignments.

Pattern config and allowlist: [scripts/secrets_audit/secrets_audit.toml](../../scripts/secrets_audit/secrets_audit.toml). Details and exit codes — [README.md](../../scripts/secrets_audit/README.md).

Useful options:
- `uv run --no-project python scripts/secrets_audit/secrets_audit.py --root src` — a specific subdirectory only.
- `uv run --no-project python scripts/secrets_audit/secrets_audit.py --format json` — for CI/notifications.
- `uv run --no-project python scripts/secrets_audit/secrets_audit.py --no-strict` — a report without failing (exit 0 even with findings).

**Exit codes:** `0` — clean, `1` — findings present (under `strict=true`), `2` — config error.

**When to use:**
- Before a commit / in the `pre-push` hook (together with sentrux).
- In CI as a gate before merging into main.
- When onboarding an open-source repo — searching for development artifacts.

**Notes:**
- Inline suppression: add `# secrets-audit: ignore` on the same line for one-off exclusions (for example, a deliberately fake test key in a documentation snippet).
- Test fixtures (`tests/fixtures/**`, `tests/data/**`, `**/test_*.py`) are already in the allowlist — adjust the config to your stack.
- Regex is not an AST: it doesn't distinguish a literal from a comment. For a deep audit of the git history, see `gitleaks` / `trufflehog`.

$ARGUMENTS
