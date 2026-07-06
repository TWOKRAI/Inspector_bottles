#!/usr/bin/env python3
"""lint_settings.py — enforce hardening invariants on .claude/settings.json.

Why: the seed ships a hardened `permissions` policy (allow/ask/deny). When
the seed is applied to a new project, or when settings.json is edited locally
("temporary allow that never gets reverted"), defensive entries silently
disappear. This linter is the safety net that catches that drift.

Checks:
  1. Required `deny` patterns are present (--no-verify, push --force, reset --hard, ...)
  2. `Write`/`Edit` on secrets paths is denied (.env, *.pem, *.key, id_rsa, ...)
  3. Forbidden patterns are NOT in `allow` (uv add, pip install, npx, cp *, chmod +x*, ...)
  4. Required hooks are wired in (validate-safe-command, protect-readonly, protect-branch, ...)

Exit codes:
  0 — all invariants hold
  1 — one or more REQUIRED invariants violated
  2 — only WARNINGs (recommended but not required)

Usage:
  python scripts/lint_settings.py                       # lint .claude/settings.json
  python scripts/lint_settings.py --strict              # warnings also fail with exit 1
  python scripts/lint_settings.py path/to/settings.json # explicit path

Stdlib only — no extra deps so it can run in any venv / pre-commit hook.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# ─── Invariants ───────────────────────────────────────────────────────────────

# Patterns that MUST appear somewhere in permissions.deny (regex match against
# each deny entry). Each tuple = (regex, human description).
REQUIRED_DENY: list[tuple[str, str]] = [
    (r"--no-verify", "git commit/push --no-verify must be denied (hook bypass)"),
    (r"git push --force", "git push --force must be denied"),
    (r"git push -f", "git push -f (short form) must be denied"),
    (r"git reset --hard", "git reset --hard must be denied"),
    (r"git clean -[fF]", "git clean -f* must be denied (destructive)"),
    (r"sudo ", "sudo * must be denied"),
    (r"chmod 777", "chmod 777 * must be denied"),
    (r"mkfs", "mkfs* must be denied (disk format)"),
    (r"dd if=", "dd if=* must be denied (disk-level write)"),
]

# Secrets that MUST NOT be writable / editable by the agent.
# Each entry = path pattern that must appear in BOTH Write(...) and Edit(...) deny.
REQUIRED_SECRET_DENY: list[str] = [
    "**/.env",
    "**/.env.local",
    "**/*.pem",
    "**/*.key",
    "**/id_rsa",
    "**/id_ed25519",
]

# Patterns that MUST NOT be in `allow` (regex against allow entries).
# These should live in `ask` (user confirmation) or `deny`.
FORBIDDEN_ALLOW: list[tuple[str, str]] = [
    (r"^Bash\(uv add\b", "uv add * must require confirmation (slopsquatting risk)"),
    (r"^Bash\(uv pip install\b", "uv pip install * must require confirmation"),
    (
        r"^Bash\(pip install\b",
        "pip install * must require confirmation (slopsquatting)",
    ),
    (r"^Bash\(npm install\b", "npm install * must require confirmation"),
    (r"^Bash\(npm i\b", "npm i * must require confirmation"),
    (r"^Bash\(npx\b", "npx * must require confirmation (arbitrary package execution)"),
    (r"^Bash\(pnpm\b", "pnpm * must require confirmation"),
    (r"^Bash\(yarn\b", "yarn * must require confirmation"),
    (
        r"^Bash\(cp \*\)$",
        "bare 'cp *' must require confirmation (can overwrite anything)",
    ),
    (r"^Bash\(chmod \+x\*\)$", "bare 'chmod +x*' must require confirmation"),
    (r"^Bash\(chmod \*\)$", "bare 'chmod *' must require confirmation"),
    (r"^Bash\(rm \*\)$", "bare 'rm *' must require confirmation or be denied"),
    (r"^Bash\(git merge \*", "git merge * must require confirmation"),
    (r"^Bash\(git rebase ", "git rebase * must require confirmation"),
    (r"^Bash\(git cherry-pick ", "git cherry-pick * must require confirmation"),
    (
        r"^Bash\(git reset \*",
        "git reset * (non-deny variants) must require confirmation",
    ),
    (
        r"^Bash\(git checkout \*\)$",
        "bare 'git checkout *' must require confirmation (can wipe local state)",
    ),
    (r"^Bash\(curl \*\)$", "bare 'curl *' must require confirmation"),
    (r"^Bash\(wget \*\)$", "bare 'wget *' must require confirmation"),
    (r"^Bash\(docker\b", "docker * must require confirmation"),
    (r"^Bash\(sudo\b", "sudo * must be in deny, not allow"),
]

# Required hooks — (lifecycle event, substring match on command field).
# NOTE: Stop-хук session-end-daily-log.sh убран как required с seed v0.4.0 —
# журналирование переведено на pre-commit (hooks/git/pre-commit-session-log.sh),
# чтобы запись попадала в коммит, а не висела как untracked. Stop-вариант
# остался как fallback для проектов без pre-commit (см. docstring файла).
REQUIRED_HOOKS: list[tuple[str, str]] = [
    ("PreToolUse", "validate-safe-command.sh"),
    ("PreToolUse", "protect-readonly.sh"),
    ("PreToolUse", "protect-branch.sh"),
    ("PostToolUse", "autoformat-python.sh"),
    ("PostToolUse", "check-imports.sh"),
    ("PostCompact", "restore-context.sh"),
    ("SessionStart", "session-health-check.sh"),
]

# ─── Linter ───────────────────────────────────────────────────────────────────


def load_settings(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"error: {path} not found", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"error: {path} is not valid JSON: {e}", file=sys.stderr)
        return None


def check_deny(deny_list: list[str]) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    for pattern, desc in REQUIRED_DENY:
        compiled = re.compile(pattern)
        if not any(compiled.search(d) for d in deny_list):
            errors.append(f"deny missing required pattern: {desc}")
    return errors, warnings


def check_secret_protection(deny_list: list[str]) -> list[str]:
    errors = []
    write_patterns = [d for d in deny_list if d.startswith("Write(")]
    edit_patterns = [d for d in deny_list if d.startswith("Edit(")]
    for secret in REQUIRED_SECRET_DENY:
        write_entry = f"Write({secret})"
        edit_entry = f"Edit({secret})"
        if write_entry not in write_patterns:
            errors.append(f"deny missing Write protection for {secret}")
        if edit_entry not in edit_patterns:
            errors.append(f"deny missing Edit protection for {secret}")
    return errors


def check_forbidden_allow(allow_list: list[str]) -> list[str]:
    errors = []
    for pattern, desc in FORBIDDEN_ALLOW:
        compiled = re.compile(pattern)
        matches = [a for a in allow_list if compiled.search(a)]
        for m in matches:
            errors.append(f"FORBIDDEN in allow: {m!r} — {desc}")
    return errors


def check_hooks(hooks_root: dict) -> list[str]:
    warnings = []
    for lifecycle, needle in REQUIRED_HOOKS:
        bucket = hooks_root.get(lifecycle, [])
        found = False
        for entry in bucket:
            for h in entry.get("hooks", []):
                if needle in h.get("command", ""):
                    found = True
                    break
            if found:
                break
        if not found:
            warnings.append(f"hook missing: {lifecycle} → {needle}")
    return warnings


def lint(path: Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for the settings.json at path."""
    s = load_settings(path)
    if s is None:
        return ["could not load settings.json"], []

    perms = s.get("permissions", {})
    allow = perms.get("allow", [])
    deny = perms.get("deny", [])
    hooks_root = s.get("hooks", {})

    errors: list[str] = []
    warnings: list[str] = []

    e1, w1 = check_deny(deny)
    errors += e1
    warnings += w1

    errors += check_secret_protection(deny)
    errors += check_forbidden_allow(allow)
    warnings += check_hooks(hooks_root)

    return errors, warnings


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    explicit = next((a for a in argv[1:] if not a.startswith("--")), None)

    if explicit:
        path = Path(explicit)
    else:
        candidates = [Path(".claude/settings.json"), Path("settings.json")]
        path = next((c for c in candidates if c.exists()), None)
        if path is None:
            print(
                "error: no .claude/settings.json found — pass path explicitly",
                file=sys.stderr,
            )
            return 1

    errors, warnings = lint(path)

    print(f"Checked: {path}")
    print(f"Errors:  {len(errors)}")
    print(f"Warns:   {len(warnings)}")
    if errors:
        print()
        print("ERRORS:")
        for e in errors:
            print(f"  ✗ {e}")
    if warnings:
        print()
        print("WARNINGS:")
        for w in warnings:
            print(f"  ! {w}")

    if errors:
        return 1
    if warnings and strict:
        return 1
    if warnings:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
