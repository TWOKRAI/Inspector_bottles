---
name: grill-me
description: >
  Interview the user relentlessly about an existing plan or design until reaching
  shared understanding ("design concept" in Brooks' sense). One question at a time,
  each with your recommended answer. Resolve each branch of the decision tree
  before moving on. Distinct from `brainstorm` (no plan yet — generate options);
  grill-me attacks an EXISTING plan or proposal. Triggers: "grill me", "stress-test
  this plan", "challenge this design", "interview me", "find holes in this", "/grill-me".
---

# Grill Me — relentless interview to shared understanding

The user has a plan, design, or proposal. Your job is to **find every unspecified
decision, hidden assumption, and ambiguous boundary** by interviewing them — one
question at a time — until you both see the same picture.

This skill is **not** about writing a document. The artifact is the shared mental
model. A summary at the end is optional (and the user may not even read it —
Pocock: «PRD — это квитанция о синхронизации, а не руководство»).

## Workflow

### 1. Restate the goal in one sentence

If you can't summarize the plan in one sentence, ask one clarifying question
first. Don't start grilling until you can.

### 2. Build a decision tree (mentally, not on disk)

Identify the branches that the plan implicitly contains:
- **Behavioral** — what should happen in each scenario (happy path, edge cases, error states)
- **Boundary** — what's in scope vs out of scope; where this module ends
- **Data** — schema, persistence, migrations, defaults, nullability
- **Interaction** — who calls this; who can be called; sync/async; backpressure
- **Failure** — what's recoverable, what's fatal, what's silent fallback (and is fallback intentional?)
- **Lifecycle** — init, ready, shutdown, hot-reload, cleanup
- **Observability** — logs, metrics, traces, alerts
- **Security / authz** — who's allowed to do what; who can see what

Don't dump the list. Walk the branches one at a time.

### 3. Ask one question at a time, each with your recommendation

Format:
```
**Q<n>:** <question — concrete, not "what about errors?">

**My recommended answer:** <your default — committed, not "it depends">

**Why this default:** <one line — what trade-off this picks>
```

Wait for the user. They will: (a) accept your default, (b) override with their answer,
(c) ask you to explore the codebase before answering, (d) flag the question as wrong premise.

### 4. Use ground truth, don't guess

If a question can be answered by reading the code, **read the code** instead of
asking the user. Same for MCP-backed questions:
- Callers / impact of changing a signature → `codegraph_explore`
- Architectural fit (cycles, layer violations) → `sentrux:dsm` / `sentrux:check_rules`
- Library API / version-specific behavior → `context7:query-docs`
- Semantic neighborhood ("where else does this concept live") → `qex:search_code`

Name the tool you used so the user sees the source: «I checked `codegraph_explore`
on `process_event` — 3 callers, all in same module. My recommendation: …».

If MCP isn't available, fall back to `Grep` / `Read` and say so.

### 5. Track resolved vs open

Mentally keep a list:
- Resolved: <branch>: <decision>
- Open: <branch>: <question> (waiting on user / waiting on codebase exploration)

When all branches are resolved (or the user says "good enough"), stop.

### 6. When to stop

Stop when **one of**:
- All branches resolved with explicit decisions
- User says "stop / good enough / I have what I need"
- You hit 3 questions in a row where the user has no preference and your recommendation isn't pushed back on — that's a sign the user trusts your defaults; summarize and stop

Typical session: 10–40 questions. If you're past 50 and not converging, surface
that meta-fact: «We've covered 50 questions and 8 branches are still open. Do
you want to defer the rest to /dev:plan, or keep grilling?»

### 7. Output (optional summary)

If asked, or if the session was long, end with a compact summary:

```
## Shared understanding

**Goal:** <one sentence>

**Decisions resolved:**
- <branch>: <decision> (reason: <one line>)
- ...

**Out of scope:**
- <thing>: <reason>

**Open (deferred to implementation):**
- <thing>: <who decides / when>

**Hidden assumptions surfaced:**
- <assumption>: <implication>
```

The user may not read this. The value was the dialog, not the doc.

## Rules

- **One question per turn.** Batched questions ("a, b, c — what do you think?")
  lose nuance and the user skips half. Single questions force engagement.
- **Always provide your recommendation.** «What do you think?» is lazy. «I'd
  default to X because Y — agree?» forces a real answer.
- **Push back on the premise.** If a question reveals the plan rests on a
  false assumption, surface it: «You said X, but the codebase shows Y. Should
  we revise the goal before continuing?»
- **No code in this phase.** Pseudo-code OK to clarify a contract, but no
  edits. Grilling is dialog, not implementation.
- **Don't lecture.** The user knows their domain. Your job is to interrogate
  decisions they haven't made yet, not explain decisions they have.

## When NOT to use this skill

- No plan exists yet → use `brainstorm` (generate options) first
- Task is < 20 lines of code → just propose and implement; grilling is overhead
- Bug fix with a single failing test → debugger workflow, not grilling
- User explicitly says "just do it" — respect that, ask only 1–2 critical questions max

## Anti-patterns

- ❌ «Tell me more about your plan.» — too vague, lazy
  ✅ «You said `process_event` should be async. Does it need to preserve event order, or is per-key ordering enough?»

- ❌ Batched: «What about errors, timeouts, retries, and observability?»
  ✅ One at a time: «If `process_event` times out, what's the desired behavior — retry, dead-letter, propagate? My default: dead-letter with metric.»

- ❌ «What do you think?» without recommendation
  ✅ «I'd recommend X because Y. Agree, or have a different angle?»
