# План: Аудит и развитие папки `.claude/`

## Контекст

Пользователь попросил профессионально оценить содержимое [.claude/](.claude/) проекта Inspector_bottles (Python/PyQt5, многопроцессный фреймворк + прототип инспекции бутылок) и предложить, что добавить/улучшить. Задача — именно **ревью и план улучшений**, а не немедленная правка.

Текущий состав папки:
- [CLAUDE.md](.claude/CLAUDE.md) — основной проектный контекст (~5.8 KB, на русском, хорошо структурирован)
- [CLAUDE.local.md](.claude/CLAUDE.local.md) — локальные команды/venv
- [CLAUDE-SETUP.md](.claude/CLAUDE-SETUP.md) — инструкция по копированию `.claude` в другие проекты
- [FRAMEWORK_RULES_EXTRACT.md](.claude/FRAMEWORK_RULES_EXTRACT.md) (14 KB) и [FRAMEWORK_CONSTRUCTOR_OVERVIEW.md](.claude/FRAMEWORK_CONSTRUCTOR_OVERVIEW.md) (8.9 KB) — развёрнутые справочники по фреймворку
- [QEX_SETUP_GUIDE.md](.claude/QEX_SETUP_GUIDE.md) (20 KB) — инструкция по qex MCP
- [settings.json](.claude/settings.json) — permissions + 1 PreToolUse hook
- [settings.local.json](.claude/settings.local.json) — allow для `mcp__qex__*`
- [mcp.json](.claude/mcp.json) — только qex MCP (Qdrant+Ollama)
- [agents/security-reviewer.md](.claude/agents/security-reviewer.md) — 1 субагент
- [hooks/validate-safe-command.sh](.claude/hooks/validate-safe-command.sh) — bash-хук против опасных команд
- [skills/debug-issue/SKILL.md](.claude/skills/debug-issue/SKILL.md), [skills/refactor-code/SKILL.md](.claude/skills/refactor-code/SKILL.md) — 2 навыка

---

## Оценка по категориям (0–10)

| # | Категория | Балл | Комментарий |
|---|---|---|---|
| 1 | **CLAUDE.md — проектный контекст** | 8/10 | Чёткий, с архитектурой, путями, запретами. Минус: `python Inspector_prototype/multiprocess_prototype/main.py` дублирован в local, запреты короткие, нет раздела о style-guide (ruff/mypy конфиг). |
| 2 | **CLAUDE.local.md** | 7/10 | Полезен, но дублирует быстрые команды из setup. Нет персональных override для путей логов. |
| 3 | **settings.json (permissions)** | 7/10 | Разумные allow/ask/deny, есть хук. Минус: нет `Bash(ruff check *)` / `Bash(mypy *)` явно проверены, нет deny для `git push --force`, `git reset --hard`, нет `additionalDirectories`. |
| 4 | **Hook безопасности** | 8/10 | Хороший список паттернов, logger, exit 2. Минус: shell-хук под Git Bash на Windows хрупок (jq должен быть в PATH); нет PostToolUse-хука для автоформатирования. |
| 5 | **mcp.json** | 6/10 | Только qex, захардкожены абсолютные Windows-пути (не переносимо). Нет `context7` / `sequential-thinking` / GitHub MCP, которые дали бы заметный прирост. |
| 6 | **agents/** | 4/10 | Один security-reviewer. Для этого проекта напрашиваются: `framework-architect` (знает ADR/DECISIONS.md), `test-runner`, `ipc-routing-checker` (критично: targets vs channel), `pyqt-ui-reviewer`. |
| 7 | **skills/** | 5/10 | Два общих навыка (debug, refactor) без специфики проекта. Нет навыков под многопроцессный IPC, регистры, конфиги, схемы Pydantic. |
| 8 | **Документация-контекст (FRAMEWORK_*.md, QEX_SETUP_GUIDE.md)** | 6/10 | Полезно, но **всё это автоматически вчитывается в контекст** — 43 KB overhead в каждой сессии. Надо вынести в `docs/` или пометить как справочный материал «по запросу». |
| 9 | **Output styles / statusline / commands** | 0/10 | Отсутствуют полностью. Нет кастомных slash-команд (`/framework-test`, `/qex-reindex`), нет statusLine, нет output-style. |
| 10 | **Git-гигиена папки** | 6/10 | `settings.local.json` и `CLAUDE.local.md` должны быть в `.gitignore` — проверить. `QEX_SETUP_GUIDE.md` помечен как untracked в `git status` — решить: коммитить или в ignore. |

### Итог: **55 / 100** — «крепкая база, но много возможностей недоиспользовано»

Сильные стороны: внятный CLAUDE.md, безопасный hook, рабочий qex MCP.
Слабые: мало агентов/скиллов под доменную специфику, раздутый контекст, отсутствие slash-команд и дополнительных MCP.

---

## Предлагаемые изменения (по приоритету)

### P0 — критично (быстро + большой эффект)

1. **Сократить вчитываемый контекст.** Перенести [FRAMEWORK_RULES_EXTRACT.md](.claude/FRAMEWORK_RULES_EXTRACT.md), [FRAMEWORK_CONSTRUCTOR_OVERVIEW.md](.claude/FRAMEWORK_CONSTRUCTOR_OVERVIEW.md), [QEX_SETUP_GUIDE.md](.claude/QEX_SETUP_GUIDE.md) в `Inspector_prototype/multiprocess_framework/docs/` или `docs/claude/`. В [CLAUDE.md](.claude/CLAUDE.md) оставить только ссылки. Экономия: ~43 KB токенов на старте сессии.

2. **Добавить `.gitignore`-правила** для `.claude/settings.local.json` и `.claude/CLAUDE.local.md` (если их ещё нет в корневом `.gitignore`). Проверить: `git check-ignore .claude/settings.local.json`.

3. **Расширить deny в [settings.json](.claude/settings.json):**
   ```json
   "deny": [
     "Bash(sudo *)",
     "Bash(chmod 777 *)",
     "Bash(git push --force *)",
     "Bash(git push -f *)",
     "Bash(git reset --hard *)",
     "Bash(git clean -fd *)",
     "Bash(docker system prune *)"
   ]
   ```

### P1 — высокая отдача

4. **Новые субагенты в [.claude/agents/](.claude/agents/):**
   - `framework-architect.md` — знает `DECISIONS.md`, `ROUTING_GLOSSARY.md`, правила «Dict at Boundary», проверяет соответствие ADR.
   - `ipc-routing-checker.md` — проверяет, что код не путает имя процесса (`targets`) и канал Router (`FieldRouting.channel`). Это явно упомянуто в CLAUDE.md как частая ошибка.
   - `test-runner.md` — запускает `scripts/validate.py` и `scripts/run_framework_tests.py` с правильным `PYTHONPATH`.
   - `pyqt-ui-reviewer.md` — проверяет сигналы/слоты, утечки QObject, threading в `frontend_module`.

5. **Новые скиллы в [.claude/skills/](.claude/skills/):**
   - `add-process-module/SKILL.md` — чек-лист создания нового `ProcessModule` (README, STATUS, tests, регистрация в SystemLauncher).
   - `add-register-schema/SKILL.md` — как добавить схему в `multiprocess_prototype/registers/` согласно `SchemaBase`.
   - `qex-search/SKILL.md` — шаблон поиска через `mcp__qex__search_code` перед рефакторингом (это уже в CLAUDE.md как правило — вынести в user-invocable skill).

6. **Кастомные slash-команды** (`.claude/commands/`):
   - `/validate` → `python Inspector_prototype/scripts/validate.py`
   - `/fw-test` → `python Inspector_prototype/scripts/run_framework_tests.py`
   - `/qex-status` → вызов `mcp__qex__get_indexing_status`
   - `/qex-reindex` → `mcp__qex__index_codebase` с force=true
   - `/run-proto` → запуск прототипа
   - `/cold-start` → `docker start qdrant && ollama serve &` (напоминание)

### P2 — средняя отдача

7. **PostToolUse-хук автоформатирования.** После `Edit`/`Write` по `*.py` запускать `ruff format` + `ruff check --fix` на изменённом файле.

8. **Сделать [mcp.json](.claude/mcp.json) переносимым.** Заменить абсолютный путь к `qex-mcp-v2.exe` на `${workspaceFolder}` или относительный от `venv/`. Документировать, что требуется `venv` в корне.

9. **Расширить MCP серверы:**
   - **context7** — актуальная документация PyQt5/Pydantic v2/loguru.
   - **github** — работа с PR/issues проекта.
   - **filesystem** — если нужен доступ к соседним проектам.

10. **StatusLine.** Показывать активную ветку (`clean_v3`), статус qex-индекса, состояние `ollama serve`/`docker ps qdrant`. Одна строка — быстрая диагностика перед работой.

### P3 — «nice to have»

11. **Output style** под формат ответов из CLAUDE.md («План → поиск → код → следующие шаги») — формализовать.

12. **[.claude/README.md](.claude/README.md)** — краткий индекс: что в какой папке лежит и зачем. Упростит онбординг новых участников.

13. **CI-проверка CLAUDE.md.** Скрипт, который валидирует размер (≤ 80 строк рекомендуется) и наличие ключевых разделов. Можно повесить на pre-commit.

14. **Шаблон багрепорта для Claude** (`templates/bug-report.md`) — чтобы пользователь быстрее давал структурированный контекст (шаги, ожидаемое, факт, логи, env).

---

## Файлы, которые затронет реализация

- [.claude/CLAUDE.md](.claude/CLAUDE.md) — сокращение, ссылки наружу
- [.claude/settings.json](.claude/settings.json) — расширение deny, возможно PostToolUse
- [.claude/mcp.json](.claude/mcp.json) — переносимость путей, новые серверы
- [.claude/agents/](.claude/agents/) — 3–4 новых `.md`
- [.claude/skills/](.claude/skills/) — 3 новых папки со `SKILL.md`
- [.claude/commands/](.claude/commands/) — **новая папка**, 5–6 slash-команд
- `Inspector_prototype/multiprocess_framework/docs/` (или `docs/claude/`) — переносимые справочники
- Корневой `.gitignore` — проверка на `CLAUDE.local.md` и `settings.local.json`

---

## Верификация после внедрения

1. **Размер контекста:** `wc -c .claude/CLAUDE.md .claude/CLAUDE.local.md` — суммарно < 6 KB.
2. **Permissions:** попытаться выполнить `git push --force origin clean_v3` — должно блокироваться.
3. **Hook:** прогнать `bash .claude/hooks/validate-safe-command.sh <<< '{"tool_input":{"command":"rm -rf /"}}'` → exit 2.
4. **Субагенты:** в сессии `/agents` — все новые видны.
5. **Скиллы:** `/skill add-process-module` — раскрывается.
6. **Slash-команды:** `/validate` — запускает `scripts/validate.py`.
7. **qex MCP:** `mcp__qex__get_indexing_status` отвечает после `docker start qdrant && ollama serve`.
8. **Портативность:** проверить, что `.claude/` можно скопировать в другой клон проекта без правки абсолютных путей (кроме `mcp.json`, где остаётся `WORKSPACE_PATH`).

---

## Что делать после одобрения плана

Внедрять **поэтапно**: сначала P0 (сокращение контекста + deny) одним коммитом, затем P1 (агенты/скиллы/команды) отдельными коммитами по логическим блокам. Это позволит откатывать отдельные изменения, если что-то начнёт мешать.
