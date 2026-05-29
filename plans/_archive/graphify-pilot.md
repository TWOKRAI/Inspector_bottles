---
title: "Пилот: Graphify как граф зависимостей для multiprocess_framework"
type: plan
status: draft
date_created: 2026-05-18
date_updated: 2026-05-18
owner: Sergey
tags: [tooling, ai-dev, knowledge-graph, pilot]
related:
  - plans/ai-dev-tooling.md
  - plans/mcp-consolidation.md
---

## 0. Контекст

Inspector_bottles — multiprocess_framework + 8 plugin-категорий, 122 Python-файла, центральные узлы: `command_module/core/command_manager.py`, `router_module/core/router_manager.py`. Архитектура plumbing-heavy: команды ходят через router → ProcessManagerProcess, plugins регистрируются как процессы, сквозные concerns (логи/метрики) живут на CommandManager.

Сейчас у dev-агентов (Claude Code) **нет** инструмента, который ответит:
- «Если переименовать `RouterAdapter.send` — что отвалится?»
- «Какие модули зависят от `command_module` транзитивно?»
- «Где CommandManager стал god-объектом — какие узлы стянуты к нему сильнее всего?»

Сейчас они отвечают через `grep + Read` по 5–15 файлам. Это работает, но дорого по токенам и оставляет слепые зоны при транзитивных зависимостях.

## 1. Гипотеза

> На корпусе 122 файлов с plumbing-heavy архитектурой Graphify (Tree-sitter AST + NetworkX) даст реалистично **5–15× экономии токенов** на структурных вопросах (path, explain, god-nodes) против `grep+Read`, и команда `path A B` будет давать ответы, недостижимые текущим тулингом.

Гипотеза **отвергается**, если хотя бы одно из:
- На 3 реальных задачах (см. §6) граф не показывает ничего, что не нашёл бы `grep` за то же время.
- `--update` после рефакторинга с переименованием даёт >20% устаревших узлов (drift).
- Время первичной индексации >5 минут или стоимость extraction >$1 за прогон.

## 2. Скоуп

### В скоупе

- Локальная установка Graphify **только в этот проект** (`uv tool install` в локальной .venv или `uvx`).
- Индексация **только кода**: `multiprocess_framework/`, `Plugins/`, `Services/`, `Utils/`, `run.py`. БЕЗ docs/markdown/изображений (минимизирует токены extraction).
- Тестовая выборка: 3 реальных вопроса (§6), которые dev-агент задавал за последние 2 недели.

### Вне скоупа

- Глобальная регистрация skill в `~/.claude/` — НЕ делать, чтобы не засорять hook других проектов.
- MCP-сервер (`--mcp`) — НЕ запускать на первом проходе. CLI достаточно для пилота.
- Индексация `docs/`, `data/`, `logs/` — НЕ нужно, это раздует extraction-токены.
- Neo4j экспорт — не нужно, JSON+HTML хватит.
- Параллельная индексация `multiprocess_prototype/` и `services_backup/` — это legacy, граф будет зашумлён.

## 3. Подготовка

### 3.1. Артефакты в .gitignore

Перед установкой добавить в [.gitignore](.gitignore):

```
# Graphify pilot — output не коммитим, перегенерируется
graphify-out/
.graphify_*
```

**Проверка:** `git status` после `graphify .` не показывает новых tracked файлов.

### 3.2. Установка

```bash
cd /Users/twokrai/Project_code/Inspector_bottles
uvx graphify --help    # запуск без установки в .venv проекта
# или, если решено ставить локально:
# uv tool install graphify
```

**Проверка:** `uvx graphify --version` возвращает версию (ожидаем v6.x).

### 3.3. Конфигурация индексации

Создать файл `.graphify.toml` в корне проекта (если поддерживается; иначе передавать флагами):

```toml
include = ["multiprocess_framework/**/*.py", "Plugins/**/*.py", "Services/**/*.py", "Utils/**/*.py", "run.py"]
exclude = [
    "**/__pycache__/**",
    "**/tests/**",                  # тесты — отдельный прогон, не смешивать
    "multiprocess_prototype*/**",   # legacy
    "services_backup/**",
    "templates/**",
    "**/.venv/**",
]
mode = "code-only"   # без LLM extraction для docs/изображений
```

**Проверка:** `graphify detect .` показывает ожидаемое число файлов (≈80–100, не 200+).

## 4. Этапы

### Этап 1 — Первичная индексация (1 час)

**Действие:**
```bash
graphify .
```

**Verify:**
- `graphify-out/graph.json` создан, размер 0.5–5 МБ.
- `graphify-out/graph.html` открывается в браузере, видны кластеры.
- `graphify-out/GRAPH_REPORT.md` содержит секции «god nodes», «communities», «surprising connections».
- Время выполнения зафиксировано в [logs/graphify-pilot.md](logs/graphify-pilot.md) (создать).
- Стоимость в токенах/долларах зафиксирована (вывод graphify в конце).

**Стоп-критерий:** если время >5 мин или стоимость >$1 — остановиться, скоуп явно слишком широкий.

### Этап 2 — Sanity-check на known-good вопросах (30 минут)

Цель: убедиться, что граф НЕ врёт на вопросах, на которые ты знаешь ответ.

| # | Вопрос (известный ответ) | Команда | Verify |
|---|---|---|---|
| S1 | «Кто использует `CommandManager.execute`?» (знаем: router_adapter, process_manager) | `graphify query "callers of CommandManager.execute"` | в ответе есть оба известных вызывающих |
| S2 | «Путь между `Plugins/sources/` и `command_module`?» | `graphify path Plugins/sources/__init__.py multiprocess_framework/modules/command_module/core/command_manager.py` | путь существует и проходит через router_module |
| S3 | «Самые связанные узлы» | смотреть `GRAPH_REPORT.md` → god nodes | CommandManager и RouterManager в топ-5 |

**Verify:** все три ответа совпадают с ожидаемым. Если хотя бы один промахивается — баг в Graphify или скоупе индексации; разобраться до §5.

### Этап 3 — Реальные задачи (2–3 часа)

Три **реальные** задачи из недавнего dev-pipeline. Перед запуском Graphify зафиксировать в `logs/graphify-pilot.md`:
- сколько токенов/времени потратил агент на эту задачу через `grep+Read` (если уже решена — оценка по сессии);
- какой был ответ.

Затем — задать тот же вопрос Graphify, сравнить.

#### R1 — «Куда добавить новый process.command для нового плагина?»

**Команда:**
```bash
graphify explain "registering a new process.command"
```

**Verify:** ответ показывает связку CommandManager → router → ProcessManagerProcess + указывает конкретный файл, где регистрируются handler'ы. Сравнить с тем, что нашёл бы grep по `process.command`.

#### R2 — «Что сломается, если убрать `RouterAdapter`?»

**Команда:**
```bash
graphify query "what depends on RouterAdapter, direct and transitive"
```

**Verify:** список содержит все прямые импортёры (grep find их быстро) **И** транзитивных потребителей через 2–3 хопа (это уже добавленная ценность).

#### R3 — «Где `data_schema_module` соприкасается с `command_module`?»

**Команда:**
```bash
graphify path multiprocess_framework/modules/data_schema_module multiprocess_framework/modules/command_module
```

**Verify:** показывает конкретные edges — какой класс из data_schema используется в какой команде. Это запрос, на котором grep тонет (слишком много false positive по словам «schema», «command»).

### Этап 4 — Drift-тест (30 минут)

**Действие:** взять последний коммит с переименованием/удалением файла (см. `git log --diff-filter=R`), откатить состояние графа на момент **до** коммита, накатить коммит, прогнать `graphify . --update`, открыть `graph.html`.

**Verify:**
- Удалённые файлы исчезли из графа (нет ghost-nodes).
- Переименованные файлы либо корректно подхвачены, либо граф честно сообщает о потере (provenance: `AMBIGUOUS`).
- Доля устаревших узлов <20%.

**Стоп-критерий:** drift >20% → команда `--update` не годится для активной разработки, граф нужно полностью пересобирать после рефакторинга. Это не отменяет ценность графа для read-only анализа, но снижает интеграцию в pipeline.

### Этап 5 — Решение go/no-go (15 минут)

Заполнить таблицу в [logs/graphify-pilot.md](logs/graphify-pilot.md):

| Задача | Время grep+Read (мин) | Время Graphify (мин) | Качество ответа Graphify (1–5) | Уникальный insight? (y/n) |
|---|---|---|---|---|
| R1 | | | | |
| R2 | | | | |
| R3 | | | | |

**GO**, если суммарно ≥2 из 3 задач:
- быстрее на ≥40% **И** качество ≥4,
- ИЛИ дали уникальный insight (graphify нашёл то, что grep пропустил).

**NO-GO** иначе — заархивировать `graphify-out/`, удалить `.graphify.toml`, обновить статью [graphify-mcp в KnowledgeOS](file:///Users/twokrai/Project_code/obsidian/knowledge/wiki/tools/graphify-mcp.md) с пометкой «не оправдалось на Inspector_bottles».

## 5. Интеграция в dev-pipeline (только если GO)

### 5.1. Skill для агентов проекта

Создать `.claude/skills/graphify-query.md` **локально** в Inspector_bottles (не глобально):

- Кому: developer, reviewer, debugger.
- Когда вызывать: вопросы вида «кто зависит от X», «что сломается если изменю Y», «как соединены модули A и B».
- Когда НЕ вызывать: семантический поиск по комментариям/именам (это к `grep`), поиск багов в логике (это к `Read+pytest`).

### 5.2. Обновление графа

Cron/hook не делать. Правило: **dev обновляет граф вручную** после merge крупных PR командой `graphify . --update`. Это сознательный outbox-режим, чтобы не платить токены при каждом коммите.

**Verify раз в неделю:** `graphify . --update` отрабатывает <30 сек инкрементально.

### 5.3. MCP-сервер (отложенное)

Только если §5.1 покажет, что developer-агент реально вызывает `graphify` через Bash в >30% сессий — поднять `graphify --mcp` как локальный MCP и зарегистрировать в `.mcp.json` **этого проекта** (не корневого obsidian). Тогда вызовы пойдут через MCP-tool, а не через Bash.

## 6. Артефакты на выходе

1. `logs/graphify-pilot.md` — журнал замеров (этапы 1, 2, 3, 4) с финальной таблицей go/no-go.
2. `.graphify.toml` (или эквивалент в виде Makefile-таргета `make graph`).
3. `.gitignore` — добавлены `graphify-out/`, `.graphify_*`.
4. Решение в README.md проекта (1 строкой): «Graphify: используется / не оправдался».
5. Обновлённая статья [knowledge/wiki/tools/graphify-mcp.md](file:///Users/twokrai/Project_code/obsidian/knowledge/wiki/tools/graphify-mcp.md) — ответы на open questions из секции «Открытые вопросы» (особенно про drift и нелатинские имена, если попадутся).

## 7. Риски и митигации

| Риск | Митигация |
|---|---|
| LLM extraction для не-кода съест токены | `mode = "code-only"`, exclude docs/data/logs |
| Граф устареет после рефакторинга | Drift-тест на этапе 4 как gate-критерий |
| Дублирование с qex_inspector (векторный) | Чёткое разделение: qex — семантика, graphify — структура. Не индексировать одинаковые слои |
| Versionlock на v6 | uvx без pin'а версии в pyproject — обновления через `uvx graphify@latest` |
| Skill засорит соседние проекты | Skill только локально в `.claude/skills/` Inspector_bottles |

## 8. Не делать (anti-scope)

- Не интегрировать в CI (зря потраченное время на этапе пилота).
- Не писать обёртки над `graphify` в `Utils/` или `multiprocess_framework/` — это внешний tool, не часть фреймворка. Принцип «не плодить тонкие обёртки» применим.
- Не индексировать `tests/` — структура тестов плоская, граф там бесполезен.
- Не строить второй граф для `Plugins/` отдельно — общий граф уже покажет связи плагинов с framework.

## 9. Оценка времени

| Этап | Время |
|---|---|
| §3 Подготовка | 30 мин |
| §4.1 Первичная индексация | 1 ч (включая первый просмотр HTML) |
| §4.2 Sanity-check | 30 мин |
| §4.3 Реальные задачи (3 шт) | 2–3 ч |
| §4.4 Drift-тест | 30 мин |
| §4.5 Решение | 15 мин |
| **Итого пилот** | **~5 часов** одной сессии |

Если §4.1 не пройдён за час — стоп, разбираться (скорее всего проблема в `pyproject.toml` v3.12-only ограничении и Python-версии Graphify).

## 10. Следующий шаг

Не запускать всё сразу. Начать с §3.1 (`.gitignore`) и §3.2 (`uvx graphify --help`) — это 5 минут. Если установка отрабатывает чисто — продолжать. Если падает на macOS/Apple Silicon — зафиксировать ошибку в `logs/graphify-pilot.md` и решить, чинить или закрыть пилот.
