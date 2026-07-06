---
description: Cold start the environment — Ollama serve + venv check (cross-platform)
---

Подготовь окружение проекта после перезагрузки или с нуля.

## Шаги

### 1. Проверить Ollama (нужен для qex embeddings, если qex используется)

```bash
curl -s --max-time 1 http://localhost:11434/ 2>/dev/null | grep -q running && echo "ollama: UP" || echo "ollama: DOWN"
```

Если `DOWN`:
- **macOS:** запусти `ollama serve` через Bash tool с `run_in_background=true`
- **Linux:** аналогично
- **Windows:** `ollama serve` через Bash tool с `run_in_background=true` (Git Bash требуется)
- Подожди 2-3 секунды и проверь снова.

Если `ollama` не установлен — выведи install-команду под платформу:
- macOS: `brew install ollama`
- Linux: `curl -fsSL https://ollama.com/install.sh | sh`
- Windows: `winget install Ollama.Ollama` или https://ollama.com/download

### 2. Проверить наличие embedding-модели

Платформо-зависимая модель (см. `.claude/plugins/mcp-qex/qex-launcher.py`):
- macOS / Linux: `qwen3-embedding:8b` (4096 dim)
- Windows: `qwen3-embedding:4b` (2560 dim)

```bash
ollama list
```

Если нужная модель отсутствует — предложи `ollama pull qwen3-embedding:{8b|4b}`.

### 3. Проверить venv

Поиск:
- macOS / Linux: `.venv/bin/python` или `venv/bin/python`
- Windows: `.venv\Scripts\python.exe` или `venv\Scripts\python.exe`

Если найден — покажи команду активации (но НЕ активируй сам — Claude Code запускает каждый Bash в новом sub-shell):
- macOS / Linux: `source .venv/bin/activate`
- Windows (cmd): `.venv\Scripts\activate.bat`
- Windows (PowerShell): `.venv\Scripts\Activate.ps1`

Если venv нет — предложи `uv sync --group dev`.

### 4. Финальная сводка

| Компонент | Статус |
|-----------|--------|
| Ollama daemon | UP / DOWN / not installed |
| Embedding model | загружена / отсутствует |
| venv | найден / не найден |
| qex MCP | работает (если `mcp__qex__get_indexing_status` доступен) |

Если qex показывает `indexed: false` или индекс старше 7 дней — порекомендуй `/mcp-qex:qex-reindex`.

## Project override

Если в `.claude/modes/_stack.md` есть секция "Cold start" — следуй ей дополнительно (например, проект может требовать запуска БД, кэша Redis и т.п.).

$ARGUMENTS
