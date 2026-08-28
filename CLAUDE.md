# Inspector_bottles — Проектный контекст

## Проект

Фреймворк для приложений с **многопроцессной архитектурой** (процессы-воркеры, разделяемая память, очередь задач).
На его основе — **прототип** системы инспекции дефектов через камеру (PySide6, OpenCV, детекция брака).

## Архитектура

- **Оркестрация:** `SystemLauncher` → `ProcessManagerProcess` → дочерние процессы (`ProcessModule`)
- **IPC:** `Message` / `MessageAdapter` → `RouterManager` → `shared_resources_module` (pickle-safe)
- **Внутри процесса:** `CommandManager`, `worker_module`, `LoggerManager` / `ErrorManager` / `StatsManager` (база `channel_routing_module`), `RouterManager`
- **Данные/конфиг:** `data_schema_module` (`SchemaBase`), `config_module` + `ConfigStore`
- **Состояние:** `state_store_module` — реактивное дерево (StateStoreManager + StateProxy + glob-подписки)
- **Pipeline-исполнители:** `chain_module` — DAG/Chain engine (ChainRunnable, DagRunnable, WorkerPoolDispatcher)
- **GUI:** `frontend_module` (PySide6), схемы регистров в приложении. Виджеты v3 сгруппированы по доменам (`chrome/`, `sources/`, `recipes/`, `processing/`, `settings/`, `pipeline/`, `tabs_setting/`, `base/`) — детали в [`docs/refactors/2026-04_widgets_reorg.md`](docs/refactors/2026-04_widgets_reorg.md).
- **Роутинг:** НЕ путать **имя процесса** (`targets`, `send_message`) и **канал Router** (`FieldRouting.channel`, `msg["channel"]`). См. `ROUTING_GLOSSARY.md`
- **Всего модулей в `multiprocess_framework/modules/`:** 27 (`sql_module` вынесен в `Services/sql`, Phase 4.1; `recipe` — крыша над рецептами, C1/ADR-RCP-001; `app_module` — Ф5.11; `telemetry_readmodel_module` — ADR-136). Ярусная карта core/optional/frozen — [`docs/MODULE_TIERS.md`](multiprocess_framework/docs/MODULE_TIERS.md) (сверяется контракт-тестом). Карта ответственности и границы модулей — [`docs/MODULES_RESPONSIBILITY_MAP.md`](multiprocess_framework/docs/MODULES_RESPONSIBILITY_MAP.md). См. также [`MODULES_STATUS.md`](multiprocess_framework/MODULES_STATUS.md), [`Services/STATUS.md`](Services/STATUS.md), [`docs/MODULES_OVERVIEW.md`](multiprocess_framework/docs/MODULES_OVERVIEW.md).

## Ключевые пути

| Что | Путь |
|-----|------|
| **АКТИВНЫЙ прототип** | `multiprocess_prototype/` ← **только сюда вносить app-specific изменения** |
| Фреймворк | `multiprocess_framework/` |
| Прикладные сервисы (sql, hikvision, …) | `Services/` ← Phase 4 carve-out |
| Vocabulary плагинов (19 шт., reuse между приложениями) | `Plugins/` ← Phase 5 carve-out (см. ADR-120) |
| Документация фреймворка | `multiprocess_framework/docs/` (`MODULES_OVERVIEW.md`, `MODULE_CONTRACTS.md`, `DIAGRAMS.md`) |
| Диаграммы архитектуры | `docs/diagrams/` (Mermaid, PlantUML, SVG — diagrams-as-code) |
| Конструктор-blueprint фреймворка (25 модулей) | [`multiprocess_framework/docs/CONSTRUCTOR_BLUEPRINT.md`](multiprocess_framework/docs/CONSTRUCTOR_BLUEPRINT.md) |
| Точка входа v3 | `multiprocess_prototype/run.py` |
| Регистры приложения v3 | `multiprocess_prototype/registers/` |
| Конспект правил | `docs/claude/FRAMEWORK_RULES_EXTRACT.md` |
| Нарратив «конструктор» | `docs/claude/FRAMEWORK_CONSTRUCTOR_OVERVIEW.md` |
| Настройка qex | [`.claude/plugins/mcp-qex/README.md`](.claude/plugins/mcp-qex/README.md) (quick-start), [`SETUP_GUIDE.md`](.claude/plugins/mcp-qex/SETUP_GUIDE.md) (полный) |
| Гайд по sentrux | [`.claude/plugins/mcp-sentrux/README.md`](.claude/plugins/mcp-sentrux/README.md) (метрики, slash-команды, сценарии) |
| Path-scoped правила | [`.rules/`](.rules/) — загружаются при работе с соответствующими файлами |

## История версий и архив

Активный прототип — **`multiprocess_prototype/`** (единственный). Старые v1/v2 директории и снэпшот `multiprocess_prototype_backup/` физически удалены (e128b930, 2026-06; хвосты в конфигах вычищены 2026-07-03), см. git log.

## Стек

Python 3.12 (см. корневой `pyproject.toml`), PySide6 6.10 (Phase 2 завершена 2026-04), OpenCV 4.13, NumPy 2.x | SQLite/PostgreSQL
Ollama, pytest + pytest-qt (`qt_api = pyside6`) | Pydantic v2
Логирование — своё (`logger_module`: `get_std_logger` + LoggerManager процесса). loguru снята в 4.3: писателей мимо разъёма не осталось
ML (Phase 1.5): PyTorch 2.11 + Ultralytics YOLO + ONNX Runtime — extras `[ml]` в pyproject

## Правила проекта

1. **Dict at Boundary** — между процессами только `dict` (`to_dict`/`from_dict`); Pydantic внутри процесса
2. Зависимости через `interfaces.py`; у каждого модуля `README.md`, `STATUS.md`, `tests/`
3. **ADR-решения:**
   - Локальные → `modules/X/DECISIONS.md`
   - Глобальные → `multiprocess_framework/DECISIONS.md`
4. **Тесты:** из корня — `python scripts/validate.py`, `python scripts/run_framework_tests.py`. Ручной pytest — из `` (иначе `ModuleNotFoundError`)
5. Конфиг на границе — dict, внутри Pydantic v2
6. Логи через `ObservableMixin`, пути из env (`MULTIPROCESS_LOG_DIR` / `INSPECTOR_LOG_DIR`)
7. Индекс ADR: `multiprocess_framework/DECISIONS.md` → ссылки на локальные DECISIONS.md
8. **Документация — auto-sync:** при правках `multiprocess_framework/DECISIONS.md` или `multiprocess_framework/modules/*/DECISIONS.md` запусти `python -m scripts.sync` для пересборки сводных разделов («Оглавление», «Модульные решения», «Устарело», «Коды модулей»). CI ловит дрифт через `python scripts/validate.py`. Список синхронизируемых разделов: `python -m scripts.sync --list`.
9. **Слои импортов:** `multiprocess_framework → Services → Plugins → multiprocess_prototype` (composition root). Обратные импорты запрещены и enforced через `.sentrux/rules.toml` (boundaries `framework → prototype/Services/Plugins`, `Services → prototype/Plugins`, `Plugins → prototype`). Плагин знает только `PluginContext` и не должен импортировать `multiprocess_prototype.*` — см. ADR-120.
10. **Commit-сообщения:** Conventional Commits + обязательные trailers `Why:` и `Layer:`. Опциональные — `Refs:`, `Risk:`, `Reversible:`, `Tested:`, `Rejected:`. Шаблон в `.gitmessage`, гайд в [`docs/claude/COMMIT_GUIDE.md`](docs/claude/COMMIT_GUIDE.md), валидирует hook `.git/hooks/commit-msg` (установка `bash scripts/validate_commit/install_hook.sh`). Агенты обязаны генерировать trailers — иначе commit будет отклонён.

## Формат commit-сообщений (для агентов)

Каждый коммит:

```
<type>(<scope>): краткое описание в императиве (кратко, без длинных предложений)

- что сделано (буллетами, файлы/классы/числа тестов)

Why: одна-две строки про мотивацию (не реализацию)
Layer: framework | services | plugins | prototype | docs | scripts | tests | infra | mixed
Refs: plans/<slug>.md, ADR-XXX, PR#NN  (ОБЯЗАТЕЛЬНО если задача из плана; опц. для hotfix)
Risk: low|medium|high — короткое почему  (опц.)
Reversible: yes | migration-needed | no  (опц.)
Tested: scope/N passed, например auth/120  (опц., при изменении кода)
Rejected: альтернатива X — отвергнута, потому что Y  (опц., но ценно)

Co-Authored-By: ...
```

**Обязательны:** `Why:` и `Layer:`. Без них hook отклонит коммит. Полный гайд — [`docs/claude/COMMIT_GUIDE.md`](docs/claude/COMMIT_GUIDE.md). Whitelist'ы значений в [`scripts/validate_commit/validate_commit.py`](scripts/validate_commit/validate_commit.py).

## Plan-Driven Development

Новые планы создаются через `/plan` с единой конвенцией:
- **Slug:** kebab-case, `<домен>-<суть>`, max 40 символов. Хранение: `plans/<slug>.md` (дефолт) или `plans/<slug>/plan.md` (multi-phase)
- **Ветка:** `<type>/<slug>` — автоматически при `/plan`. Стандарт: `feat/`, не `feature/`
- **Refs:** коммит из плана **обязан** содержать `Refs: plans/<slug>.md` (enforce на уровне агентов)
- **Коммиты плана:** создание/закрытие — отдельный `docs(plans):` коммит. Статусы задач — допустимо в коммите кода
- **Статус:** `/plan-status` — прогресс по текущей ветке

Подробности — в [`plans/` конвенциях](.claude/commands/dev/plan.md) и промптах агентов.

## Memory (dual-write)

Проектная память хранится в **двух местах** — локальном (Claude Code) и git-tracked (между машинами):

| Место | Путь | Git | Что хранить |
|-------|------|-----|-------------|
| **Локальная** | `~/.claude/projects/<hash>/memory/` | Нет | Всё: project, feedback, user, reference |
| **Git-tracked** | `docs/claude/memory/` | **Да** | project + feedback (без личных user-записей) |

**Правило dual-write:** при создании/обновлении memory — писать в **оба** места. MEMORY.md индекс — тоже в обоих.

- `docs/claude/memory/` — проектная (project, feedback), синхронизируется через git
- `~/.claude/.../memory/` — + личное (user, reference), остаётся локально
- `.claude/` — универсальная конфигурация, портируется между проектами. Memory здесь **не хранить**

## MCP: qex (семантический поиск)

**qex** = Ollama (`qwen3-embedding:0.6b`) + BM25 (Tantivy) + brute-force dense vectors (`~/.qex/`). `search_code` — гибрид dense+sparse.
Холодный старт: `ollama serve` (или `/cold-start`). Docker/Qdrant не нужны.
Модель сменена с 4b на 0.6b 2026-08-27: 4b не помещалась в 4 ГБ VRAM (0% успешных реиндексов три недели), 0.6b — с запасом.

**Сверка свежести — ПЕРВЫЙ шаг любого обращения к qex, до первого `search_code`.** `mcp__qex__get_indexing_status` → сравнить `last_indexed` с сегодняшним днём. Причина правила: при `indexed: true` и живом `vector_search_available` выдача выглядит здоровой и отвечает уверенно — старым, а о своём возрасте индекс не сообщает.

**Состояние на 2026-08-27: индекс СВЕЖИЙ, пересобран с нуля** (`incremental: false`, 3270 файлов / 43172 чанка, ~62 мин), векторы `1024` / `qwen3-embedding:0.6b` — сверено с `dense/vector_meta.json`, рассинхрона «индекс на одной модели, запросы на другой» нет. Прежняя посылка «индекс живёт устаревшим намеренно» (решение владельца 2026-08-23, когда реиндекс упирался в BM25-половину на часы) **снята**: полный ребилд сжал `tantivy/` с 5.7 ГБ до 127 МБ, и похоже, что тормозили накопленные несмёрженные сегменты, а не qex как таковой. Гипотеза с числами, не факт — скорость инкрементального реиндекса на текущей дельте не мерена, первый же прогон её подтвердит или опровергнет.

- Свежий (дни) — работает qex-first правило ниже.
- Устаревший (недели) — qex остаётся подсказкой «куда посмотреть», источник истины `Grep`/`rg`/чтение файла; номера строк из выдачи перепроверять, а не переписывать. Любые ЧИСЛА (инвентарь «сколько вызывающих») считать только грепом — хит устаревшего индекса в счёт не идёт.
- **Возраст индекса сообщать субагентам в промпте числом.** Сами они его не знают и выдаче верят; проза «проверь сам» слабее даты «индекс от такого-то числа, вот чего он не видел».
- **Смысловые запросы к `search_code` — по-английски, лексикой ближе к коду.** Точные RU-термины BM25 всё ещё ловит нормально (это не зависит от эмбеддера), слабость именно в русском абстрактном перефразе без точных слов — измерено на fencing-тесте (EN точные термины → топ-1, EN перефраз → топ-3, RU перефраз того же вопроса → мимо совсем).

**qex-first правило:** при рефакторинге, анализе «где используется», смене API/IPC-контракта — **сначала `mcp__qex__search_code`**, потом `Grep`. Подробная логика: `/qex-search`.

## MCP: sentrux (архитектурный анализ)

**sentrux** (`brew install sentrux/tap/sentrux`, бинарь `/opt/homebrew/bin/sentrux`) — структурный health-gate. Метрики modularity / acyclicity / depth / equality / redundancy → score 0–10000. Девять MCP-инструментов: `scan`, `health`, `dsm`, `test_gaps`, `check_rules`, `session_start`, `session_end`, `evolution`, `rescan`.

**sentrux-first правило:** при работе с **архитектурой и связями между модулями** (не отдельными строками) — звать sentrux, не qex/Grep:

| Задача | Инструмент |
|--------|------------|
| «Где используется `X`?», поиск по семантике кода | `mcp__qex__search_code` |
| **«Кого заденет правка модуля?»** — границы модуля перед рефакторингом | **`python scripts/graph_slice/graph_slice.py <модуль>`** (slash: `/graph-slice`) — [README](scripts/graph_slice/README.md) |
| «Насколько модули связаны?», поиск циклов | `mcp__sentrux__dsm` |
| Baseline перед рефакторингом → дельта после | `session_start` → правки → `session_end` |
| «Что не покрыто тестами?» перед `/ship` | `mcp__sentrux__test_gaps` |
| Проверка инвариантов (`process_module` не импортирует `frontend_module` и т.п.) | **CLI `sentrux check .`**, НЕ `mcp__sentrux__check_rules` — см. предупреждение ниже |
| Снимок здоровья проекта целиком | `mcp__sentrux__scan` + `health` |

**⚠ `mcp__sentrux__check_rules` даёт зелёный по ЧАСТИ правил и не говорит этого в вердикте.** Замер 2026-08-27 на этом репозитории: MCP-инструмент вернул `"✓ All architectural rules pass"`, `pass: true`, `violation_count: 0` — при `rules_checked: 9` из `total_rules_defined: 39` и примечании free-tier «Checking up to 3 rules». CLI на том же дереве: `sentrux check — 36 rules checked`, `✓ All rules pass`. То есть формулировка «все архитектурные правила проходят» покрывает четверть набора, а 30 правил (включая часть `[[boundaries]]` про слои `framework → Services → Plugins → prototype`) не смотрел никто. **Вердикт о границах слоёв выносить только по CLI**; MCP-инструмент годится как быстрый сигнал, но его «All pass» в ревью не цитировать.

**qex и sentrux ортогональны:** qex отвечает «*где*», sentrux — «*насколько здорово*». Не дублируют. Третья ось — **`/graph-slice`**: «*кого заденет*», граница конкретного модуля из графа graphify (единый граф в `graphify-out/`, отдельных графов на модуль нет). Свежесть графа скрипт печатает сам — устаревший срез за факт не выдавать.

**⚠ Цена бэкендов `--backend=claude-cli` (graphify label и любой инструмент, зовущий `claude` в цикле).** Это НЕ API-вызов, а **полная сессия Claude Code на каждый батч**: в неё грузятся три `CLAUDE.md` + `MEMORY.md` (~22.4k токенов) плюс системный промпт и схемы инструментов — порядка 45–50k на вызов до первого байта полезных данных. Замер 2026-08-27: `graphify label --batch-size=25` = 53 вызова ≈ 2.5 млн входных токенов, почти весь дневной лимит, ради 1316 коротких имён. **Рычаг обратный интуиции: мельчить батчи = множить накладные** (снижение batch-size со 100 до 25 перевело 14 вызовов в 53). Перед запуском считать `вызовов × ~50k` и называть число вслух. Дешевле: `ANTHROPIC_API_KEY` + прямой API, максимальный batch-size, либо локальная генеративная модель. Побочный эффект: порождённая сессия читает проектный `CLAUDE.md` и подчиняется его правилам — имена сообществ вернулись по-русски из-за language policy. Подробности — [`docs/claude/memory/feedback_claude_cli_backend_costs_a_full_session.md`](docs/claude/memory/feedback_claude_cli_backend_costs_a_full_session.md).

**Обслуживание графа graphify.** Инкрементальный `graphify update .` (LLM не нужен) стоит на `post-commit`-хуке рядом с qex-секцией. Он **не чистит** узлы исчезнувших файлов и не переименовывает новые сообщества — накопленный мусор снимает только `graphify update . --force` (замер 2026-08-27: убрал 3 файла-призрака и 51 тест, живший в графе вопреки `.graphifyignore`). `graph.html` не генерируется: лимит визуализации 5000 узлов против наших ~29 тысяч.

**⚠ Имена сообществ graphify — подсказка, а не факт.** Они **переносятся по ID**, а состав сообществ при каждой пересборке сдвигается, поэтому подпись расходится с содержимым тем сильнее, чем дольше живёт граф — и сигнала об этом нет. Замер 2026-08-28, один инкрементальный проход: сообществ стало 1343 против 1320 при нуле заглушек и без запуска именования; `#10 «DI-контейнеры рантайма»` переехало с `settings/_sections.py` на `recipes/tab.py`, сохранив имя; `#22 «Фасад авторизации»` стоит на `adapters/stores/config_store.py`. Часть имён при этом точна и устойчива (`#6 «Каналы Modbus-драйвера»` → `Services/modbus/core/device.py`). **Вывод для ревью: сообщество опознавать по составу узлов, имя в вердикт не цитировать.** Структурные ответы (`god_nodes`, `shortest_path`, `get_neighbors`, `get_node`) от имён не зависят вовсе — на них и опираться. `query_graph` вдобавок обрезается по `token_budget` и уводит лексически (замер: 33 узла из 173, по слову «writer» притянуло GUI-панели) — начинать с `god_nodes`/`get_node`, сужать `context_filter`.

## Slash-команды

46 команд в 7 категориях. Список (упорядочено по namespace):

| Категория | Ключевые команды |
|-----------|------------------|
| **dev/** | `/plan`, `/implement`, `/test`, `/review`, `/debug`, `/ship`, `/pipeline`, `/adr`, `/plan-status` |
| **quality/** | `/sentrux-health`, `/sentrux-dsm`, `/sentrux-gaps`, `/qex-status`, `/code-stats`, `/test-ratio`, `/arch-review`, `/doctor`, `/lint-agents`, `/lint-settings` |
| **analysis/** | `/channel-map`, `/message-contracts`, `/todo-inventory`, `/graph-slice` |
| **memory/** | `/memory:init`, `/memory:search`, `/memory:status` |
| **spec/** | `/spec`, `/spec-sync` |
| **infra/** | `/validate`, `/fw-test`, `/cold-start`, `/run-proto`, `/clean-cache`, `/diagrams` |
| **team/** | `/team`, `/hire`, `/handoff`, `/docs`, `/wrap-up` |

Гайд по sentrux: [`.claude/plugins/mcp-sentrux/README.md`](.claude/plugins/mcp-sentrux/README.md). Гайд по скриптам: [`scripts/README.md`](scripts/README.md).

## Makefile

Единая точка входа для всех операций. Основные targets:

| Target | Что делает |
|--------|-----------|
| `make check` | ruff + pyright + bandit (быстрая проверка) |
| `make test` | pytest с coverage |
| `make gate` | check + test (полный gate) |
| `make diagrams` | pyreverse + pydeps → `docs/diagrams/` |
| `make clean` | удалить Python-кэши |
| `make help` | справка по всем targets |

## Diagrams-as-Code

Визуализация архитектуры хранится в [`docs/diagrams/`](docs/diagrams/):
- `architecture.mmd` — C4 Container-level (Mermaid, ручная)
- `classes/` — UML классов (авто: `pyreverse`)
- `deps/` — граф зависимостей (авто: `pydeps`)
- `flows/` — sequence-диаграммы (ручные)

Регенерация: `make diagrams` или `/diagrams`. Установка: `uv sync --group diagrams`.
