# EXAMPLES — Project-specific anti-patterns

Live document. Add entries when the agent (or you) repeatedly trips on the same kind of mistake. Captures lessons that don't belong in any single file's comment but are too project-specific for the global agent prompt.

Each entry follows a fixed format so the agent can scan and apply them.

## Format

```
## N. <Short rule name>

**Rule:** <one sentence that states the rule>

**❌ Violation signal:**
- <concrete signal — code shape / comment / structure>
- ...

**✅ What to do:**
- <concrete alternative>
- ...

**Why:** <reason, ideally with consequence>

**Where it lives:** <relevant file paths or modules>
```

## When to add an entry

- Noticed the agent make the **same mistake twice or more**
- Noticed **you yourself** recently made a mistake the system didn't catch
- An architectural pattern emerged that isn't obvious from the code
- Not for trivial style rules (that's covered by ruff/pyright)

## When to remove an entry

- The rule is now enforced automatically (lint, test, type check)
- The codebase changed so the violation is no longer possible
- The entry is stale (deprecated module, removed zone)

## Connections

- Link from the root `CLAUDE.md`: `Project-specific anti-patterns → [EXAMPLES.md](EXAMPLES.md)`
- Supplements, but doesn't duplicate, comments in the code

---

<!-- Remove this placeholder and add real rules as they accumulate.
     The minimal smoke example below is for illustrating the format. -->

## 1. (placeholder) Don't duplicate in a script what the Makefile already has

**Rule:** one-off commands for running tests / lint / build — via `make <target>`, not your own bash scripts.

**❌ Violation signal:**
```bash
# scripts/run_tests.sh
uv run pytest --cov=mypackage --cov-report=term-missing
```

**✅ What to do:**
```bash
# Use existing target
make test
```

**Why:** duplicate scripts drift from the Makefile and get forgotten when pytest flags change. Single entry point — `Makefile`.

**Where it lives:** `Makefile`, `scripts/`.
