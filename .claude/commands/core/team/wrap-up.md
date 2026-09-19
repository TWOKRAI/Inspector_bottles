---
description: Semantic session close — summary in docs/sessions/ + (optional) memory update
---

Deliberate close of a work session. Complements the automatic Stop hooks with semantics: writes **what was done / what remains / next step**.

## When to use

- Before closing Claude Code after a long session
- When you've worked on one task for several hours and want to record the state
- Before switching to another task — so it's easier to come back later

## When NOT to use

- After a short Q&A with no code changes (nothing to summarize)
- If you already used `/core:team:handoff` in this session (it does something similar, but for switching machines)

## Algorithm

### 1. Gather context (in parallel)

- `git diff --stat HEAD` — what changed
- `git log --oneline -5` — recent commits
- `git status --short` — uncommitted
- TodoRead — what's in progress / done
- (optional) the latest file from `docs/sessions/` — what happened before

### 2. Generate a summary (≤150 words)

Format:
```markdown
## [HH:MM] wrap-up | branch=<branch> | commit=<short-sha>

**Сделано:**
- <конкретно что завершено — файлы, тесты, фичи>
- ...

**Не закончено:**
- <что осталось и почему — блокер, недоделанный refactor, etc>
- ...

**Следующий шаг:**
- <одно конкретное действие для старта следующей сессии>
```

Rules:
- **Be concrete, not abstract**: "added protect-readonly hook + test" — not "improved security"
- If nothing significant was done → don't force it, write `informational / Q&A session — not writing a wrap-up`
- Max 150 words — this is a summary, not a report

### 3. Write to `docs/sessions/`

Path: `docs/sessions/YYYY-MM-DD.md`

If the file doesn't exist — create it with frontmatter:
```markdown
---
title: "Сессии YYYY-MM-DD"
type: session-log
date: YYYY-MM-DD
---

# Журнал сессий — YYYY-MM-DD

```

Append the summary after the frontmatter. Several wrap-ups in one day go one after another.

`mkdir -p docs/sessions` if it doesn't exist.

### 4. (optional) Update project-memory

Check: did this session produce **long-lived** facts that will help future sessions?
- New architectural decision → memory of type `project`
- Clarification of a workflow or user preference → memory of type `feedback` or `user`
- External resource/link → memory of type `reference`

If yes — save it through the standard memory mechanism. If no — skip this step.

### 5. (optional) Update the project map

If this session changed **module-level knowledge** (a new decision, a gotcha, an open question) — update the corresponding `<module>/CONTEXT.md` (or `DECISIONS.md`) and rebuild the registry: `/core:quality:sync-context`. If module knowledge didn't change — skip this step.

### 6. Print the summary to the chat

The same text that was written. No extra preambles or markdown wrappers — just a clean wrap-up.

## What NOT to do

- Don't run `make gate` / tests automatically — that's the user's decision
- Don't do `git commit` — wrap-up is **logging**, not an operation on the repo
- Don't write "today we discussed..." — write results, not process
