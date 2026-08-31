---
description: Транскрибировать одно или несколько видео через MCP-tool `kos_transcribe` (KnowledgeOS). Результат — в obsidian-vault, не в текущем проекте.
---

Запусти транскрипцию для одного или нескольких видео через MCP-сервер `knowledgeos`.

Входные данные: $ARGUMENTS — один или несколько URL/файлов через пробел/перевод строки.

> **Архитектура:** слэш — тонкий клиент. Pipeline крутится в KnowledgeOS-vault'е (отдельный репо) через MCP-tool `kos_transcribe`. Все артефакты падают в `<knowledgeos-vault>/knowledge/inbox/{slug}/`, не в текущий проект. Это by design — единая база знаний на машину.

## Алгоритм

### 1. Парсинг аргументов

- Разбей $ARGUMENTS по whitespace → список URL/файлов.
- Отфильтруй пустые токены.
- Если список пуст — попроси указать ссылку и стоп.
- Если в аргументах есть `--force` — вытащи его, остальное считай URL'ами, при вызове передай `force=true`.

### 2. Вызов MCP

Для каждого URL вызови tool `mcp__knowledgeos__kos_transcribe`:

```
kos_transcribe(url=<URL>, force=<bool>)
```

Дополнительные параметры (`model`, `translate`) **не передавай**, если пользователь не указал явно — сервер сам подберёт дефолты (`large-v3` + claude-cli fallback chain). Полное описание аргументов tool возвращает в своей `description` (MCP сам показывает Claude'у при `list_tools`).

**Если tool недоступен:** проверь через `/mcp` — `knowledgeos` должен быть `connected`. Если сервер не зарегистрирован — сообщи пользователю и стоп. Никакого локального fallback не делай.

### 3. Отчёт

Собери ответы всех вызовов:
- `status="ok"` → созданная папка из `folder`.
- `status="skipped"` → видео уже было (дедуп), показать существующую папку.
- `status="error"` → показать `error` и последние строки `log_tail`.

Покажи пользователю компактный список: создано / пропущено / упало.

### 4. Следующий шаг

Если есть `ok` или `skipped` — предложи `/knowledge:curate` для переноса транскриптов из `knowledge/inbox/` в wiki.

## Примеры использования

```
/knowledge:transcribe https://youtu.be/abc123
/knowledge:transcribe https://youtu.be/abc https://youtu.be/def
/knowledge:transcribe --force https://youtu.be/abc123
/knowledge:transcribe ./local/audio.mp3
```

## Структура вывода

После успеха в `<knowledgeos-vault>/knowledge/inbox/{YYYY-MM-DD_slug}/`:
- `meta.md` — метаданные (название, канал, длительность, язык)
- `transcript.<lang>.md` — оригинал
- `transcript.ru.md` — перевод (если язык != ru)
- `timestamps.vtt` + `timestamps.md` — таймкоды
