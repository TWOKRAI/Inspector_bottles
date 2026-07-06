---
description: Incremental qex index update (Merkle-diff, seconds-minutes). For a full reindex — /mcp-qex:qex-rebuild
---

Инкрементальная индексация: qex сравнивает Merkle-snapshot из `~/.qex/projects/<hash>/snapshot.json`
с текущим состоянием файлов и переиндексирует только изменившиеся. На большом репо это секунды-минуты вместо десятков минут.

Перед индексацией убедись что Ollama работает:

```bash
curl -s --max-time 1 http://localhost:11434/ | grep -q running && echo UP || echo DOWN
```

Если DOWN — предложи пользователю запустить `/core:infra:cold-start`, не индексируй.

Если UP — вызови tool `mcp__qex__index_codebase` с параметрами:
- `path`: абсолютный путь к корню проекта
- **БЕЗ** параметра `force` (или `force: false`)

После завершения покажи итог: число файлов, чанков, время.

Если в репо ничего не изменилось с прошлой индексации — qex вернёт результат за секунды без работы.

Когда нужна **полная** переиндексация (а не инкремент) — пользователь должен вызвать `/mcp-qex:qex-rebuild`:
- сменили embedding-модель;
- snapshot повреждён / индекс отдаёт мусор;
- массивный рефакторинг (>50% файлов).

$ARGUMENTS
