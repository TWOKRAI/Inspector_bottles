---
description: Семантический поиск через sci-searcher (Sonnet + qex MCP) по выбранной зоне — knowledge, projects, apps, workspace, custom.
---

Запусти агента **sci-searcher** (Sonnet) для семантического поиска.

Входные данные: $ARGUMENTS — запрос с опциональным префиксом зоны:
- `<запрос>` — поиск по зоне `knowledge` (по умолчанию)
- `knowledge:<запрос>` — явно в knowledge
- `projects:<slug> <запрос>` — в конкретном проекте
- `apps <запрос>` — в `apps/`
- `workspace <запрос>` — в `workspace/plans/` + `workspace/dev/`
- `custom:<path> <запрос>` — в произвольном пути
- `clear <zone>` — удалить индекс зоны
- `status` — показать статус всех индексов

## Алгоритм

1. **Разобрать $ARGUMENTS**:
   - Префикс зоны (если есть)
   - Остаток = поисковый запрос
   - Если первое слово `clear`, `status` — специальный режим

2. **Специальные режимы**:
   - `/knowledge:search status` → `mcp__qex__get_indexing_status()` по всем известным зонам
   - `/knowledge:search clear <zone>` → подтверди с пользователем → `mcp__qex__clear_index(<zone>)`

3. **Обычный поиск**:
   - Определи зону (если не указана — `knowledge`)
   - Проверь статус индекса
   - Если отсутствует или устарел (>10 мин после последних правок) — спроси подтверждение на индексацию
   - Вызови sci-searcher

4. **Вызов**:
   ```
   Agent(subagent_type: "sci-searcher",
         prompt: "Зона: <zone>. Запрос: <query>. Найди топ-10 релевантных фрагментов с путями и строками.")
   ```

## Типовые вызовы

```
/knowledge:search "gap analysis"                       → по knowledge
/knowledge:search knowledge:"экономия токенов"          → явно в knowledge
/knowledge:search projects:specs "роутер IPC"           → в projects/specs/
/knowledge:search apps "whisper transcription"          → в apps/
/knowledge:search workspace "multi level wiki"          → в workspace/

/knowledge:search status                                → статус всех индексов
/knowledge:search clear projects:specs                  → удалить индекс (после подтверждения)
```

## Изоляция зон

Каждая зона имеет **отдельный qex-индекс**. Последствия:
- Удаление `projects/<slug>/` не трогает индекс `knowledge`
- Переиндексация `apps` не затрагивает `projects`
- Индекс живёт в `.qex/` либо в глобальной директории qex с ключом по пути

## Граница с /knowledge:research

| Команда | Модель | Задача |
|---------|--------|--------|
| `/knowledge:search <запрос>` | Sonnet (searcher) | **Retrieval**: найти релевантные фрагменты |
| `/knowledge:research <вопрос>` | Opus (researcher) | **Reasoning**: синтезировать ответ из найденного |

Researcher внутри может вызвать searcher (и скорее всего будет). Быстрый список совпадений → `/knowledge:search`. Осмысленный ответ → `/knowledge:research`.

## Когда не нужен qex

- Wiki < 30 статей — Grep быстрее (searcher окупается с 30+)
- Точное совпадение строки → `Grep` напрямую
- Поиск по имени файла → `Glob`

Когда нужен:
- Семантические запросы («как сэкономить токены», «архитектура роутера»)
- Поиск по похожим темам в большой зоне
- Найти «что-то про X» в незнакомой кодобазе
