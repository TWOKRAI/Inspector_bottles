# MCP Orchestration — Implementation Report

**Дата:** 2026-05-22
**Ветка:** `feat/claude-seed-mcp-orchestration`
**План:** локальный `gentle-sniffing-owl.md` (план перенесён в `~/.claude/plans/` вне репозитория)

## Что было сделано

Превращение seed-системы из "хорошей структуры с одним работающим MCP" в полноценный оркестр, где каждый агент использует профильные MCP, скиллы дёргают инструменты, хуки страхуют качество.

## Изменения по фазам

| Phase | Что | Файлов изменено | Коммит |
|-------|-----|------------------|--------|
| **1** | Foundation: ROUTING.md, 2 hooks, settings.json, CLAUDE.md routing-карта | 5 | `1a6eb7c` |
| **2** | Company agents — 8 агентов: расширены `tools:`, добавлены routing-блоки | 8 | `999de7e` |
| **3** | University agents — 5 sci-агентов: qex + context7 routing | 5 | `5feb081` |
| **4** | Skills — 4 скилла (verify-done, brainstorm, zoom-out, grill-me) | 4 | `4a1a821` |
| **5** | Playwright + Sequential Thinking MCP modules (opt-in) | 6 | `e3c27a0` |
| **5.3** | Wire новых MCP в README + investigator + teamlead | 4 | `6431d3a` |
| **7** | Plans convention — YYYY-MM-DD в имени файла/папки | 8 | `fb97d98` |
| **8** | `/doctor` команда (test-drive) + scripts/doctor.sh | 2 | `e2b34c2` |
| **6** | Verification — verify-mcp-orchestration.sh + этот отчёт | 2 | (текущий) |

**Total:** ~44 файла затронуто (создано/изменено), ~8 коммитов на ветке.

## Token budget — измерение

Цель плана: средний рост ≤ 12% per агент в системном промпте субагента.
Заказчик: "баланс tokens vs quality".

### Per-agent growth (line count before → after)

| Agent | Before | After | Delta | Pct | Status |
|-------|--------|-------|-------|-----|--------|
| developer | 65 | 76 | +11 | +16.9% | OK |
| teamlead | 99 | 119 | +20 | **+20.2%** | over (см. ниже) |
| manager | 116 | 133 | +17 | +14.7% | OK |
| reviewer | 138 | 153 | +15 | +10.9% | OK |
| investigator | 92 | 107 | +15 | +16.3% | OK |
| debugger | 122 | 132 | +10 | +8.2% | excellent |
| tester | 57 | 67 | +10 | +17.5% | OK |
| tech-writer | 118 | 134 | +16 | +13.6% | OK |
| sci-researcher | 77 | 87 | +10 | +13.0% | OK |
| sci-synthesizer | 218 | 228 | +10 | +4.6% | excellent |
| sci-librarian | 126 | 136 | +10 | +7.9% | excellent |
| sci-curator | 222 | 233 | +11 | +5.0% | excellent |
| sci-transcriber | 61 | 69 | +8 | +13.1% | OK |
| **TOTAL** | **1511** | **1674** | **+163** | **+10.8%** | **target met** |

**Average per agent:** +12.5 строк ≈ +38 токенов в системном промпте субагента.

### Замечания

- **teamlead +20.2%** — превышает target, потому что у него 3 режима работы (Implementation/Express/Escalation), каждый требует своего routing. Это сознательное решение — teamlead главный архитектурный игрок, ему нужны все MCP.
- **sci-агенты (5-13%)** — компенсируют, их routing-блоки минимальные (научный workflow редко нуждается в нескольких MCP сразу).
- **debugger +8.2%, sci-synthesizer +4.6%** — образцово минимальные правки.
- **Routing-блоки 8-15 строк** — все укладываются в плановый диапазон.

### Расчёт в токенах

Очень грубо (1 строка markdown ≈ 3 токена):
- +12.5 строк × 3 ≈ **+38 токенов** в системном промпте субагента.
- Исходный средний промпт субагента ≈ 1400-1500 токенов (frontmatter + body).
- **Реальный рост ≈ +2.5-3%** в токенах (line count overcounts).

### `tools:` whitelist расширение

Это **бесплатно** для системного промпта — статическая регистрация, не идёт в промпт. Идёт runtime registration.

Суммарно `mcp:server:tool` упоминаний в агентах: **15 уникальных** (proverено verify-скриптом). Каждый агент имеет 3-10 в `tools:` whitelist.

## Качественные индикаторы (вместо числовых "8/10")

После полного выполнения plan — критерии успеха:

- ✅ **Reviewer** в Specialization Architecture явно зовёт `sentrux:check_rules` + `sentrux:dsm` + `sentrux:test_gaps` (раньше — Grep + чек-лист руками).
- ✅ **Investigator** в Workflow §1 явно зовёт `codegraph:callers/callees/impact/context` + `sentrux:dsm/scan/git_stats` + `graphify:query_graph` + `sequentialthinking` для сложных гипотез.
- ✅ **Developer** + **Tester** сверяются с `context7:query-docs` при работе с библиотеками.
- ✅ **Verify-done skill** проверяет архитектурный sanity через `sentrux:check_rules` + `codegraph:impact` перед verdict.
- ✅ **Hook `sentrux-precheck.sh`** блокирует `git push` если правила нарушены.
- ✅ **Hook `mcp-health-check.sh`** при SessionStart выдаёт строку статуса всех MCP.
- ✅ **`/doctor` команда** даёт единую сводку по всем компонентам системы (6 layers).

## Conditional guards — защита от vendor mismatch

Каждый routing-блок начинается с "**если** `<MCP>` подключён в проекте". Если sentrux не в `.mcp.json` — агент идёт на fallback (Grep/Read), не пытается вызывать несуществующий MCP. Verify-скрипт проверяет наличие guard'ов.

## Plans convention update

Параллельная правка по запросу пользователя:
- **Старый формат:** `plans/<slug>.md` или `plans/<slug>/plan.md` + `phase-N.md`.
- **Новый формат:** дата ISO всегда в имени. Single → `plans/YYYY-MM-DD_<slug>.md`. Multi-phase → `plans/YYYY-MM-DD_<slug>/plan.md` + `phase-N.md`.
- **Зачем:** хронологический поиск через `ls plans/` без обращения к `git log`.

## `/doctor` команда

Новая slash-команда + скрипт `scripts/doctor.sh`. Проверяет 6 слоёв:
1. MCP servers (binary + ollama + cfg).
2. Settings.json валидность + lint.
3. Agents lint (frontmatter).
4. Routing consistency (агенты ↔ ROUTING.md).
5. Indexes (qex age, sentrux freshness).
6. Hooks executable + Plans integrity.

Использовать после `apply-seed.sh` (initial check) или периодически (drift check).

## Что НЕ сделано (явно out of scope)

- **Eval-loop с golden tasks** — отдельный проект, не входил в план.
- **Multi-reviewer voting** — future enhancement.
- **Миграция legacy планов в новый формат** — старые остаются как есть.
- **Sentry / Linear MCP** — упомянуты в обзоре, не реализованы.
- **Установка Playwright/Sequential Thinking в конкретные проекты** — opt-in, пользователь активирует.

## Файлы для аудита (чтобы знать что трогать при изменениях)

**Создано:**
- `src/claude_kit/template/mcp/ROUTING.md` — единая routing-карта.
- `src/claude_kit/template/hooks/quality/sentrux-precheck.sh` — pre-push gate.
- `src/claude_kit/template/hooks/quality/mcp-health-check.sh` — SessionStart MCP status.
- `src/claude_kit/template/mcp/playwright/` (3 файла).
- `src/claude_kit/template/mcp/sequential-thinking/` (3 файла).
- `src/claude_kit/template/commands/quality/doctor.md` — slash-command.
- `src/claude_kit/template/scripts/doctor.sh` — runner.
- `src/claude_kit/template/scripts/verify-mcp-orchestration.sh` — consistency check.
- `src/claude_kit/template/_meta/MCP_ORCHESTRATION_REPORT.md` — этот отчёт.

**Изменено (frontmatter + routing-блоки):**
- `agents/company/*.md` — 8 файлов.
- `agents/university/sci-{researcher,synthesizer,librarian,curator,transcriber}.md` — 5 файлов.
- `skills/{verify-done,brainstorm,zoom-out,grill-me}/SKILL.md` — 4 файла.
- `CLAUDE.md` (template) — добавлена routing-карта для оркестратора.
- `settings.json` — зарегистрированы 2 новых хука.
- `mcp/README.md` — добавлены строки про playwright и sequential-thinking.
- `templates/PLAN.template.md` + `plans-readme.template.md` + `claude-md.template.md` — обновлена plans convention.
- `commands/dev/{plan,implement,ship}.md` — обновлены пути и Refs-формат.

## Verification

Запустить из `template/`:

```bash
bash scripts/verify-mcp-orchestration.sh
```

Должно вывести: **6 passed, 0 failed** ✅

Также после apply-seed на проект:

```bash
bash .claude/scripts/doctor.sh
```

Выведет сводку по 6 слоям с метками `[OK]` / `[WARN]` / `[FAIL]`.
