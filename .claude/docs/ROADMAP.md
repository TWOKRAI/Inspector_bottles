# ROADMAP — Seed Evolution Backlog

> Кандидаты на интеграцию в `.claude/` seed-шаблон. Каждая позиция —
> с оценкой, обоснованием и решением (in core / opt-in module / backlog / reject).
>
> Источник анализа: hesreallyhim/awesome-claude-code, rohitg00/awesome-claude-code-toolkit,
> ComposioHQ/awesome-claude-plugins, thedotmack/claude-mem (май 2026).

---

## A. Memory & context

### A.1 claude-mem (thedotmack)
- **Что:** Worker (:37777, Bun) + SQLite/FTS5 + Chroma + 6 lifecycle hooks + 3 MCP tools.
- **Решает:** контекст между сессиями, ~10x token efficiency через progressive disclosure.
- **Не решает:** конфликты версий памяти/кода, дедупликацию противоречий, git-integrity.
- **Принципиальная несовместимость с текущей `.claude/memory/`:** централизованное SQLite vs распределённые .md под git; автозахват vs explicit commit; opaque vs diffable.
- **Звёзды:** 76.7k (реальный спрос).
- **Решение:** **opt-in модуль `mcp/claude-mem/`** (когда понадобится), по тому же паттерну, что qt-mcp/graphify/serena. **НЕ в core.** Текущая git-tracked .md система — фундамент, claude-mem — потенциальный семантический слой над `docs/sessions/`, не замена.

---

## B. Hooks (apply to core seed)

### B.1 agnix — linter for agent files
- **Что:** Comprehensive linter для .md-агентов в `.claude/agents/`.
- **Зачем:** У нас 10 агентов в seed; ручная проверка консистентности — хрупкая.
- **Приоритет:** **HIGH.** Кандидат на `quality:agnix` command или pre-commit hook для проектов с агентами.
- **Действие:** изучить детально, оценить интеграцию в `hooks/tests/` или `commands/quality/`.

### B.2 Dippy — AST-parse safe bash auto-approve
- **Что:** Auto-approve безопасных bash через AST вместо regex.
- **Зачем:** Наш `hooks/core/validate-safe-command.sh` — regex-based, ограничен.
- **Приоритет:** **MEDIUM.** Апгрейд существующего hook.
- **Действие:** сравнить AST-подход с регексами, оценить false-positive rate.

### B.3 parry — prompt injection scanner
- **Что:** Hook-сканер для prompt injection в пользовательском вводе.
- **Зачем:** Безопасность при работе с внешним контентом (web fetch, raw data).
- **Приоритет:** **MEDIUM.** Возможен как opt-in hook.
- **Действие:** добавить в backlog `hooks/security/parry.sh`.

### B.4 TDD Guard — блокировка TDD-violations
- **Что:** Hook, блокирующий modify файла без теста сначала.
- **Зачем:** Жёсткий TDD-discipline для проектов, где это важно.
- **Приоритет:** **LOW.** Слишком жёстко для дефолта, opt-in.
- **Действие:** документировать в `hooks/README.md` как опц.

---

## C. Commands

### C.1 /tdd — Red-Green-Refactor workflow
- **Что:** Структурированный TDD-pipeline (написать тест → запустить FAIL → реализовать → PASS → refactor).
- **Зачем:** Дополняет developer+tester чёткой дисциплиной.
- **Приоритет:** **MEDIUM.** Может быть `commands/dev/tdd.md`.

### C.2 /commit — conventional commits с emoji
- **Что:** Автогенерация conventional commit messages.
- **Зачем:** У нас уже свой validator + COMMIT_GUIDE.md, но можно подсмотреть UX.
- **Приоритет:** **LOW.** Возможно слияние с `/ship`.

### C.3 /prd-generator — PRD из описания
- **Что:** Генерация Product Requirements Document.
- **Зачем:** Дополняет spec-writer структурированным выходом.
- **Приоритет:** **LOW.** spec-writer уже покрывает похожий use-case.

---

## D. MCP servers (kandidates for opt-in modules)

### D.1 claude-context (Zilliz) — гибридный BM25 + vector
- **Что:** То же, что qex (Qdrant+Ollama+BM25), но от Zilliz.
- **Зачем:** Прямой конкурент qex. Может быть стабильнее / быстрее / дешевле.
- **Приоритет:** **HIGH.** Заслуживает A/B vs qex на реальном проекте.
- **Действие:** провести Phase-3-style benchmark vs qex; если выигрывает — переключить дефолт.

### D.2 preflight — prompt validator
- **Что:** MCP, который проверяет промпты до отправки, ловит размытость, экономит 2-3x токенов.
- **Зачем:** Уникальная функциональность, нет аналога в seed.
- **Приоритет:** **HIGH.** Изучить детально, кандидат на `mcp/preflight/`.

### D.3 container-use (Dagger) — изолированные dev env
- **Что:** Развёрнутые контейнеры для параллельных multi-agent сессий.
- **Зачем:** Альтернатива git worktrees для многоагентного режима.
- **Приоритет:** **MEDIUM.** Только если активно используем параллельные subagents с конкурентным доступом к файлам.

### D.4 VoiceMode / stt-mcp — голосовой ввод
- **Что:** STT/TTS для голосовой работы с Claude Code.
- **Зачем:** UX-апгрейд, но требует OpenAI-compatible STT.
- **Приоритет:** **BACKLOG.** Личный choice пользователя, не для шаблона.

### D.5 read-only-postgres / sqlite-mcp
- **Что:** SELECT-only MCP для БД.
- **Зачем:** Безопасный доступ к данным проекта без рисков mutation.
- **Приоритет:** **LOW (opt-in).** Для проектов с БД (rhymes использует SQLite!). Возможно `mcp/sqlite-readonly/`.

### D.6 AWS MCP Server
- **Что:** AWS operations через MCP.
- **Зачем:** Если проект использует AWS.
- **Приоритет:** **BACKLOG.** Per-project, не для шаблона.

### D.7 mcp-builder
- **Что:** Утилиты для разработки своих MCP-серверов.
- **Зачем:** Если будем писать кастомные MCP.
- **Приоритет:** **BACKLOG.** Когда понадобится.

### D.8 codegraph (colbymchenry) — pre-indexed call graph ✅ (2026-05-20)
- **Что:** MCP-сервер на TypeScript/Node 18+. tree-sitter → SQLite+FTS5, native file-watcher. 8 tools: `search`, `context`, `callers`, `callees`, `impact`, `node`, `files`, `status`. 19+ языков, framework-aware routing (Django/Flask/FastAPI/Express/Rails/Spring/SvelteKit/...).
- **Решение:** **opt-in модуль `mcp/codegraph/`** (реализовано). Закрывает дыру function-level call graph + impact, которой не давали qex (intent search, не граф), sentrux (модули, не функции), graphify (визуал, не запрос).
- **Не вытесняет:** qex (нет dense embeddings → fuzzy intent слабее), sentrux (нет метрик / health gate), graphify (нет визуализации). См. routing-таблицу в [`mcp/codegraph/README.md`](mcp/codegraph/README.md).
- **Стоимость:** Node 18+ как новый рантайм seed-а (рядом с Rust/Python). Без Ollama/GPU. SQLite-индекс растёт с репо.
- **Маркетинговые цифры** (-92% tool calls, -77% time) сравнены против пустого агента (Read+Grep), не против qex+sentrux+graphify; маржа на нашем baseline скромнее, см. § "Why honest expectations matter" в README модуля.
- **Действие:** обкатать на одном реальном проекте (5 smoke-вопросов из SETUP_GUIDE.md § 5), замерить tool calls vs baseline; при положительном результате — добавить опциональную активацию в `mcp/<name>/SETUP_GUIDE.md`.

### D.9 github-mcp (official) — Issues/PR/Actions ✅ (2026-05-20)
- **Что:** Official GitHub MCP, ~20k★, MIT, OAuth scope filtering, remote (`mcp.github.com`) + локальный Go-binary с PAT.
- **Решение:** **opt-in модуль `mcp/github/`** (реализовано). Replaces ad-hoc `gh`-вызовы в `/ship`, `/handoff`, `/review` для проектов на GitHub.
- **Не вытесняет:** `git` local ops (status/log/diff/commit остаются shell), и `gh` CLI для разовых лукапов без OAuth.
- **Действие:** включить на одном GitHub-проекте, проверить smoke-сценарий «прочитай CI логи последнего PR».

### D.10 ast-grep MCP — structural search + rewrite ✅ (2026-05-20)
- **Что:** AST-pattern search и **rewrite** через tree-sitter на 20+ языках. MIT, 8k+★ для CLI.
- **Решение:** **opt-in модуль `mcp/ast-grep/`** (реализовано). Закрывает дыру «pattern-based bulk codemods», которой не было ни у Grep (текст), ни у serena (LSP-scope), ни у codegraph (read-only graph).
- **Дополняет codegraph** (codegraph читает граф, ast-grep его меняет) и **serena** (serena — scope-aware rename одного символа, ast-grep — pattern bulk).
- **Действие:** обкатать на одном codemod-сценарии (например, миграция `requests → httpx`).

### D.11 Playwright MCP (Microsoft) — browser automation
- **Что:** Accessibility-tree-based browser MCP. Apache-2.0, ~20k★, **de-facto default** браузер-MCP на май 2026.
- **Решение:** **add as opt-in** для проектов с web/UI частью. Не для каждого проекта в core.
- **Приоритет:** **MED.** Документировать как кандидат opt-in модуля `mcp/playwright/` — реализовать при первом web-проекте.

### D.12 Semgrep MCP — SAST на 5000+ правил
- **Что:** В мае 2026 MCP-функциональность включена в `semgrep` binary напрямую (раньше отдельный repo, теперь deprecated в пользу built-in).
- **Решение:** **add as opt-in** для проектов, где код агента попадает в прод.
- **Приоритет:** **MED.** Документировать как кандидат opt-in модуля `mcp/semgrep/`.

### D.13 Postgres MCP Pro / DBHub — БД-MCP
- **Что:** Postgres MCP Pro (Crystal DBA, MIT, Python, RO/RW + index tuning + EXPLAIN) или DBHub (Bytebase, MIT, Node, multi-DB включая SQLite/DuckDB).
- **Решение:** **add as opt-in** только для проектов с БД. Per-project, не core.
- **Приоритет:** **LOW.** Документировать при первом проекте с БД.

### D.14 Chrome DevTools MCP (Google) — frontend debug
- **Что:** ~7k★, Apache-2.0. Network/console/heap/perf для отладки live Chrome. Дополняет Playwright (Playwright = driving, CDT = debugging).
- **Решение:** **add as opt-in** для проектов с frontend.
- **Приоритет:** **LOW.** Документировать при необходимости.

### E.1 RIPER Workflow — Research → Innovate → Plan → Execute → Review
- **Что:** 5-фазный workflow.
- **Сравнение с нашим:** У нас уже plan → implement → test → review → ship. RIPER добавляет explicit "Research" и "Innovate" фазы.
- **Приоритет:** **STUDY.** Стоит изучить, могут быть идеи для расширения `pipeline.md`.

### E.2 Compound Engineering — error-to-lesson discipline
- **Что:** Систематическое превращение ошибок в записанные уроки.
- **Сравнение с нашим:** Совпадает с auto-memory rules (`memory/feedback_*.md`).
- **Приоритет:** **VALIDATE.** Проверить, есть ли паттерны, которых нет у нас.

### E.3 Claude Code PM
- **Что:** Comprehensive project management для Claude Code.
- **Приоритет:** **STUDY.** Возможно вдохновляющий шаблон, но может быть избыточен.

### E.4 Ralph for Claude Code — autonomous iteration
- **Что:** Автономная итерация до завершения задачи.
- **Сравнение с нашим:** Конфликт с принципом "failure-recovery: hard 2-iteration limit → escalate to teamlead".
- **Приоритет:** **REJECT.** Противоречит нашему правилу 2-итераций.

---

## F. Plugin architecture (concept)

### F.1 Claude Code Plugins (`.claude-plugin/plugin.json` + skills/commands/agents/hooks)
- **Что:** Стандартизованная упаковка модулей (alternative to seed approach).
- **Pros:** Переиспользование между проектами, marketplace, версионирование.
- **Cons:** Усложнение архитектуры; наш seed уже даёт переиспользование через `apply-seed.sh`.
- **Приоритет:** **DEFER, re-eval Q3 2026.** На май 2026 экосистема выросла (15,134 плагин-репов в quemsah/awesome-claude-plugins, anthropics/claude-plugins-official 20.4k★, top-проекты shipпят как плагины). Re-eval по запросу. См. § K.

### F.2 connect-apps (500+ интеграций)
- **Что:** Плагин для Slack/Notion/GitHub/email и т.д.
- **Приоритет:** **REJECT для core.** Per-project, если нужно. Не относится к шаблону.

---

## G. Domain-specific agents (NOT for core seed)

Из awesome-claude-code-toolkit (135 agents) интересны как **per-project hires** через `/hire`, но не для core seed:

- Geospatial Engineer (PostGIS, spatial)
- Fintech Engineer (precision arithmetic, compliance)
- Healthcare Engineer (HIPAA, HL7 FHIR)
- Robotics Engineer (ROS2, SLAM)
- Payment Integration Specialist (PCI DSS, 3D Secure)
- SEO Specialist
- Patent Analyst
- ETL Specialist

**Решение:** не включать в core. Использовать template `agents/_template.md` + skill `/hire` для добавления по необходимости в конкретный проект.

---

## H. Решённое (для контекста)

- ✅ **qt-mcp, graphify, serena** — opt-in модули в `mcp/`, добавляются в Phase 2 текущего апгрейда seed.
- ✅ **codegraph** — opt-in модуль `mcp/codegraph/` (2026-05-20). Закрывает function-level call graph + impact. Не вытесняет qex/sentrux/graphify, см. § D.8.
- ✅ **github-mcp, ast-grep** — opt-in модули в `mcp/` (2026-05-20). Закрывают GitHub state и structural codemods. См. § D.9–D.10.
- ✅ **`.claude/memory/` — остаётся** git-tracked .md, не заменяем на claude-mem/mem0/letta.
- ✅ **Plugins architecture** — отложено, см. пересмотр в § F.1 (May 2026: пересмотрено, всё ещё DEFER, но re-eval в Q3 2026).

### Closed in May 2026 agent-system upgrade (2026-05-20)

- ✅ **PreCompact hook** (`hooks/core/precompact-context-save.sh`) — симметричен `restore-context`, форсирует дамп решений в `.claude/memory/` ДО компактификации. Закрывает потерю мелких решений в длинных сессиях.
- ✅ **Skill `brainstorm`** (`skills/brainstorm/`) — pre-`/plan` генерация 2–4 опций с trade-offs. Закрывает дыру между fuzzy idea и формальным планом. Дополняет `grill-me` (тот атакует существующий план).
- ✅ **Skill `verify-done`** (`skills/verify-done/`) — pre-`/ship` checklist «фикс реально работает». Лечит ложное «done» при зелёных тестах.
- ✅ **observability/** — OTel-telemetry, claude-code-otel Docker stack, ccusage/ccstatusline. Закрывает слепое пятно «токены и tool calls». Необходимо для честной оценки новых MCP (codegraph/ast-grep/...).
- ✅ **`agents/_WORKTREE_PATTERN.md`** — паттерн `isolation: worktree` для агентов, документирован но НЕ применён к существующим агентам (применять при появлении параллельного `/pipeline`).

### Closed in seed-gap-closure release (2026-05-19)

- ✅ **§ B.1 (agent-linter)** → реализован собственный минимальный (`scripts/lint_agents.py` + `commands/quality/lint-agents.md`). Agnix отклонён — Node-deps, overkill для 10 файлов.
- ✅ **§ I.1 (Phase 3 pilot rhymes)** → завершён, шаблон валидирован на реальном проекте.
- ✅ **§ I.2 (`apply-seed --claude-only`)** → реализован, validated на rhymes Task 3.1.
- ✅ **§ I.3 (`python3` cross-platform)** → реализован через `hooks/_lib/python-bin.sh` helper.
- ✅ **Security tier** (вне B/I, добавлено в session): `gitleaks` + `bandit` + `pip-audit` + `sentrux` в pre-commit (Task 2.1, 2.2, 2.4).
- ✅ **ADR workflow** (вне B/I, добавлено в session): `templates/ADR.template.md` + `commands/dev/adr.md` (Task 2.3).

---

## Принципы решения

1. **Core seed остаётся лёгким:** только то, что нужно >70% проектов.
2. **Opt-in модули в `mcp/<name>/`** — для тяжёлых/специфичных инструментов.
3. **Backlog в этом ROADMAP** — для отслеживания "обсудили, не сейчас".
4. **A/B перед заменой:** любой инструмент-конкурент существующему (claude-context vs qex) — сначала benchmark, потом решение.
5. **Не плодить overlap:** если новая команда дублирует существующую (`/commit` vs наш validator) — слияние, не параллель.
6. **Анти-паттерны (community-validated на май 2026, см. § J):** не превышать потолки (≤15 skills, ≤15 hooks, ≤12 агентов), не хукать каждое событие, не делать kitchen-sink, не использовать `--dangerously-skip-permissions` по умолчанию.

---

## J. Анти-паттерны (May 2026, community-validated)

Источники: stevekinney/subagent-anti-patterns, digitalapplied/team-adoption-failures, hyperdev/claude-code-critique.

| Анти-паттерн | Риск в seed | Митигация |
|---|---|---|
| **CLAUDE.md bloat** — файл, который перестали читать | LOW (тугой split на modes/_stack.md) | Продолжать; не пускать «общую философию» в CLAUDE.md |
| **Skill sprawl** (collection over curation) | MED — сейчас 6 skills, растёт | **Потолок: ≤15 skills.** Удалять/архивировать при добавлении новых |
| **Hook spam** (каждое событие захуковано) | LOW — 8 hooks | **Потолок: ≤15 hooks** |
| **10–15+ subagent fleets, 200k+ токенов** | MED — 10 агентов уже | **Потолок: ≤12 агентов** в seed; держать threshold rule строго |
| **`--dangerously-skip-permissions` для всего** | LOW (validate-safe-command есть) | Не ослаблять; documenting в `_stack.md` если когда-то ослабят |
| **Kitchen-sink toolkits** (135 агентов как rohitg00) | LOW | Не копировать чужие toolkit'ы целиком — куратировать |
| **20 reads + 12 greps в main session перед `/plan`** | MED | Enforce investigator agent перед `/plan` для нетривиальных задач |
| **Ralph-style autonomous loops** | NONE — уже отклонено | Не пересматривать без сильной причины |

## K. Re-evals для будущих сессий (2026-05-20)

Решения, которые надо пересмотреть позже:

- **F.1 Plugins architecture** — пересмотр Q3 2026. Если ecosystem (15k+ плагинов на май) докажет ценность за месяцы — упаковать seed как плагин.
- **D.1 claude-context vs qex A/B** — давний open. Запустить замер через observability/, когда тот будет включён в боевом проекте.
- **D.2 preflight** — изучить детально, если в Q3 2026 будет stable.
- **B.1 agnix re-eval** — если появится более лёгкая Python-версия (наш `lint_agents.py` минимален; cclint покрывает шире).

---

## Следующие шаги по приоритету

1. ✅ Завершить текущий Phase 1+2 seed-санитизации (qt-mcp + graphify + serena).
2. ✅ Pilot на rhymes — Phase 3 (см. § I.1 ниже).
3. **Добавить `apply-seed.sh --claude-only`** (см. § I.2 ниже) — необходимо для безопасной миграции существующих проектов.
4. **Изучить agnix** детально → если стабилен, добавить как `commands/quality/agnix.md`.
5. **A/B claude-context vs qex** на одном проекте.
6. **Изучить preflight** — если работает как заявлено, добавить `mcp/preflight/`.
7. **RIPER / Compound Engineering** — критическое чтение, выводы в `modes/dev.md`.

---

## I. Findings из Phase 3 pilot (rhymes)

### I.1 Pilot rhymes — успех
- Дата: 2026-05-19.
- Бэкап: `/tmp/rhymes_claude_backup_20260519_132012.tar.gz` (156K).
- Что работает: все agents (10), commands (39), hooks (9), mcp-модули (6), memory (7 записей) корректно перенесены.
- Что осталось rhymes-specific (per design): `memory/`, `modes/_stack.md`, `commit-layers.txt`. Не трогаем при back-port (см. excludes в `sync-back.sh`).
- Что **удалено** из rhymes (legacy seed-artifacts, ехало по ошибке): `apply-seed.sh`, `sync-back.sh`, `CHANGELOG.md`, `hooks/tests/`. Теперь живут только в canonical seed.

### I.2 apply-seed.sh не подходит для existing-project миграции
**Проблема:** `apply-seed.sh` рассчитан на **новый** проект. Он перезаписывает `pyproject.toml`, `Makefile`, `src/<pkg>/__init__.py`, `tests/test_smoke.py`, `README.md` корня. Для существующего проекта (rhymes, Inspector_bottles) это **разрушительно**.

**Workaround в Phase 3:** ручной алгоритм через `cp -R` + восстановление per-project артефактов из бэкапа. Сработало, но не масштабируется.

**TODO (новая фаза):** добавить флаг `--claude-only` в `apply-seed.sh`:
- Не генерит `pyproject.toml` / `Makefile` / `src/` / `tests/` / `README.md` / `CLAUDE.md` корня.
- Делает только: backup → `.claude/` clean → cp from seed → preserve per-project (`memory/`, `modes/_stack.md`, `commit-layers.txt`, `settings.local.json`) → restore.
- Это **режим обновления** существующих проектов.

**Также TODO:** проверить, что `rsync` отсутствует в стандартном Git Bash на Windows — если так, заменить `rsync` в `sync-back.sh` на `cp -R` + ручные `--exclude`, чтобы скрипт работал на Windows без доп. установки.

### I.3 `python3` хардкод ломает Windows
**Проблема:** На Windows `python3` обычно отсутствует (либо Microsoft Store stub, который падает). Реальный интерпретатор — `python`. В seed `python3` зашит в 8 местах:
- `mcp/<name>/SETUP_GUIDE.md` → `qex` command (исправлено 2026-05-19: `python3` → `python`)
- `apply-seed.sh:182` (substitute helper)
- `hooks/core/protect-readonly.sh:25`
- `hooks/core/validate-safe-command.sh:23`
- `hooks/python/autoformat-python.sh:8`
- `hooks/python/check-imports.sh:7,27`
- `commands/dev/ship.md:78` (validate_commit invocation)
- `CLAUDE-SETUP.md:24` (docs только — для macOS/Linux примера, можно оставить)

**TODO:** ввести один helper, например `.claude/scripts/python_bin.sh`:
```bash
PYTHON_BIN=$(command -v python3 || command -v python || echo python)
```
и подменить вызовы `python3 -c` → `"$PYTHON_BIN" -c` во всех hooks. Аналогично — `apply-seed.sh` подбирать интерпретатор при старте.

Альтернатива: в самих скриптах `python3 || python` через shebang `#!/usr/bin/env bash` + первая строка `PY=$(command -v python3 || command -v python)`. Менее invasive.

**Приоритет:** **HIGH** — это блокирует hooks на Windows.
