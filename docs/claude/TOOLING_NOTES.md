# Заметки об инструментах: qex, sentrux, graphify

Перенесено дословно из корневого `CLAUDE.md` (атлас, задача 2.4c). Здесь обоснования и замеры. Правила остаются строками в корневом `CLAUDE.md` → разделы «MCP: qex» и «MCP: sentrux».

## qex (семантический поиск)

**qex** = Ollama (`qwen3-embedding:0.6b`) + BM25 (Tantivy) + brute-force dense vectors (`~/.qex/`). `search_code` — гибрид dense+sparse.
Холодный старт: `ollama serve` (или `/cold-start`). Docker/Qdrant не нужны.
Модель `0.6b` выбрана потому, что `4b` не помещалась в 4 ГБ VRAM (0% успешных реиндексов три недели). При смене модели сверять размерность векторов (`1024` для `0.6b`) с `dense/vector_meta.json`: рассинхрон «индекс на одной модели, запросы на другой» выдача не показывает.

**Сверка свежести — ПЕРВЫЙ шаг любого обращения к qex, до первого `search_code`.** `mcp__qex__get_indexing_status` → сравнить `last_indexed` с сегодняшним днём. Причина правила: при `indexed: true` и живом `vector_search_available` выдача выглядит здоровой и отвечает уверенно — старым, а о своём возрасте индекс не сообщает.

**Держать индекс свежим дёшево.** Замер 2026-08-31: инкрементальный проход на четырёхдневной дельте (151 файл / 8861 чанк) занял 7 мин 9 с, не часы. Реиндекс раньше тормозили накопленные несмёрженные BM25-сегменты (`tantivy/` до полного ребилда весил 5,7 ГБ, после — 127 МБ), а не сам qex. Поэтому реиндекс после дня работы стоит около семи минут и одного подъёма `ollama serve`. Текущее состояние индекса — только из `get_indexing_status`.

- Свежий (дни) — работает qex-first правило ниже.
- Устаревший (недели) — qex остаётся подсказкой «куда посмотреть», источник истины `Grep`/`rg`/чтение файла; номера строк из выдачи перепроверять, а не переписывать. Любые ЧИСЛА (инвентарь «сколько вызывающих») считать только грепом — хит устаревшего индекса в счёт не идёт.
- **Возраст индекса сообщать субагентам в промпте числом.** Сами они его не знают и выдаче верят; проза «проверь сам» слабее даты «индекс от такого-то числа, вот чего он не видел».
- **Смысловые запросы к `search_code` — по-английски, лексикой ближе к коду.** Точные RU-термины BM25 всё ещё ловит нормально (это не зависит от эмбеддера), слабость именно в русском абстрактном перефразе без точных слов — измерено на fencing-тесте (EN точные термины → топ-1, EN перефраз → топ-3, RU перефраз того же вопроса → мимо совсем).

**qex-first правило:** при рефакторинге, анализе «где используется», смене API/IPC-контракта — **сначала `mcp__qex__search_code`**, потом `Grep`. Подробная логика: `/qex-search`.

## sentrux (архитектурный анализ)

**sentrux** (`brew install sentrux/tap/sentrux`, бинарь `/opt/homebrew/bin/sentrux`) — структурный health-gate. Метрики modularity / acyclicity / depth / equality / redundancy → score 0–10000. Девять MCP-инструментов: `scan`, `health`, `dsm`, `test_gaps`, `check_rules`, `session_start`, `session_end`, `evolution`, `rescan`.

**sentrux-first правило:** при работе с **архитектурой и связями между модулями** (не отдельными строками) — звать sentrux, не qex/Grep:

| Задача | Инструмент |
|--------|------------|
| «Где используется `X`?», поиск по семантике кода | `mcp__qex__search_code` |
| **«Кого заденет правка модуля?»** — границы модуля перед рефакторингом | **`python scripts/graph_slice/graph_slice.py <модуль>`** (slash: `/graph-slice`) — [README](../../scripts/graph_slice/README.md) |
| «Насколько модули связаны?», поиск циклов | `mcp__sentrux__dsm` |
| Baseline перед рефакторингом → дельта после | `session_start` → правки → `session_end` |
| «Что не покрыто тестами?» перед `/ship` | `mcp__sentrux__test_gaps` |
| Проверка инвариантов (`process_module` не импортирует `frontend_module` и т.п.) | **CLI `sentrux check .`**, НЕ `mcp__sentrux__check_rules` — см. предупреждение ниже |
| Снимок здоровья проекта целиком | `mcp__sentrux__scan` + `health` |

**⚠ `mcp__sentrux__check_rules` даёт зелёный по ЧАСТИ правил и не говорит этого в вердикте.** Замер 2026-08-27 на этом репозитории: MCP-инструмент вернул `"✓ All architectural rules pass"`, `pass: true`, `violation_count: 0` — при `rules_checked: 9` из `total_rules_defined: 39` и примечании free-tier «Checking up to 3 rules». CLI на том же дереве: `sentrux check — 36 rules checked`, `✓ All rules pass`. То есть формулировка «все архитектурные правила проходят» покрывает четверть набора, а 30 правил (включая часть `[[boundaries]]` про слои `framework → Services → Plugins → prototype`) не смотрел никто. **Вердикт о границах слоёв выносить только по CLI**; MCP-инструмент годится как быстрый сигнал, но его «All pass» в ревью не цитировать.

**qex и sentrux ортогональны:** qex отвечает «*где*», sentrux — «*насколько здорово*». Не дублируют. Третья ось — **`/graph-slice`**: «*кого заденет*», граница конкретного модуля из графа graphify (единый граф в `graphify-out/`, отдельных графов на модуль нет). Свежесть графа скрипт печатает сам — устаревший срез за факт не выдавать.

## graphify и цена `--backend=claude-cli`

**⚠ Цена бэкендов `--backend=claude-cli` (graphify label и любой инструмент, зовущий `claude` в цикле).** Это НЕ API-вызов, а **полная сессия Claude Code на каждый батч**: в неё грузятся три `CLAUDE.md` + `MEMORY.md` (~22.4k токенов) плюс системный промпт и схемы инструментов — порядка 45–50k на вызов до первого байта полезных данных. Замер 2026-08-27: `graphify label --batch-size=25` = 53 вызова ≈ 2.5 млн входных токенов, почти весь дневной лимит, ради 1316 коротких имён. **Рычаг обратный интуиции: мельчить батчи = множить накладные** (снижение batch-size со 100 до 25 перевело 14 вызовов в 53). Перед запуском считать `вызовов × ~50k` и называть число вслух. Дешевле: `ANTHROPIC_API_KEY` + прямой API, максимальный batch-size, либо локальная генеративная модель. Побочный эффект: порождённая сессия читает проектный `CLAUDE.md` и подчиняется его правилам — имена сообществ вернулись по-русски из-за language policy. Подробности — [`docs/claude/memory/feedback_claude_cli_backend_costs_a_full_session.md`](memory/feedback_claude_cli_backend_costs_a_full_session.md).

**Обслуживание графа graphify.** Инкрементальный `graphify update .` (LLM не нужен) стоит на `post-commit`-хуке рядом с qex-секцией. Он **не чистит** узлы исчезнувших файлов и не переименовывает новые сообщества — накопленный мусор снимает только `graphify update . --force` (замер 2026-08-27: убрал 3 файла-призрака и 51 тест, живший в графе вопреки `.graphifyignore`). `graph.html` не генерируется: лимит визуализации 5000 узлов против наших ~29 тысяч.

**⚠ Имена сообществ graphify — подсказка, а не факт.** Они **переносятся по ID**, а состав сообществ при каждой пересборке сдвигается, поэтому подпись расходится с содержимым тем сильнее, чем дольше живёт граф — и сигнала об этом нет. Замер 2026-08-28, один инкрементальный проход: сообществ стало 1343 против 1320 при нуле заглушек и без запуска именования; `#10 «DI-контейнеры рантайма»` переехало с `settings/_sections.py` на `recipes/tab.py`, сохранив имя; `#22 «Фасад авторизации»` стоит на `adapters/stores/config_store.py`. Часть имён при этом точна и устойчива (`#6 «Каналы Modbus-драйвера»` → `Services/modbus/core/device.py`). **Вывод для ревью: сообщество опознавать по составу узлов, имя в вердикт не цитировать.** Структурные ответы (`god_nodes`, `shortest_path`, `get_neighbors`, `get_node`) от имён не зависят вовсе — на них и опираться. `query_graph` вдобавок обрезается по `token_budget` и уводит лексически (замер: 33 узла из 173, по слову «writer» притянуло GUI-панели) — начинать с `god_nodes`/`get_node`, сужать `context_filter`.

## Справка, вынесенная из корневого CLAUDE.md

Дословно; одна правка — `uv sync` → `uv sync --inexact` (простой `uv sync` сносит необъявленные пакеты). Правила из этих абзацев остались строками в корневом `CLAUDE.md`; канон шаблона коммита — `.claude/COMMIT_GUIDE.md`, копия ниже — старый текст корневого файла. Относительные ссылки пересчитаны от `docs/claude/`; ссылки на `docs/claude/COMMIT_GUIDE.md` ведут на канон `.claude/COMMIT_GUIDE.md`.

### История версий и архив

Активный прототип — **`multiprocess_prototype/`** (единственный). Старые v1/v2 директории и снэпшот `multiprocess_prototype_backup/` физически удалены (e128b930, 2026-06; хвосты в конфигах вычищены 2026-07-03), см. git log.

### Стек

Python 3.12 (см. корневой `pyproject.toml`), PySide6 6.10 (Phase 2 завершена 2026-04), OpenCV 4.13, NumPy 2.x | SQLite/PostgreSQL
Ollama, pytest + pytest-qt (`qt_api = pyside6`) | Pydantic v2
Логирование — своё (`logger_module`: `get_std_logger` + LoggerManager процесса). loguru снята в 4.3: писателей мимо разъёма не осталось
ML (Phase 1.5): PyTorch 2.11 + Ultralytics YOLO + ONNX Runtime — extras `[ml]` в pyproject

### Правила проекта, п.10 (полный текст)

10. **Commit-сообщения:** Conventional Commits + обязательные trailers `Why:` и `Layer:`. Опциональные — `Refs:`, `Risk:`, `Reversible:`, `Tested:`, `Rejected:`. Шаблон в `.gitmessage`, гайд в [`docs/claude/COMMIT_GUIDE.md`](../../.claude/COMMIT_GUIDE.md), валидирует hook `.git/hooks/commit-msg` (установка `bash scripts/validate_commit/install_hook.sh`). Агенты обязаны генерировать trailers — иначе commit будет отклонён.

### Формат commit-сообщений (для агентов)

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

**Обязательны:** `Why:` и `Layer:`. Без них hook отклонит коммит. Полный гайд — [`docs/claude/COMMIT_GUIDE.md`](../../.claude/COMMIT_GUIDE.md). Whitelist'ы значений в [`scripts/validate_commit/validate_commit.py`](../../scripts/validate_commit/validate_commit.py).

### Plan-Driven Development

Новые планы создаются через `/plan` с единой конвенцией:
- **Slug:** kebab-case, `<домен>-<суть>`, max 40 символов. Хранение: `plans/<slug>.md` (дефолт) или `plans/<slug>/plan.md` (multi-phase)
- **Ветка:** `<type>/<slug>` — автоматически при `/plan`. Стандарт: `feat/`, не `feature/`
- **Refs:** коммит из плана **обязан** содержать `Refs: plans/<slug>.md` (enforce на уровне агентов)
- **Коммиты плана:** создание/закрытие — отдельный `docs(plans):` коммит. Статусы задач — допустимо в коммите кода
- **Статус:** `/plan-status` — прогресс по текущей ветке
- **Один активный план на инструмент или модуль:** новую работу добавляют фазой в него, не новым файлом

Подробности — в [`plans/` конвенциях](../../.claude/commands/dev/plan.md) и промптах агентов.

### Память

- **Канон — `docs/claude/memory/`** (git, общий для обеих машин). Индекс `MEMORY.md` ≤ 8 КБ; уроки лежат в `CRAFT-*.md` и читаются по триггеру; архив — [`docs/claude/memory/_archive/INDEX.md`](memory/_archive/INDEX.md).
- **Локальная папка Claude Code — кэш**, не источник. Обновляется из канона через `diff`; никогда не `robocopy /MIR` и не `cp` без `diff`: копия затирает правки другой стороны молча.
- **Ручного dual-write больше нет.** Новый или обновлённый урок пишут в канон; локальная копия догоняет его.
- **Личное (`user`) и машинное (`reference`, local-only)** живут только в локальной папке и в git не попадают.
- **Mac** переходит на эту схему позже, по решению владельца; до тех пор `.claude/memory/` на Mac — рабочая папка Mac.

### Slash-команды

Файлы команд считать так: `find .claude/commands -name '*.md' | wc -l`. Ключевые по семи основным категориям:

| Категория | Ключевые команды |
|-----------|------------------|
| **dev/** | `/plan`, `/implement`, `/test`, `/review`, `/debug`, `/ship`, `/pipeline`, `/team` (живая команда агентов, [руководство](AGENT_TEAMS_GUIDE.md)), `/adr`, `/plan-status` |
| **quality/** | `/sentrux-health`, `/sentrux-dsm`, `/sentrux-gaps`, `/qex-status`, `/code-stats`, `/test-ratio`, `/arch-review`, `/doctor`, `/lint-agents`, `/lint-settings` |
| **analysis/** | `/channel-map`, `/message-contracts`, `/todo-inventory`, `/graph-slice` |
| **memory/** | `/memory:init`, `/memory:search`, `/memory:status` |
| **spec/** | `/spec`, `/spec-sync` |
| **infra/** | `/validate`, `/fw-test`, `/cold-start`, `/run-proto`, `/clean-cache`, `/diagrams` |
| **team/** | `/team`, `/hire`, `/handoff`, `/docs`, `/wrap-up` |

Гайд по sentrux: [`.claude/plugins/mcp-sentrux/README.md`](../../.claude/plugins/mcp-sentrux/README.md). Гайд по скриптам: [`scripts/README.md`](../../scripts/README.md).

### Makefile

Единая точка входа для всех операций. Основные targets:

| Target | Что делает |
|--------|-----------|
| `make check` | ruff + pyright + bandit (быстрая проверка) |
| `make test` | pytest с coverage |
| `make gate` | check + test (полный gate) |
| `make diagrams` | pyreverse + pydeps → `docs/diagrams/` |
| `make clean` | удалить Python-кэши |
| `make help` | справка по всем targets |

### Diagrams-as-Code

Визуализация архитектуры хранится в [`docs/diagrams/`](../diagrams/):
- `architecture.mmd` — C4 Container-level (Mermaid, ручная)
- `classes/` — UML классов (авто: `pyreverse`)
- `deps/` — граф зависимостей (авто: `pydeps`)
- `flows/` — sequence-диаграммы (ручные)

Регенерация: `make diagrams` или `/diagrams`. Установка: `uv sync --inexact --group diagrams`.
