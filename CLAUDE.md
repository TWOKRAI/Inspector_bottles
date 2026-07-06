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
- **Всего модулей в `multiprocess_framework/modules/`:** 20 (после Phase 4 carve-out `sql_module` → `Services/sql`). См. [`MODULES_STATUS.md`](multiprocess_framework/MODULES_STATUS.md), [`Services/STATUS.md`](Services/STATUS.md), [`docs/MODULES_OVERVIEW.md`](multiprocess_framework/docs/MODULES_OVERVIEW.md).

## Ключевые пути

| Что | Путь |
|-----|------|
| **АКТИВНЫЙ прототип** | `multiprocess_prototype/` ← **только сюда вносить app-specific изменения** |
| Фреймворк | `multiprocess_framework/` |
| Прикладные сервисы (sql, hikvision, …) | `Services/` ← Phase 4 carve-out |
| Vocabulary плагинов (19 шт., reuse между приложениями) | `Plugins/` ← Phase 5 carve-out (см. ADR-120) |
| Документация фреймворка | `multiprocess_framework/docs/` (`MODULES_OVERVIEW.md`, `MODULE_CONTRACTS.md`, `DIAGRAMS.md`) |
| Диаграммы архитектуры | `docs/diagrams/` (Mermaid, PlantUML, SVG — diagrams-as-code) |
| Конструктор-blueprint фреймворка (20 модулей) | [`multiprocess_framework/docs/CONSTRUCTOR_BLUEPRINT.md`](multiprocess_framework/docs/CONSTRUCTOR_BLUEPRINT.md) |
| Точка входа v3 | `multiprocess_prototype/run.py` |
| Регистры приложения v3 | `multiprocess_prototype/registers/` |
| Конспект правил | `docs/claude/FRAMEWORK_RULES_EXTRACT.md` |
| Нарратив «конструктор» | `docs/claude/FRAMEWORK_CONSTRUCTOR_OVERVIEW.md` |
| Настройка qex | `.claude/mcp/qex/README.md` (quick-start), `.claude/mcp/qex/SETUP_GUIDE.md` (полный) |
| Гайд по sentrux | [`.claude/mcp/sentrux/README.md`](.claude/mcp/sentrux/README.md) (метрики, slash-команды, сценарии) |
| Path-scoped правила | [`.rules/`](.rules/) — загружаются при работе с соответствующими файлами |

## История версий и архив

Активный прототип — **`multiprocess_prototype/`** (единственный). Старые v1/v2 директории и снэпшот `multiprocess_prototype_backup/` физически удалены (e128b930, 2026-06; хвосты в конфигах вычищены 2026-07-03), см. git log.

## Стек

Python 3.12 (см. корневой `pyproject.toml`), PySide6 6.10 (Phase 2 завершена 2026-04), OpenCV 4.13, NumPy 2.x | SQLite/PostgreSQL
Ollama, pytest + pytest-qt (`qt_api = pyside6`) | Pydantic v2, loguru
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

**qex** = Ollama (`qwen3-embedding:4b`) + BM25 (Tantivy) + brute-force dense vectors (`~/.qex/`). `search_code` — гибрид dense+sparse.
Холодный старт: `ollama serve` (или `/cold-start`). Docker/Qdrant не нужны.

**qex-first правило:** при рефакторинге, анализе «где используется», смене API/IPC-контракта — **сначала `mcp__qex__search_code`**, потом `Grep`. Подробная логика: `/qex-search`.

## MCP: sentrux (архитектурный анализ)

**sentrux** (`brew install sentrux/tap/sentrux`, бинарь `/opt/homebrew/bin/sentrux`) — структурный health-gate. Метрики modularity / acyclicity / depth / equality / redundancy → score 0–10000. Девять MCP-инструментов: `scan`, `health`, `dsm`, `test_gaps`, `check_rules`, `session_start`, `session_end`, `evolution`, `rescan`.

**sentrux-first правило:** при работе с **архитектурой и связями между модулями** (не отдельными строками) — звать sentrux, не qex/Grep:

| Задача | Инструмент |
|--------|------------|
| «Где используется `X`?», поиск по семантике кода | `mcp__qex__search_code` |
| «Насколько модули связаны?», поиск циклов | `mcp__sentrux__dsm` |
| Baseline перед рефакторингом → дельта после | `session_start` → правки → `session_end` |
| «Что не покрыто тестами?» перед `/ship` | `mcp__sentrux__test_gaps` |
| Проверка инвариантов (`process_module` не импортирует `frontend_module` и т.п.) | `mcp__sentrux__check_rules` (через `.sentrux/rules.toml`) |
| Снимок здоровья проекта целиком | `mcp__sentrux__scan` + `health` |

**qex и sentrux ортогональны:** qex отвечает «*где*», sentrux — «*насколько здорово*». Не дублируют.

## Slash-команды

46 команд в 7 категориях. Список (упорядочено по namespace):

| Категория | Ключевые команды |
|-----------|------------------|
| **dev/** | `/plan`, `/implement`, `/test`, `/review`, `/debug`, `/ship`, `/pipeline`, `/adr`, `/plan-status` |
| **quality/** | `/sentrux-health`, `/sentrux-dsm`, `/sentrux-gaps`, `/qex-status`, `/code-stats`, `/test-ratio`, `/arch-review`, `/doctor`, `/lint-agents`, `/lint-settings` |
| **analysis/** | `/channel-map`, `/message-contracts`, `/todo-inventory` |
| **memory/** | `/memory:init`, `/memory:search`, `/memory:status` |
| **spec/** | `/spec`, `/spec-sync` |
| **infra/** | `/validate`, `/fw-test`, `/cold-start`, `/run-proto`, `/clean-cache`, `/diagrams` |
| **team/** | `/team`, `/hire`, `/handoff`, `/docs`, `/wrap-up` |

Гайд по sentrux: [`.claude/mcp/sentrux/README.md`](.claude/mcp/sentrux/README.md). Гайд по скриптам: [`scripts/README.md`](scripts/README.md).

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
