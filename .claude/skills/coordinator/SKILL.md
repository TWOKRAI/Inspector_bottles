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
merging: <session> | <branch> | since <HH:MM>
```

- `<session>` is the session name as `ListAgents` prints it, **without** the `[ref]` suffix (the first line reads
  «This session is inspector-bottles-84 [cfb773] …», or «This process's main session is …» inside a subagent).
- After every hand edit of `machine.lock` run `machine_gate.sh status`: a malformed line returns rc=2 to every
  lane's gate. `waiting:` and `window:` need all four fields; the kind is only quiet|heavy|stand (a timed
  `medium` waits and runs as `heavy`).
- One `window:` line at most. Kinds: **quiet** — only the holder runs anything (A/B, flaky-test
  discriminators, timing measurements); **heavy** — the holder runs one heavy process at a time, others run
  `light` and non-timed `medium` (§3); **stand** — `run_sim_all.ps1` / backend stand, plus the `stand:` line;
  others run `light` only.
- `scripts/stand_gate` in live mode still requires `stand.lock` with its own line — the holder of a `quiet` or
  `stand` window takes `stand.lock` too; the `stand:` line here is the coordinator's record.
- **Self-service (owner, 2026-10-27):** lanes queue, hold and hand over windows themselves through `machine_gate.sh`; the coordinator is not asked for a window and does not write `waiting:` / `window:` lines for them.
  - `request <s> quiet|heavy|stand <min> <what…>` — a lane calls it only when it can start NOW; prints `GRANTED until ~HH:MM` or `QUEUED position N`; a repeated call does not duplicate the line.
  - `wait <s> [--timeout <min>]` — blocks until the window is the caller's (rc 0; 124 = timeout); run it in the background, the harness notifies. It promotes the first `waiting:` when no window is open and prints `OVERDUE <s> +N min` for a foreign window past its `until`.
  - `release <s>` — closes the caller's own window and opens the next `waiting:` (FIFO); on a queued request it cancels it (`CANCELLED`); a foreign window → rc 2. `extend <s> <min>` moves the caller's `until`.
  - `merge-begin <s> <branch>` / `merge-end <s>` — one `merging:` slot per lock; refused while the slot is taken or a `quiet` window is open. These replace «сливаю» / «ок».
  - An overdue window is never taken automatically (the holder may still run a process): only `grant` / `close` by the coordinator or the owner remove a foreign window. `promote` is not run by `grant`, `close` or `merge-end`: after a manual `close` the next `wait` or `request` promotes.
  - The coordinator no longer holds a manual `waiting:` for a lane; before a lane merges it removes the stale ones (a `waiting:` left from the old protocol is promoted like any request).
- Hand edits stay for the coordinator only (a broken lock gives rc=2 to every lane): `machine_gate.sh grant|close <coordinator> …` (checks the format, writes atomically); never append from two sessions. `machine_gate.sh status` prints the lock with free RAM and CPU.
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

Windows and merges are not signals any more (owner, 2026-10-27): a lane takes them from the gate (§2 self-service) and no
message is sent. Sessions are messaged only for: a question for the owner, ownership of a file outside the lane's
boundary, a finding in code the lane does not own. A timed `medium` asks for a `heavy` window; `light` and non-timed
`medium` ask for none.
- lane: `request <s> quiet|heavy|stand <min> <what…>` when it can start NOW (not "to be in line early"), `wait` in the
  background, `release` with the numbers in its own report file; `merge-begin` / `merge-end` around a merge.
- coordinator → lane: only the order of the queue when it changes by a decision of the owner, never by the gate.
- lane → coordinator: no report message. The result lives in the lane's report file (template §5 REPORT); the
  coordinator reads the files and folds them into the day table of `docs/sessions/<YYYY-MM-DD>.md` (lane, task, result, models, tokens, open) and plans from it.
A window can be split: a short lane slots in while a long lane pauses (2026-10-13: robot 10 min between
lane Zh's radius and its matrix). The queue is FIFO by the gate; the owner's priority («visible result first») is
applied by the coordinator with `grant` / `close`, not by messages.

**Message economy (owner, 2026-10-25).** Every message wakes the receiver, which re-reads its whole context
(a lead often holds 100k+), so a message costs the receiver's context, not its text. Lanes write only:
a question for the owner, files outside their boundary before an edit, a finding in code they do not own. A window
request, ОТЧЁТ and «сливаю» are gone (gate: `request` / `merge-begin`; report: the file); a registry line is a file
in `plans/queue/inbox/` (format: its README), folded into the registry by the coordinator or any session about
twice a day, which assigns the C-NN numbers. No acknowledgements («принял», «понял»). The coordinator replies
only when the lane must act or wait; a question to every lane only when it cannot wait for that lane's next signal.

**Session reset at a merge (owner, 2026-10-25).** A lane session that runs task after task re-reads every
finished task on each request; the usage panel put this at 61 % of the day. The reset point is «влит <sha>»:
by then the work lives in git, the plan, ORDER and the registry, and the task's agents are no longer
re-summoned. Before «влит» the lane commits a short handoff (`docs/handoffs/<date>_<lane>-<task>-merged.md`,
10–15 lines: next ORDER line, what stays open, findings for the coordinator). On «влит» the coordinator sends
the owner one line: «<lane>: граница — /clear во вкладке <label>, затем вставить: `Ты полоса <X>, координатор
<name>. Прочитай <handoff> и продолжай.`». Inside a task (stage 0 → tester → developer → injections → review)
nobody clears — the lead holds the predictions and the agentId table; past ~150k there it is `/compact`
(focus: files + tests + plan path). A pause to the next day is the same boundary. After a reset the session
name may change: the lane sends its name first, as at any start. The coordinator itself resets once a day,
after its evening handoff.

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
  window — take it yourself with `request` / `wait` / `release` (§2), no message. Merge: `merge-begin` /
  `merge-end` instead of «сливаю» / «ок». Pass the session name to every agent brief.
COMMITS: Conventional Commits + Why:/Layer:/Refs: trailers (.claude/COMMIT_GUIDE.md); stage explicit paths;
  plan open/close is its own docs(plans) commit. Before a merge into main (owner, 2026-10-21): rebase on main, then
  validate.py + multiprocess_prototype/backend/tests + the framework suite (heavy, in your window); every red named
  against plans/queue/defects.md — a red not in the registry blocks the merge until the coordinator registers it.
LIMITS: 2 iterations per loop, escalate on the 3rd one level up; owner decisions you need → list them, do not guess.
REPORT: Russian; numbers, not adjectives; a non-empty «what I left open / unreliable»; agentId table;
  at the end of the task — handoff and a new session (/clear), not /compact.
  Per finished task (not per step) — a report file `docs/reports/<YYYY-MM-DD>_<plan-slug>_<task>.md`, committed
  with the task; no message to the coordinator (owner, 2026-10-27; it reads the files). A decision needed from the
  owner goes into the file's «Дальше» and, if it blocks, into one question to the owner. The file: ≤ ~15 lines,
  plain words first, no filler; the handoff links it instead of retelling:
    ОТЧЁТ: Полоса <X> · Task <Y> · <session>
    Суть: what the task was — 1–2 sentences a non-programmer understands.
    Итог: what works or changed now; commits, branch, merged or not.
    Проверка: tests N passed / stand numbers.
    Проблемы → решение: 1–3 lines.
    Агенты: role · model · tokens (from each Agent result), total; lead context ~Nk (UI estimate, say so).
    Открыто: what is left or unreliable.
    Дальше: next step; what the owner or the coordinator must decide.
    Подробно: handoff / review / result files, if any.
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
- A lane may switch the shared main checkout to its own branch (2026-10-19: `checkout: moving from main to
  fix/…` in the reflog) — the coordinator's next `git add` there rides in the lane's commit. Before every commit
  in the main checkout run `git branch --show-current` (must be `main`); a lane works in its own worktree, and
  every start prompt says so.
- A session's own permission rules can block `git checkout -- <file>` even after the owner said yes; do not
  route around it with another tool — give the owner the exact command to run.

## 8. Handoff

The state is `machine.lock` plus `ORDER.md`; the coordinator's context holds nothing else of value.
Before closing: rewrite the lock with the new coordinator's name (or delete it), message every peer.
