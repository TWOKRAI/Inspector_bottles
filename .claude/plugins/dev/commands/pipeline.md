---
description: Full development cycle in one command — plan → implement → test → review → ship (with failure-recovery via debugger)
disable-model-invocation: true
---

Автоматический полный цикл. Director управляет каждым этапом. Явные петли failure-recovery через `debugger` и эскалация в `teamlead`.

## Алгоритм

> **Нумерация стадий.** Заголовки `### N.` — порядок чтения; канонические ID стадий — `S0…S7`
> (research → plan → contract → RED → GREEN → final → review → integration). Машинные шлюзы —
> **callable gates** (S2 contract-complete, S3 RED-block, S7 Integration): вызываются вручную из
> этого файла, TRUE enforcement (git pre-commit/CI) — Phase 2.

### 0. Research (S0)

> Стартовая стадия выбора подхода с человеком в петле — **до** планирования.
> **Skip-условие:** задача явно trivial (один файл, нет кросс-модульных эффектов, < 1 дня) →
> S0 пропускается, `research.md` не создаётся; STATE.md фиксирует «S0 skipped (trivial)».

Запусти агента **investigator** (Opus, read-only) с активными skills `grill-me` и `brainstorm`:
- Передай задачу: $ARGUMENTS
- Investigator исследует задачу и генерирует `plans/YYYY-MM-DD_<slug>/research.md`:
  2–4 подхода с trade-offs, рекомендуемый подход, открытые вопросы.
- Если skills `grill-me`/`brainstorm` недоступны — investigator работает в free-form режиме
  и явно помечает это в `research.md` («skills unavailable — free-form analysis»).
- **Шлюз S0 (HUMAN):** пользователь выбирает подход или подтверждает рекомендованный →
  pipeline продолжается к §1. Это единственный шлюз системы, где решает человек, не машина.

### 1. Планирование
Запусти агента **manager** (Sonnet):
- Передай задачу: $ARGUMENTS
- Получи план с Task X.Y в `plans/` (slug-конвенция: kebab-case, `<домен>-<суть>`, max 40 симв.)
- Убедись что план содержит обязательный frontmatter (Slug, Дата, Статус, Ветка)
- **Сначала создай ветку, потом коммить план** (важен порядок — иначе plan-коммит осядет на текущей ветке, напр. `main`; и commit-msg hook требует `Refs:`, если на ветке `<type>/<slug>` уже есть план): `git checkout -b <type>/<slug>` (feat/fix/refactor/docs)
- Обнови поле `Ветка:` в плане → `<type>/<slug>`
- Сделай коммит плана на ветке: `docs(plans): создать план <slug>` + `Refs: plans/YYYY-MM-DD_<slug>.md`
- Покажи пользователю краткое резюме плана + имя ветки и спроси подтверждение

### 2. Реализация (Contract-first TDD: interface → red → green → refactor)

**Baseline (перед изменениями).** Один раз до первого изменения кода (до 2-INTERFACE / S2 Contract):
`python scripts/capture_baseline.py` → `.sentrux/baseline.json` (coverage% + опц. sentrux snapshot).
Это предусловие S7-delta: без baseline integrator (§7) работает в advisory mode — S7 gate не блокирует.

Для каждой Task X.Y из плана — **порядок обязателен**. Развилка по полю `Module contract:` из ТЗ:

| Module contract | Этапы 2 |
|---|---|
| `new-full` / `new-lite` | **2-INTERFACE → 2-RED → 2-GREEN → 2-REFACTOR** |
| `public-api-change` | **2-INTERFACE (правка) → 2-RED → 2-GREEN → 2-REFACTOR** |
| `impl-only` / `n/a` | **2-RED → 2-GREEN → 2-REFACTOR** (interface не трогается) |

**Почему такой порядок** (не бюрократия): без формального контракта-в-коде тест опирается на пересказ ТЗ — реализация и тест расходятся, потому что каждый интерпретирует ТЗ по-своему. С interface.py в коде у tester и developer **общая ground truth** (Protocol + Pre/Post). Без RED-первого агент-implementer подгоняет тесты под сломанный код — Pocock: «модель пишет код с ошибкой → пишет тест, подтверждающий это неверное поведение → подгоняет тест под свой сломанный код. Это **алгоритмическая оптимизация**, не злой умысел». Контракт-в-коде + RED-первым = двойная структурная защита.

**2-INTERFACE — формальный контракт ПЕРВЫМ** (только для `new-*` / `public-api-change`).
Запусти **developer** (Sonnet) или **teamlead** (Opus, если Senior+) с активным skill `module-contract`:
- Создаёт `interface.py` (full) или module docstring (lite) с `Protocol`/`ABC` + DbC: `Pre:`/`Post:`/`Invariants:` для каждой публичной функции
- README модуля: Purpose / Public API / Boundaries / Stability — **без** Usage examples на этом шаге (примеры = contract tests из 2-RED, не дублируем)
- Имплементации ещё нет — `_impl/` пустой или содержит только `raise NotImplementedError`
- Коммит: `feat(<scope>): interface for Task X.Y` + `Refs: plans/<slug>.md`. Layer: `interface` (если в commit-layers.txt).
- **callable gate S2 contract-complete** — детерминированная проверка полноты контракта перед 2-RED:
  `python scripts/s2_gate.py --interface <path/to/interface.py>`.
  `VERDICT: PASS` (exit 0) → каждая публичная функция (имя не с `_`) имеет `Pre:` и `Post:` в docstring → продолжить к 2-RED.
  `VERDICT: BLOCK` (exit 1) → перечислены функции без Pre/Post → вернуть developer/teamlead дополнить контракт, **не** идти в 2-RED на дырявом контракте.
  Нестандартный docstring-формат (не-ASCII, многострочный Pre/Post) парсер не классифицирует → эскалация к агенту **ai-judge** (семантическая проверка). callable gate — вызывается вручную; enforcement в git pre-commit/CI — Phase 2.

**2-RED — tester пишет failing-тест от контракта.**
Запусти агента **tester** (Sonnet) в режиме `MODE: red` (передай через header первых строк промпта — см. `agents/tester.md` → "How the orchestrator passes parameters"):
- Передай: путь к `interface.py` (или module docstring) из 2-INTERFACE + acceptance criteria из Task
- Tester читает **только** `interface.py` + Pre/Post в docstring, **не читает** `_impl/`. Если impl-only Task (нет 2-INTERFACE) — читает существующий контракт + спек.
- Tester пишет минимальный тест на одну Pre/Post строку (один тест = одна assertion)
- Tester запускает тест и **демонстрирует**, что он fails:
  - Для `new-*`: `NotImplementedError` (из заглушки в `_impl/`) или `AttributeError` (если impl ещё нет)
  - Для `public-api-change`/`impl-only`: `AssertionError` показывающий wrong output
  - Не годится: `ImportError` / `SyntaxError` (setup сломан, фикси test setup)
- Если тест passes → STOP. Тест неверен (тестирует текущее поведение, не желаемое). Переписать.
- **callable gate RED-block (S3)** — детерминированная перепроверка RED-состояния:
  `pytest <test> -v 2>&1 | tee /tmp/red_out.txt` → `python scripts/red_gate.py --report /tmp/red_out.txt`.
  `VERDICT: PASS` → RED подтверждён (FAILED + NotImplementedError/AssertionError) → продолжить к 2-GREEN.
  `VERDICT: BLOCK` → тест неверен (all-green) либо setup сломан (ImportError/SyntaxError) → переписать тест.
  (callable gate — вызывается вручную; enforcement в git pre-commit/CI — Phase 2.)
- Коммит: `test(<scope>): failing test for Task X.Y` + `Refs: plans/<slug>.md`

**2-GREEN — developer/teamlead пишет минимальную реализацию.**
- Если уровень Senior/Senior+ → запусти **teamlead** (Opus)
- Если уровень Middle/Middle+ → запусти **developer** (Sonnet)
- Передай: путь к `interface.py` + путь к failing-тесту (агент **читает оба**, не угадывает контракт)
- Цель — **минимальный код в `_impl/`, чтобы failing-тест прошёл и Pre/Post из interface соблюдены**. Никакой over-engineering под будущие сценарии.
- Агент **не правит** `interface.py` и failing-тест. Если контракт оказался неверен — это сигнал переделать ТЗ в плане + вернуться к 2-INTERFACE, **не** подогнать тест/импл.
- Коммит: `feat(<scope>): impl for Task X.Y` + `Refs: plans/<slug>.md`. Обнови статус `[PENDING]` → `[DONE]`.

**2-REFACTOR (опц.) — если 2-GREEN оставил очевидный долг.**
- Если реализация уродлива но проходит тест → `developer` чистит в том же контексте, тесты остаются зелёными после каждой правки.
- Контракт (`interface.py`) **не трогается** — это меняет публичный API, должно идти через `public-api-change` Task.
- Skip если код и так чистый.

### 3. Regression — tester прогоняет полный suite

Запусти агента **tester** (Sonnet) в режиме `MODE: regression` (передай через header первых строк промпта):
- Цель: проверить, что 2b/2c **не сломали соседний код** (не Task-acceptance — те уже зелёные из 2a).
- Прогон: `pytest` весь модуль/слой + relevant integration tests.
- **Live-smoke (S5-гейт перед S6)** — зелёный pytest ≠ приложение стартует. Один smoke-сценарий «приложение запускается и отвечает» ловит класс багов, невидимых для unit-тестов (import-cycle при старте, broken entrypoint, misconfigured env):
  - **CLI / есть entrypoint** → определи **реальную** точку входа и запусти её non-destructive (`--version`/`--help`): **сначала** `[project.scripts]` из `pyproject.toml` — `uv run <console-command> --version`, или `/core:infra:run-proto` (сам резолвит entrypoint из `[project.scripts]`/`make run`/`python -m`); голый `uv run python -m <pkg>` — **только** если у пакета есть `__main__.py` (иначе падает «No module named `<pkg>.__main__`» для проектов с console-scripts entrypoint). Не делает реальную работу.
  - **Web / GUI** → подними приложение, Playwright `navigate` + `screenshot` главного экрана (web) или qt-mcp `qt_screenshot` (GUI); проверь отсутствие fatal в логах старта.
  - **Skip** если у проекта нет entrypoint или это library-only → достаточно `uv run python -c "import <pkg>"`. Запиши в статус «live-smoke: skipped (library-only)».
  - **Шлюз:** smoke FAIL → **СТОП перед шагом 4**: не ревьюить нерабочее приложение — developer/teamlead чинит старт (та же петля 2-итерации→эскалация, что для regression FAIL).
- Если PASS (suite + live-smoke) → шаг 4 (ревью)
- Если FAIL:
  - **Итерация 1 (FAIL)**: запусти **debugger** (Sonnet) с failing-тестом и стеком → либо debugger фиксит в scope, либо выдаёт диагноз → `developer`/`teamlead` применяет фикс → tester retry regression
  - **Итерация 2 (повторный FAIL)**: снова debugger + developer → tester retry
  - **Итерация 3 (всё ещё FAIL)**: **СТОП**, эскалируй в **teamlead** (Opus) — либо ТЗ неадекватно, либо нужен пересмотр архитектуры

### 4. Ревью
Запусти агента **reviewer** (Opus):
- Передай: `git diff main...HEAD` + план + acceptance criteria
- Если APPROVED → шаг 5 (ship)
- Если CHANGES REQUESTED:
  - **Итерация 1**: `developer`/`teamlead` применяет правки → reviewer повторный review
  - **Итерация 2** (последняя): `developer`/`teamlead` финальный шанс → reviewer
  - **Итерация 3**: **СТОП**, эскалация в **teamlead** (Opus) для пересмотра ТЗ или архитектуры

**Model diversity (advisory).** Ревью ценнее, когда ошибки ревьюера **не коррелируют**
с ошибками имплементера: один и тот же вес модели склонен повторить слепое пятно автора
(«uncorrelated errors» — независимый ревьюер ловит то, что автор структурно не видит).
Идеал — ревью моделью **другого семейства/версии**, чем писала код.
- **Конфиг (когда станет возможным):** `reviewer_model: claude-opus-4-9` в этом файле или
  `.claude/modes/_stack.md` → оркестратор поднимает reviewer на указанной модели в S6.
- **Текущий статус — advisory-only:** Claude Code привязан к семейству `claude-*`, кросс-вендор
  ревью недоступен; пока выбирай **максимально иную доступную** конфигурацию (новейшая версия
  Opus / extended thinking для reviewer), даже если имплементер был на ней же. Поле
  `reviewer_model:` фиксирует намерение для будущего, фактически reviewer остаётся Opus.

### 7. Integration (S7)

> Запускается после §4 Ревью, перед Ship (концептуально: S6 Review → S7 Integration → Ship).
> **callable gate** — вызывается вручную из этого файла; TRUE enforcement (git pre-commit/CI) — Phase 2.

Запусти агента **integrator** (Opus, read-only):
- Передай: список изменённых файлов (`git diff --name-only main...HEAD`) + путь к `.sentrux/baseline.json`.
- Integrator создаёт `plans/YYYY-MM-DD_<slug>/integration.md` (с machine-readable JSON-блоком).
- Запусти **callable gate**: `python scripts/integration_gate.py --report plans/.../integration.md`
  - exit 0 (`VERDICT: PASS`) → продолжить к §5 Документация / §6 Ship.
  - exit 1 (`VERDICT: BLOCK`) → **СТОП**. Возврат к `developer`/`teamlead` для устранения причины
    (новый цикл зависимостей / coverage-drop > 5% / рост god-node > 20%). Те же **2 итерации** →
    эскалация в **teamlead**.
- **Advisory-skip:** если integrator вернул PASS с пометкой «MCP unavailable» (или нет
  `.sentrux/baseline.json` — Task 1.6 не выполнен) → pipeline продолжается, в лог пишется
  «S7 advisory: no MCP data / no baseline — delta unavailable».

### 5. Документация и диаграммы (опционально)
Если задача затрагивает архитектуру:
- Обычная документация (docstrings, README) → **docs-writer** (Haiku)
- ADR / ARCHITECTURE.md / migration guide → **tech-writer** (Sonnet)
- **Диаграммы устарели** (менялись модули / зависимости / публичный API) → `/core:infra:diagrams` (pyreverse + pydeps + опц. mermaid) — регенерируй из кода, не рисуй руками
- **Менялось пользовательское поведение фичи** → синхронизируй живое ТЗ: `/dev:spec:spec-sync` (spec-writer сверяет `docs/direction/` с кодом)

### 6. Ship
Выполни `/dev:ship`:
- validate → тесты → линтер
- Покажи итоговый diff
- Предложи commit message в формате Conventional Commits + trailers
  (`Why:`, `Layer:`, `Refs:` — **обязательно** если есть файл плана для текущей ветки, + опц. `Risk:` / `Reversible:` / `Tested:` / `Rejected:`).
  Полный гайд: `.claude/COMMIT_GUIDE.md`. Валидация: `scripts/validate_commit/validate_commit.py`.
- Если все Task в плане = [DONE] → предложи закрыть план (Status: DONE, отдельный коммит `docs(plans): закрыть <slug>`)
- Спроси разрешение на push

## Failure-recovery граф

```
                  ┌─ new-* / public-api-change ─→ INTERFACE (Protocol+DbC) ─┐
plan → (developer)│                                                          │
                  └─ impl-only / n/a ───────────────────────────────────────→┴→ tester(RED) → impl(GREEN) → [refactor] → tester(regression)
                                                                                                                       ↓ PASS  ↓ FAIL
                                                                                                                       review  debugger → impl [fix] → tester (retry)
                                                                                                                                       ↓ FAIL (итерация 2)
                                                                                                                                       debugger → impl → tester
                                                                                                                                           ↓ FAIL (итерация 3)
                                                                                                                                           ESCALATE → teamlead (пересмотр)

review → [APPROVED] → integration (S7) → docs? → ship
review → [CHANGES] → impl → tester(regression) → review (итерация 2)
                ↓ CHANGES (итерация 3)
                ESCALATE → teamlead (пересмотр ТЗ/архитектуры)

integration (S7) → integrator → integration_gate.py
                ↓ PASS                    ↓ BLOCK (новый цикл / coverage-drop / god-node)
                docs? → ship              developer/teamlead [fix] → integration (retry)
                                                  ↓ BLOCK (итерация 3)
                                                  ESCALATE → teamlead
```

## Правила

- Между этапами показывай пользователю краткий статус
- **S0 (§0) пропускается** при trivial-задачах (один файл, нет кросс-модульных эффектов, < 1 дня)
- **callable gates (S2 contract-complete, S3 RED-block, S7 Integration)** вызываются вручную из этого
  файла через `scripts/s2_gate.py` / `scripts/red_gate.py` / `scripts/integration_gate.py`;
  TRUE enforcement (git pre-commit/CI) — Phase 2
- **Максимум 2 итерации** на каждой петле (test-fix-test, review-fix-review) — на 3-й эскалация в **teamlead**
- debugger вызывается автоматически на первом FAIL от tester (не ждать ручного /dev:debug)
- Если задача явно Senior+ → сразу teamlead на implementation (не developer)
- Если архитектурное изменение — reviewer проверяет, что есть запись в `DECISIONS.md` (или вызван tech-writer)
- По умолчанию этапы **последовательны**; для плана с независимыми Task — opt-in **Parallel mode** (см. ниже)

## Token budget (observability, opt-in)

Чтобы мерить реальную стоимость pipeline (честное «до/после», а не оценка на глаз),
каждая стадия может логировать токены/tool-calls в `data/pipeline-metrics.jsonl`
(append-only, gitignored) через opt-in Stop-hook `token-budget-meter.sh`.

**Включение** (по умолчанию НЕ зарегистрирован — это инструмент, не always-on guard):
добавь в `.claude/settings.json` под `"hooks"`:
```json
"Stop": [
  { "hooks": [{ "type": "command",
                "command": "${CLAUDE_PLUGIN_ROOT}/hooks/token-budget-meter.sh",
                "timeout": 10 }] }
]
```
и вокруг каждой стадии экспортируй `PIPELINE_STAGE=S3` (S0…S7). Запись на стадию:
`{ts, session_id, stage, tokens_in, tokens_out, tool_calls}`.

**Hard-stop правило.** Задай бюджет стадии через `PIPELINE_STAGE_BUDGET=<tokens>`.
Если `tokens_in + tokens_out > budget` — хук пишет warning в stderr (Stop-hook не может
заблокировать событие). Оркестратор, увидев breach (warning или запись в jsonl выше
порога), **ОБЯЗАН остановить стадию** перед переходом к следующей и **эскалировать в
teamlead** (стадия вышла за бюджет → вероятен loop/drift; не продолжать жечь токены).
Это та же дисциплина, что smart-zone (см. `CLAUDE.md` → Behavioral additions): бюджет —
упреждающий гейт, не ретроспективный.

## Parallel mode (опц.) — fan-out по независимым Task

> Включай **только** когда план содержит независимые Task (поле `Dependencies:` у manager
> пустое, `Files:` не пересекаются) и большой план нужно ускорить. По умолчанию
> `/dev:pipeline` последовательный; parallel mode — opt-in, его риски реальны.

**Механизм — нативная изоляция субагента, НЕ session-worktree.**
Fan-out делается через `Agent(isolation: "worktree")` на **пишущих** агентах (developer,
tester), запущенных несколькими Agent-вызовами в одном сообщении. `EnterWorktree` /
`ExitWorktree` переключают **всю сессию** в один worktree и не умеют параллелить (сессия =
один worktree) — это escape-hatch для изоляции одной Task, не инструмент fan-out. Контракт
изоляции, lifecycle и какие агенты годятся — [`core/agents/_WORKTREE_PATTERN.md`](../../core/agents/_WORKTREE_PATTERN.md).

**Кто в worktree, кто нет:**
- **developer + tester** (пишут файлы и коммитят) → каждый в своём `isolation: "worktree"`.
- **reviewer** (read-only, не коммитит) → worktree НЕ нужен; reviewer'ов по разным Task можно
  гнать параллельно без изоляции (читают только закоммиченный diff, не гонятся за файлы).

**Поток:**
1. **Gate независимости.** Бери Task без `Dependencies:` и с непересекающимися `Files:`.
   Зависимые / пересекающиеся по файлам → последовательно (иначе merge-конфликты). `Dependencies:`
   опционально → при его отсутствии И возможном пересечении файлов **по умолчанию
   последовательно** (отсутствие поля ≠ доказательство независимости).
2. **Pre-flight (base-ref).** Выстави `worktree.baseRef=head` — worktree ветвится от локального
   HEAD (feature-ветка со всем WIP). Дефолт `fresh` базируется от `origin/<default-branch>`,
   поэтому worktree НЕ увидит коммиты ветки, ещё не вмёрженные в default. **Push feature-ветки в
   `origin/<feature>` это НЕ чинит** (нужен `baseRef=head` либо коммиты в `origin/<default>`) →
   иначе тесты против устаревшего кода. Не можешь выставить → **последовательно**.
3. **Fan-out.** На каждую независимую Task — developer+tester в `isolation:"worktree"` (этапы
   2-RED→2-GREEN как в §2), параллельными Agent-вызовами. Конкурентность ограничь (≤2-3
   worktree, см. Caps). ⚠️ tester в worktree без **per-worktree `uv sync`** даёт ложно-зелёные
   тесты против старого `src/` главного checkout'а — детали и фикс в _WORKTREE_PATTERN.md
   (venv false-green trap).
4. **Merge-back → cleanup.** Перед удалением worktree всё закоммичено/смержено (`ExitWorktree
   action:"remove"` откажет при незакоммиченных/несмёрженных правках без `discard_changes:true`).
   Lifecycle create→work→commit→merge-back→cleanup — см. _WORKTREE_PATTERN.md.
5. **Review.** После merge-back — reviewer на каждую Task (§4), можно параллельно (read-only).

**Caps.** Петлевой cap = **2 итерации → teamlead** действует как в §3/§4 (`## Правила`) — не
вводи второй источник. Доп. для parallel: держи **≤2-3 одновременных worktree** — это и
стоимость (Opus+Sonnet ×N), и надёжность: tooling-heavy агенты (teamlead, 40+ tool-uses) при
>1-2 параллельно рискуют попасть под session-limit и не успеть закоммитить (потеря работы).
Эскалируй в **teamlead** на конфликте merge-back / осиротевшем worktree (cleanup-команды — в
_WORKTREE_PATTERN.md; текущий cap покрывает только test-fail / review-петли, не worktree-сбои).

**Хук-гонки (worktree делят общий `.git/hooks`):**
- **qex post-commit reindex** срабатывает в КАЖДОМ worktree → гонка за `~/.qex` lock +
  фрагментация (индекс на каждый путь). Реиндексируй **только из главного worktree**; как
  отключить хук в fan-out и звать реиндекс вручную — `/mcp-qex:install-reindex-hook` (блок
  «Worktree / lock-гонка»). Класс проблемы — _WORKTREE_PATTERN.md (Local indexes per worktree).
- **session-log pre-commit hook** стейджит `docs/sessions/<today>.md` в каждый коммит → конфликт
  по этому append-only журналу **на каждом merge-back после первого**. Резолвь union-merge
  (журнал только дополняется); durable-фикс — `docs/sessions/*.md merge=union` в `.gitattributes`
  (отдельный follow-up).

Задача: $ARGUMENTS
