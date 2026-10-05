# Stack — Inspector_bottles

> Per-project customization point. `=preserved` при `claude-kit upgrade` (devseed) —
> правки здесь переживают апгрейд, в отличие от `settings.json` и остальных `modes/*`.
> Единственный источник правды по архитектуре и путям — корневой `CLAUDE.md`.
> Здесь только то, чего там нет, и то, что seed заполнил бы неверно.

## Project

- **Name:** Inspector_bottles — фреймворк многопроцессных приложений + прототип инспекции дефектов
- **Layout:** НЕ src-layout. Слои: `multiprocess_framework/` → `Services/` → `Plugins/` → `multiprocess_prototype/` (composition root)
- **Точка входа:** `multiprocess_prototype/run.py`

## Toolchain (правится под проект — дефолты seed здесь неверны)

- **Language:** Python **3.12** (не 3.11+ из seed)
- **Библиотеки** (из root `CLAUDE.md` «Стек»): PySide6 6.10, OpenCV 4.13, NumPy 2.x | SQLite/PostgreSQL; pytest + pytest-qt (`qt_api = pyside6`) | Pydantic v2; ML: PyTorch 2.11 + Ultralytics YOLO + ONNX Runtime — extras `[ml]` в pyproject
- **Package manager:** `uv`, но **пакеты ставит пользователь** — не выполнять install самому.
  `uv sync` сносит необъявленное → только `--inexact`
- **Test:** `python scripts/run_framework_tests.py` / `python scripts/validate.py` / `make test`.
  Ручной pytest — из корня проекта, иначе `ModuleNotFoundError`. НЕ `uv run pytest -q`
- **Worktree:** без `uv sync` и без `uv run` без `--no-sync` (CUDA torch → CPU) — `<основное дерево>/.venv/Scripts/python.exe` + `PYTHONPATH=<корень worktree>`; пруф — путь импорта `multiprocess_framework` из того же cwd, что pytest. Переопределяет рецепт `core/agents/_WORKTREE_PATTERN.md`
- **Gate:** `make gate` (= `make check` + `make test`); `make check` = ruff + pyright + bandit
- **Агентские прогоны:** всегда `QT_QPA_PLATFORM=offscreen` — Qt-окно вешает агента

## Commit format

- **Validator:** [x] enabled (`.git/hooks/commit-msg`)
- **Required trailers:** `Why:` **и** `Layer:` — оба обязательны (seed по умолчанию считает
  `Layer:` выключённым; здесь это неверно, хук отклонит коммит)
- **Layer values:** framework | services | plugins | prototype | docs | scripts | tests | infra | mixed
- **Refs:** обязателен, если задача из плана — `Refs: plans/<slug>.md`

## Language policy

- **User-facing output:** русский, строго (см. `.claude/CLAUDE.md` § Language policy)
- **Code comments / docstrings:** русский
- **System files (.claude/, settings.json, memory):** английский

## Plans & Specs

- **Plans root:** `plans/<slug>.md` или `plans/<slug>/plan.md` (multi-phase)
- **Specs root:** `docs/direction/` — живые спеки продукта
- **Branch:** `<type>/<slug>`, стандарт `feat/`, не `feature/`

## MCP — фактическое состояние

Серверы по ролям — `docs/claude/LEAD_RULES.md` → «MCP routing» (замер 2026-10-05).
Выключены: **playwright** (проект не веб), **hello-world**, **knowledge**.

Схемы MCP-инструментов отложены (ToolSearch) — держать сервер включённым дёшево.

## Architecture notes

- **R1** — Dict at Boundary: между процессами только `dict` (`to_dict`/`from_dict`), Pydantic внутри процесса
- **R2** — обратные импорты между слоями запрещены, enforced через `.sentrux/rules.toml`
- **R3** — имя процесса (`targets`) ≠ канал Router (`FieldRouting.channel`); см. `ROUTING_GLOSSARY.md`
- **R4** — логи только через `ObservableMixin` / менеджеры, пути из env (`MULTIPROCESS_LOG_DIR` / `INSPECTOR_LOG_DIR`)
- ADR: локальные → `modules/X/DECISIONS.md`, глобальные → `multiprocess_framework/DECISIONS.md`;
  после правок — `python -m scripts.sync`

## Gates (seed ini block)

Added 2026-09-20 (seed 1.2.0 rollout, task H.3): `pre_report_gate` was unset here (default
off) — the SubagentStop gate never ran in this project, silently, because there was no fenced
`ini` block at all. This is now the only such block in this file; `validate_commit.py` and
`hooks/subagent-stop-gate.sh` read config from it exclusively, so the prose around it may name
keys/values freely (see `.claude/CLAUDE.md`).

```ini
# Tests-discipline commit gate — read by scripts/validate_commit/validate_commit.py.
# Every key is optional; the values below are also the defaults, except `tests_gate` (default `on`, set `off` here).
tests_gate = off                     # on | off — OFF by owner's decision 2026-10-03, see the paragraph below the block
tests_gate_code = src/**/*.py        # staged paths the gate applies to (comma-separated globs)
tests_gate_exclude = **/template/**  # subtracted from tests_gate_code before the gate fires

# Pre-report gate — read by hooks/subagent-stop-gate.sh (SubagentStop).
pre_report_gate = on                            # on | off — off allows without running anything
pre_report_gate_tests = multiprocess_framework/modules/state_store_module/tests multiprocess_framework/modules/router_module/tests  # space-separated test paths passed to pre_report_gate.py --tests
pre_report_gate_base = main                     # merge-base ref for the gate's diff scope; empty = @{upstream} → origin/HEAD → main → master
report_status = on                              # on | off — off skips the STATUS: line check entirely; independent of pre_report_gate

# Project memory — read by /core:memory:* commands.
memory_dir = docs/claude/memory                # canonical memory (git, both machines); the local auto-memory folder is a cache

# Subagent context budget — read by hooks/agent-context-ceiling.sh (PreToolUse).
agent_context_budget = 100000                   # soft: start + N -> checkpoint (finish or hand off), repeated every +50000; off = none
agent_context_hard_budget = off                 # hard: start + N -> deny all but commit / handoff / report; off (default) = never deny

# Document size budget — read by scripts/lint_doc_size.py and hooks/doc-size-guard.sh.
doc_size = on                                   # on | off — off disables every finding
doc_size_warn_kb = 32                           # a whole markdown FILE over this many KB is flagged
doc_section_warn_kb = 8                         # a single heading-delimited SECTION over this many KB is flagged
doc_size_exempt = CHANGELOG.md, **/_archive/**, **/fixtures/**, **/node_modules/**  # comma-separated globs, REPLACES the default list when set

# Executor brief lint - read by dev/hooks/lint-brief.sh (PreToolUse on Agent).
brief_lint = on                                 # on | off — off allows every writer spawn without checking the brief
brief_max_files = 6                             # FILES block's numbered/bulleted entry count above this is denied
brief_lint_roles = developer, teamlead, tester, junior, debugger  # subagent_type values the lint applies to; others pass silently

# Web search routing - read by hooks/web-search-routing.sh (PreToolUse on WebSearch|WebFetch).
web_search = auto                               # auto | delegate | allow — auto allows only sonnet/opus/haiku main sessions
web_search_deny_agents = cto                    # comma-separated subagent_type values denied even in auto (top-tier roles)
```

`pre_report_gate_tests` picks two clean, fast framework-module directories
(`state_store_module`, `router_module` — core mechanisms, no hardware/process I/O): 1133 tests,
~35s measured (`python -m pytest -q -x --tb=short -p no:cacheprovider <paths>` from repo root,
`.venv` interpreter, `QT_QPA_PLATFORM=offscreen`) — comfortably under the gate's 240s budget.
The cross-module contract directory (`multiprocess_framework/modules/tests`) was excluded: it
measured ~114s AND already carries an unrelated pre-existing failure
(`test_no_test_dir_is_invisible_to_every_runner` — a backup/archive dir with a loose `tests/`
the runner-coverage guard does not know about), so it would red the gate on day one for a
reason this task did not touch. `pre_report_gate_base = main` pins the diff scope to the
owner's main branch (today's seed 1.2.0 rollout landed there). Every other key above keeps the
template's default value — no behaviour change from before this block existed.

`tests_gate = off` (owner's decision 2026-10-03, plan `commit-mechanism` Task 1.3): the gate never fired here
(`tests_gate_code = src/**/*.py`, there is no `src/`), and pointing it at the real code would reject almost every
code commit: it counts only a top-level `tests/**` as tests (0 files — tests live in `<module>/tests/`) and accepts
`Tested:` only as `tests/<path>` | `skip (<reason>)`, while project practice is `scope/N passed`. Test discipline is
held by roles (blind tester before the code, lead's break-injection, reviewer by running). Revisit after the
Task 3.2 measurement; turning it back on needs the test-dir glob and the `Tested:` grammar changed first.
