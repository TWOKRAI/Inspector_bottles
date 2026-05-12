---
description: Холодный старт окружения — Ollama serve + проверка venv (кросс-платформа)
---

Запусти окружение Inspector_bottles после перезагрузки или с нуля.

## Шаги

### 1. Проверить Ollama (нужен для qex embeddings)

```bash
curl -s --max-time 1 http://localhost:11434/ 2>/dev/null | grep -q running && echo "ollama: UP" || echo "ollama: DOWN"
```

Если `DOWN`:
- **macOS:** запусти `ollama serve` через Bash tool с `run_in_background=true`
- **Windows:** запусти `ollama serve` через Bash tool с `run_in_background=true` (Git Bash требуется)
- Подожди 2-3 секунды и проверь снова через curl

Если `ollama` не установлен — выведи install-команду под платформу:
- macOS: `brew install ollama`
- Linux: `curl -fsSL https://ollama.com/install.sh | sh`
- Windows: https://ollama.com/download или `winget install Ollama.Ollama`

### 2. Проверить наличие embedding-модели

Платформо-зависимая модель:
- macOS / Linux: `qwen3-embedding:8b` (4096 dim)
- Windows: `qwen3-embedding:4b` (2560 dim)

```bash
ollama list
```

Если нужная модель отсутствует — предложи `ollama pull qwen3-embedding:{8b|4b}`.

### 3. Проверить venv (опционально, если используется)

Поиск:
- macOS / Linux: `.venv/bin/python` или `venv/bin/python`
- Windows: `.venv\Scripts\python.exe` или `venv\Scripts\python.exe`

Если найден — покажи команду активации под платформу пользователю (но НЕ активируй сам — Claude Code запускает каждый Bash в новом sub-shell, активация не сохраняется):
- macOS / Linux: `source .venv/bin/activate`
- Windows (cmd): `.venv\Scripts\activate.bat`
- Windows (PowerShell): `.venv\Scripts\Activate.ps1`

### 4. Финальная сводка

Покажи статус таблицей:

| Компонент | Статус |
|-----------|--------|
| Ollama daemon | UP / DOWN |
| Модель `qwen3-embedding:{N}b` | загружена / отсутствует |
| venv | найден по пути / не найден |
| qex MCP | работает (вызови `mcp__qex__get_indexing_status`) |

Если qex показывает `indexed: false` или индекс старше 7 дней — порекомендуй `/qex-reindex`.

$ARGUMENTS
