---
description: Запустить sci-compressor (Haiku) — сжать wiki-статью в wiki-llm (Уровень 2 → Уровень 3).
---

Запусти агента **sci-compressor** (Haiku) для компрессии wiki-статей в Уровень 3.

Входные данные: $ARGUMENTS — путь к статье, `all`, `queue` (по умолчанию `queue`).

## Алгоритм

1. **Определи режим**

   | Аргумент | Что делать |
   |----------|------------|
   | `<путь к wiki-статье>` | Сжать одну статью |
   | `all` | Сжать все статьи в `knowledge/wiki/**` (с подтверждением) |
   | `queue` или пусто | Обработать накопленную очередь `knowledge/wiki-llm/.compress_queue` |

2. **Режим `queue`** (основной для автоматизации)

   - Прочитай `knowledge/wiki-llm/.compress_queue`. Если пусто — сообщи и выйди.
   - Для каждого пути в очереди (по одному, последовательно) — запусти sci-compressor.
   - После всех компрессий — запусти sync-линтер если он есть в проекте:
     ```bash
     [ -f scripts/check_wiki_llm_sync.py ] && python3 scripts/check_wiki_llm_sync.py
     [ -f workspace/scripts/check_wiki_llm_sync.py ] && python3 workspace/scripts/check_wiki_llm_sync.py
     ```
   - Если линтер прошёл (`exit 0`) — очисти очередь: `> knowledge/wiki-llm/.compress_queue`.
   - Если линтер ругается — НЕ очищай, выведи ошибки пользователю.

3. **Режим одной статьи**

   - Проверь что файл существует в `knowledge/wiki/`
   - Вызови sci-compressor:
     ```
     Agent(subagent_type: "sci-compressor",
           prompt: "Сжать knowledge/wiki/{path}. Сохранить в knowledge/wiki-llm/. Реальный sha1 через Bash, не выдумывать.")
     ```
   - После — запусти sync-линтер (см. выше).
   - Если статья была в очереди — убери её строку.

4. **Режим `all`**

   - Посчитай статьи: `find knowledge/wiki -name "*.md" -not -name "index.md" -not -name "README.md" | wc -l`
   - Спроси подтверждение: «Сжать N статей через Haiku? Стоимость ~N×$0.001»
   - Запусти параллельно (батчами по 5-10) sci-compressor для каждой
   - В конце: sync-линтер + очисти очередь

## Типовые вызовы

```
/knowledge:compress                            — обработать очередь (по умолчанию)
/knowledge:compress queue                      — то же самое явно
/knowledge:compress knowledge/wiki/{path}.md   — одна статья
/knowledge:compress all                        — массовая компрессия
```

## Автоматический режим

Если в проекте подключены knowledge-хуки:
- `PostToolUse` на правки `knowledge/wiki/**/*.md` добавляет путь в `.compress_queue`.
- `SessionStart` напоминает о непустой очереди в начале сессии.
- `Stop` запускает линтер при выходе.

Тогда достаточно запускать `/knowledge:compress` (без аргумента) раз в сессию — он подберёт всё что накопилось.

## Проверка результата

После компрессии sync-линтер гарантирует:
- Размер L3 ≈ 80-200 слов (для каталогов до 350)
- `[?DETAILS]` метки на потерях точности
- `source_hash` совпадает с реальным sha1 первых 8 символов L2
- Связи `[[wikilinks]]` сохранены
- Каждой L3 соответствует L2 (нет осиротевших)

## Когда не вызывать

- Wiki < 30 статей — компрессия не имеет смысла (L3 layer окупается на ≥30)
- Статья в процессе активного редактирования — дождись стабилизации
- Wiki-статья пустая или draft (<100 слов) — компрессия не имеет смысла
