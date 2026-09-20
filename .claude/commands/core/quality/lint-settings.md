---
description: Check .claude/settings.json — are critical deny/ask/allow and hooks in place?
---

Run the `settings.json` invariant check:

```bash
uv run --no-project python scripts/lint_settings.py
```

What it checks:

1. **`deny` contains critical patterns:** `--no-verify`, `git push --force`, `git reset --hard`, `git clean -f`, `sudo`, `chmod 777`, `mkfs`, `dd if=`
2. **Secrets are protected:** `Write/Edit(**/.env)`, `**/*.pem`, `**/*.key`, `**/id_rsa`, `**/id_ed25519`
3. **`allow` doesn't contain slop vectors:** `uv add *`, `pip install *`, `npx *`, `cp *`, `chmod *`, `git merge *`, `git rebase *`, `sudo *`, etc.
4. **Hooks are wired:** `validate-safe-command`, `protect-readonly`, `protect-branch`, `autoformat-python`, `check-imports`, `restore-context`, `session-health-check` (the `session-end-daily-log` Stop hook was dropped in v0.4.0 — logging moved to pre-commit)

Exit codes:
- `0` — all OK
- `1` — required invariants violated (CI should fail)
- `2` — warnings only (fixing recommended)

Run in strict mode (warnings → fail):
```bash
uv run --no-project python scripts/lint_settings.py --strict
```

**When to call:**
- Before `/dev:ship` if `settings.json` was edited in this session
- In the CI workflow on every PR
- After `claude-kit upgrade --apply` to make sure the upgrade didn't drop protection
- When you suspect someone locally weakened permissions
