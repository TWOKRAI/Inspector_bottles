---
name: module-contract
description: >
  Activates when creating a new public module, package, or class with a
  public API. Enforces contract-first discipline: README + Protocol
  interface (or module docstring for lite) + Design-by-Contract pre/post
  + contract tests. Two levels: full (package module) / lite (single file).
  Triggers: "create module", "new module", "new package", "new public class",
  "design module", "contract-first", "module boundary", "/module-contract".
---

# Contract-first module design

The agent is about to create a new public module. Before writing
implementation code, follow this discipline so a future reader (human or
agent) can understand the module by reading **README + interface + contract
tests** — not the implementation.

## Decision tree — which level applies

```
Is the module name prefixed with "_"? ──► none (private — skip discipline)
Is it < 50 lines and has no __all__?   ──► none (utility — skip)
Is it ≥ 3 files OR ≥ 2 public classes? ──► full
Otherwise (single file, public API)    ──► lite
```

If unsure, **ask the user** — don't pick silently.

## Full scaffold (package module)

```
src/<package>/<module>/
├── README.md            # Purpose / Public API / Usage (3 examples) / Boundaries / Stability
├── __init__.py          # __all__ + re-export only from interface.py
├── interface.py         # Protocol/ABC + Design-by-Contract docstrings
├── _facade.py           # OPTIONAL — if module has > 3 public classes
└── _impl/               # private implementation (not imported from outside the module)
    ├── __init__.py
    └── <concrete>.py

tests/contract/test_<module>.py    # readable as documentation
tests/unit/test_<module>_<impl>.py # implementation-specific tests
```

**README.md must have these sections:**

```markdown
# <module> — <one-line purpose>

## Purpose
What problem this module solves. 2-3 sentences.

## Public API
Symbols re-exported from __init__.py (matches __all__). For each:
- `Function/Class` — one-line description, link to interface.py

## Usage
Three concrete examples (not pseudocode). Real input, real output.

## Boundaries
- What this module does NOT do
- Which modules it depends on
- Which modules import from it (high-level)

## Stability
contract | lite | partial | legacy
```

## Lite scaffold (single-file module)

```python
"""<module> — <one-line purpose>.

Purpose:
    What problem this module solves. 2-3 sentences.

Public API:
    - func_a — one-line description
    - ClassB — one-line description

Stability: lite
"""

__all__ = ["func_a", "ClassB"]

def func_a(...) -> ...:
    """<one-line summary>.

    Pre:
      - <precondition>
    Post:
      - <postcondition>
    """
```

Plus `tests/contract/test_<module>.py` with executable examples.

## Design by Contract — format

DbC lives in docstrings as a convention (no `icontract` / `deal` runtime
dependency). Contract tests verify pre/post **executably**.

```python
def transfer(from_acc: Account, to_acc: Account, amount: Decimal) -> None:
    """Move amount from one account to another.

    Pre:
      - amount > 0
      - from_acc.balance >= amount
      - from_acc != to_acc
    Post:
      - from_acc.balance == old(from_acc.balance) - amount
      - to_acc.balance == old(to_acc.balance) + amount
    Invariants:
      - total balance across all accounts is unchanged
    """
```

Use the words **Pre:**, **Post:**, **Invariants:** literally — reviewer and
tooling grep for them.

## Contract test as example

A contract test reads like documentation. Names are sentences, structure
is given/when/then. Tests live in `tests/contract/`, separate from
implementation tests.

```python
def test_transfer_moves_amount_between_accounts():
    # given two accounts with known balances
    src = Account(balance=Decimal("100"))
    dst = Account(balance=Decimal("50"))

    # when transferring 30 from src to dst
    transfer(src, dst, Decimal("30"))

    # then balances reflect the move
    assert src.balance == Decimal("70")
    assert dst.balance == Decimal("80")


def test_transfer_rejects_zero_amount():
    # pre-condition violation: amount must be > 0
    src = Account(balance=Decimal("100"))
    dst = Account(balance=Decimal("50"))

    with pytest.raises(ValueError):
        transfer(src, dst, Decimal("0"))
```

Every Pre/Post line from the docstring should have at least one contract
test demonstrating it (positive or negative).

## Public API discipline

- `__all__` is the source of truth for what's public. If it's not in
  `__all__`, callers must not import it.
- For full scaffold: `__init__.py` re-exports only from `interface.py`.
  Concrete implementations in `_impl/` are never imported from outside the
  module — cross-module callers can't reach into another module's `_impl/`.
- Private helpers inside the module: prefix with `_`.

## Stability levels

Marked in README (full) or module docstring (lite):

- **contract** — full scaffold, all four artefacts present
- **lite** — lite scaffold, single-file with docstring contract
- **partial** — has some artefacts (e.g. README + Protocol) but not all
- **legacy** — old-style module, not migrated yet

New modules: **contract** or **lite**. Existing modules keep their level
until touched. When touched, raise the level if cheap; if not, document
"still legacy" in the PR.

## Workflow (what the agent does)

1. Decide level using the decision tree. If unclear, ask the user.
2. **Full:** create directory `src/<package>/<module>/` with the 4 files
   (README, `__init__.py`, `interface.py`, `_impl/`). Use the structures
   above as templates — substitute the module name, fill the sections.
3. **Lite:** create `src/<package>/<module>.py` with module docstring,
   `__all__`, and DbC in public functions.
4. Create `tests/contract/test_<module>.py` with at least one given/when/then
   test per Pre/Post line in the docstring.
5. Only then write the implementation.
6. Smoke: `python -m compileall src/<package>/<module>` + run contract tests.

The slash-command `/dev:scaffold-module` is **not** required — it's a
convenience wrapper (currently out of scope, see plan backlog). For now,
the agent generates files directly from the templates above.

## When NOT to use this skill

- Private module (name prefixed with `_`).
- Utility module < 50 lines with no `__all__` (helpers, constants).
- Test-only module (under `tests/`).
- Refactoring inside an existing module without changing its public API.
- One-line bug fix.

## Notes on project layout

This skill assumes **src-layout** (`src/<package>/...`). If the project
uses flat layout or another structure, adapt paths accordingly. If unsure,
read `.claude/modes/_stack.md` → "Layout" section, or ask the user.

## CONTEXT.md per-module — recommendation

When creating a non-trivial module (full or lite), also recommend creating
`<module>/CONTEXT.md` from `.claude/templates/CONTEXT.template.md` if **any**
of the following hold:

- Module has ≥1 non-obvious **Gotcha** (footgun, threading constraint,
  ordering requirement) that's not visible from `interface.py`
- Module has ≥2 **design decisions** worth recording (without going to
  full `DECISIONS.md` ADR yet)
- Module introduces **local glossary terms** (words meaning something
  different from project-wide usage)

CONTEXT.md is opt-in (you don't auto-create it for every module). When
you decide it's warranted, mention this in your "files created" report
so the human can review. After creating, suggest running `/sync-context`
to update `docs/PROJECT_CONTEXT.md`.

For tracking formal ADR with numbered history → `<module>/DECISIONS.md`
(see `.claude/templates/DECISIONS.template.md`). For one-off global
architectural decisions → use `/adr` (creates in `docs/claude/DECISIONS/`).

## Output format (when agent reports)

```
**Module:** <name>
**Level:** full | lite | none (with reason if none)
**Files created:**
  - src/<package>/<module>/README.md
  - src/<package>/<module>/__init__.py
  - src/<package>/<module>/interface.py
  - src/<package>/<module>/_impl/<concrete>.py
  - tests/contract/test_<module>.py
**Contract:** Pre/Post lines covered by tests: N/M
**Next:** implementation in _impl/ — separate task
```
