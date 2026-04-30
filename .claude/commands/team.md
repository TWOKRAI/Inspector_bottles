---
description: Показать текущий состав команды разработки — агенты, модели, роли
---

Покажи полный состав обеих команд KnowledgeOS.

1. Прочитай агентов Dev Company из `.claude/agents/company/`
2. Прочитай агентов University из `.claude/agents/university/`
3. Для каждого агента извлеки: name, model, description из frontmatter
4. Выведи две таблицы:

```
## IT-Компания по разработке (Dev Company)
Агенты: .claude/agents/company/

| # | Роль | Агент | Модель | Когда вызывать |
|---|------|-------|--------|----------------|
| 1 | Manager | manager | Sonnet | Декомпозиция, ТЗ (Task X.Y) |
| 2 | TeamLead | teamlead | Opus | Senior+ implementation + express review + эскалация |
| 3 | Developer | developer | Sonnet | Middle/Middle+ реализация |
| 4 | Debugger | debugger | Sonnet | Диагностика FAIL, регрессий, root cause |
| 5 | Tester | tester | Sonnet | pytest по acceptance criteria |
| 6 | Reviewer | reviewer | Opus | Full review (10+ файлов), только читает, макс 2 итерации |
| 7 | Docs Writer | docs-writer | Haiku | Простая документация (docstrings, README, STATUS) |
| 8 | Tech Writer | tech-writer | Sonnet | Сложная документация (ADR, ARCHITECTURE, migrations) |
| 9 | Spec Writer | spec-writer | Sonnet | Живое ТЗ docs/direction/ |

Workflow: /plan → /implement → /test → [FAIL → /debug] → /review → /docs → /ship
Полный автомат: /pipeline | Нанять нового: /hire

---

## Исследовательский Университет (Science Company)
Агенты: .claude/agents/university/

| # | Роль | Агент | Модель | Когда вызывать |
|---|------|-------|--------|----------------|
| 1 | Transcriber | sci-transcriber | Sonnet | URL/файл → raw/videos/ |
| 2 | Curator | sci-curator | Sonnet | 1 источник → draft wiki-статья |
| 3 | Synthesizer | sci-synthesizer | Opus | 2+ источников → draft→reviewed |
| 4 | Researcher | sci-researcher | Opus | Глубокий Q&A по wiki |
| 5 | Librarian | sci-librarian | Sonnet | Единственный owner index.md, дедупликация, битые ссылки |
| 6 | Translator | sci-translator | Sonnet/Haiku | EN→RU (роутинг по длине + содержимому) |
| 7 | Compressor | sci-compressor | Haiku | Phase 3: wiki → wiki-llm (авто) |
| 8 | Digest | sci-digest | Haiku | Phase 3: еженедельный дайджест по cron |
| 9 | Searcher | sci-searcher | Sonnet | Phase 3: семантический поиск через qex MCP (per-zone индексы) |

Workflow: /transcribe → /curate → /synthesize → /research → /library
Перевод: /translate | Дайджест: /digest | Поиск: /search
```

## Правила вывода

- Если агент помечен `Phase 3` — укажи рядом статус готовности (`[создан]` / `[файл есть, не активирован]`)
- В конце покажи общую сводку: `Dev: N агентов | Science: M агентов | Всего: N+M`
- Если какого-то агента нет в папке — пометь `[отсутствует]` красным
