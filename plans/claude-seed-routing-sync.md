# План: claude-seed-routing-sync

**Slug:** `claude-seed-routing-sync`
**Ветка:** `feat/claude-seed-routing-sync` (создаётся в репозитории claude_seed, не здесь)
**Целевой репозиторий:** upstream `claude_seed` (bundled template источник для `claude-kit`)
**Дата:** 2026-05-26
**Автор:** Director (Opus)
**Статус:** ✅ **DONE upstream** (закрыт в seed 0.5.2 — `scripts/lint_routing.py` + canonical `ROUTING.md`, doctor зелёный)

---

## Проблема

После `claude-kit upgrade 0.4.0 → 0.5.0` локальный `bash .claude/scripts/doctor.sh` даёт **FAIL Routing sync**: 29 из 37 `mcp:server:tool` упоминаний в агентах отсутствуют в `ROUTING.md`.

Причина — не дрейф проекта, а **семантическое рассогласование внутри самого seed-шаблона**:

1. **Агенты** (`.claude/agents/company/*.md`) пишут tools в формате `mcp:server:tool` (через одинарное двоеточие, с префиксом `mcp:`).
2. **ROUTING.md** перечисляет tools в трёх разных форматах:
   - `mcp__server__tool` — полный (matches регулярки doctor'а).
   - `server:tool` — без префикса `mcp:` (matches фрагменту, но не правильно).
   - `tool` или `server_tool` — без префиксов вообще (не matches).
3. **Regex в `.claude/scripts/doctor.sh:174-175`** ищет строго `mcp:server:tool` ИЛИ `mcp__server__tool`. Короткие формы пропадают.

**Эффект:** свежесозданный проект через `claude-kit new` сразу красный на `doctor`. Это плохой first-impression и подрывает доверие к `doctor` как индикатору здоровья.

**В моём проекте:** локально починил [.claude/mcp/ROUTING.md](.claude/mcp/ROUTING.md) — добавил блоки `**Canonical refs:**` в 6 секций (codegraph, serena, ast-grep, graphify, qt-mcp, sequential-thinking). Doctor стал 6 OK + 1 WARN (qex index, не блокирующее).

**Без upstream-фикса:** следующий `claude-kit upgrade` затрёт мой ROUTING.md → FAIL вернётся.

---

## Цели

1. **ROUTING.md в seed** должен быть consistent с регулярками `doctor.sh` — все упоминания tools в канонической форме `mcp:server:tool`.
2. **Сам `doctor.sh`** должен быть устойчив к коротким формам в описаниях (defense in depth) — расширить regex чтобы matchить также `server:tool` в контексте секции.
3. **Lint в seed**: добавить проверку «каждый tool из агентов = упомянут в ROUTING.md» в pre-commit / CI самого `claude_seed` — чтобы новые агенты не разъезжались с ROUTING.md.

---

## Scope

**В scope (только seed-репозиторий):**

- `template/.claude/mcp/ROUTING.md` — добавить блоки `**Canonical refs:**` для каждого MCP-сервера (как в моём локальном фиксе, но в каноническом template).
- `template/.claude/scripts/doctor.sh` — расширить regex чтобы понимать также `server:tool` в контексте раздела `### <server>`.
- `template/.claude/scripts/lint_routing.py` (новый) — отдельный линтер, который сравнивает агенты ↔ ROUTING.md строже doctor'а (для CI).
- `template/.claude/CHANGELOG.md` — запись о breaking-fix.
- Bump template version `0.5.0 → 0.5.1` (patch — багфикс, без миграции).

**Вне scope:**

- Изменения формата routing-блоков в самих агентах (они уже в каноне `mcp:server:tool`).
- Миграции — фикс обратносовместимый, старые ROUTING.md проектов будут просто перезаписаны на корректные.
- Добавление новых MCP-серверов.

---

## Задачи

### Task 1 — ROUTING.md: канонические refs во всех секциях

**Level:** Junior+ (Haiku)
**Assignee:** docs-writer
**Goal:** добавить блок `**Canonical refs:**` после каждой секции `### <server>` со списком всех tools в формате `mcp:server:tool`.

**Files:**
- `template/.claude/mcp/ROUTING.md`

**Steps:**
1. Для каждой `### <server>` секции собрать список упоминаемых tools (включая короткие формы из описательных bullet'ов).
2. После последнего bullet'а (но до следующей `###`) добавить:
   ```
   **Canonical refs:** `mcp:<server>:<tool1>`, `mcp:<server>:<tool2>`, ….
   ```
3. Покрыть все серверы: qex, sentrux, context7, codegraph, serena, ast-grep, graphify, github-mcp, qt-mcp, playwright, sequential-thinking.

**Acceptance criteria:**
- [ ] Каждая `### <server>` секция содержит ровно один блок `**Canonical refs:**`.
- [ ] Все tools упоминаемые в любом агенте template'а matchятся канонической refs (проверка через `lint_routing.py` из Task 3).
- [ ] Описательный текст НЕ удаляется — только добавляется новый блок.
- [ ] Дубликаты `### playwright` / `### sequential-thinking` (есть в текущем ROUTING.md, строки 160-186) — мерджатся в одну секцию.

**Out of scope:** менять описательный текст, добавлять новые tools.

---

### Task 2 — doctor.sh: устойчивый regex для коротких форм

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** научить `doctor.sh` понимать tools в виде `server:tool` (без префикса `mcp:`) если они находятся в контексте `### <server>` секции в ROUTING.md. Текущее поведение слишком хрупкое.

**Files:**
- `template/.claude/scripts/doctor.sh` (строки ~169-193, блок «Routing consistency»)

**Steps:**
1. Заменить однострочный `grep -oE` на двухпроходный парсинг ROUTING.md:
   - Пройти по файлу построчно, отслеживать текущую `### <server>` секцию.
   - Внутри секции `<server>` собирать все идентификаторы вида `<tool>` (snake_case или kebab-case) → нормализовать в `mcp:<server>:<tool>`.
2. Альтернативно (если bash-парсер слишком сложен): добавить второй проход `grep -oE "<server>:[a-zA-Z_-]+"` для каждого сервера из списка и склеить.
3. Сохранить backwards compat — existing форматы `mcp__server__tool` и `mcp:server:tool` тоже matchятся.

**Acceptance criteria:**
- [ ] `bash .claude/scripts/doctor.sh` на тестовом ROUTING.md (с коротким форматом) даёт OK Routing sync.
- [ ] На canonical ROUTING.md (после Task 1) — тоже OK.
- [ ] Skрипт работает в Git Bash / WSL / Linux одинаково (без GNU-only флагов).

**Out of scope:** переписывать на Python (хочется оставить bash для портабельности).

---

### Task 3 — lint_routing.py: строгий CI-линтер

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** новый скрипт `lint_routing.py` для строгой проверки в pre-commit самого `claude_seed` — чтобы шаблон не уходил в релиз с дрейфом.

**Files:**
- `template/.claude/scripts/lint_routing.py` (новый)
- `template/.pre-commit-config.yaml` (добавить hook)

**Steps:**
1. Скрипт ищет все `mcp:server:tool` в `template/.claude/agents/**/*.md`.
2. Парсит `template/.claude/mcp/ROUTING.md`, собирает canonical refs (из новых блоков `**Canonical refs:**`).
3. Сравнивает множества:
   - `agents \ routing` → ошибка «agent X references unknown tool».
   - `routing \ agents` → warning «routing lists orphan tool».
4. Exit code: 0 = clean, 1 = errors, 2 = warnings only.
5. Pre-commit hook запускает скрипт перед коммитом в seed-репозитории.

**Acceptance criteria:**
- [ ] `python lint_routing.py` на чистом template даёт exit 0.
- [ ] Если умышленно убрать одну canonical ref → exit 1 + понятная ошибка.
- [ ] Hook отрабатывает за <1s.

**Out of scope:** интеграция в проектный doctor.sh (это Task 2).

---

### Task 4 — CHANGELOG + version bump

**Level:** Junior (Haiku)
**Assignee:** docs-writer
**Goal:** зафиксировать изменения в seed CHANGELOG, поднять версию `0.5.0 → 0.5.1`.

**Files:**
- `template/CHANGELOG.md` (или `_meta/CHANGELOG.md`)
- `template/_meta/VERSION` (или эквивалент в seed-репо)

**Steps:**
1. Запись в CHANGELOG:
   ```
   ## 0.5.1 — 2026-05-26
   ### Fixed
   - ROUTING.md и doctor.sh теперь consistent — Routing sync FAIL после `claude-kit new`
     устранён. Добавлены canonical refs в каждую секцию.
   ### Added
   - `lint_routing.py` — pre-commit gate против дрейфа агенты ↔ ROUTING.md в самом seed.
   ```
2. Bump VERSION → `0.5.1`.

**Acceptance criteria:**
- [ ] CHANGELOG обновлён.
- [ ] VERSION = 0.5.1.

---

## Порядок выполнения

1. Task 1 (ROUTING.md) — основной фикс, разблокирует остальное.
2. Task 3 (lint_routing.py) — параллельно, использует данные из Task 1.
3. Task 2 (doctor.sh regex) — defense in depth, можно отложить, но желательно в этом же релизе.
4. Task 4 (CHANGELOG + version) — финальный коммит.

**Acceptance gate перед merge в `main` claude_seed:**
- `lint_routing.py` exit 0
- `doctor.sh` на test-fixture проекте даёт 0 FAIL по Routing sync
- В тестовом проекте после `claude-kit upgrade --apply` имеем 0 FAIL

---

## Риски

| Риск | Митигация |
|------|-----------|
| Фикс ROUTING.md в seed конфликтнёт с моими локальными правками в проекте | После upstream-фикса я **удалю** свои canonical-блоки и сделаю `claude-kit upgrade --apply` — он принесёт каноническую версию. |
| `lint_routing.py` найдёт другие дрейфы которые ломают CI seed'а | Перед мержем pruning — либо чиним сейчас, либо добавляем в whitelist с TODO. |
| doctor.sh regex усложняется и ломает Git Bash | Покрыть тестами на 3 платформах (Win Git Bash, WSL, Linux) до merge. |

---

## Reversibility

- Все изменения текстовые, в `.md` / `.sh` / `.py`. Откат — `git revert`.
- Никаких миграций состояния / breaking API изменений.
- Reversible: yes.

---

## После апстрим-фикса (в этом проекте)

Когда seed выкатит 0.5.1:

1. `claude-kit upgrade --dry-run` → должен показать что ROUTING.md модифицируется (заменяется на canonical-версию).
2. Удалить мои локальные canonical-блоки (или просто принять upstream — они будут эквивалентны).
3. `claude-kit upgrade --apply`.
4. `bash .claude/scripts/doctor.sh` → 6 OK + 1 WARN (qex index — не относится к этому плану).
5. Commit: `chore(claude-kit): bump bundled seed → 0.5.1 — Routing sync fix`.

---

## Notes

- Этот план — для **upstream `claude_seed`**, не для текущего проекта. В `plans/` сохраняется как living-doc о моих требованиях к seed'у.
- Локальный фикс в [.claude/mcp/ROUTING.md](.claude/mcp/ROUTING.md) — временная заплатка до upstream-релиза 0.5.1.
- Если у seed-репозитория есть свой issue tracker — этот файл следует продублировать туда как RFE.
