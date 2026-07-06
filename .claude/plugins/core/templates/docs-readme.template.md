# docs/ — project documentation

| Subdir | Purpose | Owner |
|--------|---------|-------|
| `sessions/` | Daily session journals (continuity between Claude runs) | `/core:team:wrap-up`, hooks |
| `direction/` | Living product specs — current state of WHAT is being built | `/dev:spec:spec`, `/dev:spec:spec-sync` |
| `decisions/` | Architecture Decision Records (ADRs) — WHY a choice was made | tech-writer / developer |

## Conventions

- **Sessions** are ephemeral context. Don't put rationale or specs here.
- **Direction** docs are *living* — they describe the system as it is now, not history. Old direction lives in git.
- **Decisions** are immutable once accepted — supersede with a new ADR, don't rewrite.

## Generated artifacts

Architecture diagrams produced by `make diagrams` land in `docs/diagrams/` (gitignored — regenerate as needed).
