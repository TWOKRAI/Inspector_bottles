---
description: qex index status (file count, chunks, index date, languages)
---

Вызови tool `mcp__qex__get_indexing_status` с параметром `path` = абсолютный путь к корню текущего проекта.

Покажи результат пользователю в виде таблицы:
- Indexed: ✅/❌
- Files / Chunks
- Languages
- Last indexed (как давно)
- Dense search available

Если `last_indexed` старше 7 дней или были недавние коммиты — порекомендуй `/mcp-qex:qex-reindex` (инкрементальное обновление через Merkle-diff, секунды-минуты).
Полная переиндексация (`/mcp-qex:qex-rebuild`) нужна только при смене embedding-модели или повреждении индекса.
