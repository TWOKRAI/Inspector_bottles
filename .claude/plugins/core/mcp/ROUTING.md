# MCP Routing — Canonical Map

> **Назначение этого файла:** для авторов агентов (при правке `.md`), для verify-скрипта
> (`scripts/verify-mcp-orchestration.sh`), для линтера (`scripts/lint_routing.py`),
> для человека-ревьюера системы. **Агенты этот файл runtime НЕ читают** (this file is
> not for runtime — agents do not load it) — у каждого свой самодостаточный routing-блок
> в собственной `.md`. Эта карта — единый канон, на который опираются авторы при правке
> агентов и при ревью изменений.
>
> Если правишь routing-блок в каком-то агенте — сверяйся с этим файлом. Если добавляешь
> новый MCP — сначала описываешь здесь (включая `**Canonical refs:**` блок), потом
> в агентах.
>
> **Canonical refs:** каждая `### <server>` секция заканчивается блоком
> `**Canonical refs:** \`mcp:<server>:<tool>\`, …` — это authoritative-список tools.
> Линтер (`scripts/lint_routing.py`) сверяет каждое упоминание `mcp:server:tool` в агентах
> с этим списком. Короткие формы в bullet'ах (`qt_find_widget`, `callers`) — читабельность,
> канон — только в `Canonical refs`.

---

## TL;DR — таблица всех серверов

| Тип запроса | Primary MCP | Сервер подключён? | Fallback |
|-------------|-------------|-------------------|----------|
| Семантический / fuzzy поиск по коду | `qex:search_code` | **core** (всегда в seed) | `Grep` (дешевле для exact strings) |
| Архитектурные метрики, DSM, циклы | `sentrux:dsm` / `sentrux:health` | **core** | руками через `pydeps` |
| Проверка архитектурных правил | `sentrux:check_rules` | **core** | руками + чек-лист |
| Документация библиотек (актуальная) | `context7:query-docs` | **core** (user-level) | `WebFetch` для официальных docs |
| Callers / callees / call path | `codegraph:codegraph_explore` | optional | `Grep` + чтение |
| Blast radius изменения | `codegraph:codegraph_explore` | optional | руками через git diff + Grep |
| Verbatim source + структура символов | `codegraph:codegraph_explore` | optional | `Glob` + `Read` |
| Symbol-level refs / rename across files | `serena:find_referencing_symbols` / `serena:rename_symbol` | optional (experimental) | `ast-grep` или ручной Grep+Edit |
| Structural codemod на N файлов | `ast-grep:scan` / `ast-grep:rewrite` | optional | `Grep` + ручные Edits (опасно) |
| Architectural overview / hubs | `graphify:query_graph` | optional | `sentrux:dsm` + руками |
| GitHub PR / Issues / Actions state | `github:*` | optional | `gh` CLI |
| PyQt/PySide widget tree, screenshot, click | `qt-mcp:qt_find_widget` / `qt_snapshot` / `qt_screenshot` / `qt_batch` | optional (GUI only) | руками через `pytest-qt` |
| Browser / web UI verify (navigate, screenshot) | `playwright:browser_navigate` / `screenshot` | optional (web only) | `curl` + проверка HTML |
| Multi-step reasoning (сложная гипотеза) | `sequential-thinking:sequentialthinking` | optional | внутренний chain-of-thought |
| Живой бэкенд multiprocess_framework (introspect, команды, state, логи) | `backend-ctl:capabilities` / `backend-ctl:send_command` | optional (framework-only) | `backend_ctl` driver из Bash+Python-сниппета |
| Поиск по базе знаний / wiki / транскриптам | `knowledgeos:kos_search` / `kos_ask` | optional (knowledge plugin) | `Grep` / `Read` по `docs/` |
| Точная строка / regex | `Grep` | always | — |

---

## Per-server details

### qex — семантический поиск (core)

**Когда вызывать:** "где код, который X", fuzzy intent, рефакторинг с разведкой.

**Ключевые tools:**
- `mcp__qex__search_code` — гибридный BM25 + dense поиск.
- `mcp__qex__get_indexing_status` — состояние индекса.
- `mcp__qex__index_codebase` — переиндексация (force/incremental).
- `mcp__qex__clear_index` — сбросить индекс (редко, при corruption).

**Не дублируй:** если qex дал релевантный список — не Grep'ай те же файлы.

**Canonical refs:** `mcp:qex:search_code`, `mcp:qex:get_indexing_status`, `mcp:qex:index_codebase`, `mcp:qex:clear_index`, `mcp:qex:download_model`.

### sentrux — архитектурный health-gate (core)

**Когда вызывать:** перед `/dev:ship`, перед рефакторингом, для review §Architecture, для investigator при cross-module расследовании.

**Ключевые tools:**
- `mcp__sentrux__check_rules` — валидация `.sentrux/rules.toml` (cycles, layer violations).
- `mcp__sentrux__dsm` — Dependency Structure Matrix.
- `mcp__sentrux__health` — quality_signal + bottleneck snapshot.
- `mcp__sentrux__test_gaps` — модули без покрытия.
- `mcp__sentrux__git_stats` — churn, hotspots, bus factor.
- `mcp__sentrux__scan` / `rescan` — расчёт графа.
- `mcp__sentrux__session_start` / `session_end` — baseline и diff.

**Не дублируй:** если sentrux:check_rules дал список нарушений — не пересматривай руками.

**Canonical refs:** `mcp:sentrux:check_rules`, `mcp:sentrux:dsm`, `mcp:sentrux:health`, `mcp:sentrux:test_gaps`, `mcp:sentrux:git_stats`, `mcp:sentrux:scan`, `mcp:sentrux:rescan`, `mcp:sentrux:session_start`, `mcp:sentrux:session_end`.

### context7 — документация библиотек (core, user-level) **[CONSUME — official]**

**Когда вызывать:** работа с любой внешней библиотекой — особенно при unfamiliar API, version-specific migration, exact method signature.

**Ключевые tools:**
- `mcp__context7__resolve-library-id` — найти ID библиотеки (`/org/project`).
- `mcp__context7__query-docs` — задать вопрос по докам.

**Не для:** stdlib, well-known patterns core-стека проекта (если уверен в API), refactoring внутренней бизнес-логики.

**Consume status (Task 6.3-fix):** `source: context7@claude-plugins-official` (marketplace-qualified ref, D6-SOURCE-ENCODING) — официальный плагин context7 в маркетплейсе Anthropic. Был user-level/no-op в нашем seed (нет mcpServers в plugin.json) → переклассифицирован в CONSUME. CC wireит сервер из своего маркетплейс-кэша; наш `plugin.json` не содержит `mcpServers`. Версии нет — SHA-pinned upstream.

**Canonical refs:** `mcp:context7:resolve-library-id`, `mcp:context7:query-docs`.

### codegraph — code intelligence по индексированному графу (optional)

**Когда подключён:** проекты ≥5k LOC с активным рефакторингом. Pre-indexed граф символов (`@colbymchenry/codegraph` — SQLite + tree-sitter).

**Один tool — `codegraph_explore(query, maxFiles?, projectPath?)`:** `query` — это natural-language вопрос ИЛИ bag имён символов/файлов (`"RouterManager send_message channel"`). Отдельных `callers`/`callees`/`impact`/`context`/`files`/`search`/`node`/`status` **нет** — всё это один вызов. Один `codegraph_explore` возвращает:
- **verbatim** line-numbered исходник релевантных символов, сгруппированный по файлам (Read-эквивалент — не перечитывай эти файлы `Read`'ом);
- **call path** среди них (кто кого вызывает — заменяет callers/callees);
- **blast radius** — что зависит от символа + покрывающие тесты (для оценки последствий правки; заменяет impact);
- **relationships** (extends / instantiates / calls).

**Read-first привычка:** зови `codegraph_explore` ПЕРЕД `Read`/`Grep`-петлёй при «как работает X» и перед правкой символа — один вызов вместо десятков round-trip'ов.

**Не дублируй:** codegraph дал источник + callers → не Grep'ай и не Read'ай те же символы.

**Canonical refs:** `mcp:codegraph:codegraph_explore`.

### serena — LSP symbol retrieval (optional, experimental) **[BUNDLED — upstream-caveat]**

**Когда подключён:** проекты ≥10k LOC с активным cross-file refactoring + стабильным LSP для языка.

**Ключевые tools:**
- `mcp__serena__find_symbol`, `find_referencing_symbols`, `find_implementations`, `find_declaration`.
- `mcp__serena__rename_symbol` — атомарный refactor по LSP.
- `mcp__serena__replace_symbol_body`, `insert_before_symbol`, `insert_after_symbol`, `safe_delete_symbol`.
- `mcp__serena__get_symbols_overview`, `get_diagnostics_for_file`.

**Конфликт с codegraph/ast-grep:** serena делает scope-aware (LSP) операции; ast-grep — pattern-based; codegraph — pre-indexed graph. Выбирай по задаче.

**Bundled rationale (Task 6.3 — USP-gate / upstream-caveat):** serena есть в маркетплейсе Anthropic (`external_plugins/serena`), но **upstream `oraios/serena` явно не рекомендует marketplace-install** — установочные команды там «contain outdated and suboptimal installation commands». Рекомендованный путь: `serena start-mcp-server --context claude-code --project-from-cwd`. Наш curated `plugin.json` (с `--project-from-cwd`) корректнее маркетплейс-версии. Решение: `source: None` (bundled), `mcpServers` сохранить — переклассификация в CONSUME отложена до исправления upstream.

**Canonical refs:** `mcp:serena:find_symbol`, `mcp:serena:find_referencing_symbols`, `mcp:serena:find_implementations`, `mcp:serena:find_declaration`, `mcp:serena:rename_symbol`, `mcp:serena:replace_symbol_body`, `mcp:serena:insert_before_symbol`, `mcp:serena:insert_after_symbol`, `mcp:serena:safe_delete_symbol`, `mcp:serena:get_symbols_overview`, `mcp:serena:get_diagnostics_for_file`.

### ast-grep — structural codemods (optional)

**Когда подключён:** проекты с активным codemod-refactoring, polyglot, или строгие code-rules в CI.

**Ключевые tools:**
- `ast-grep:scan` — найти паттерн.
- `ast-grep:rewrite` (через rules) — AST-safe замена.

**Не дублируй с serena:** serena для одного символа (scope-aware), ast-grep для bulk patterns.

**Canonical refs:** `mcp:ast-grep:scan`, `mcp:ast-grep:rewrite`.

### graphify — knowledge graph (optional)

**Когда подключён:** периодический architectural review, onboarding в кодбейз, поиск god-nodes и hubs.

**Ключевые tools:**
- `graphify:query_graph` — natural language запросы к графу.
- `graphify:graph_stats` — сводная статистика графа (узлы, рёбра, communities).
- `graphify:god_nodes` — узлы-хабы с наибольшей связностью.
- `graphify:get_node`, `get_neighbors`, `get_community` — инспекция узла, его соседей, сообщества.
- `graphify:shortest_path` — путь между двумя узлами.

**Не для:** обычная навигация по коду — это `qex`/`codegraph`.

**Canonical refs:** `mcp:graphify:query_graph`, `mcp:graphify:get_node`, `mcp:graphify:get_neighbors`, `mcp:graphify:get_community`, `mcp:graphify:god_nodes`, `mcp:graphify:graph_stats`, `mcp:graphify:shortest_path`.

### github-mcp — GitHub state (optional) **[CONSUME — official]**

**Когда подключён:** проект на GitHub, активная работа с PR/Issues/Actions.

**Категории tools:** Issues, Pulls, Actions, Repo, Projects (всего 80+ tools — динамический набор, точные имена эволюционируют между релизами upstream).

**Не для:** локальный `git` (status, log, diff, commit) — это shell `git`, всегда дешевле.

**Consume status (Task 6.3-fix):** `source: github@claude-plugins-official` (marketplace-qualified ref, D6-SOURCE-ENCODING) — официальный GitHub MCP plugin (github/github-mcp-server) в маркетплейсе Anthropic. CC wireит сервер из своего маркетплейс-кэша; `plugin.json` не содержит `mcpServers`. Это чистый CONSUME: плагин лишь декларирует зависимость через `source` в `enabled.yaml`. Версии нет — SHA-pinned upstream.

**Canonical refs:** *dynamic tool set — конкретные tools перечисляются в агентах при необходимости. Линтер `lint_routing.py` для github-mcp работает в режиме warning (orphan-tools допустимы).*

### qt-mcp — PyQt/PySide runtime (optional, GUI-only)

**Когда подключён:** проект использует PyQt5/PySide6.

**Когда вызывать:**
- **tester** — GUI smoke / интеграционные тесты (snapshot, find, click, batch action+verify) вместо самописного `pytest-qt` бойлерплейта.
- **reviewer** (Specialization: UI Thread-safety) — `qt_thread_check` / `qt_signals` / `qt_messages` для runtime-проверки thread-safety и signal/slot leaks.
- **debugger** — диагностика зависаний UI и непонятных visual-багов (`qt_messages` warnings/errors, `qt_widget_details`, `qt_active_popup`, `qt_screenshot`).
- **investigator** — cross-module GUI bugs (state propagation в widget tree, `qt_object_tree` + `qt_snapshot`).
- **spec-writer** — снять реальную UI-структуру для living spec (`qt_list_windows`, `qt_menu_items`, `qt_snapshot`).
- **verify-done skill** — золотой путь проверяется `qt_screenshot` + `qt_snapshot` для GUI-проектов вместо «нельзя проверить вручную».

**Ключевые tools:**
- `qt_find_widget` — быстрый поиск по class/name/text (предпочтительнее `qt_snapshot` если известно что ищем).
- `qt_snapshot` — полное дерево виджетов (overall structure, discovery).
- `qt_batch` — цепочка операций (click, type, key_press, wait, snapshot, find_widget) в одном round-trip.
- `qt_screenshot` — ТОЛЬКО для visual-контента (рендеренные plots/images/custom drawing). Состояние виджета — через `qt_snapshot`/`qt_get_text` (дешевле).
- `qt_click` / `qt_type` / `qt_key_press` / `qt_trigger_action` / `qt_invoke_slot` — input/action.
- `qt_get_text` / `qt_widget_details` / `qt_set_property` — чтение/правка состояния.
- `qt_messages` — Qt log messages (warnings, debug output).
- `qt_thread_check` — runtime thread-safety check (UI updates вне main thread).
- `qt_signals` — список signal/slot connections (поиск утечек).
- `qt_object_tree` — иерархия QObject (parent/children).
- `qt_layout_check` — overlap/cutoff детекция в layout.
- `qt_active_popup` / `qt_list_windows` / `qt_menu_items` — диагностика модалок и навигации.
- `qt_wait_for` — синхронное ожидание условия (для интеграционных тестов).
- `qt_vtk_screenshot` / `qt_vtk_scene_info` — VTK-сцены (если используются).

**`qt_type` с `use_clipboard=True`** — для многострочного текста (иначе newline сабмитит каждую строку в console-виджетах).

**Canonical refs:** `mcp:qt-mcp:qt_find_widget`, `mcp:qt-mcp:qt_snapshot`, `mcp:qt-mcp:qt_batch`, `mcp:qt-mcp:qt_screenshot`, `mcp:qt-mcp:qt_click`, `mcp:qt-mcp:qt_type`, `mcp:qt-mcp:qt_key_press`, `mcp:qt-mcp:qt_trigger_action`, `mcp:qt-mcp:qt_invoke_slot`, `mcp:qt-mcp:qt_get_text`, `mcp:qt-mcp:qt_widget_details`, `mcp:qt-mcp:qt_set_property`, `mcp:qt-mcp:qt_messages`, `mcp:qt-mcp:qt_thread_check`, `mcp:qt-mcp:qt_signals`, `mcp:qt-mcp:qt_object_tree`, `mcp:qt-mcp:qt_layout_check`, `mcp:qt-mcp:qt_active_popup`, `mcp:qt-mcp:qt_list_windows`, `mcp:qt-mcp:qt_menu_items`, `mcp:qt-mcp:qt_wait_for`, `mcp:qt-mcp:qt_vtk_screenshot`, `mcp:qt-mcp:qt_vtk_scene_info`.

### playwright — browser automation (optional, web-only)

**Когда подключён:** проект — веб-приложение, нужно verify UI в браузере (`verify-done` для веб).

**Ключевые tools:** `browser_navigate`, `browser_screenshot`, `browser_click`, `browser_fill`, `browser_press_key`, `browser_evaluate`, `browser_console_logs`, `browser_network_requests`.

**Используется:** verify-done skill (golden-path screenshot), tester при e2e debugging.

**Canonical refs:** `mcp:playwright:browser_navigate`, `mcp:playwright:browser_screenshot`, `mcp:playwright:browser_click`, `mcp:playwright:browser_fill`, `mcp:playwright:browser_press_key`, `mcp:playwright:browser_evaluate`, `mcp:playwright:browser_console_logs`, `mcp:playwright:browser_network_requests`.

### sequential-thinking — externalized reasoning (optional)

**Когда подключён:** investigator на 3-й гипотезе, teamlead на эскалации, ADR с 3+ альтернативами.

**Один tool:** `sequentialthinking` — chain-of-thought scratchpad с поддержкой revision и branching.

**Используется:** investigator (Workflow §1 при сложных cross-module bugs), teamlead (Escalation mode).

**Canonical refs:** `mcp:sequential-thinking:sequentialthinking`.

### backend-ctl — живой бэкенд multiprocess_framework (optional, framework-only)

**Когда подключён:** проект построен на `multiprocess_framework` и содержит пакет `backend_ctl/` (сервер живёт в репо проекта — плагин лишь лаунчер). Нужен запущенный бэкенд с `BACKEND_CTL=1`; без него инструменты возвращают понятную ошибку.

**Ключевые tools:**
- `capabilities` — «контактная книжка» системы: процессы, их команды, регистры, каналы (первый вызов сессии — вместо чтения исходников).
- `get_status`, `introspect_handlers`, `introspect_registers`, `introspect_router_stats`, `introspect_queues` — диагностика процесса («есть ли приёмник команды X»).
- `send_command`, `system_command`, `set_register` — команды, лайфцикл, live-запись регистров.
- `state_get`, `state_get_subtree`, `state_subscribe`, `events` — state-дерево и push-события.
- `log_tail` / `log_untail` — LogRecord'ы процесса с level ≥ порога в `events`.

**Используется:** developer/debugger/tester при отладке бэкенда без GUI (backend-путь до qt-mcp: сперва доказать бэкенд, потом GUI).

**Canonical refs:** `mcp:backend-ctl:capabilities`, `mcp:backend-ctl:get_status`, `mcp:backend-ctl:introspect_handlers`, `mcp:backend-ctl:introspect_registers`, `mcp:backend-ctl:send_command`, `mcp:backend-ctl:set_register`, `mcp:backend-ctl:state_get`, `mcp:backend-ctl:state_subscribe`, `mcp:backend-ctl:events`, `mcp:backend-ctl:log_tail`.

### knowledgeos — knowledge-base OS (optional, knowledge plugin)

**Когда подключён:** включён плагин `knowledge` (knowledge-mode проекты — Obsidian-vault, wiki, транскрипты). Не входит в дефолтный dev-набор.

**Ключевые tools:**
- `mcp__knowledgeos__kos_search` — поиск по базе знаний (wiki / inbox / raw).
- `mcp__knowledgeos__kos_ask` — вопрос-ответ по базе.
- `mcp__knowledgeos__kos_know` — извлечь / записать факт.
- `mcp__knowledgeos__kos_read_wiki` — прочитать wiki-страницу.

**Используется:** science-агенты (`sci-*`), команды `/curate` / `/research` / `/synthesize` / `/kb`.

**Canonical refs:** `mcp:knowledgeos:kos_search`, `mcp:knowledgeos:kos_ask`, `mcp:knowledgeos:kos_know`, `mcp:knowledgeos:kos_read_wiki`.

---

## Heuristics — общие правила

1. **Не дублируй.** Если MCP A дал ответ — не перепроверяй MCP B на тех же данных. Цель — минимум tool calls.
2. **Grep — последний или первый.** Для точной строки `Grep` дешевле любого MCP. Для fuzzy intent — `qex` первым.
3. **Fallback всегда explicit.** Если в routing-блоке агента упомянут optional MCP — там же должен быть fallback ("если codegraph не подключён → Grep").
4. **Conditional guards обязательны.** Каждое упоминание optional MCP в routing — с условием "если `<server>` подключён".
5. **MCP молчит → не зацикливайся.** Если MCP вернул ошибку или таймаут — fallback на стандартные tools, не повторяй тот же вызов трижды.

---

## Health-fallback — что делать если MCP упал

| Симптом | Действие |
|---------|----------|
| qex отвечает ошибкой / пустотой | Проверить Ollama (`curl localhost:11434`) → если down, fallback на `Grep` |
| sentrux команда не находится | Проверить `command -v sentrux` → если нет, skip architectural-блок ревью, отметить в output |
| context7 timeout | Fallback на `WebFetch` к официальным docs либо память LLM (с оговоркой) |
| codegraph index устарел | Подсказать пользователю `codegraph reindex` → пока fallback на `Grep` |
| serena LSP не стартует | Skip serena, fallback на `qex` + `Grep` |

Health-check выводится при `SessionStart` хуком `hooks/quality/mcp-health-check.sh` — оркестратор знает что доступно в текущей сессии.

---

## Per-project filtering — apply-seed time

В seed-шаблоне ROUTING.md описывает **все** возможные MCP. В конкретном проекте после `apply-seed`:
- `.mcp.json` содержит только активированные сервера.
- `_stack.md` помечает чекбоксами какие optional MCP включены.
- Агенты вызывают MCP **только если подключены** (conditional guard в routing-блоке).

Это значит: routing-блок в `reviewer.md` всегда говорит "если sentrux подключён → sentrux:check_rules". В проекте без sentrux агент пойдёт на fallback (Grep) без ошибок.

---

## Consume vs Bundled classification (Task 6.3 snapshot — 2026-05-29)

Каждый MCP-плагин seed'а имеет один из двух статусов:

| Плагин | Статус | `source:` в enabled.yaml | `mcpServers` в plugin.json | Обоснование |
|--------|--------|--------------------------|---------------------------|-------------|
| `mcp-context7` | **CONSUME** | `context7@claude-plugins-official` | отсутствует | Официальный context7 в маркетплейсе; был user-level/no-op → consume чисто; версии нет (SHA-pinned) |
| `mcp-github` | **CONSUME** | `github@claude-plugins-official` | отсутствует | Официальный GitHub MCP (github/github-mcp-server) в маркетплейсе; версии нет (SHA-pinned) |
| `mcp-serena` | **BUNDLED** | отсутствует | сохранён | upstream-caveat: `oraios/serena` не рекомендует marketplace-install; curated setup корректнее |
| `mcp-qex` | BUNDLED | отсутствует | сохранён | локальный semantic search (offline embedding, Merkle-инкремент) — нет официального эквивалента |
| `mcp-sentrux` | BUNDLED | отсутствует | сохранён | DSM/health-score специфика, официального нет |
| `mcp-graphify` | BUNDLED | отсутствует | сохранён | custom knowledge graph, нет официального эквивалента |
| `mcp-qt` | BUNDLED | отсутствует | сохранён | runtime introspection MCP уникален; официальные = только статичные skills |
| `mcp-ast-grep` | BUNDLED | отсутствует | сохранён | structural codemod, semgrep — другой UX |
| `mcp-codegraph` | BUNDLED | отсутствует | сохранён | REPLACE? — open question #11 (Phase 8) |
| `mcp-playwright` | BUNDLED | отсутствует | сохранён | web-only optional, без официального эквивалента |
| `mcp-sequential-thinking` | BUNDLED | отсутствует | сохранён | externalized reasoning, no equivalent |

**USP-gate rule:** плагин остаётся BUNDLED, если у него есть явное преимущество (offline, доменные знания, оркестрация, curated setup) ИЛИ upstream-caveat против marketplace-install. Иначе → CONSUME (`source: <plugin>@<marketplace>`).

**Миграция/upgrade:** marketplace-qualified `source` — добавочная семантика. Существующий проект с уже настроенным `mcp-github`/`mcp-context7` локально — не ломается (consume = skip в recompose; пользовательские `mcpServers` в `.mcp.json` не трогаются). Default-набор только для новых проектов (`claude-kit-project new`).

---

## Maintenance

- При добавлении нового MCP — сначала описать здесь (новая секция + строка в TL;DR + блок `**Canonical refs:**`), потом править агентов.
- При удалении MCP — убрать отсюда, прогнать verify-скрипт (найдёт orphan-упоминания в агентах).
- verify-скрипт (`scripts/verify-mcp-orchestration.sh`) проверяет consistency: все `mcp:server:tool` упомянутые в агентах присутствуют здесь.
- Линтер (`scripts/lint_routing.py`) — строгая Python-проверка для CI: agents → canonical (error), canonical → agents (warning, orphans допустимы).
- При изменении consume-статуса плагина — обновить таблицу выше + `enabled.yaml` + `plugin.json` атомарно (один коммит).
