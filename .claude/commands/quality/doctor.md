---
description: Test-drive системы — единая команда для проверки MCP, агентов, скиллов, хуков, индексов. После `claude-kit new` и периодически.
---

Запусти проверку здоровья всей системы Claude-Kit. Это **read-only diagnostic** — ничего не чинит, только сообщает что работает, что нет, и что требует внимания.

## Что проверяется

1. **MCP layer** — какие MCP-серверы доступны:
   - qex (binary + Ollama для embeddings)
   - sentrux (binary)
   - context7 (cfg в `~/.claude.json` или `.mcp.json`)
   - optional MCP из `.mcp.json`: codegraph, ast-grep, serena, graphify, github, qt-mcp, playwright, sequential-thinking

2. **Config layer** — валидность конфигурации:
   - `settings.json` — JSON валиден + критичные deny/ask/allow на месте (через `/lint-settings`)
   - `agents/*/*.md` — frontmatter валиден (через `/lint-agents`)

3. **Routing consistency** — согласованность routing-блоков агентов с `.claude/mcp/ROUTING.md`:
   - Все `mcp:server:tool` упомянутые в агентах есть в ROUTING.md
   - Нет orphan-инструментов в ROUTING.md (упомянуты, но никто не использует)

4. **Indexes** — состояние индексов MCP (если активны):
   - qex: `qex --version` + (опц.) индекс существует
   - sentrux: `sentrux --version` + (опц.) свежий scan

5. **Hooks** — исполнимость:
   - Все `.sh` в `.claude/hooks/` имеют executable bit
   - Тестовый запуск каждого хука с пустым stdin (smoke check, не должны крашиться)

6. **Plans** — целостность планов:
   - `plans/` существует
   - Нет orphan-папок (multi-phase без `plan.md` внутри)
   - Refs-трассировка свежих коммитов: коммиты на текущей ветке с Refs указывают на существующие файлы

## Как запускать

```bash
# Запустить из корня проекта (где .claude/)
bash .claude/scripts/doctor.sh

# Или с verbose выводом
bash .claude/scripts/doctor.sh --verbose
```

## Output

Команда выводит сводную таблицу с метками `[OK]` / `[WARN]` / `[FAIL]` + краткое описание. Финальный verdict в конце.

Пример:
```
=== Claude-Kit System Health ===

MCP servers       [OK]    qex UP  ollama UP  sentrux UP  context7 cfg
Settings lint     [OK]
Agents lint       [OK]    19/19 valid
Routing sync      [OK]    all mcp:server:tool references valid
Indexes           [WARN]  qex index age: 5 days (consider /qex-reindex)
Hooks executable  [OK]    14/14 +x
Plans integrity   [OK]    3 plans, no orphans

Verdict: ✅ Healthy (1 warning — informational)
```

## Когда использовать

- **После `claude-kit new`** — убедиться что инфраструктура развернулась корректно.
- **Периодически** — раз в неделю / при возврате к проекту после паузы (drift check).
- **Перед длинной сессией работы** — быстрая проверка что MCP UP, чтобы агенты не тратили токены на тихие падения.
- **При подозрении на проблему** — "почему агенты ведут себя странно?" → `/doctor` покажет если MCP не отвечают.

## Exit codes (для CI)

- `0` — всё OK (могут быть WARN, но критичных проблем нет)
- `1` — есть FAIL (что-то критичное не работает)
- `2` — есть FAIL + WARN

## Auto-fix (out of scope для v1)

Эта команда **только диагностирует**. Для починки см. предложения в выводе:
- `WARN qex index age` → `/qex-reindex`
- `FAIL Ollama DOWN` → `ollama serve` или `/cold-start`
- `FAIL Settings lint` → исправь `.claude/settings.json` руками
- `FAIL Routing sync` → правь routing-блоки агентов чтобы упоминать только инструменты из ROUTING.md

$ARGUMENTS
