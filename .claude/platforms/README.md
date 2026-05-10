# Platform-specific конфиги

Заготовки для machine-specific overrides — отдельно для **macOS** и **Windows**.

> **MCP-сервера НЕ нужно копировать руками под платформу** — кросс-платформенность решает [`../mcp/qex-launcher.py`](../mcp/qex-launcher.py) (auto-detect ОС → правильная модель Ollama). Для bootstrap нового проекта:
>
> ```bash
> python3 .claude/mcp/bootstrap.py    # macOS / Linux
> python .claude/mcp/bootstrap.py     # Windows
> ```

---

## Содержимое

| Файл | Платформа | Назначение |
|------|-----------|------------|
| [`settings.local.macos.json`](settings.local.macos.json) | macOS | Заготовка `.claude/settings.local.json` для macOS |
| [`settings.local.windows.json`](settings.local.windows.json) | Windows | Заготовка `.claude/settings.local.json` для Windows |
| [`README.md`](README.md) | — | Этот файл |

`settings.local.json` — gitignored, поэтому на каждой машине должен создаваться отдельно. Заготовки в этой папке — стартовая точка.

---

## Как использовать

### На macOS-машине

```bash
cp .claude/platforms/settings.local.macos.json .claude/settings.local.json
```

### На Windows-машине

```powershell
copy .claude\platforms\settings.local.windows.json .claude\settings.local.json
```

После этого `settings.local.json` будет содержать allowlist для qex MCP-тулов и не попадёт в git.

---

## Двух-машинный workflow

Сценарий: днём работаю на Windows, вечером — на macOS.

| Что | Где | Синхронизация |
|-----|-----|---------------|
| `.claude/settings.json` | в git | автоматом через `git pull` |
| `.claude/settings.local.json` | gitignored | заготовка из `platforms/settings.local.{os}.json` |
| `.mcp.json` | в git | автоматом через `git pull` |
| `~/.claude.json` (Context7) | user-level | OAuth один раз на машину |
| `~/.qex/` (qex-индекс) | у каждой машины свой | `/qex-reindex` после `git pull` |
| `~/.ollama/` (Ollama-модели) | у каждой машины свои | `ollama pull qwen3-embedding:{8b\|4b}` |

---

## Phase 3 — MCP zones (на будущее)

Сейчас один `qex` сервер индексирует весь проект. В будущем планируется раздробить на зоны:

- `qex-projects` — `projects/`
- `qex-knowledge` — `knowledge/wiki/`
- `qex-areas-work` — `areas/work/`
- `qex-areas-study` — `areas/study/`

Каждая зона = отдельный блок `mcpServers.*` с собственным `WORKSPACE_PATH`.

Это будет разворачиваться в `mcp.template.json` (и автоматически работать на обеих платформах через `qex-launcher.py`).
