---
description: System test-drive — one command to check MCP, agents, skills, hooks, indexes. After `claude-kit-project new` and periodically.
---

Запусти проверку здоровья всей системы Claude-Kit. Это **read-only diagnostic** — ничего не чинит, только сообщает что работает, что нет, и что требует внимания.

## Что проверяется

1. **MCP layer** — какие MCP-серверы доступны:
   - qex (binary + Ollama для embeddings)
   - sentrux (binary)
   - context7 (cfg в `~/.claude.json` или `.mcp.json`)
   - optional MCP из `.mcp.json`: codegraph, ast-grep, serena, graphify, github, qt-mcp, playwright, sequential-thinking

2. **Config layer** — валидность конфигурации:
   - `settings.json` — JSON валиден + критичные deny/ask/allow на месте (через `/core:quality:lint-settings`)
   - `agents/*/*.md` — frontmatter валиден (через `/core:quality:lint-agents`)

3. **Routing consistency** — согласованность routing-блоков агентов с `.claude/plugins/core/mcp/ROUTING.md`:
   - Все `mcp__server__tool` упомянутые в агентах есть в ROUTING.md
   - Нет orphan-инструментов в ROUTING.md (упомянуты, но никто не использует)

3b. **Content lints** — единый язык + неймспейсинг команд:
   - **Language** (`lint_language.py`) — нет кириллицы в `agents/` и `modes/` (EN-only зоны; FAIL при регрессии). Тела `commands/`/`skills/`, ждущие отложенного EN-прохода, — non-blocking WARN.
   - **Namespacing** (`lint_namespacing.py`) — нет legacy flat-имён команд (`/plan` → `/dev:plan` и т.п.) в контенте плагинов. <!-- lint-namespacing: ignore -->

4. **Indexes** — состояние индексов MCP (если активны):
   - qex: `qex --version` + (опц.) индекс существует
   - sentrux: `sentrux --version` + (опц.) свежий scan

5. **Hooks** — исполнимость:
   - Все `.sh` в `.claude/plugins/*/hooks/` имеют executable bit
   - Тестовый запуск каждого хука с пустым stdin (smoke check, не должны крашиться)
   - **Git hooks** (`.git/hooks/`, opt-in, per-machine): установлен ли `post-commit`
     (qex auto-reindex, `/mcp-qex:install-reindex-hook`) и `pre-push` (sentrux gate,
     `/mcp-sentrux:install-pre-push`). Отсутствие — норма (не warn, видно в verbose).

6. **Plans** — целостность планов:
   - `plans/` существует
   - Нет orphan-папок (multi-phase без `plan.md` внутри)
   - Refs-трассировка свежих коммитов: коммиты на текущей ветке с Refs указывают на существующие файлы

7. **Harness-bloat** — потолки ROADMAP § J (advisory soft-warning, держит систему в «smart zone»):
   - **agents ≤ 12** в одном team-плагине (seed: `dev` ровно 12 — у потолка)
   - **hooks ≤ 15** в одном плагине (seed: `core` ровно 15 — у потолка)
   - **skills ≤ 15** суммарно по всем плагинам (seed: ~9)
   - **MCP ≤ 8** настроенных серверов в `.mcp.json` (default: ~4)
   - Счёт **per-plugin** для agents/hooks (единица bloat — плагин; плоский total
     сложил бы dev+core и фолс-срабатывал бы на самом seed), **total** для skills/MCP.
   - **Только WARN, никогда FAIL** — пересечение потолка это сигнал консолидировать
     (свернуть/объединить), а не сломанная система. Свежий `claude-kit-project new` = чисто
     (всё ровно у потолка или ниже); WARN появляется, когда проект **перерастает** § J.

## Как запускать

```bash
# Запустить из корня проекта (где .claude/)
bash .claude/plugins/core/scripts/doctor.sh

# Или с verbose выводом
bash .claude/plugins/core/scripts/doctor.sh --verbose
```

## Output

Команда выводит сводную таблицу с метками `[OK]` / `[WARN]` / `[FAIL]` + краткое описание. Финальный verdict в конце.

Пример:
```
=== Claude-Kit System Health ===

MCP servers       [OK]    qex UP  ollama UP  sentrux UP  context7 cfg
Settings lint     [OK]
Agents lint       [OK]    19/19 valid
Routing sync      [OK]    all mcp__server__tool references valid
Language lint     [OK]    agents/ + modes/ are EN-clean (N non-blocking warn(s) in deferred bodies)
Namespacing lint  [OK]    no flat command names
Indexes           [WARN]  qex index age: 5 days (consider /mcp-qex:qex-reindex)
Hooks executable  [OK]    14/14 +x
Git hooks         [OK]    post-commit installed (qex auto-reindex)
Plans integrity   [OK]    3 plans, no orphans
Harness-bloat     [OK]    agents:12/12(dev) hooks:15/15(core) skills:9/15 mcp:4/8 — within §J ceilings

Verdict: ✅ Healthy (1 warning — informational)
```

## Когда использовать

- **После `claude-kit-project new`** — убедиться что инфраструктура развернулась корректно.
- **Периодически** — раз в неделю / при возврате к проекту после паузы (drift check).
- **Перед длинной сессией работы** — быстрая проверка что MCP UP, чтобы агенты не тратили токены на тихие падения.
- **При подозрении на проблему** — "почему агенты ведут себя странно?" → `/core:quality:doctor` покажет если MCP не отвечают.

## Exit codes (для CI)

- `0` — всё OK (могут быть WARN, но критичных проблем нет)
- `1` — есть FAIL (что-то критичное не работает)
- `2` — есть FAIL + WARN

## Auto-fix (out of scope для v1)

Эта команда **только диагностирует**. Для починки см. предложения в выводе:
- `WARN qex index age` → `/mcp-qex:qex-reindex`
- `FAIL Ollama DOWN` → `ollama serve` или `/core:infra:cold-start`
- `FAIL Settings lint` → исправь `.claude/settings.json` руками
- `FAIL Routing sync` → правь routing-блоки агентов чтобы упоминать только инструменты из ROUTING.md
- `FAIL Language lint` → переведи кириллицу в `agents/`/`modes/` на EN (или пометь `<!-- lint-language: allow -->`)
- `FAIL Namespacing lint` → замени flat-имена команд на namespaced (см. `docs/plugin-namespacing.md`)
- `WARN Harness-bloat` → проект пересёк потолок § J: сверни/объедини лишние агенты/хуки/skills или отключи неиспользуемые MCP в `enabled.yaml` (advisory — не блокирует)

$ARGUMENTS
