---
name: shared-stand-and-tests-protocol
description: "Параллельные сессии на одной машине: замок стенда stand.lock с режимами measure/functional, замер только из отдельного дерева по SHA, A/B в одном окне, тесты не во время замера; при координаторе — machine.lock (shared machine, stand lock, coordinator)"
mechanism: [agents, live-stand]
metadata:
  type: feedback
---

**2026-10-13 (owner): when a coordinator session runs, `machine.lock` and skill `coordinator` replace
`stand.lock` and the message-by-message agreements below** — the stand is the `stand:` line, a `measure` is a
`quiet` window. Exception: `scripts/stand_gate` in live mode still requires `stand.lock` with its own line — the holder of a
`quiet`/`stand` window takes it too. This file stays the rule when no `machine.lock` exists. On 2026-10-13 no session remembered
this protocol: a rule kept only in memory was not triggered, so the trigger now lives in `.claude/CLAUDE.md`
and `project-rules` §8.

Owner's standing rule (2026-09-30, "запомнить механизм, чтоб мне не писать каждый раз"): several Claude
sessions work on this repo at once on ONE machine. Follow this without asking the owner; agree deviations
with the neighbour session by SendMessage.

**Stand**
1. Lock file `D:\PROJECT_INNOTECH\Inspector_vision\stand.lock`, one line: session | time | mode | SHA | what is up (ports).
   File exists = busy. Check before raising, delete after, message the neighbour both times.
2. Modes: `measure` — numbers that go into a report (CPU, fps, stale, capacity): exclusive AND quiet — no second
   stand, no heavy tests by anyone. `functional` — "does it work" (UI, sim, live Chrome): another functional run on
   other ports is fine, a measure is not.
3. Measurements only from one stand worktree `.claude/worktrees/stand`, always detached at an explicit SHA
   (`git -C .claude/worktrees/stand checkout --detach <sha>`). Never commit or merge others' work there. SHA goes
   into the lock line and the report. Functional runs may start from one's own worktree.
4. A/B inside ONE lock window: baseline SHA then candidate SHA, same recipe and duration. Never compare numbers
   from different windows.
5. A shared integration branch only to measure the combined effect before merging to main — measured by SHA too.
6. Before a `measure`, message the neighbour in advance; if it has a `functional` run up, it stops it and confirms —
   only then take the lock.
7. Data outside git: when the stand worktree is created, copy in the prototype `data/` from the main tree and
   `data/line_sim/` from worktree `ls-look` (belt_tile.png, belt_photo_full.png, letters_ink/, letters_ink_disk.png,
   letter catalog). Afterwards the stand is self-contained. If data changed, say so in the report next to the SHA.
8. Stale lock: if the lock's session is absent from `ListAgents`, the lock may be removed only after checking that
   ports 8765/8766 are free (or after `system.shutdown`); tell the neighbour that a foreign lock was removed.

**Tests**
9. Tests, radius, break-injection run in one's own worktree: main `.venv` + `PYTHONPATH=<worktree>`, no `uv sync`
   (pulls CPU torch); injection only on committed code ([[feedback-injection-scripts-on-committed-code]]).
10. Full suite, radius, e2e, timing tests and injection never run during someone else's `measure`: they add noise to
   the measurement, and stand load flakes timing tests (pacing ±2 ms flake seen under load, 2026-09-30).
11. The main working tree belongs to the session that owns its branch; others work in worktrees and merge into a
   branch only through its owner.

**Why:** the owner proposed "stand only on main / one worktree where every session merges and measures" to avoid
double launches and extra load. Load comes from simultaneous runs, which the lock already prevents. Merging every
session's work into the measured tree would destroy attribution of a delta to one change, and the whole point of
measuring is capacity planning ([[project-capacity-planning-goal]]). Also on 2026-09-30 a neighbour started
`merge main` in the shared main tree while this session was committing there, and nearly duplicated Task 4.5.

**How to apply:** before any stand run, read the lock; pick the mode; for `measure` check out the stand worktree at
the SHA(s) and tell the neighbour to hold heavy tests. Before a heavy test run, check that no `measure` lock is held.
Agreed with session inspector-bottles-79 (line-sim) on 2026-09-30.
