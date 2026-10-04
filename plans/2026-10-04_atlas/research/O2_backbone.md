# O2 — Автоматический хребет «единого организма»

Ось: какие готовые инструменты становятся хребтом одной системы.
Репо: main, HEAD 03952a020, 2026-10-04. Всё read-only. qex недоступен (Ollama не запущен); graphify читался и из `graph.json`, и через `mcp__graphify__*` (работает).

## 0. Итог в шести строках

1. Хребет уже частично есть: **диспетчер post-commit с «частями»** (`.claude/plugins/core/hooks/git/post-commit.sh`, части в `plugins/<id>/hooks/git/post-commit.d/*.sh`). На этой машине он **не установлен**: в `.git/hooks/post-commit` лежит старый ручной скрипт (qex + graphify), `.claude/logs/post-commit.log` не существует.
2. graphify уже кладёт в граф md-файлы (1662 файла, 6540 узлов `document`), но **связей doc→code почти нет**: 32 ребра md→py на 62206. Тесты в графе — 0 узлов (`.graphifyignore`). Планы, ADR, карты, тесты можно сделать узлами с типизированными рёбрами **без LLM**, постобработкой (раздел 2.4).
3. Лучшая модель данных для роста — **не одна из существующих**. Берём контракт `plans_progress` (JSON со стабильными ключами, коды находок, `--check` с baseline), маркеры из `scripts/sync/registry.py`, обнаружение модулей из `aggregate_context/discover.py`. Ядро — новый маленький пакет (раздел 3.3).
4. qex индексирует markdown (`stats.json`: языки `javascript, markdown, python`), но `.ignore` исключает `docs/` и `**/plans/`. Облако без Ollama: векторы — **необязательный слой**, реестр от них не зависит (раздел 4).
5. HTML: один путь — **собственный генератор на stdlib** из реестра, статические страницы без CDN. mkdocs отвергаем, pdoc не подходит (раздел 5).
6. Универсальность: ядро (схема узлов/рёбер, экстракторы git/md/plans/modules, сборка, гейты, HTML) — в seed; Inspector-адаптер — тонкий `registry.toml` + 3–4 плагина-экстрактора (раздел 6).

---

## 1. Инвентарь хуков

Команды: `ls .git/hooks`, `cat .git/hooks/*`, разбор `.claude/settings.json` скриптом на Python, `cat .github/workflows/ci.yml`, `cat .pre-commit-config.yaml`.

### 1.1 Git-хуки (`.git/hooks/`, **не версионируются**)

| Хук | Триггер | Что делает | Цена | Linux/облако |
|---|---|---|---|---|
| `commit-msg` | каждый commit | `python scripts/validate_commit/validate_commit.py "$1"`: Conventional Commits + `Why:`/`Layer:` | доли секунды | В клоне из GitHub **отсутствует**: `.git/hooks` не клонируется. Ставится `bash scripts/validate_commit/install_hook.sh` |
| `post-commit` (ручной, 108 строк) | каждый commit | фон: `graphify update .` (если есть `graph.json`), затем qex reindex (только если есть бинарь и Ollama) | graphify: без LLM, время не мерил; qex: ~7 мин на дельту 4 дня (root CLAUDE.md, замер 2026-08-31) | graphify — если установлен. qex в облаке пропустится сам (`Ollama not reachable`). Локальный файл, не в репо |
| `pre-commit` (от pre-commit.com) | commit | `.pre-commit-config.yaml`: trailing-whitespace, end-of-file-fixer, check-yaml/toml, merge-conflict, large-files 500 КБ, debug-statements, ruff + ruff-format, bandit | секунды | Да (Python). Ставится `pre-commit install` |
| `pre-push` (от pre-commit.com) | push | pyright (advisory, `\|\| true`) | десятки секунд | Да. `scripts/hooks/pre-push` (sentrux check + gate) — отдельный файл, ставится `scripts/install_pre_push_hook.sh`; sentrux без бинаря пропускается |
| `post-commit.bak-before-graphify` | — | резервная копия | — | — |

**Находка 1.** В репо есть **правильный** диспетчер `core/hooks/git/post-commit.sh` с контрактом «одна часть = один файл `post-commit.d/<имя>.sh`», фоном, fail-open, логом с ротацией 1 МБ, пропуском linked worktree. Части: `mcp-graphify/.../graphify-update.sh`, `mcp-qex/.../qex-reindex.sh`. Но **установлен старый ручной скрипт**, а не диспетчер. Реестр должен стать ещё одной частью `registry-update.sh`; это работает только после замены `.git/hooks/post-commit` диспетчером.

**Находка 2.** Git-хуки локальны. В облачной сессии (клон с GitHub) ни одного из них нет. Значит всё, что обязано держать актуальность, дублируется в **CI** (`.github/workflows/ci.yml`) — иначе в облаке гарантий нет.

### 1.2 Хуки Claude Code (`.claude/settings.json`, собираются из `.claude/plugins/*/…`)

Исходники хуков — bash-скрипты в `.claude/plugins/<id>/hooks/`. `plugin.json` у плагинов лежит в `.claude-plugin/`, а `.claude/plugins/*/plugin.json` нет (команда `ls .claude/plugins/*/plugin.json` пуста); хуки собраны в `settings.json`.

| Событие | Matcher | Скрипт | Таймаут, с | Назначение |
|---|---|---|---|---|
| SessionStart | — | `core/session-health-check.sh`, `session-plan-status.sh`, `session-project-map.sh`, `mcp-health-check.sh`, `session-memory-banner.sh`, `observability/agent-journal.sh` | 5–10 | баннер здоровья, статус плана по ветке (через `validate_commit.py --resolve-plan`), карта проекта, MCP, память, журнал |
| PreToolUse | Bash | `validate-safe-command.sh` (30), `protect-branch.sh` (5) | | запрет опасных команд, запрет commit в main |
| PreToolUse | Edit\|Write | `protect-readonly.sh` | 5 | защита read-only зон |
| PreToolUse | `*` | `agent-context-ceiling.sh` | 5 | потолок контекста агента |
| PreToolUse | WebSearch\|WebFetch | `web-search-routing.sh` | 5 | маршрутизация поиска |
| PreToolUse | Agent\|Task | `dev/lint-brief.sh` | 10 | линт брифа субагента |
| PostToolUse | Edit\|Write | `doc-size-guard.sh` (10), `autofix-text.sh` (10), `lang-python/autoformat-python.sh` (15) | | размер md, автоформат |
| PreCompact / PostCompact | — | `precompact-context-save.sh`, `restore-context.sh` | 5 | сохранение контекста |
| SubagentStop | — | `subagent-stop-gate.sh` (300), `agent-journal.sh` | | `pre_report_gate.py` для developer/teamlead/junior/debugger, лимит 2 блокировки |
| SubagentStart | — | `agent-journal.sh` | 5 | журнал `data/team-journal.jsonl` |
| TaskCompleted / TeammateIdle | — | `agent-teams/team-task-completed-gate.sh` (150), `team-teammate-idle-gate.sh` (15) | | ruff+pytest по изменённым файлам, незакоммиченная работа |

Всего 23 привязки хуков. **Linux/облако:** все — `bash` + `python`, пути через `${CLAUDE_PROJECT_DIR}`. Они лежат в репо и поэтому **доезжают в облачную сессию**, если там есть bash и Python (не проверено). Это единственный механизм «хука» в облаке, и он срабатывает на **события агента**, а не на git-коммит. Следствие: триггер реестра в облаке = `SessionStart` (восстановить) + `Stop`/`TaskCompleted` (проверить) + CI на push.

### 1.3 CI (`.github/workflows/ci.yml`, один файл)

Триггеры: push в main, pull_request, cron `17 2 * * *`, workflow_dispatch. Задания: `lint` (ruff, advisory), `validate` (`scripts/validate.py`, блокирует), `tests` (framework, headless, `QT_QPA_PLATFORM=offscreen`, ~3800 тестов ~90 с), `examples-smoke`, `backend-ctl-nightly` (только по расписанию). Все на `ubuntu-latest` с `uv sync`. **Gate-ы на планы уже в CI через `validate.py`** (проверка 7: `plans_progress --check --baseline`) и на ADR (`scripts.sync --check`). Заданий для реестра, графа, ссылок, `docs_verify` — нет.

Вывод: хребет «хук → проверка» существует в трёх несвязанных местах (git-хуки, хуки Claude, CI) с разными наборами проверок. Единый реестр должен вызываться из всех трёх **одной командой**, чтобы не было трёх версий правды.

---

## 2. graphify как реестр

Команды: чтение `graphify-out/graph.json` (55.5 МБ, не в git: `graphify-out/` в `.gitignore`, `git ls-files graphify-out` = 0), `mcp__graphify__god_nodes/get_node/get_neighbors`, `graphify --help` (версия 0.9.26).

### 2.1 Схема

Верхний уровень: `directed:false, multigraph:false, graph, nodes[37747], links[62206], hyperedges[143], built_at_commit`. `built_at_commit` — готовый маркер свежести.

Узел: `id, label, file_type, source_file, source_location ("L12" или null), community, community_name, norm_label, _origin ("ast" или нет), rationale (307)`. Ребро: `source, target, relation, confidence (EXTRACTED/INFERRED/AMBIGUOUS), confidence_score, weight, source_file, source_location, context (25448), _origin`.

`file_type`: `code` 17500, `rationale` 12264, `document` 6610, `concept` 1373. Рёбра `relation` (16 видов): `rationale_for` 11504, `references` 9628, `method` 9301, `contains` 9218, `calls` 9123, `imports` 6105, `imports_from` 2190, `uses` 1430, `re_exports` 1070, `inherits` 1057, `indirect_call` 510, `conceptually_related_to` 481, `shares_data_with` 265, `implements` 160, `semantically_similar_to` 145, `cites` 19.

### 2.2 Что в графе есть по документам

| Что | Факт (команда: Python по `graph.json`) |
|---|---|
| Узлы с `source_file` на `.md` | 9571 в 1662 файлах |
| Из них `_origin=ast` (детерминированно, без LLM) | 5968, все `file_type=document`: узел файла + узел на каждый заголовок, ребро `contains` md→md (5270). Пример: `plans/layer-render/*` — 114 узлов, все `ast` |
| Из них без `_origin` (LLM-проход) | 3742: `concept` 1335, `rationale` 1100, `code` 596, `document` 572 |
| Цена LLM-прохода | `graphify-out/cost.json`: 2026-08-27, 335 500 входных + 42 400 выходных токенов на 1031 файл; затем 62 000 + 11 000 на 16 файлов |
| Планы | 1974 узла в 283 файлах `plans/` |
| Тесты | **0 узлов** (`.graphifyignore`: `**/tests/`, `**/test_*.py`) |
| Рёбра doc→code | md→py: 32 (27 `references/EXTRACTED`, 5 `INFERRED`); plans→py: **1** |
| Рёбра md→md | `references` 2912 (ссылки), `contains` 5270 |

### 2.3 Пример «идентичность разорвана»

`get_neighbors("multiprocess_framework/modules/router_module/README.md")` (MCP) вернул `references → RouterManager, QueueChannel, RouterAdapter, AsyncSender` с `[EXTRACTED]`. Проверка в `graph.json`: все четыре цели — узлы `file_type=concept` с `source_file=…/router_module/README.md`. Это **не** класс `RouterManager` из кода, а одноимённое «понятие», рождённое LLM из README. Граф выглядит связным, но документ с кодом не соединён. `god_nodes` (SchemaBase 320, PluginContext 253, BackendDriver 229…) — все код: документы в верхушку не попадают.

### 2.4 Могут ли план, ADR, карта, тест стать узлами с типизированными рёбрами

Да, но **не конфигом graphify**. Конфиг (`.graphifyignore`) только включает и выключает файлы: типов рёбер `plan→touches→module` в нём нет. Три способа, по возрастанию цены:

| Способ | Что даёт | Цена | Вердикт |
|---|---|---|---|
| A. Конфиг graphify | включить `tests/` (убрать из `.graphifyignore`) | граф раздувается; `**/tests/` исключён сознательно («плоская структура») | не берём |
| B. Постобработка `graph.json` + git + файлы (детерминированно) | узлы plan/task/adr/commit/test/module и рёбра `touches`, `covers`, `tests`, `decides`, `closed_by`, `depends_on` | нулевая в токенах, секунды-минуты CPU | **берём** |
| C. LLM-проход graphify | `concept`/`rationale`, `semantically_similar_to` | ~335k токенов на ~1000 файлов; в облаке ($250) возможен, но нестабилен: имена сообществ дрейфуют (root CLAUDE.md) | только по запросу, не в хребте |

Как строить рёбра способом B (все — детерминированные правила с полем `evidence`):

- `commit —refs→ plan`: из `%B` коммита строка `^Refs:`; **ловушка: `git log --format=%(trailers:key=Refs)` теряет большую часть**. Замер: на `-n200` разбор git даёт 0 из 200, а `git log -n200 --format=%B | grep -c '^Refs:'` = 198; на всей истории git-парсер даёт 881 коммит, regex по `%B` — 3827 строк `Refs: …plans/…`. Парсить своим regex (как `validate_commit.py`), не trailers git. Причину расхождения не выясняла.
- `commit —touches→ module`: `git log --name-only` (на 4492 коммита 0.7 с) + карта «путь → модуль» из обнаружения модулей. Транзитивно `plan —touches→ module` через `Refs`.
- `task —closed_by→ commit`: хеш в `[DONE … hash]` строки задачи (формат уже парсит `plans_progress`).
- `doc —covers→ module/file`: (1) по расположению: `<module>/README|STATUS|DECISIONS.md` покрывают `<module>`; (2) явно: поле `covers:` во frontmatter карт `docs/maps/*.md`; (3) по именам: заменить узел-`concept` `RouterManager` на ребро к узлу кода по точному совпадению `norm_label` (разрешитель, ~100 строк).
- `test —tests→ module`: AST-скан импортов тестов (`scripts/arch_graph/ast_graph.py` уже умеет AST-граф импортов фреймворка, тесты исключены; нужен обратный режим).
- `adr —decides→ module`: код `ADR-BM-001` → модуль через `module_code` (`scripts/sync/adr_modules.py` уже строит эту таблицу).
- `module —depends_on→ module`: агрегация `imports/imports_from` графа graphify по модулю или `ast_graph.json`.

---

## 3. Генераторы скриптов: вход, выход, годность для реестра

Объёмы — `git ls-files … | xargs cat | wc -l` (включают тесты, где они есть).

| Скрипт | Вход | Выход | Кормит реестр? |
|---|---|---|---|
| `scripts/sync` (`python -m scripts.sync [--check]`) | `DECISIONS.md` фреймворка и модулей + ручной `_adr_layers.py` | правит разделы между маркерами | Да как **механизм**: `registry.py` (`SyncModule`, `replace_between_markers`, `--check` с diff). ADR-парсер переиспользуем |
| `scripts/aggregate_context` | папки с `CONTEXT.md`/`DECISIONS.md` (`discover.py`) | сводка между маркерами | Механизм обнаружения модулей. **Мёртв здесь**: `CONTEXT.md` нет нигде. Уже в seed (`template/plugins/core/scripts/aggregate_context`) |
| `scripts/plans_progress` (2150 строк, 48 файлов с тестами) | `plans/**`, `ORDER.md`, `git worktree` | `--json` (план, задачи, статусы, `after`, `ready`, `dep_cycle`, `lane`, `tier`), `--html`, `--check`, `--who` | **Лучший источник узлов plan/task** и лучший пример контракта |
| `scripts/plans_ledger.py` (3266 строк) | `plans/README.md` как таблица | ledger, жизненный цикл plan→Refs→архив | Источник статусов ACTIVE/DONE/ARCHIVED (в seed не найден); пересекается с `plans_progress` (два парсера планов — дубль) |
| `scripts/docs_verify` | 14+ документов наблюдаемости | 19 проверок «утверждение = код», exit 0/1/2 | **Образец гейта «документ не врёт»**; узкий (только наблюдаемость). Обобщаем в `verifies:` |
| `scripts/channel_map`, `message_contracts` | AST кода | таблицы каналов/схем | Экстракторы `channel`/`schema` узлов — Inspector-адаптер |
| `scripts/code_stats`, `test_ratio` | файлы | счётчики | Атрибуты узла `module` (loc, tests) |
| `scripts/link_check` | md-ссылки (`link_check.toml`) | список битых | Готовый экстрактор рёбер `doc→doc` и гейт «ссылка жива». В seed есть |
| `scripts/claude_md_audit` | `.claude/` | находки по агентам/командам | Экстрактор узлов agent/skill/command; в seed есть |
| `scripts/validate.py` (320 строк) | модули, README/STATUS, ADR-sync, планы | exit 0/1 | **Единый вход гейтов** — его и вызывает CI; реестр подключаем проверкой №8 |
| `scripts/graph_slice` | `graph.json` | «кого заденет модуль» | Первый потребитель реестра; сейчас читает граф напрямую |
| `scripts/validate_commit` | сообщение коммита, ветка | вердикт, `--resolve-plan` | Единственный разрешитель «ветка → план»; реестр обязан использовать его, а не писать второй |
| `scripts/todo_inventory`, `secrets_audit`, `observability_seal` | код | отчёты | Побочные; вне хребта |
| `make diagrams` (pyreverse/pydeps) | код | `docs/diagrams/{classes,deps}` | Выход, не вход: диаграммы — **представления** реестра |

### 3.1 Вопрос «какой скрипт растёт в реестр»

- `plans_progress`: лучшая модель данных **про планы** (стабильные ключи JSON, коды находок, baseline, `--check`, обнаружение циклов зависимостей, учёт worktree). Минусы: один файл 2150 строк, привязан к формату `ORDER.md` и русским заголовкам «Порядок выполнения», узел только двух видов (plan, task).
- `aggregate_context`: самый универсальный по замыслу и уже в seed, но 745 строк, не содержит графа и мёртв.
- `sync/registry.py`: хороший механизм маркеров, но модели данных нет.

**Рекомендация: не растить ни один.** Ядро — новый пакет `kos` (рабочее имя; один каталог `scripts/kos/` → в seed `plugins/core/scripts/kos/`): `schema.py` (Node/Edge), `extract/*.py` (по одному на источник), `build.py`, `check.py`, `render/*.py`. Из старого берём: **формат контракта** `plans_progress` (JSON, коды находок, baseline-файл), **маркеры** `sync/registry.py`, **обнаружение** `aggregate_context/discover.py`. `plans_progress` целиком становится экстрактором `plans` (его `--json` — вход, ничего не переписываем на первом этапе). Дубль `plans_ledger` ↔ `plans_progress` — снять отдельным решением, после реестра.

### 3.2 Схема реестра (минимум)

```
node: {id, kind, path, anchor, title, status, attrs{}, src_sha, extractor}
edge: {src, rel, dst, evidence, confidence, extractor}
kind: module | file | doc | adr | plan | task | commit | test | rule | diagram | agent | skill
rel : contains | covers | touches | tests | decides | closed_by | refs | depends_on | links | verifies | supersedes
```

`id` стабилен и выводится из пути/якоря (`plan:layer-render#6.3`, `module:Services/layer_render`), а не из хеша содержимого. `evidence` — строка-причина («Refs: trailer в 6738af1», «README рядом»). `confidence`: `exact` (по правилу) или `inferred`. Реестр **не хранится в git** (как `graph.json` и `data/plans_progress.html`): производная, строится из клона за секунды-минуты; в git лежат схема и конфиг. Иначе параллельные агенты получат конфликты слияния в генерируемом файле.

---

## 4. qex и векторный поиск

Факты: `~/.qex/projects/*/stats.json`; `.claude/plugins/mcp-qex/README.md`; `.ignore`.

- Индекс текущего проекта `Inspector_bottles_f2281d7d`: 52443 chunks, языки `javascript, markdown, python`, дата каталога 2026-10-01. **markdown индексируется.** Чанки — по tree-sitter AST (для md — по структуре).
- Но `.ignore` — белый список шести каталогов (`multiprocess_framework/, multiprocess_prototype/, Services/, Plugins/, backend_ctl/, scripts/`) и `**/plans/` исключён. Значит в qex есть README/STATUS/DECISIONS модулей, но **нет `docs/` (1024 md) и `plans/` (459 md)**. Для «учебника» это главный корпус.
- Плотные векторы — Ollama (`qwen3-embedding:0.6b-qex`, 1024) и usearch/brute-force под `~/.qex/`. Нужен Ollama и бинарь Rust. В облаке ($250, Linux, без Ollama) этого нет.

Как векторный поиск встраивается в реестр:

1. Реестр хранит **ключ чанка**: `node.id` + `anchor` (заголовок md) — стабильный адрес секции. Это «таблица соответствия» чанк→узел, единственное, что нужно поиску от реестра.
2. Поисковый бэкенд — сменный плагин с двумя реализациями: **BM25-only** (stdlib/SQLite FTS5, работает везде, в облаке по умолчанию) и **dense** (qex/Ollama локально). Реестр выдаёт `chunks.jsonl` (`node_id, anchor, text, src_sha`); бэкенд считает векторы по нему.
3. Свежесть: чанк пересчитывается, если `src_sha` изменился (qex сам делает Merkle-diff по файлам; для реестра достаточно сравнить `src_sha`).
4. В расширении `.ignore` добавить `docs/` и `plans/` — **решение владельца** (вопрос 3), так как это увеличит индекс и время реиндекса.
5. Запросы по-английски лучше (root CLAUDE.md); для русского учебника BM25 по точным терминам работает без эмбеддера — на первом этапе его хватает.

---

## 5. HTML-вывод

Что есть (`git ls-files '*.html'`, `ls data`):

| Файл | Как сделан | Проблема |
|---|---|---|
| `data/plans_progress.html` (472 КБ, не в git) | `plans_progress.py --html`, stdlib, **без внешних ресурсов** | работает офлайн; только планы |
| `docs/diagrams/lifecycle/lifecycle-system.html` (37 КБ), `layer-render/editor-system.html` (33 КБ) | ручные, mermaid с `cdn.jsdelivr.net/npm/mermaid@11.4.1` | нужна сеть; ручные → устаревают |
| `docs/audits/2026-09-04_management-brief.html`, `plans/line-sim/vision.html`, `docs/diagrams/wiring/id3013-wiring.html` | ручные, Google Fonts | то же |
| `docs/diagrams/architecture.mmd` | ручной Mermaid, правка 2026-05-14 | устарел (по брифу) |

Варианты:

| Вариант | Зависимости | Seed-переносимость | Минусы |
|---|---|---|---|
| mkdocs (+тема, плагины) | `mkdocs`, тема, поиск; сборка 1500+ md | средняя: ещё один пакет и `mkdocs.yml` на проект | не знает про узлы реестра (план/задача/покрытие); граф и статусы — отдельными плагинами |
| pdoc | `pdoc` | — | **только API-доки из docstring**; планы, ADR, карты не покрывает. Отвергаем |
| **Собственный генератор на stdlib** | 0 обязательных; `markdown-it-py` — необязательный (в `uv.lock` уже есть как зависимость `rich`; без него тело md выводится как `<pre>`) | высокая: один каталог скриптов, уже доказано `plans_progress --html` | пишем сами шаблоны страниц |

**Выбор: собственный статический генератор** `scripts/kos/render/` → каталог `site/` (не в git; публикуется как артефакт CI / GitHub Pages). Причина одна: страницы строятся **из реестра** (модуль → его план, ADR, тесты, карта, коммиты; план → задачи → коммиты), а не из дерева md. mkdocs этого не умеет без плагина, равного половине генератора. Страницы: `index`, `modules/<id>`, `plans/<slug>`, `adr`, `docs/…` (рендер md), `stale` (долг свежести), `graph` (инлайн-SVG, без CDN). Диаграммы Mermaid — `<pre class=mermaid>` + локальная копия скрипта при наличии, иначе исходник текстом. Существующий `plans_progress --html` остаётся страницей `plans/` без переписывания.

---

## 6. Универсальность для `claude_seed`

Найдено в `D:\PROJECT_INNOTECH\claude_seed`: seed (по `git ls-files`) уже поставляет `aggregate_context`, `plan_file_map.py` (в `plugins/core/scripts/`), `link_check`, `claude_md_audit`, `validate_commit`, `graph_slice` + плагин `mcp-graphify`. **Нет:** `plans_progress`, `docs_verify`, реестра. `plans_ledger.py` в seed `git ls-files` не найден (в этом репо он лежит в `.claude/plugins/core/scripts/` и `scripts/`; docstring говорит «доставляется проектам» — расхождение не разбирала). Seed устроен как `src/claude_kit_claude/template/plugins/<id>/…`; диспетчер post-commit и части — часть плагинной модели.

### 6.1 Ядро (любой репозиторий) — `plugins/core/scripts/kos/`

| Компонент | Что делает | Растёт из |
|---|---|---|
| `schema` | Node/Edge, `id`-правила | **новое** |
| `extract/git` | коммиты, `Refs:`/`Layer:`/`Why:` (свой regex), файлы | `validate_commit` (разбор trailers) |
| `extract/markdown` | md → узлы doc/adr, заголовки, ссылки, frontmatter `covers:`/`verifies:` | `link_check` + `sync` ADR-парсер |
| `extract/plans` | план/задача/статус/зависимости | `plans_progress --json` (вход как есть) |
| `extract/modules` | модуль = папка с README/STATUS/interfaces/DECISIONS | `aggregate_context/discover.py` |
| `extract/tests` | тест→модуль по AST-импортам и пути | `arch_graph/ast_graph.py` |
| `extract/claude` | agent/skill/command | `claude_md_audit` |
| `extract/graphify` | необязательный: символы, импорты модуль→модуль | `graph_slice` (чтение `graph.json`, проверка `built_at_commit`) |
| `build` | сборка реестра, инкрементальная по `src_sha` | **новое** |
| `check` | гейты, `--baseline`, коды находок | контракт `plans_progress --check` |
| `render` | статические страницы | `plans_progress --html` (стиль/офлайн) |
| `blocks` | генерируемые блоки в рукописных md | `sync/registry.py` маркеры |

### 6.2 Адаптер проекта — `registry.toml` + плагины

| Что | Inspector-специфика |
|---|---|
| Корни модулей | `multiprocess_framework/modules/`, `Services/`, `Plugins/` |
| Яруса модулей | `docs/MODULE_TIERS.md` (core/optional/frozen) → атрибут `tier` |
| Слои | `framework → Services → Plugins → prototype` (в `.sentrux/rules.toml`) |
| Экстракторы доменов | `channel_map`, `message_contracts`, `line_sim` инструменты |
| Формат плана | `ORDER.md`, поле `После:` |
| Обязательные поля | `Layer:` из `.claude/commit-layers.txt` |

Критерий универсальности: на пустом репо с `plans/` и `docs/` ядро строит реестр без `registry.toml`; модули, ярусы, домены — только через адаптер.

---

## 7. Предлагаемая архитектура

### 7.1 Поток данных

```
 правка файла / commit
   │
   ├─ [локально] commit-msg: validate_commit (trailers, Refs → план существует)
   ├─ [локально] pre-commit: ruff/форматтеры (как сейчас)
   ▼
 git commit ──► post-commit ДИСПЕТЧЕР (core/hooks/git/post-commit.sh)  [установить вместо ручного]
                  ├─ part: graphify-update   (есть)
                  ├─ part: qex-reindex       (есть, пропускается без Ollama)
                  └─ part: registry-update   (НОВАЯ: kos build --incremental, ≤ секунды, без LLM)
                                 │
                                 ▼
                         РЕЕСТР  (build/registry/*.jsonl + registry.db, НЕ в git)
                                 │
          ┌──────────────┬───────┴────────┬───────────────┐
          ▼              ▼                ▼               ▼
     kos check      kos render       chunks.jsonl     graph_slice,
     (гейты)        (site/ HTML)     → qex / BM25     plans_progress,
                                                      session-баннеры
 push ──► CI (ubuntu): validate.py + kos build --full + kos check + kos render → артефакт/Pages
 облачная сессия: SessionStart → kos build --incremental; TaskCompleted/Stop → kos check --changed
```

Правило: **одна команда** `python -m scripts.kos {build|check|render}`; хуки, CI и агент зовут её, а не свои копии логики.

### 7.2 Компоненты: растёт из / новое

| Компонент | Из чего растёт | Новое |
|---|---|---|
| Диспетчер post-commit | `core/hooks/git/post-commit.sh` + части | часть `registry-update.sh`; установка диспетчера вместо ручного скрипта |
| Сборка реестра | экстракторы из таблицы 6.1 | `schema`, `build`, постобработка graphify (разрешитель имён doc→code) |
| Гейты | `docs_verify` (идея), `validate.py` (вход), `plans_progress --check` (форма) | `kos check` + проверка №8 в `validate.py` |
| Генерируемые блоки в рукописных картах | `sync/registry.py` | блок «Модули и публичное API» в `docs/maps/*.md` из AST вместо ручной таблицы |
| Свежесть | `built_at_commit` graphify, `src_sha` | метрика «долг свежести» |
| HTML | `plans_progress --html` | `render/` страниц по реестру |
| Поиск | qex/Ollama | `chunks.jsonl` + BM25-бэкенд для облака |

### 7.3 Как реестр остаётся актуальным при параллельных агентах

Три уровня, от дешёвого к жёсткому:

1. **Строится, а не пишется.** Производные факты (список модулей и API, статусы задач, покрытие) — только генерация между маркерами; рукописное остаётся рукописным (инварианты, решения, «почему»). Это закрывает класс «карта устарела»: `docs/maps/layer_render.md` держит номера строк `effects.py:261` вручную. Замена: якорь по имени символа, проверяемый `kos check`.
2. **Гейт «ссылка/утверждение жива»** — жёсткий, deterministic: битая ссылка (`link_check`), `Refs:` на несуществующий план, документ без владельца (узел без входящего `covers`), `verifies:` не сошёлся (обобщение `docs_verify`). Блокирует CI; baseline-файл как у `plans_progress`, чтобы не краснить за старый долг.
3. **Долг свежести** — мягкий, число: для каждого `doc —covers→ X` считать коммиты, тронувшие X **после** последней правки документа. Показывается страницей `stale` и баннером SessionStart; блокировать нельзя (много ложных срабатываний до калибровки).

Параллельные агенты не конфликтуют: реестр вне git, у каждого клона/worktree своя копия; единственный общий «писатель» — CI.

### 7.4 Что в первую очередь (минимальный жизнеспособный путь, без оценок времени)

1. Схема + экстракторы `git`, `plans` (обёртка `plans_progress --json`), `modules`, `markdown` → `registry.jsonl`; `kos check` с тремя жёсткими гейтами. Без graphify, без qex, без HTML.
2. Часть `registry-update.sh` + замена `.git/hooks/post-commit` диспетчером; job `registry` в CI.
3. `render/`: страницы модуль/план/stale.
4. Разрешитель doc→code на graphify; блоки `docs/maps/*` из AST.
5. `chunks.jsonl` + BM25; расширение `.ignore` qex (по решению владельца).

---

## 8. Ветка на модуль (совет по вопросу владельца)

Не моя ось, один абзац. **Ветка на модуль — нет.** Модуль не единица работы: задача (`Task X.Y`) обычно трогает 2–4 модуля, а правка контракта идёт через слои `framework → Services → Plugins → prototype` вместе. Долгоживущие ветки на модуль дадут конфликты на `interfaces.py` и слоёв, а связь «план ↔ ветка» (`<type>/<slug>`, `Refs:`) уже нормализована. Модульность дают **узлы реестра** (`module` + рёбра `touches`): запрос «все коммиты и планы по модулю X» отвечается без веток. Остаётся ветка на план/задачу, как сейчас.

---

## 9. Что я оставила открытым и что ненадёжно в моей работе

- **Не запускала** `plans_progress --json` (30 с), `graphify update`, `kos`-прототипа нет. Оценки «секунды» для `registry-update` — по замеру `git log --name-only` (0.7 с на 4492 коммита), а не по прогону сборки. Время `graphify update` не мерила.
- **Хуки Claude в облаке:** вывод «доезжают, если есть bash и Python» — по чтению `settings.json`, не по запуску в облачной среде. Поведение `CLAUDE_PROJECT_DIR` и таймаутов на Linux не проверено.
- **graphify на Linux/в облаке** не проверен (версия 0.9.26; ставится через uv tool). Если его нет, реестр обязан работать без него (шаг 1 так и задуман).
- **Расхождение `%(trailers)` git и regex по `%B`** измерено, причина не найдена (трейлеры стоят в последнем абзаце вместе с `Co-Authored-By`). Для реестра это решено выбором своего regex, но объяснения у меня нет — не цитировать как «потому что».
- «Тесты в графе 0 узлов» — из `file_type`/`source_file` и `.graphifyignore`; отдельной проверки того, что в графе нет ни одного пути с `/tests/`, я не делала (проверила только `'/tests/' in source_file` → 0).
- Сводка стоимости LLM-прохода graphify взята из `cost.json` (2026-08-27); сколько файлов с тех пор добавилось без семантики — не считала (по плану `layer-render` 114 узлов все `ast`, значит новые файлы получают только заголовки).
- Утверждение «в seed нет `plans_progress`/`docs_verify`» — по `git ls-files` seed (866 файлов), не по рабочему дереву seed.
- Оценка «mkdocs не умеет узлы реестра» — по общему знанию, без попытки сборки.
- Схема 3.2 и имя `kos` — предложение, не проверено на реальном объёме (1483 md в `docs/`+`plans/`).
- Не смотрела `.sentrux/rules.toml` и MODULE_TIERS: как адаптер их подключать — гипотеза.

---

## 10. Вопросы владельцу (с рекомендацией)

1. **Реестр хранить в git?** Рекомендую: **нет**, только схема и конфиг; строить в CI и локально. Иначе при параллельных агентах — конфликты слияния в генерируемом файле.
2. **Установить диспетчер post-commit вместо ручного `.git/hooks/post-commit`?** Рекомендую: **да**. Он уже в плагине `core`, держит части graphify/qex и даст место реестру. Цена: ручной скрипт заменяется; поведение graphify/qex сохраняется частями.
3. **Добавить `docs/` и `plans/` в qex `.ignore`?** Рекомендую: **да, после первого шага** (реестр выдаёт `chunks.jsonl`). Корпус для «учебника» там; цена — рост индекса и время реиндекса (не мерила).
4. **Долг свежести — блокировать или только показывать?** Рекомендую: **только показывать** 2–3 недели, потом выбрать порог по данным; жёстко блокировать лишь битые ссылки, `Refs:` на несуществующий план и `verifies:`.
5. **Что делать с дублем `plans_ledger.py` ↔ `plans_progress.py` (3266 + 2150 строк, два парсера планов)?** Рекомендую: **сначала реестр поверх `plans_progress`, затем отдельным решением слить**. Не трогать до первого рабочего реестра, чтобы не смешивать два риска.
