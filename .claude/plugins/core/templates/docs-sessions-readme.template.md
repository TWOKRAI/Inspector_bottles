# docs/sessions/ — session journals

One file per work session, written automatically by `/core:team:wrap-up` (or the `session-end-daily-log.sh` hook if enabled).

## Format

`docs/sessions/YYYY-MM-DD.md` — one file per day (multiple sessions on the same day append).

Each entry covers:
- What was done (concrete: files, tests, features)
- What was left unfinished (and why — blocker, half-done refactor)
- Next step (where to resume)

## Why this matters

- Cross-session continuity: a fresh Claude session reads the latest entry to recover context.
- `/core:memory:search <query>` indexes this directory alongside `.claude/memory/`.
- Pairs with `/core:team:handoff` (cross-machine) and `MEMORY.md` (long-term facts).

## Don't

- Don't write code rationale here — that goes in commit messages (`Why:`).
- Don't write architecture decisions here — those go in `docs/decisions/`.
- Sessions are ephemeral context, not authoritative documentation.
