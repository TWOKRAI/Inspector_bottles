# Platform-specific конфиги

Заготовки для machine-specific overrides — отдельно для **macOS** и **Windows**.

> **MCP-сервера НЕ нужно копировать руками под платформу** — кросс-платформенность решает [`../mcp/qex-launcher.py`](../mcp/qex-launcher.py) (auto-detect ОС → правильная модель Ollama). Для создания нового проекта используй `claude-kit-project new`; `.mcp.json` генерируется автоматически из `manifest.yaml`.

---

## Содержимое

| Файл | Платформа | Назначение |
|------|-----------|------------|
| [`settings.local.macos.json`](settings.local.macos.json) | macOS | Заготовка `.claude/settings.local.json` для macOS |
| [`settings.local.windows.json`](settings.local.windows.json) | Windows | Заготовка `.claude/settings.local.json` для Windows |
| [`README.md`](README.md) | — | Этот файл |

`settings.local.json` — gitignored, поэтому на каждой машине должен создаваться отдельно. Заготовки в этой папке — стартовая точка.

## Что внутри заготовок

Permissions для всех **четырёх стандартных MCP-серверов** (qex, sentrux, context7, serena) — разделены на три зоны:

| Зона | Что туда попало | Принцип |
|---|---|---|
| **allow** | read-only / search ops: `mcp__qex__search_code`, `mcp__sentrux__scan/health/dsm`, `mcp__context7__*`, `mcp__serena__find_*`, `read_memory`, `list_memories` | Чтение и анализ — без вопросов, иначе агент будет дёргать пользователя на каждый поиск |
| **ask** | мутации: `mcp__qex__clear_index`, `mcp__serena__rename_symbol/replace_*/insert_*/safe_delete_symbol/delete_memory`, `write/edit/rename_memory`, `onboarding` | Меняют код или накопленный контекст — пользователь должен подтвердить |
| **deny** | (пусто) | По умолчанию deny не используется — все мутации в ask, пользователь решает в моменте. Добавь сюда что-то, только если есть конкретная причина блокировать наглухо. |

Принцип такой же как в корневом `settings.json` для Bash: «функциональность не теряем, slop-векторы перекрываем».

Если ты добавляешь свой MCP-сервер (`graphify`, `qt-mcp` и т.д.) — расширь allow/ask по тому же принципу.

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

## `statusLine` — per-OS поведение

`statusLine.command` в `settings.json` определяется во время `claude-kit-project new` по OS, на которой запускается команда:

| OS | statusLine.command | Что показывает |
|----|--------------------|----------------|
| macOS / Linux | `printf 'branch: %s \| ollama: %s' "$(git branch --show-current)" "$(curl ... && echo UP \|\| echo DOWN)"` | `branch: main \| ollama: UP` |
| Windows | `git branch --show-current` | `main` |

**Почему так:** bash-команда с `printf` + `"$(...)"` + `curl` + `\|\|` — POSIX-конструкции. На Windows их не понимает ни `cmd.exe`, ни PowerShell, statusLine падает с warning'ом и пользователь видит пустую строку. Windows-вариант — чистый git-вызов, который работает в любой оболочке.

### Token-aware statusline (опц., upgrade)

Дефолтная строка показывает только ветку/ollama. Для **токен-экономии** полезнее видеть
заполнение контекст-окна и burn-rate — это операционализирует `CLAUDE.md` → Smart-zone
discipline («split at ~80k», prefer `/clear`): видишь %, режешь сессию вовремя, а не задним
числом. CC передаёт statusLine-команде на stdin JSON с полями context-usage / cost / git /
session, так что строку можно собрать самому или взять готовый community-инструмент:

| Инструмент | Команда для `statusLine.command` | Что добавляет |
|------------|----------------------------------|---------------|
| ccusage | `npx -y ccusage statusline` | context % + стоимость + burn-rate сессии |
| ccstatusline | `npx -y ccstatusline@latest` | context-window fill (dedup-corrected токены), настраиваемый |

**Third-party, не official** (в офиц. доках CC не упомянуты) и требуют Node/`npx` —
поэтому это **opt-in upgrade**, не дефолт сида (не навязываем сетевой `npx`-вызов каждому
новому проекту). Включить: заменить `statusLine.command` в `settings.json` (или per-machine
в `settings.local.json`) на команду из таблицы. Возврат — вернуть git/printf-вариант выше.

**Двух-машинный workflow:** `settings.json` зафиксирован под OS на момент создания (он же в git). Если проект создан на Windows и синкается на macOS — bash-варианта не будет. Решения:

1. Скопировать `settings.json` руками после первого `git pull` на новой ОС.
2. Использовать `settings.local.json` для платформенного override — он gitignored, у каждой машины свой. См. ниже.

---

## Двух-машинный workflow

Сценарий: днём работаю на Windows, вечером — на macOS.

| Что | Где | Синхронизация |
|-----|-----|---------------|
| `.claude/settings.json` | в git | автоматом через `git pull` |
| `.claude/settings.local.json` | gitignored | заготовка из `platforms/settings.local.{os}.json` |
| `.mcp.json` | в git | автоматом через `git pull` |
| `~/.claude.json` (Context7) | user-level | OAuth один раз на машину |
| `~/.qex/` (qex-индекс) | у каждой машины свой | `/mcp-qex:qex-reindex` после `git pull` |
| `~/.ollama/` (Ollama-модели) | у каждой машины свои | `ollama pull qwen3-embedding:{8b\|4b}` |

---

## Phase 3 — MCP zones (на будущее)

Сейчас один `qex` сервер индексирует весь проект. В будущем планируется раздробить на зоны:

- `qex-projects` — `projects/`
- `qex-knowledge` — `knowledge/wiki/`
- `qex-areas-work` — `areas/work/`
- `qex-areas-study` — `areas/study/`

Каждая зона = отдельный блок `mcpServers.*` с собственным `WORKSPACE_PATH`.

Это будет разворачиваться через компоненты в `manifest.yaml` (и автоматически работать на обеих платформах через `qex-launcher.py`).
