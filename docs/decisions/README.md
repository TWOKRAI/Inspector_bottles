# docs/decisions/ — Architecture Decision Records (ADRs)

One file per architectural decision, written when the decision is taken.

## Naming

`docs/decisions/NNNN-kebab-case-title.md` — zero-padded sequential number, immutable once accepted.

Examples: `0001-use-uv-instead-of-poetry.md`, `0002-postgres-over-sqlite.md`.

## Template

New ADRs start from [`.claude/plugins/core/templates/ADR.template.md`](../../.claude/plugins/core/templates/ADR.template.md):

- **Context** — what forces drove the decision
- **Decision** — what we chose
- **Consequences** — trade-offs accepted

## Lifecycle

- **Proposed** → discussion in PR
- **Accepted** → merged, immutable
- **Superseded by NNNN** → replaced; original stays as history

Never edit an Accepted ADR — write a new one that supersedes it. Link both directions (`Supersedes: 0007`, `Superseded by: 0042`).
