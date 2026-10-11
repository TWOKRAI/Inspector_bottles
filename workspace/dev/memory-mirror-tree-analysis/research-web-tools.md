# Отчёт веб-исследователя: готовые решения памяти для кодовых агентов

Источник: агент `web-researcher`, прогон 2026-10-11, статус DONE_WITH_CONCERNS. Текст — отчёт агента, без правки по существу.
Тег [поиск] — страница не открывалась, опора на выдачу поиска. У страниц документации даты публикации нет, указана дата открытия.

## 1. Claude Code (https://code.claude.com/docs/en/memory)
- `CLAUDE.md` из cwd и родительских папок грузится при старте.
- `CLAUDE.md` в подпапках под cwd грузится лениво, когда Claude читает, пишет или правит файл в этой подпапке (в том числе `cat`/`head` одного файла).
- `.claude/rules/**/*.md` ищется рекурсивно. Без `paths` правило грузится всегда. С `paths:` (glob, `**`, `{a,b}`) грузится при Read/Write/Edit подходящего файла. `paths` — единственное читаемое поле frontmatter.
- `@path` грузится при запуске, вложенность до 4 прыжков, контекст не экономит.
- Auto memory: `~/.claude/projects/<project>/memory/`, на старте первые 200 строк `MEMORY.md` или 25 КБ, тематические файлы читаются по требованию. Рекомендация — до 200 строк на `CLAUDE.md`.
- Нативной привязки «зеркальное дерево памяти по пути правки» нет. Ближайшее: `CLAUDE.md` в самом дереве кода плюс `paths:`-правила. Зеркало в отдельной папке потребует правила на модуль или свой хук (поведение хука не проверялось).

## 2. Аналоги привязки правил к путям
- Cursor: `globs`, `alwaysApply`, `description`, вложенный `AGENTS.md`.
- Copilot: `applyTo` в `.github/instructions/*.instructions.md`, ближайший `AGENTS.md` побеждает.
- Windsurf/Devin Desktop: режимы `always_on`/`model_decision`/`glob`/`manual`, `AGENTS.md` подпапки = auto-glob. Лимиты 6000 / 12000 символов.
- Continue: `globs`, `regex` по содержимому, `alwaysApply`.
- Aider: repo map по графу зависимостей, бюджет 1k токенов, контекст на запрос, не память.

## 3. Инструменты памяти (дата — последний релиз)
- claude-mem: SQLite+Chroma, локально, привязки к коду не указано, v13.35.0, 2026-10-09.
- mem0: библиотека, Docker или облако, привязки к коду нет, Node SDK ts-v3.3.1, 2026-09-25.
- Letta: локальный `letta server` или Letta Cloud, модель памяти не проверена, 0.16.8, 2026-05-14 (старше 4 месяцев).
- basic-memory: Markdown-файлы плюс SQLite, `[[wiki-link]]`, AGPL-3.0, привязки к коду нет, v0.23.2, 2026-08-25. Ближе всего к идее владельца.
- Graphiti/Zep: темпоральный граф, самохостинг, привязки к коду нет, v0.30.2, 2026-09-08.
- cognee: граф+вектор+реляционная БД, локально, есть граф символов кода (детали не раскрыты), v1.6.3, 2026-10-07.
- Serena memories: Markdown в `.serena/memories/`, `/` в имени даёт подпапку, ссылки `mem:`, привязки к символам нет, v1.7.0, 2026-08-09.
- MCP memory server: JSONL-граф, привязки к коду нет, дату релиза не проверял.

## 4. Устаревание привязок
- docrot (https://github.com/dager23/docrot): детерминированная проверка ссылок на символы и пути, в том числе AG002 в `AGENTS.md`/`CLAUDE.md`, через griffe и git-историю, GitHub Action и pre-commit, только Python, alpha, MIT.
- docpin: `[pin:path:10-25 @hash]`, `docpin check` в CI [поиск]. doksnet (Rust) и codocia — хеши на уровне файла [поиск].
- DocSync: tree-sitter, платный [поиск].
- DeepWiki: публичные репозитории, MCP, ответы из сгенерированной вики [поиск]. Cody Free/Pro закрыт 2025-07-23, остался Enterprise [поиск].
- Стандарта «якорь на символ через tree-sitter + хеш» не найдено. По git notes подтверждений не найдено.

## 5. NotebookLM (https://github.com/jacob-bd/notebooklm-mcp-cli)
- CLI `nlm` и MCP на 53 инструмента, `nlm login` забирает cookies Google, внутренний недокументированный API, README: возможное нарушение ToS, на свой риск.
- Cookies живут около 2–4 недель. Квоты чата по окну около 5 часов плюс недельный лимит.
- v0.15.4, 2026-10-06, проект живой, MIT.
- Официально (https://support.google.com/notebooklm/answer/16213268): 50/100/300/500/600 источников на ноутбук (Standard/Plus/Pro/Ultra), 100–500 ноутбуков.
- Лимит 500k слов или 200 МБ на источник — только сторонние гайды [поиск].
- Официальный API: только Enterprise в Google Cloud, статус v1alpha [поиск, страницы Google не открывались]. Для потребительской версии не найден.
- Минусы против markdown-дерева: неофициальный API, риск поломки и бана, cookies, квоты, лимит на число источников, нет привязки «путь правки → заметка». Это вывод из перечисленных ограничений, отдельно не проверялся.

## Что осталось открытым или ненадёжным (по отчёту агента)
- Даты публикации страниц документации неизвестны.
- Пункты [поиск] (docpin, DeepWiki, Cody, NotebookLM API, 500k слов) не проверены по самим страницам.
- Модель памяти Letta и привязка mem0 к графу не подтверждены, дата релиза MCP memory server не искалась.
- `paths:`-правила на Windows и в worktree не проверялись; нужен живой тест (строка `Loaded` или хук `InstructionsLoaded`). Позже проба 2026-10-11 подтвердила доставку на Windows у субагента без `omitClaudeMd`; роли с флагом и worktree — задача 0.1 плана.
- Переименование NotebookLM в Gemini Notebook (2026-07-16) подтверждает один блог и README репозитория, официально не проверено.

## Источники
Открыты: code.claude.com/docs/en/memory; cursor.com/docs/context/rules; docs.github.com (Copilot repository instructions); docs.devin.ai/desktop/cascade/memories; docs.continue.dev/customize/deep-dives/rules; aider.chat/docs/repomap.html; GitHub: thedotmack/claude-mem, mem0ai/mem0, letta-ai/letta, basicmachines-co/basic-memory, getzep/graphiti, topoteretes/cognee, oraios.github.io/serena, modelcontextprotocol/servers (memory), dager23/docrot, jacob-bd/notebooklm-mcp-cli; support.google.com/notebooklm/answer/16213268.
Из выдачи поиска, страницы не открыты: pypi.org/project/docpin; sourcegraph.com/changelog/cody-plan-changes; codersera.com (DeepWiki); horadecodar.com.br/notebooklm-api; github.com/K-dash/nblm-rs; fast.io/resources/notebooklm-limits; claudemarket.ai (docsync).
