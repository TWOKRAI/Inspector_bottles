Переиндексируй кодовую базу в qex (Qdrant + Ollama).

Вызови: `mcp__qex__index_codebase(force=True)`

Это займёт время. После завершения вызови `mcp__qex__get_indexing_status()` и сообщи результат.

Если сервисы недоступны — сначала запусти:
```bash
docker start qdrant
ollama serve
```
