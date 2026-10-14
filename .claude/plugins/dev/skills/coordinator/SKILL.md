---
name: coordinator
description: "Machine coordinator for parallel Claude sessions on one PC: owns machine.lock, grants load and stand windows, keeps the owner queue, writes start prompts for lane sessions in the project's form, relays between sessions. Use when the owner names this session the coordinator, or for 'watch the neighbours', 'who runs what', 'give out windows', 'write the prompt for the next task'."
---

# Coordinator — one session watches the machine, the queue and the neighbours

Owner's decision 2026-10-13: a **separate** session coordinates; it never runs a lane itself.
Born from one day of practice (2026-10-13): 7 load windows, 0 overlaps, one false red caught (C-4),
one polluted qex index stopped after 36 min instead of 80.
Participant side: `.claude/CLAUDE.md` → «Shared machine», `project-rules` §8, gate `scripts/machine_gate.sh`
(call it by the main checkout's absolute path — see §8; worktrees cut earlier lack the script).
Older stand rules (still the fallback): `docs/claude/memory/feedback_shared_stand_and_tests_protocol.md`.

## 1. What the coordinator owns — and what it does not

| Owns | Does not |
|---|---|
| `machine.lock` (the only writer) | run tests, stands, matrices or indexing itself |
| the order of windows; the owner-queue block of `plans/queue/ORDER.md` (read it with `plans_progress --queue`; lanes write their own plan lines) | answer for another role (a question to a lane lead stays with that lead) |
| start prompts for lane sessions (§5) | execute what a classifier denied in another session — the owner approves there |
| relaying facts between sessions | kill another session's process (each `qex.exe` is some session's MCP server) |
| registry lines in `plans/queue/defects.md` for cross-lane findings | decide product questions — list them for the owner |

## 2. machine.lock

Path: `D:\PROJECT_INNOTECH\Inspector_vision\machine.lock` (outside git, shared by every worktree). Plain lines:

```
coordinator: <session> | since <YYYY-MM-DD HH:MM>
window: <session> | quiet|heavy|stand | <what runs> | until ~<HH:MM>
waiting: <session> | quiet|heavy|stand | <what> | ~<N> min
stand: free | <session> measure|functional <SHA> <ports>
```

- `<session>` is the session name as `ListAgents` prints it, **without** the `[ref]` suffix (the first line reads
  «This session is inspector-bottles-84 [cfb773] …», or «This process's main session is …» inside a subagent).
- One `window:` line at most. Kinds: **quiet** — only the holder runs anything (A/B, flaky-test
  discriminators, timing measurements); **heavy** — the holder runs one heavy process at a time, others run
  `light` and non-timed `medium` (§3); **stand** — `run_sim_all.ps1` / backend stand, plus the `stand:` line;
  others run `light` only.
- `scripts/stand_gate` in live mode still requires `stand.lock` with its own line — the holder of a `quiet` or
  `stand` window takes `stand.lock` too; the `stand:` line here is the coordinator's record.
- Rewrite the whole file on every change with the Write tool; never append from two sessions.
- Holder gone from `ListAgents` while the coordinator lives → the coordinator closes the window and tells the queue.
- Coordinator gone from `ListAgents` → any session may delete the file after telling the peers; if a `stand:`
  line names a session, first check that ports 8765/8766 are free. No file = the old stand protocol.

## 3. What counts as heavy (measured 2026-10-13, 16 logical CPUs, ~2 GB free RAM)

| Work | Duration | Load |
|---|---|---|
| full framework suite `run_framework_tests.py` | ~17 min | timing tests flake under load |
| injection matrix | 6–20 min | one pytest per mutant |
| blind tester / e2e series with a simulator | 5–30 min | sim threads, Modbus TCP |
| qex full index (ollama embeddings) | 80+ min | GPU 89 %, −1.3 GB RAM |
| live stand `run_sim_all.ps1` | session-long | several processes |

Admission: no new heavy work while free RAM < ~1.5 GB or CPU > ~70 % (5-second sample of top processes).
Measure before you open a window; quote the numbers in the signal. The gate does not measure RAM — the coordinator does.

Command classes — decided by `classify` in `scripts/machine_gate.sh`; a session may raise its claim, never lower it.
`medium` is a command class, not a window kind.

| Class | Duration | Typical command | Without its own window |
|---|---|---|---|
| light | < ~2 min | one pytest process on own files | runs; skipped (exit 75) only in a foreign `quiet` window |
| medium | ~2–5 min | one module's tests directory: `pytest Services/<pkg>/tests` | runs; skipped (exit 75) in a foreign `quiet` or `stand` window |
| medium, timed | ~2–5 min | the same on a timed path, or `--timed` first | skipped (exit 75) — only in its own window, like heavy |
| heavy | > ~5 min | the table above; a whole package `pytest Services/<pkg>`, several directories, `-n`, no path, `make gate` / `make test` | skipped (exit 75) — only in its own window |

**timed** — the command touches a path listed in `scripts/machine_gate_timed.txt` (the list lives only there), or the
session passes `--timed` as the first gate argument; it can be set, never unset, and changes only `medium`. A module's
`tests` directory is `medium`; the package directory around it, a subdirectory of `tests` and a bare `pytest tests` are
`heavy`. The holder of any window runs every class. A skipped command is not retried by the gate — the session asks
for a window or runs it later. While `machine.lock` exists the PreToolUse hook `machine-gate-guard.sh` blocks any
command `classify` marks (bare `pytest`, `make gate` / `make test`, `run_framework_tests.py`, `run_sim_all`, …) that
bypasses the gate and prints the gated command to run instead.

## 4. Signals — fixed words, so a session can find them in its inbox

- lane → coordinator: `ready for window: <what>, ~<N> min, <K> process(es), quiet|heavy|stand`
  (a timed `medium` asks for a `heavy` window; `light` and non-timed `medium` ask for none)
- coordinator → holder: `window <session> open (<HH:MM>), ~<N> min: <what>; close with numbers`
- holder → coordinator: `window <session> closed (<HH:MM>): <numbers>`
- coordinator → waiting lanes: the new order and an ETA, every time the order changes.
A window can be split: a short lane slots in while a long lane pauses (2026-10-13: robot 10 min between
lane Zh's radius and its matrix). The lane on the owner's priority («visible result first») goes first
when two are ready. Update `machine.lock` before sending the signal, not after.

## 5. Start prompt template — every prompt the coordinator writes

Render it in Russian (the owner reads it); keep every block, write «none» rather than drop one.
The first line is the tab label. The owner finds lanes by tab titles only — the session name
(`inspector-bottles-xx`) is visible nowhere in the UI — and the auto-title drifts as the chat goes on
(2026-10-13), so the owner pastes this label into VS Code «Rename Session Tab» by hand.

```
ВКЛАДКА: Полоса <X> · <Task X.Y> <short title>
ROLE: lead of lane <name>, plan <plans/…/plan.md>, Task <X.Y> «<title>» (after <deps>, status from git, not the header).
READ FIRST: brief <tasks/X.Y.md> (if missing — manager writes it, project spec format «Task X.Y»),
  last result <tasks/…result.md>, handoff <docs/handoffs/…> if any.
GOAL: one sentence. ACCEPTANCE: literal criteria — test names, numbers, «xfail removed», stand numbers.
PIPELINE: as in .claude/CLAUDE.md «Task launch convention» (cite it, do not retell it); add only what is task-specific
  (solo-trivial stated aloud, which stages run in a window, «no commit to main, no push» for implementers).
BOUNDARIES: files you own; neighbours' files (lane, session, paths) you must not touch; known cross-lane traps.
LOAD: coordinator is <session> (name also in machine.lock). First message to it: your session name — the first
  line of your own ListAgents, never a name from a handoff. First line of every reply to the owner:
  the ВКЛАДКА label plus your session name — «Полоса <X> · <Task X.Y> · <session name>».
  Every test/stand command through the gate from project-rules §8 (absolute path); heavy only in your
  window — request it in advance: `ready for window: …`. Pass the session name to every agent brief.
COMMITS: Conventional Commits + Why:/Layer:/Refs: trailers (.claude/COMMIT_GUIDE.md); stage explicit paths;
  plan open/close is its own docs(plans) commit.
LIMITS: 2 iterations per loop, escalate on the 3rd one level up; owner decisions you need → list them, do not guess.
REPORT: Russian; numbers, not adjectives; a non-empty «what I left open / unreliable»; agentId table;
  at the end of the task — handoff and a new session (/clear), not /compact.
LESSONS: the traps the previous session of this lane hit (from its result or messages).
```

## 6. Judging a red that appeared during someone's window

A red timing test in a run that overlapped another lane's load is **not attributed** until a discriminator:
quiet machine ×10 on the base and ×10 on the branch; if the branch is green there, the same ×5+×5 under
the suspected load. Red on the base too → flaky test, registry line (`defects.md`), merge not blocked.
Red only on the branch → the branch's finding. Give the window as `quiet` for this.

## 7. Traps seen on this machine

- `idle` in `ListAgents` does not mean «runs finished»: background Bash keeps running. Ask, or list processes.
- A venv `python.exe` on Windows starts a second (base) interpreter: two processes per run, not two runs.
- Several `qex.exe` = several sessions' MCP servers; the one with high CPU may be a neighbour's. Stop
  ollama (its starter is known), not qex.
- qex progress: `get_indexing_status` shows the last committed index, not live progress; ollama's request
  count ≈ chunks. A chunk count far above the previous index means the ignore rules did not apply — stop.
- A check that nothing gates is not a gate, and `A && cmd || echo skipped` hides a red run as «skipped»
  with exit 0 — use `machine_gate.sh` (exit 75 = skipped).
- The gate does not enforce «one heavy process at a time» inside the holder's session — say it in the prompt.
- A restarted session signs with the old name from a handoff or a message (2026-10-13: twice in one evening,
  `51` as `a4`, `5c` as `1c`); the gate then exits 75. Trust `from-name` of its message, not its signature.
- The owner sees tab titles, not session names. In every report to the owner name a session by its lane and
  tab title, the session name in brackets; keep the lane ↔ tab ↔ name table current after each restart.

## 8. Handoff

The state is `machine.lock` plus `ORDER.md`; the coordinator's context holds nothing else of value.
Before closing: rewrite the lock with the new coordinator's name (or delete it), message every peer.
