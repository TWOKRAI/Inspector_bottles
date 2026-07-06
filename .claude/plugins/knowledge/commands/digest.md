---
description: Запустить sci-digest (Haiku) — еженедельный отчёт: что добавлено в wiki, выросшие статьи, открытые вопросы.
---

Запусти агента **sci-digest** (Haiku) для генерации отчёта о состоянии базы знаний.

Входные данные: $ARGUMENTS — период (опционально, по умолчанию `1 week ago`).

## Алгоритм

1. **Определи период**
   - Без аргументов → `1 week ago`
   - `/knowledge:digest 2 weeks` → `2 weeks ago`
   - `/knowledge:digest month` → `1 month ago`

2. **Вызови sci-digest**
   ```
   Agent(subagent_type: "sci-digest",
         prompt: "Период: <период>. Собери git-активность по knowledge/, новые статьи, выросшие статьи, открытые вопросы. Сохрани в workspace/digests/YYYY-MM-DD.md")
   ```

3. **Покажи путь к отчёту**

## Типовые вызовы

```
/knowledge:digest                — за последнюю неделю
/knowledge:digest 2 weeks        — за 2 недели
/knowledge:digest month          — за месяц
```

## Cron-запуск

Для автоматического еженедельного дайджеста через skill `schedule`:
```
/schedule weekly 0 9 * * 1 /knowledge:digest
```

Каждый понедельник в 9:00 создаётся отчёт в `workspace/digests/`.

## Когда полезно

- Понедельник утром — оценить прогресс за неделю
- Перед большим `/knowledge:synthesize` — посмотреть какие draft-статьи накопились
- При подготовке к `/knowledge:library` — увидеть сколько открытых вопросов
