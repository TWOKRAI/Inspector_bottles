---
description: Запустить sci-librarian (Sonnet) — уборка wiki: дедупликация, битые ссылки, обновление index, валидация promos.
---

Запусти агента **sci-librarian** (Sonnet) для поддержания порядка в `knowledge/wiki/`.

Входные данные: $ARGUMENTS — режим работы (опционально).

## Режимы

| Режим | Что делает |
|-------|------------|
| (без аргументов) | Полный проход: проверки + обработка proposals + обновление index |
| `check` | Только проверки (битые ссылки, дубликаты, осиротевшие) — без правок |
| `apply` | Применить предложения из `workspace/wiki_index_proposals.md` к index.md |
| `validate <path>` | Валидировать конкретную статью на готовность к `status: reviewed` |

## Алгоритм

1. **Определи режим** из $ARGUMENTS (по умолчанию — полный проход)

2. **Вызови librarian**
   ```
   Agent(subagent_type: "sci-librarian", prompt: "Режим: <режим>. <контекст>")
   ```

3. **Обработай результат**
   - Если есть проблемы (битые ссылки, дубликаты) → покажи пользователю список, спроси как действовать
   - Если всё чисто → отчёт сохрани в `workspace/library_reports/YYYY-MM-DD.md`

## Типовые вызовы

```
/knowledge:library              — еженедельная уборка
/knowledge:library check        — быстрая проверка здоровья wiki
/knowledge:library apply        — после curator/synthesizer, чтобы внести их предложения
/knowledge:library validate knowledge/wiki/concepts/auto-memory.md
```

## Рекомендованный триггер

- **Cron еженедельно**: `/schedule weekly 0 9 * * 1 /knowledge:library`
- **После каждого /knowledge:curate или /knowledge:synthesize** (автоматически в pipeline Science)

## Когда НЕ вызывать

- Wiki ≤ 10 статей — Grep и глаз быстрее (librarian включать с 15+)
- Сразу после создания одной статьи — лучше накопить батч
