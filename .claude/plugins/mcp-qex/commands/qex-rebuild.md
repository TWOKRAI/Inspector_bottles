---
description: Full qex reindex from scratch (force=true, 30-60 min on a large repo). Use only when changing the embedding model or when the index is corrupted
---

Полная переиндексация — **долго** (десятки минут на большом репо). По умолчанию пользуйся `/mcp-qex:qex-reindex` (инкрементально).

Перед переиндексацией спроси подтверждение у пользователя — это дорогая операция. Если он согласен:

1. Проверить Ollama:

```bash
curl -s --max-time 1 http://localhost:11434/ | grep -q running && echo UP || echo DOWN
```

Если DOWN — запустить `/core:infra:cold-start`, не индексировать.

2. Вызвать tool `mcp__qex__index_codebase`:
   - `path`: абсолютный путь к корню проекта
   - `force`: **true**

После завершения покажи итог: число файлов, чанков, время.

$ARGUMENTS
