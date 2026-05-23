# Сессия 2026-05-23 — Апгрейд `.claude/` через devseed + аудит стека

**Ветка:** `chore/claude-seed-upgrade`
**Коммит:** `887c0a0 chore(claude): upgrade .claude/ to seed template 0.2.0`
**Инструмент:** `devseed` (claude-kit 0.4.0, bundled template 0.2.0)
**Backup для отката:** `%TEMP%\claude_backup_Inspector_bottles_20260523_161049.tar.gz`

---

## 1. Что сделано

### 1.1 Апгрейд `.claude/`

```bash
devseed upgrade --reseed-answers --apply  # 53 modified, 80 added
```

Зафиксирован `.claude/.seed-answers.yml` — будущие `upgrade` будут точнее, без эвристики.

### 1.2 Добавлены компоненты

```bash
# 7 skills
devseed add skill-caveman skill-grill-me skill-prototype skill-zoom-out \
            skill-brainstorm skill-verify-done skill-module-contract

# 4 opt-in MCP
devseed add graphify ast-grep codegraph github

# Компенсация бага №3
devseed add hooks-quality
```

### 1.3 Ручные правки

- Восстановлены 3 user files из `git checkout HEAD --` (баг №1, ниже):
  `commands/analysis/channel-map.md`, `commands/analysis/message-contracts.md`,
  `commands/infra/validate.md`.
- `.pre-commit-config.yaml`: `bandit exclude` дополнен `\.claude/` —
  иначе bandit ругается на seed-шаблонные скрипты (баг №10).
- `.mcp.json` собран вручную из `.claude/mcp/*/templates/mcp-config.json.snippet`
  (НЕ закоммичен — в `.gitignore`). Стало 6 MCP: `sentrux`, `serena`, `qex`,
  `qt-mcp`, `graphify`, `ast-grep`. `codegraph` + `github` пропущены —
  требуют ручного init (codegraph index, GH PAT/OAuth).
- 6 seed-скриптов пере-форматированы `ruff format` через pre-commit (баг №5).
- Удалены orphan-файлы старой структуры hooks/.

### 1.4 Оставлено ВРУЧНУЮ (rm denied)

```bash
rm -rf .backup_tmp        # моя временная распаковка backup
rm -rf .mypy_cache        # реликт, проект перешёл на pyright
```

---

## 2. Текущий стек проекта

| Категория | Tool | Версия | Где живёт |
|-----------|------|--------|-----------|
| Package manager | **uv** | 0.9.4 | глобально на PATH ✓ |
| Python | **CPython** | 3.12.12 | через uv ✓ |
| Type checker | **pyright** | 1.1.409 | dev group ✓ |
| Linter / formatter | **ruff** | 0.15.14 | **только в pre-commit venv** ⚠ |
| Security | **bandit** | 1.9.4 | dev group ✓ |
| Pre-commit | **pre-commit** | 4.x | dev group ✓ |
| Build/Run | **make** | — | **нет в Git Bash** ⚠ (только PowerShell/CMD) |

### 2.1 Конфигурация (`pyproject.toml`)

- `[tool.ruff]`: `py312`, `line-length=120`, `select=["E","F"]` — минимальный набор
- `[tool.pyright]`: basic mode, gradual; шумные правила отключены для PySide6/динамики
- `[tool.bandit]`: exclude `tests`, `multiprocess_prototype_backup`; skip B101
- `[dependency-groups].dev`: pytest, pyright, bandit, pre-commit, qt-mcp
- **mypy НЕ используется** (перешли на pyright); в `Makefile.clean` мёртвая ссылка на `.mypy_cache`

### 2.2 Конфигурация (`.pre-commit-config.yaml`)

- `pre-commit-hooks v5.0.0` (whitespace, EOF, yaml, toml, merge-conflict, large-files, debug-statements)
- `ruff v0.15.12` + `ruff-format` (commit stage, autofix)
- `pyright v1.1.408` (pre-push, ADVISORY — `|| true`)
- `bandit 1.9.0` (commit stage; exclude `tests`, `multiprocess_prototype_backup`, `.claude/`)
- Global exclude: `^multiprocess_prototype_backup/`

### 2.3 Несоответствия (минор)

1. **`ruff` НЕТ в `[dependency-groups].dev`** — есть только в pre-commit's venv.
   Поэтому `make lint` упадёт без активной venv. Фикс: добавить `"ruff>=0.15"` в dev.
2. **Makefile использует bare `ruff`/`pyright`/`bandit`** — без `uv run` префикса.
   Работает только при активированной venv. Лучше: `RUFF := uv run ruff`.
3. **`make` нет в Git Bash** — если используешь bash для команд, либо `winget install GnuWin32.Make`,
   либо запускать `make` в PowerShell/CMD/CMD-from-VSCode.
4. **`Makefile.clean` чистит `.mypy_cache`** — мёртвая ссылка (mypy не используется).
   Безвредно, но шум.

---

## 3. Баги seed `claude-kit 0.4.0` (для коммита в claude_seed)

Найдены при попытке "minimum manual, max seed automation" сценария.

| # | Severity | Баг | Воспроизведение | Где чинить |
|---|----------|-----|-----------------|------------|
| 1 | **HIGH** | `upgrade --apply` УДАЛЯЕТ user files, помеченные `U (kept)` в dry-run | `channel-map.md`, `message-contracts.md`, `validate.md` исчезли при `upgrade` | `core/composition/seed_copy.py` — `_classify_path()` корректно метит, но удаление по `_remove_orphans` похоже не учитывает классификацию |
| 2 | **HIGH** | `devseed add <comp>` тоже СБРАСЫВАЕТ user files | После `add hooks-quality` user files повторно пропали | `add` должен быть строго аддитивным — copy_files без sync |
| 3 | **HIGH** | `hooks-quality` помечен `default:true` в manifest, но `reseed-answers` heuristic его пропустил, а `settings.json` после `upgrade` СОДЕРЖИТ `.claude/hooks/quality/*.sh` ссылки → ссылки на несуществующую папку | `upgrade` → `ls .claude/hooks/` показывает только `_lib core python` | `reseed-answers` должен включать ВСЕ `default:true` core-компоненты; либо settings.json рендерить с учётом фактического selection |
| 4 | MEDIUM | `upgrade` подсказывает `--prune-orphans`, но флага в CLI НЕТ | `devseed upgrade --help` его не содержит | Либо добавить флаг (logical), либо убрать подсказку. Лучше — добавить ещё `devseed prune-orphans` |
| 5 | MEDIUM | Seed-скрипты (`templates/scripts/*.py`, `templates/validate_commit/validate_commit.py`, `mcp/qex-launcher.py`, `scripts/lint_*.py`) НЕ отформатированы под `ruff format` | Pre-commit реформатит 6 файлов при первом коммите проекта | Запускать `ruff format` в CI seed-репо до релиза; добавить ruff-format в pre-push hook самого claude_seed |
| 6 | **HIGH** | `add <mcp-server>` копирует только файлы, НЕ инжектит snippet в `.mcp.json` | После `add graphify/ast-grep/codegraph/github` `.mcp.json` без них | `commands/add.py` — после copy MCP-папки прочитать `templates/mcp-config.json.snippet`, парсить JSON (strip `// comments`), merge в `mcpServers` `.mcp.json` с дедупликацией |
| 7 | MEDIUM | `doctor` не проверяет MCP servers на реальную запускаемость | serena в `.mcp.json`, но в сессии CC её нет, doctor молчит | Добавить секцию "MCP servers" в doctor: `serena --version`, ping qex binary, `curl localhost:11434/api/tags` для qex, `which uvx/npx` для opt-in |
| 8 | LOW | `.mcp.json` `_comment` ВРЁТ: "Re-generated on `claude-kit add/remove`. Hand edits to mcpServers are preserved" | См. баг 6 — `add` не пишет в `.mcp.json` вообще | Либо реализовать, либо переписать комментарий честно: "Manual merge required from `.claude/mcp/<id>/templates/...`" |
| 9 | LOW | serena snippet (`uvx --from serena-agent serena-mcp-server`) ОТЛИЧАЕТСЯ от того, что бы `add serena` теоретически писал (текущий `.mcp.json` имеет `serena start-mcp-server`) | snippet vs живой config расходятся | Привести к одному варианту. Документировать почему именно так в `mcp/serena/README.md` |
| 10 | MEDIUM | `templates/pre-commit-config.template.yaml` в bandit-exclude НЕ содержит `\.claude/` | Первый commit на проекте → bandit ругается на `.claude/templates/scripts/*.py` | В `templates/pre-commit-config.template.yaml`: `exclude: ^(tests/\|.claude/)` для bandit/ruff. То же для `.gitignore.template` (`.claude/__pycache__` etc.) |
| 11 | LOW | LF/CRLF warnings на Windows для `*.sh`, `*.snippet`, шаблонов | git ругается на 13 файлов при `git add` | В `templates/gitattributes.template`: `*.sh text eol=lf`, `*.snippet text eol=lf`, `*.template text eol=lf` |

### 3.1 Топ-3 по приоритету

1. **#1 + #2** — data loss user files. Без фикса юзеры теряют кастомизации.
   Это срыв главного обещания seed «per-project preserve».
2. **#6** — без авто-merge `.mcp.json` команда `add <mcp>` работает лишь
   наполовину. Сейчас юзер должен сам читать snippets и собирать JSON руками
   (что я и сделал).
3. **#3** — `hooks-quality` mismatch приводит к сломанным хукам сразу после
   upgrade. Зеркальная проблема: heuristic vs render.

### 3.2 Рекомендации по seed (для удобства использования в других проектах)

1. **Добавить `devseed sync-config`** — отдельная команда, которая:
   - Перегенерирует `.mcp.json` из snippets всех установленных MCP
   - Перегенерирует `settings.json` hooks под фактически установленные `hooks-*`
   - Запускает `ruff format` на seed-скриптах в `.claude/`
2. **`devseed prune-orphans` отдельной командой** (без `--apply` на upgrade)
   — безопасно, идемпотентно, можно вызывать когда захочется.
3. **`devseed doctor --check-mcp`** — за каждым `mcpServers.<id>` проверять
   что бинарь/команда есть в PATH или резолвится через `uvx`/`npx`.
4. **`.claude/.seed-answers.yml` schema v2** — добавить `custom_mcp: [...]`
   для регистрации юзерских MCP (типа `pytest-runner`), чтобы они НЕ попадали в
   orphans при upgrade.
5. **`devseed show diff <before> <after>`** — перед upgrade покажи changelog
   между текущей версией template и новой, со списком breaking changes.
6. **Раздел "Cookbook" в `docs/`** — рецепты "как добавить кастомный MCP",
   "как мигрировать с ручного `.claude/`", "как делать sync-back правильно".
7. **`devseed upgrade --backup-dir <path>`** — сейчас backup всегда в `$TMPDIR`,
   что на Windows = `%TEMP%` и периодически чистится. Дать опцию хранить
   backup в проекте (например `.claude/_backups/`).
8. **CI seed-репо**: добавить `pre-push hook` + GH Actions матрицу (Win/Mac/Linux)
   которая делает `claude-kit new <fixture>` → `make gate` на бутстрапнутом
   проекте. Поймает регрессии #1/#2/#3/#5/#10 автоматически.

---

## 4. MCP статус после перезапуска CC

`SessionStart:resume` hook отчитался:
```
MCP: qex=UP ollama=DOWN sentrux=UP context7=cfg ast-grep=cfg serena=cfg graphify=cfg qt-mcp=cfg
```

Серена сейчас активна — `mcp__serena__*` 21 tool. Бинарь `Serena 1.3.0` в
`C:\Users\INNOTECH\.local\bin\serena.exe`, запуск проверен вручную:
активирует проект `Inspector_bottles` за ~2 сек, 52 tool exposed по LSP.

Ollama надо запустить когда понадобится qex semantic search: `ollama serve`.

---

## 5. Чеклист «следующие шаги»

- [ ] `rm -rf .backup_tmp .mypy_cache` (ручной, deny на авто)
- [ ] Добавить `"ruff>=0.15"` в `[dependency-groups].dev` в `pyproject.toml`
- [ ] (опц.) Префиксовать `Makefile` через `uv run` — `RUFF := uv run ruff` и т.д.
- [ ] (опц.) Удалить `.mypy_cache` из `Makefile.clean`
- [ ] Завести issue в `claude_seed` репозитории по багам #1, #2, #6 (топ-3)
- [ ] Merge ветки `chore/claude-seed-upgrade` в main после ревью
- [ ] Если codegraph/github нужны — добавить в `.mcp.json` вручную из snippets
