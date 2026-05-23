# Перенос MCP-инфраструктуры в новый проект

Этот документ описывает пошаговый перенос MCP-инфраструктуры (qex + sentrux + Context7)
из текущего проекта в новый.

---

## Что копировать

**Копировать целиком:**

```
.claude/
```

Папка содержит всё необходимое: агентов, команды, MCP-конфиги, bootstrap, шаблоны.
Новый проект получает полноценную инфраструктуру одним действием.

---

## Что НЕ копировать

Следующие файлы либо генерируются автоматически, либо требуют адаптации под проект:

| Файл | Причина |
|------|---------|
| `.mcp.json` | Генерируется claude-kit из `manifest.yaml` (`claude-kit new` / `claude-kit add`) |
| `.sentrux/rules.toml` | Адаптировать из шаблона `sentrux/rules.template.toml` |
| `.sentrux/baseline.json` | Генерируется `sentrux` при первом сканировании |
| `.ignore` | Адаптировать из шаблона `qex/templates/ignore.template` |
| `.qex-reindex.log` | Артефакт индексации, генерируется автоматически |

---

## Чеклист переноса

1. **Скопировать `.claude/`** в корень нового проекта:

   ```bash
   # macOS / Linux
   cp -r /path/to/source-project/.claude /path/to/new-project/

   # Windows (PowerShell)
   Copy-Item -Recurse C:\path\to\source-project\.claude C:\path\to\new-project\
   ```

2. **Создать проект через `claude-kit new`** — сгенерирует `.mcp.json` из `mcp_servers:` блоков
   выбранных компонентов в `manifest.yaml`, а также инициализирует `.sentrux/rules.toml`.
   Чтобы добавить отдельный компонент в существующий проект — `claude-kit add <component>`.

3. **Адаптировать `.ignore`** под whitelist своего проекта (какие пути qex должен
   индексировать, а какие игнорировать):

   ```bash
   cp .claude/mcp/qex/templates/ignore.template .ignore
   # затем отредактировать .ignore
   ```

4. **Адаптировать `.sentrux/rules.toml`** — задать слои архитектуры и границы
   импортов своего проекта. Шаблон уже скопирован bootstrap'ом:

   ```bash
   # отредактировать .sentrux/rules.toml:
   # - адаптировать пороги [constraints]
   # - раскомментировать и заполнить [[layers]] своими путями
   # - раскомментировать и заполнить [[boundaries]] своими правилами
   ```

   Шаблон с комментариями: `sentrux/rules.template.toml`

5. **Запустить `ollama serve`** (если ещё не запущен в фоне):

   ```bash
   ollama serve
   ```

6. **Перезапустить Claude Code** — чтобы MCP-серверы подхватили новый `.mcp.json`.

7. **Проиндексировать кодовую базу** — через чат или MCP напрямую:

   ```
   /qex-reindex
   ```

   или через MCP-инструмент:

   ```python
   mcp__qex__index_codebase(path=".", force=True)
   ```

8. **Проверить статус MCP** — qex и sentrux должны быть зелёные:

   ```
   /mcp
   ```

---

## Опциональные шаги

**Git hooks** (автоматизация проверок и переиндексации):

- `pre-push` — sentrux health-gate перед push, блокирует при регрессии метрик
- `post-commit` — автоматическая переиндексация qex после каждого коммита

Шаблоны хуков: `.claude/mcp/qex/templates/post-commit.hook.sh`

**Context7** (актуальная документация библиотек):

```bash
# User-level, один раз на машину
npx -y ctx7 setup --claude
```

Context7 настраивается глобально (`~/.claude.json`) и переносить его не нужно —
только выполнить setup на новой машине.

---

## Платформенные различия

| Компонент | macOS | Windows |
|-----------|-------|---------|
| Embedding-модель | `qwen3-embedding:8b` (4096-dim) | `qwen3-embedding:4b` (2560-dim) |
| qex бинарник | `~/.local/bin/qex` | `~/.cargo/bin/qex.exe` |
| sentrux | `brew install sentrux/tap/sentrux` | скачать с GitHub Releases |

Логика выбора модели автоматически определяется в `qex-launcher.py` через `platform.system()`.
Переопределить можно через переменную окружения `QEX_BIN`.

---

## Ссылки на детальные гайды

| Тема | Файл |
|------|------|
| qex quick-start | `qex/README.md` |
| qex полный гайд установки | `qex/SETUP_GUIDE.md` |
| sentrux: метрики, команды, сценарии | `sentrux/README.md` |
| bootstrap: что делает каждый шаг | `README.md` (этот каталог) |
