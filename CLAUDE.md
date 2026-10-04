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
| Path-scoped правила | [`.rules/`](.rules/) — читать по строке карты ядра; загрузчика у них нет |

## История версий и архив

v1/v2 и `multiprocess_prototype_backup/` удалены (e128b930), см. git log.

## Стек

Версии и toolchain — `.claude/modes/_stack.md` → «Toolchain». Логирование — своё (`logger_module`), без loguru; Ollama — эмбеддинги qex.

## Правила проекта

1. **Dict at Boundary** — между процессами только `dict` (`to_dict`/`from_dict`); Pydantic внутри процесса
2. Зависимости через `interfaces.py`; у каждого модуля `README.md`, `STATUS.md`, `tests/`
3. **ADR-решения:**
   - Локальные → `modules/X/DECISIONS.md`
   - Глобальные → `multiprocess_framework/DECISIONS.md`
4. **Тесты:** из корня — `python scripts/validate.py`, `python scripts/run_framework_tests.py`. Ручной pytest — из `multiprocess_framework/modules` (там лежит `pytest.ini`; `run_framework_tests.py` выставляет cwd сам)
5. Конфиг на границе — dict, внутри Pydantic v2
6. Логи через `ObservableMixin`, пути из env (`MULTIPROCESS_LOG_DIR` / `INSPECTOR_LOG_DIR`)
7. Индекс ADR: `multiprocess_framework/DECISIONS.md` → ссылки на локальные DECISIONS.md
8. **Документация — auto-sync:** при правках `multiprocess_framework/DECISIONS.md` или `multiprocess_framework/modules/*/DECISIONS.md` запусти `python -m scripts.sync` для пересборки сводных разделов («Оглавление», «Модульные решения», «Устарело», «Коды модулей»). CI ловит дрифт через `python scripts/validate.py`. Список синхронизируемых разделов: `python -m scripts.sync --list`.
9. **Слои импортов:** `multiprocess_framework → Services → Plugins → multiprocess_prototype` (composition root). Обратные импорты запрещены и enforced через `.sentrux/rules.toml` (boundaries `framework → prototype/Services/Plugins`, `Services → prototype/Plugins`, `Plugins → prototype`). Плагин знает только `PluginContext` и не должен импортировать `multiprocess_prototype.*` — см. ADR-120.
10. **Commit-сообщения:** Conventional Commits + обязательные trailers `Why:` и `Layer:` — раздел «Формат commit-сообщений» ниже.

## Принципы владельца

Постоянные решения владельца. Их не пересматривают в каждой задаче; причины и замеры — в памяти по ссылке.

1. **Framework универсален, прототип расходный.** Спорное решение оценивают по тому, что делает framework универсальнее, а не по удобству прототипа ([память](docs/claude/memory/feedback_framework_first.md)).
2. **Framework чинят улучшением (fix forward).** Правка не удаляет функциональность; найденный баг в framework правят, а не обходят ([память](docs/claude/memory/feedback_framework_first.md)).
3. **Мёртвый код замораживают, не удаляют (FREEZE, не KILL).** Дремлющий путь остаётся контрактом ([память](docs/claude/memory/feedback_framework_first.md)).
4. **Меньше слоёв строго лучше.** При той же функциональности меньше уровней косвенности выигрывает ([память](docs/claude/memory/feedback_framework_first.md)).
5. **Каждый компонент подключаемый, тестируемый, компонуемый.** Сбой одного модуля, процесса или плагина не валит соседей ([память](docs/claude/memory/feedback_framework_first.md)).
6. **GUI формирует топологию, бэкенд исполняет headless (STRICT).** Топологию применяет оркестратор из выбора рецепта; GUI ничего не запускает сам ([память](docs/claude/memory/project_pipeline_recipe_driven_launch.md)).

## Формат commit-сообщений (для агентов)

Гайд — `.claude/COMMIT_GUIDE.md`, шаблон `.gitmessage`, hook — `bash scripts/validate_commit/install_hook.sh`. Обязательны `Why:` и `Layer:`, из плана — `Refs: plans/<slug>.md`; трейлер — одной строкой, иначе hook отклонит коммит.

**Merge в `main`:** тема `merge: <что вошло>` + `Why:`/`Layer:`/`Refs:`; `git merge -F -` не читает stdin — сообщение берут из файла.

## Plan-Driven Development

`/dev:plan`: slug `<домен>-<суть>` (≤ 40), `plans/<slug>.md` или `…/plan.md`, ветка `<type>/<slug>`. Создание и закрытие плана — отдельный `docs(plans):` коммит. Один активный план на модуль; новая работа — фазой. Детали — `.claude/commands/dev/plan.md`.

## Память

- Канон — `docs/claude/memory/` (git), индекс `MEMORY.md` ≤ 8 КБ. Урок пишут в канон; ручного dual-write нет.
- Локальная папка — кэш: догоняет канон через `diff`, не `robocopy /MIR` и не `cp` без `diff`. Личное и машинное — только локально.

## MCP: qex (семантический поиск)

- Первый шаг — `mcp__qex__get_indexing_status`: `last_indexed` против сегодня.
- Возраст индекса передавать субагенту в промпте числом.
- Рефакторинг, «где используется», смена API/IPC — сначала `search_code`, потом `Grep`. Устаревший индекс — подсказка; ЧИСЛА — грепом. Запросы — по-английски.
- Смена эмбеддера — сверить размерность (`1024`) с `dense/vector_meta.json`.

Замеры — `docs/claude/TOOLING_NOTES.md` → «qex (семантический поиск)».

## MCP: sentrux (архитектурный анализ)

- Архитектура и связи модулей — sentrux и `/graph-slice`, не qex/Grep; перед `/ship` — `test_gaps`.
- Границы слоёв — только CLI `sentrux check .`; зелёный `check_rules` частичный, в ревью не цитировать.
- graphify: начинать с `god_nodes`/`get_node`, сужать `context_filter`; имена сообществ — подсказка, а не факт (опознавать по составу узлов); устаревший срез — не факт.
- `--backend=claude-cli` — сессия на батч: до запуска `вызовов × ~50k`, число вслух.

Замеры — `docs/claude/TOOLING_NOTES.md` → «sentrux (архитектурный анализ)».

## Slash-команды

Список — `.claude/CLAUDE.md` → «Commands — quick reference».

## Makefile

`make gate` = `make check` (ruff + pyright + bandit) + `make test`; ещё `make diagrams`, `make clean`, `make help`.

## Diagrams-as-Code

`docs/diagrams/`; регенерация `make diagrams` или `/diagrams` — `docs/diagrams/README.md`.
