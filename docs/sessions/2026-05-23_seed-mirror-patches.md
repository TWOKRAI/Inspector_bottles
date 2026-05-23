# Зеркальные правки для `claude_seed` (template 0.2.0)

> Что я поправил в **Inspector_bottles**, чтобы компенсировать баги/упущения seed.
> Каждый пункт — действие в проекте + ссылка где делать **то же самое** в seed
> (`D:\PROJECT_INNOTECH\claude_seed\src\claude_kit\template\`).

**Дата:** 2026-05-23
**Версия seed:** claude-kit 0.4.0, template 0.2.0
**Полный отчёт багов:** [`2026-05-23_claude-seed-upgrade.md`](./2026-05-23_claude-seed-upgrade.md)

---

## 1. `pyproject.toml` — добавить `ruff` в dev group

### В проекте

`pyproject.toml` `[dependency-groups].dev`:
```toml
"ruff>=0.15", # linter + formatter (pre-commit ставит свой, дублируем для make lint без активной venv)
```

### В seed (зеркально)

**Файл:** `templates/pyproject.template.toml`
**Раздел:** `[dependency-groups].dev` (рядом с pyright, bandit)

**Почему:** Сейчас `ruff` есть только в pre-commit's own venv. `make lint` / `uv run ruff` упадут с `program not found` пока pre-commit не закеширован. Это сюрприз для нового проекта.

---

## 2. `Makefile` — `uv run` префиксы для всех tool-вызовов

### В проекте

```makefile
UV_RUN := uv run
PYTHON := $(UV_RUN) python
PYTEST := $(UV_RUN) pytest
RUFF := $(UV_RUN) ruff
PYRIGHT := $(UV_RUN) pyright
BANDIT := $(UV_RUN) bandit
```

### В seed (зеркально)

**Файл:** `templates/Makefile.template`
**Раздел:** «── Пути ──» в начале

**Почему:** На Windows venv часто **не активирована** в Git Bash / VSCode terminal. Без `uv run` префиксов targets падают с `command not found`. `uv run` транзитивно резолвит venv проекта.

---

## 3. `Makefile.clean` — убрать упоминание `.mypy_cache`, добавить `.ruff_cache` + `.pyright_cache`

### В проекте

```makefile
clean: ## Удалить Python-кэши (pyright/ruff caches тоже)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pyright_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name ".coverage" -delete 2>/dev/null || true
```

### В seed (зеркально)

**Файл:** `templates/Makefile.template`
**Target:** `clean`

**Почему:** Stack сменился pyright (mypy retired). Очистка должна отражать актуальные caches.

---

## 4. `.gitignore` — `.backup_tmp/`, `.mypy_cache/`, `.claude/_backups/`

### В проекте

```gitignore
# Type checker caches (mypy исторический, перешли на pyright; pyright_cache на всякий)
.mypy_cache/
.pyright_cache/

# Временные артефакты devseed / claude-kit
.backup_tmp/
.claude/_backups/
```

### В seed (зеркально)

**Файл:** `templates/gitignore.template`
**Раздел:** рядом с `.pytest_cache/` / `.coverage`

**Почему:**
- `devseed upgrade --apply` создаёт backup в `$TMPDIR`, но **`.backup_tmp/`** появляется когда юзер вручную распаковывает его внутри проекта (как я делал чтобы восстановить user files).
- `.claude/_backups/` — резерв на случай если seed добавит локальные backup'ы (рекомендация `devseed upgrade --backup-dir <path>`, см. report).
- `.mypy_cache/` — на случай если кто-то ещё использует mypy локально; безопасно игнорить.

---

## 5. `.pre-commit-config.template.yaml` — bandit / ruff exclude `.claude/`

### В проекте

`.pre-commit-config.yaml` (баг #10 из отчёта):
```yaml
  - id: bandit
    args: [-c, pyproject.toml, -q]
    additional_dependencies: ["bandit[toml]"]
    exclude: ^(tests/|multiprocess_prototype_backup/|\.claude/)
```

### В seed (зеркально)

**Файл:** `templates/pre-commit-config.template.yaml`
**Hooks:** `bandit`, опц. `ruff` (если ruff тоже скандалит на seed-скриптах)

```yaml
exclude: ^(tests/|\.claude/)
```

**Почему:** `.claude/templates/scripts/*.py` и `.claude/templates/validate_commit/validate_commit.py` — это **шаблоны** для копирования в проект, а не код проекта. Bandit ругается на `subprocess`/`shell=True` в шаблонах → блокирует первый commit. Принцип "`.claude/` opaque" из seed README не работает на уровне pre-commit.

---

## 6. `claude-md.template.md` — обновить список slash-команд

### В проекте

`CLAUDE.md` (root) + `.claude/CLAUDE.md`:
- 37 → **46 команд**, 6 → **7 категорий** (добавилась `memory/`)
- `make check` mypy → **pyright**
- Убрана ссылка на удалённый `.claude/README.md`
- Добавлены `/adr`, `/doctor`, `/lint-agents`, `/lint-settings`, `/memory:init|search|status`, `/wrap-up`

### В seed (зеркально)

**Файл:** `templates/claude-md.template.md`
**Раздел:** «Slash-команды»

**Почему:** template был под старый набор команд из 0.1.x. После Phase 11-13 в seed добавлены namespace'ы `memory/` и команды `/adr`, `/doctor`, `/lint-*`, `/wrap-up`, но `claude-md.template.md` не обновлён.

---

## 7. Что было сделано в `.mcp.json` (не зеркалируется — это per-project)

Собрал вручную **6 MCP servers** из `.claude/mcp/<id>/templates/mcp-config.json.snippet`:
`sentrux`, `serena`, `qex`, `qt-mcp`, `graphify`, `ast-grep`.

### Запрос на seed

Реализовать **баг #6** из основного отчёта:
- `devseed add <mcp>` должен инжектить snippet в `.mcp.json` (strip JS-comments + merge mcpServers)
- `devseed remove <mcp>` должен удалять блок
- Команда `devseed sync-config` для пересборки `.mcp.json` из текущего selection (recovery после ручных правок)

---

## 8. Восстановление user files (баг #1, #2)

В моём случае пострадали: `commands/analysis/channel-map.md`, `commands/analysis/message-contracts.md`, `commands/infra/validate.md`.

### В seed

Нужно править `core/composition/seed_copy.py`:
- `_classify_path()` корректно определяет user files (dry-run показывает `U (kept)`)
- но физическое удаление в `_remove_orphans` / `_sync_seed_files` не учитывает классификацию

**Тест-кейс для CI seed:**
1. `claude-kit new tmp/`
2. Добавить `tmp/.claude/commands/analysis/my-custom.md`
3. `claude-kit upgrade tmp/ --apply`
4. Проверить что `my-custom.md` НА МЕСТЕ
5. `claude-kit add skill-brainstorm tmp/`
6. Опять проверить что `my-custom.md` НА МЕСТЕ

Без такого теста баги #1 и #2 будут возвращаться.

---

## Итог — чек-лист правок в `D:\PROJECT_INNOTECH\claude_seed\`

- [ ] `templates/pyproject.template.toml` — `"ruff>=0.15"` в dev
- [ ] `templates/Makefile.template` — `UV_RUN := uv run` + префиксы tools
- [ ] `templates/Makefile.template` — `clean` target: убрать mypy, добавить ruff/pyright caches
- [ ] `templates/gitignore.template` — `.backup_tmp/`, `.mypy_cache/`, `.pyright_cache/`, `.claude/_backups/`
- [ ] `templates/pre-commit-config.template.yaml` — bandit exclude `\.claude/`
- [ ] `templates/claude-md.template.md` — список slash-команд (46/7, новые namespace'ы)
- [ ] `src/claude_kit/core/composition/seed_copy.py` — фикс багов #1/#2 (user files preserve)
- [ ] `src/claude_kit/commands/add.py` — `_inject_mcp_snippet()` для авто-merge в `.mcp.json`
- [ ] `src/claude_kit/commands/upgrade.py` — реализовать или убрать `--prune-orphans` подсказку
- [ ] `src/claude_kit/manifest.yaml` — проверить что `hooks-quality` в core required (либо документировать как opt-in)
- [ ] CI: добавить characterization test «user files preserved through upgrade + add»
