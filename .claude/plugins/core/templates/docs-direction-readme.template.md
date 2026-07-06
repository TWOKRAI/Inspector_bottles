# docs/direction/ — living product specs

Living docs that describe the **current** intent of the product / feature. Updated when intent changes; old state lives in git history.

## Workflow

1. **`/dev:spec:spec <topic>`** → spec-writer creates / updates `docs/direction/<topic>.md`.
2. **`/dev:spec:spec-sync`** → reconciles spec ↔ implementation (gaps in either direction).
3. **`/dev:plan`** reads the relevant spec(s) as primary context for new tasks.

## Format

Each spec describes:

- **Goal** — one paragraph: what user problem this solves.
- **Behavior** — observable behavior, edge cases. Avoid implementation details.
- **Non-goals** — explicit list of what this does NOT do.
- **Acceptance** — concrete checks (test ideas, manual flows).

## Don't

- Don't put implementation plans here — those go to `plans/`.
- Don't put decisions / rationale here — those go to `docs/decisions/`.
- Don't backdate or version specs — git history is the version log.
