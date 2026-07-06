---
name: verify-done
description: >
  Verification gate before declaring a task complete. Forces the agent
  to prove the change actually works — not just "tests are green" or
  "code compiles". Activates when the agent is about to say "done",
  "finished", "ready", "ship it", or before /dev:ship / /dev:pipeline closes a
  task. Triggers: "verify", "is it really done", "/verify-done",
  agent's own self-check before completion claim.
---

# Verification before completion

A task is **not done** because:
- the diff looks right
- type-check passed
- tests are green
- the agent reasoned it through

These are necessary, not sufficient. Verify by running the change end-to-end.

## Required checks (run all that apply)

### 1. Reproduce the original problem

If this was a bug fix:
- Before the fix: did you see the failure mode? (If no, you don't know
  whether you fixed it — you have a hypothesis at best.)
- After the fix: does the exact reproduction case now succeed?

If this was a new feature: did you exercise the **golden path** end-to-end?
Not unit tests of pieces — the user-visible flow.

### 2. Run the affected entry points

- **CLI:** invoke the command(s) the change affects, on a realistic input.
- **Library:** import in a clean Python process, call the public API.
- **Web:** hit the route in a browser or curl. Check status + body, not
  just that the server didn't crash.
- **UI:** click through the actual change in the running app. **Для PyQt/PySide + qt-mcp** — `qt_batch` (click → wait_for → snapshot) или `qt_screenshot` вместо ручного клика.

If you cannot run the entry point in this environment, say so explicitly:
"I cannot verify the UI runs because there is no display server here.
Tests pass, but a human must run the app before this is truly done."
Для desktop GUI: попробуй сначала qt-mcp (если подключён) — он работает даже без human-in-the-loop.

### 3. Edge cases the change should NOT break

- Empty / missing input
- Existing happy path (regression check)
- Concurrent / repeated invocation, if relevant

Pick 2–3 concrete ones, not "various edge cases".

### 4. Side effects on disk / git / state

- Did you create files that should be in `.gitignore`?
- Did you leave temp / debug artifacts?
- Is the git working tree what you expect?

### 5. Architectural sanity (если MCP подключены)

- **Если sentrux подключён** → `sentrux:check_rules` на свежие правки. Цель: нет новых нарушений архитектурных правил (cycles, layer violations). Если ругается — verdict не "done".
- **Если codegraph подключён** → `codegraph:impact` на изменённые символы. Цель: blast radius не пропущен (нет ли неучтённых callers).
- **Если playwright подключён И проект веб** → `browser_navigate` к golden-path URL + `screenshot`. Проверка визуально, не только HTTP-status.
- **Если qt-mcp подключён И проект PyQt/PySide** → поднять приложение (`/core:infra:run-proto` или эквивалент), затем:
  - `qt_snapshot` — структура дерева валидна, новый/изменённый виджет на месте.
  - `qt_thread_check` — нет cross-thread UI violations.
  - `qt_messages` — нет новых Qt warnings/errors после прогона golden-path сценария.
  - `qt_screenshot` — visual evidence для UI-изменений.
  - `qt_batch` — если нужен полный click-through scenario (click → wait → snapshot → assert).
  - Закрывает дыру «не могу проверить UI вручную в этой среде» для desktop-проектов.
- Если MCP не подключены → пропусти эту секцию (не блокируй verdict).

## Output format

```
**Task:** <one line>

**Reproduced original problem:** yes | no | n/a — <evidence>
**Golden path verified:** yes | no — <how exactly>
**Affected entry point exercised:** <command + result>
**Edge cases checked:** <list>
**Side effects:** <git status summary + any artefacts>
**Architectural sanity:** sentrux=ok|fail|n/a, codegraph impact=<list|none|n/a>, playwright=<screenshot path|n/a>, qt-mcp=<snapshot ok / thread ok / messages clean | n/a>

**Verdict:** ✅ done | ⚠️ done with caveats <list> | ❌ not done — <blocker>
```

## When to skip this skill

- Pure documentation change with no code path — verify by reading the
  rendered output, not by running.
- One-line typo fix where the change is self-evident.
- Refactor with no behaviour change AND a full passing test suite — say
  so explicitly: "no behaviour change, relying on test suite."

## What this skill is NOT

- Not a replacement for `/dev:test` or `/dev:review` — those run earlier.
- Not a code quality check — that's `/dev:review`.
- Not a permission to skip tests. Tests + verification together.

## Hard rule

If you would have to "trust" that the change works rather than show
evidence — you are not done. Say so, list the missing evidence, and ask
the user to either run the verification or accept the caveat.
