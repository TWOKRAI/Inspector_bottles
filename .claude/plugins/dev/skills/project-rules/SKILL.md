---
name: project-rules
description: "Core rules for every dev agent plus a map of what to read when. Preloaded via skills:."
---

# Project rules (apply on top of your role)

Inspector_bottles: multiprocess framework + camera defect-inspection prototype. Layers
`multiprocess_framework → Services → Plugins → multiprocess_prototype`, no reverse imports; app
changes only in `multiprocess_prototype/`. Dict at Boundary: only `dict` crosses processes.

## 1. qex — check freshness first

`mcp__qex__get_indexing_status` before `search_code`; compare `last_indexed` to today. Fresh →
qex-first. Stale → `Grep`, verify any NUMBER by grep, say the index age up front. Query in English.

## 2. Honesty over plausibility — "I don't know" is a successful outcome

Stuck, unsure, or unverified — **say so plainly**; a hidden guess costs more.

**Forbidden:** inventing an explanation instead of checking; silence about low-confidence work;
a green run as proof over a known-weak test; "impossible"/"guaranteed" without a reproduction.

**Required:** a non-empty **"What I left open / unreliable"** section in every report; questions
that outlive the task go to `docs/claude/OPEN_QUESTIONS.md`; a weak check says how it's weak and
what real proof looks like. Inventory counts use `grep -F` only, over every spelling of the family;
show a non-zero hit as the matching line.

## 3. MCP — your tool list is the truth

Your MCP servers are the ones in your tool list; the role table is `docs/claude/LEAD_RULES.md` → «MCP routing». A server named in your role prompt but absent from your tools → `Grep`/`Read`.
First use: `Read` `.claude/plugins/<id>/README.md`, load the schema via `ToolSearch`.
Layer boundaries: only CLI `sentrux check .`; MCP `check_rules` is a quick signal, not a verdict.
graphify community names are hints, not facts.
Index-building MCP ops (qex index, sentrux baseline, graphify build) — lead only, main tree.

## 4. Commits, pushes and pull requests

- Commit only if your role commits **and** the brief didn't say otherwise. Never push, never open a
  PR, never `--no-verify`, never `git add -A` — stage explicit paths.
- Conventional Commits; `Why:`/`Layer:` mandatory, `Refs:` from a plan — one last paragraph with
  `Co-Authored-By`, no blank line inside. Use `git commit -F <file> -- <paths>`.
  Habits: `.claude/COMMIT_GUIDE.md`.
- After a commit, `git show --stat HEAD` — only the paths you staged.
- Commit subject in English or Russian, never transliterated Latin.

## 5. Subagents and scope

- Default output: a report, no commit, no push.
- Spawning an agent: `model` explicitly as a tier alias (reviewer/teamlead `opus`, developer/tester
  `sonnet`, cto `fable`), `run_in_background: false` for reviewer/tester, and its prompt says: do not
  commit, do not push. Only for a sizeable independent track, never to verify your own work.
- **Brief = form** (DESIGN / FILES / REDS): first edit within 5 tool calls, never re-derive DESIGN,
  a file outside FILES → stop and ask. Apply every instruction to every listed file; targeted edits,
  not whole-file rewrites. A pre-existing bug is a report line, not a change.
- Several readings → list them; turn the task into a verifiable goal (repro → green).
- **Test radius, not the whole suite** (blast-radius tests + `ruff check` + type checker); the full
  suite runs at the lead, unless the change is shared infra (registry, model tier, index format). Lean output: `pytest -q --tb=short`, `ruff check -q`.
- **Evidence or nothing:** every "green"/"red"/"fixed" carries the command and its output.
- Environment finding (venv, shared file) → `SendMessage` to `main`, keep working.
- Don't chain unrelated Bash commands (one unmatched piece goes to the owner); never a gate-skipping flag.
- `ponytail` never cancels tests, docs or trailers. Secrets only in env; no `rm -rf`, no `curl | sh`,
  no new dependency without a reason. Log errors, never swallow them.

## 6. Language

Replies to the owner, reports, code comments and docs (README, STATUS, plans): **Russian**. Agent prompts,
skills, settings and memory: English. Don't mix languages in one file.

## 7. Escalation ladder — one level up, never sideways, never a guess

Escalate when **blocked**, after a third failed iteration (2 per loop), on spec-vs-code conflict, or
when a decision **outlives your task** (narrows an owner's decision, inherited architecture, changed
acceptance, a defect outside FILES) — say so **before** you act. Ladder: `junior`/`docs-writer` →
`developer`/`tech-writer` → `teamlead` → `cto` → owner (via the lead). `tester`, `debugger`,
`spec-writer` → `teamlead` (`debugger` → `investigator` first); `reviewer`, `investigator`, `manager`,
`integrator`, `ai-judge` → `cto`. Team: `SendMessage` to the higher role. Subagent: send this block
to `main` at the fork and repeat it in your final report:

```
ESCALATION -> <role>
Question: <one sentence, answerable with a decision>
Tried: <what you did, with observed output>
Blocked on: <the decision or information you need>
Files: <paths>
```

## 8. Tree, search and shell

- One tree — one writer. A peer may share your tree: stage explicit paths only. A writer in a
  worktree runs `ruff` itself and writes the commit message to a file; the lead commits.
- Never `grep -r` from the repo root: `git grep` or `rg`
  scoped to paths or with `--glob '!.claude/worktrees'`.
- In a worktree: no `uv sync`, `uv run` only with `--no-sync`; run the main `.venv` python with
  `PYTHONPATH=<worktree root>`; prove the import path from the same cwd as pytest.
- `uv sync` elsewhere only with `--inexact`. No global `taskkill` — `TaskStop` or a PID.
- `PYTHONUTF8=1` for Russian output. Prose in Bash breaks on apostrophes — write it to a file.
- Add an import and its use in one Edit (ruff strips an unused import).

## 9. Tests and verdicts

- Logic changed → tests changed. Authors add hazard tests (races, reentrancy, ordering, locks); an
  independent tester writes acceptance tests blind, before the code.
- Expected values are literals, never derived from the code under test.
- Assert the observable effect, not an implementation API name.
- A test that can hang runs the call in a daemon thread with a join deadline. A fake-harness suite
  needs one test that wires the real objects.
- Green without a red under break-injection proves nothing.
- A verdict without input → observed output is advice: reproduce by running and quote the output.
- A plan's premise and its stated cause are hypotheses: reproduce the blocker; the symptom holds to
  the number.
- Live tests run synchronously.

## 10. Owner principles

1. Framework universal, prototype expendable.
2. Fix the framework forward: never route around its bug or remove function.
3. Freeze dead code, never kill it; a public path with no live caller is a contract.
4. Fewer layers win at equal function.
5. Every component pluggable and testable; one failure never drops a neighbour.
6. GUI forms the topology, backend runs headless; GUI starts nothing.
Observability knobs: switchable at any boundary, zero cost when off.

## 11. Style

Reports follow STE-80: `.claude/skills/project-rules/ste-80.md`.

## Map

| when | read |
|---|---|
| editing an area | `.rules/{gui,framework,module-state,logging,plugins,services,prototype}.md` |
| architecture, key paths | root `CLAUDE.md`: Архитектура, Ключевые пути |
| IPC, ownership | `multiprocess_framework/docs/{ROUTING_GLOSSARY,MODULES_RESPONSIBILITY_MAP,MODULE_TIERS}.md` |
| stack, tests, Layer, worktree | `.claude/modes/_stack.md` (Toolchain → Worktree); `make gate` |
| lessons | `docs/claude/memory/CRAFT-{tests,injection,verdict,config-qt,by-module}.md` |
| lessons index | `docs/claude/memory/MEMORY.md`: §1 lessons, §3 Windows env, §4 writing one; owner: «## 2. Решения владельца (живые)» |
| MCP | `.claude/plugins/mcp-{qex,sentrux,backend-ctl}/README.md`; blast radius `scripts/graph_slice/README.md` |
| live backend | `backend_ctl`; qt-mcp only for GUI; no psutil; GUI stand `INSPECTOR_GUI_UNATTENDED=1` |
| skills | module-contract, systematic-debugging, verify-done, team-protocol |
