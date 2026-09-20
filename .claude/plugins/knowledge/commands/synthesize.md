---
description: Запустить sci-synthesizer (Opus) — синтез новой wiki-статьи из нескольких источников или обогащение draft.
---

Синтезируй новую wiki-статью из нескольких источников по теме.

Входные данные: $ARGUMENTS — тема для синтеза или путь к draft-статье (для Сценария B).

## Алгоритм

1. **Проверь аргументы**
   Если $ARGUMENTS пустой:
   > Укажи тему: `/knowledge:synthesize <тема>` или путь к draft: `/knowledge:synthesize knowledge/wiki/{type}/{slug}.md`

2. **Определи сценарий**
   - Путь к существующему draft → Сценарий B (обогащение)
   - Тема без пути → Сценарий A (синтез из 2+ источников)

3. **Сценарий A — Найди все источники**
   По теме `$ARGUMENTS` собери:
   - Существующие wiki-статьи в `knowledge/wiki/`
   - Транскрипты видео в `knowledge/raw/videos/` (читай `meta.md` каждого — теги, название)
   - Файлы в `knowledge/inbox/`

   Если источников < 2:
   > Недостаточно материала для синтеза по теме "{тема}".
   > Есть только: {список найденного}.
   > Добавь больше источников через `/knowledge:transcribe <url>` или `/knowledge:curate <url>`, затем повтори.

4. **Вызови sci-synthesizer**
   Передай агенту:
   - Тема синтеза (или путь к draft)
   - Список всех найденных файлов с путями
   - Инструкция: создать новую wiki-статью в `knowledge/wiki/{type_folder}/` (для A) или обогатить draft (для B)

5. **Агент создаёт/обновляет статью**
   Структура выходной статьи (A):
   ```markdown
   ---
   title: {тема}
   type: concept|tool|comparison|...
   tags: [...]
   sources: [{все источники}]
   date_created: ГГГГ-ММ-ДД
   status: draft
   ---
   ## Резюме
   ## Ключевые концепции
   ## Сравнение подходов / Связи между идеями
   ## Инсайты и выводы
   ## Противоречия и открытые вопросы
   ## Источники
   ```

6. **Append предложение в `workspace/wiki_index_proposals.md`** — для librarian.

7. **Отчёт**
   ```
   ✓ Создана статья: knowledge/wiki/{type_folder}/{slug}.md
   ✓ Использовано источников: N
   ✓ Предложение для index.md → workspace/wiki_index_proposals.md
   → Следующий шаг: /knowledge:library apply или /knowledge:research <вопрос по теме>
   ```

## Примеры

```
/knowledge:synthesize локальные языковые модели
/knowledge:synthesize методы транскрипции аудио
/knowledge:synthesize knowledge/wiki/concepts/karpathy-method.md   # Сценарий B
```
