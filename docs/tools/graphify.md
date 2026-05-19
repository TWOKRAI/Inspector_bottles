# Graphify — установка и настройка в Inspector_bottles

> **Статус:** пилот (2026-05-19). См. план [`plans/graphify-pilot.md`](../../plans/graphify-pilot.md) и решение по итогам [§5 плана](../../plans/graphify-pilot.md#5-интеграция-в-dev-pipeline-только-если-go).
> **Версия Graphify:** установлено и проверено на `graphifyy 0.8.13` (PyPI), ветка репо `v8`.
> **Источники:** официальный репо [safishamsi/graphify](https://github.com/safishamsi/graphify), PyPI [`graphifyy`](https://pypi.org/project/graphifyy/).
>
> **Внимание:** в README v8 на GitHub команды показаны как `/graphify .` — это **синтаксис skill-вызова внутри Claude Code**, а не прямой CLI. Прямые CLI-команды: `graphify update <path>` (без LLM, для кода), `graphify extract <path>` (с LLM, для доков), `graphify path/explain/query`. См. §9.

---

## 1. Что это

Graphify — CLI на Python, который превращает кодовую базу в граф знаний:

- Узлы — файлы, классы, функции, импорты, доки.
- Edges — вызовы, наследование, импорты, связи «doc ↔ code».
- Кластеры — Leiden community detection (god-nodes, surprising connections).

Граф сохраняется в `graphify-out/`: `graph.json`, `graph.html` (интерактив), `GRAPH_REPORT.md` (отчёт), плюс опционально `wiki/`, `SVG`, `Neo4j cypher`, MCP-сервер.

**Что делает локально:** AST-парсинг кода через `tree-sitter` (31 язык, для Python — `tree-sitter-python`). API не вызывается.
**Что требует LLM-вызовов:** только не-код — markdown, PDF, изображения, видео, transcript. У нас в скоупе индексации только `.py`, поэтому **API-токены при индексации = 0**.

## 2. Ниша рядом с уже работающими инструментами

В проекте уже работают три структурных tool'а. Graphify ставится **в дополнение**, не вместо них:

| Задача | Инструмент | Почему |
|---|---|---|
| «Где используется X» (семантика, по тексту/именам) | [qex](.claude/mcp/qex/README.md) | Векторный + BM25, секунды, бесплатно |
| Архитектурные правила, DSM, quality score | [sentrux](.claude/mcp/sentrux/README.md) | Rust бинарь, уже настроен (`.sentrux/rules.toml`) |
| Граф импортов (визуально) | `make diagrams` (pydeps + pyreverse) | Уже в Makefile, выгружает в `docs/diagrams/` |
| Кластеры god-nodes на уровне символов | **Graphify** | Free sentrux отдаёт `clusters: []`, pydeps кластеризацию не делает |
| `path FILE_A FILE_B` на AST-уровне | **Graphify** | DSM sentrux работает только на модулях, не файлах |
| `explain <topic>` через LLM по графу | **Graphify** | Уникально, остальные инструменты этого не дают |

**Чёткое разграничение, кто на какой вопрос отвечает:**

- «Что сломается, если переименую `RouterAdapter.send`?» → Graphify `path` или `query`.
- «Где CommandManager стал god-объектом?» → Graphify (`GRAPH_REPORT.md` → god nodes).
- «Какие модули нарушают `framework → prototype` boundary?» → sentrux `check_rules`.
- «Где в коде встречается слово `chain`?» → qex.
- «Картинка зависимостей всего framework» → `make diagrams`.

## 3. Предостережения

Прочитай перед установкой:

1. **Pre-1.0 (0.8.x).** API нестабильный, между минорами возможны breaking changes. Версию фиксировать вручную.
2. **Drift при рефакторинге.** После `git mv` или переименования файла команда `--update` теряет накопленные insights в кластерах. Лечится `graphify extract . --force` (полная пересборка).
3. **HTML тяжёлый.** На корпусе 854 файла `graph.html` может быть >5000 узлов и тормозить браузер. Для регулярного использования — флаг `--no-viz` и работа через `graphify query` / `path`.
4. **Не индексировать `multiprocess_prototype_backup/`** — это legacy snapshot, граф зашумится. См. `.graphifyignore` ниже.
5. **Тесты — отдельный вопрос.** Включать ли `tests/` в граф — на твоё усмотрение. Дефолт документации: **исключать** (структура плоская, граф там бесполезен), но можно поменять.

## 4. Требования

| Что | Минимум | Проверка | Текущее |
|---|---|---|---|
| Python | 3.10+ | `python3 --version` | 3.12.13 ✓ |
| uv | любая | `uv --version` | 0.11.8 ✓ |
| Дисковое место | ~200 МБ для 28 tree-sitter | `df -h .` | — |
| Сеть для установки | PyPI | — | — |
| API-ключи | **не нужны** для кода | — | — |

Все требования у тебя уже выполнены. Никаких системных зависимостей сверх Python + uv.

## 5. Установка

### 5.1. Установка пакета

> **Внимание:** имя пакета на PyPI — `graphifyy` (две `y`). CLI после установки — `graphify` (одна `y`). На PyPI есть форки с похожими именами — НЕ устанавливай их.

```bash
# Рекомендуемый способ (uv добавит graphify в PATH автоматически):
uv tool install graphifyy

# Альтернативы (если uv недоступен):
pipx install graphifyy
# или (хуже — может не попасть в PATH):
pip install --user graphifyy
```

**Опциональные extras** — на старте **не нужны**, в проекте только Python-код:

- `[mcp]` — MCP stdio сервер (не ставим на пилоте, см. §10)
- `[svg]` — SVG-экспорт (не нужно, есть `make diagrams`)
- `[leiden]` — Leiden community detection (Python <3.13 only). У нас 3.12 — можно поставить, если хочется лучших кластеров. Дефолт без него тоже работает.
- `[ollama]` — для индексации доков через локальную Ollama (вспомнить через 2-3 месяца, не сейчас)

Если в будущем понадобится indexing документации без API-ключей через локальную модель:

```bash
uv tool install "graphifyy[ollama,leiden]"
```

### 5.2. Проверка установки

```bash
graphify --version
# ожидаем: 0.8.11 или новее

graphify --help | head -30
# ожидаем: список команд (extract, query, path, explain, ...)
```

Если `graphify: command not found` после `uv tool install` — закрой и открой терминал, либо выполни `uv tool update-shell`.

### 5.3. Закрепление версии (опционально)

API pre-1.0, между минорами возможны breaks. Если хочешь стабильности — зафиксируй мажор-минор:

```bash
uv tool install "graphifyy==0.8.*"
```

Обновление вручную: `uv tool upgrade graphifyy`.

## 6. Конфигурация в проекте

### 6.1. `.graphifyignore` (обязательно)

Создать в корне проекта **до первого запуска**, чтобы исключить legacy и cache. Файл уже подготовлен по этой документации — формат как `.gitignore`:

```
# Legacy snapshot — НЕ индексировать
multiprocess_prototype_backup/
services_backup/

# Тесты — плоская структура, граф бесполезен
**/tests/
**/test_*.py
**/*_test.py

# Кэши и сгенерированное
**/__pycache__/
.pytest_cache/
.coverage
docs/diagrams/classes/*.puml
docs/diagrams/deps/*.svg

# Виртуальные окружения
.venv/
venv/

# Этот же tool
graphify-out/

# Логи, изображения, бинарники
logs/
*.png
*.jpg
*.webp
*.mp4
*.mov
```

### 6.2. `.gitignore` (обязательно)

Добавить в корневой `.gitignore` (в этой документации делается отдельным шагом):

```
# Graphify pilot — output не коммитим, перегенерируется
graphify-out/
.graphify_*
```

**Почему игнорируем целиком, хотя README graphify рекомендует коммитить.** README ориентирован на команду, где граф — shared knowledge. На пилоте у тебя нет смысла коммитить ~5 МБ JSON, который ещё может перестроиться завтра. Если пилот пройдёт go-критерии и решено оставить — пересмотреть в [§5 плана](../../plans/graphify-pilot.md#5-интеграция-в-dev-pipeline-только-если-go).

### 6.3. Регистрация skill в Claude Code — НЕ делать на старте

Команда `graphify install` зарегистрирует skill в `~/.claude/` глобально и поднимет hook, который будет автоматически направлять запросы в граф. **На пилоте этого делать не надо** — причины:

1. Skill регистрируется глобально для всех проектов в `~/.claude/`, засорит соседние проекты.
2. Pre-emptive hook на каждый search-style tool call увеличит latency агентов.
3. Если граф зашумлён или устарел — агенты пойдут по нему, минуя `Grep`/`Read`.

**Правильнее:** держать `graphify` как явный CLI-инструмент, вызывать **в лоб через `Bash`** в тех 5–10% сессий, где нужен структурный запрос. Если по итогам пилота окажется, что developer-агент действительно зовёт `graphify` чаще, чем `grep`, — тогда регистрировать skill **только локально** через project-scoped settings (см. §10).

## 7. Первый запуск (quick-try, 30–60 минут)

Цель: убедиться, что инструмент работает на твоём корпусе, и **получить грубое ощущение «зашло/не зашло»** на одном модуле. **НЕ запускать на всех 854 файлах сразу.**

### 7.1. Индексация одного модуля

```bash
cd /Users/twokrai/Project_code/Inspector_bottles

# AST-only, без LLM, без API-вызовов.
# ВАЖНО: команда — `update`, не `extract`. extract требует --backend.
graphify update multiprocess_framework/modules/command_module
```

**Реальный вывод на 2026-05-19, command_module, 12 файлов:**

```
Re-extracting code files in multiprocess_framework/modules/command_module (no LLM needed)...
[graphify watch] Rebuilt: 126 nodes, 118 edges, 16 communities
[graphify watch] graph.json, graph.html and GRAPH_REPORT.md updated
  in multiprocess_framework/modules/command_module/graphify-out
Code graph updated. For doc/paper/image changes run /graphify --update in your AI assistant.
Tip: set GEMINI_API_KEY or GOOGLE_API_KEY to use Gemini for semantic extraction.
```

**ВАЖНО — место артефактов.** В 0.8.13 `graphify-out/` создаётся **внутри индексированной директории**, не в корне проекта. То есть для `graphify update multiprocess_framework/modules/command_module` получишь `multiprocess_framework/modules/command_module/graphify-out/`. Это покрывается `.gitignore` правилом `graphify-out/` (matches any depth).

**Стоп-сигналы за первые 5 минут:**

- Индексация >2 мин на одном модуле — что-то не так, проверить `.graphifyignore` (cm. §6.1).
- Сетевые запросы в выводе (`POST https://...`) — значит, попал не-код. Проверить `.graphifyignore`.
- `Token cost: ... input · ... output` в `GRAPH_REPORT.md` отличен от `0 input · 0 output` — то же самое: попал не-код через `update`. Для чистого кода должно быть `0 · 0`.

### 7.2. Реальные вопросы из плана

Прогнать 3 запроса из [§4 Этап 3 плана](../../plans/graphify-pilot.md#этап-3--реальные-задачи-23-часа) на узком графе.

**ВАЖНО:** команды `path`/`explain`/`query` ищут `graph.json` в **текущей директории** (точнее в `./graphify-out/graph.json`). Запускать **из директории с графом** или передавать `--graph <path>`:

```bash
# Перейти в директорию с графом:
cd multiprocess_framework/modules/command_module

# Объяснить узел и его соседей:
graphify explain "CommandManager"
# Реальный вывод (2026-05-19):
# Node: CommandManager
#   ID:        core_command_manager_commandmanager
#   Source:    core/command_manager.py L20
#   Community: 0
#   Degree:    17
# Connections (17):
#   --> .register_command() [method] [EXTRACTED]
#   --> BaseManager [inherits] [EXTRACTED]
#   ...

# Путь между двумя символами в одном модуле:
graphify path "CommandManager" "BaseCommandManager"
# Реальный вывод: 4-hop путь через __init__.py

# BFS-запрос по графу:
graphify query "what depends on CommandManager"
```

**Cross-module queries требуют расширения графа.** Команды `path`/`query` работают **только внутри одного `graph.json`**. Чтобы спросить «что в `router_module` зависит от `CommandManager` из `command_module`» — нужно либо:

1. Проиндексировать **сразу оба модуля** через `graphify update multiprocess_framework/modules/` (общий корень).
2. Или после индексации каждого по отдельности — слить через `graphify merge-graphs command_module/graphify-out/graph.json router_module/graphify-out/graph.json --out shared-graphify-out/graph.json`, и работать из `shared-graphify-out/`.

Для квик-трая проще вариант 1.

### 7.3. Просмотр отчёта

```bash
# Из директории с графом:
open graphify-out/GRAPH_REPORT.md
# или:
less graphify-out/GRAPH_REPORT.md

# HTML-визуализация (для одного модуля 100-150 КБ, ок):
open graphify-out/graph.html
```

В отчёте смотреть: **God Nodes** (для `command_module` ожидаемо: `CommandManager`, `BaseCommandManager`, `CommandAdapter`), **Surprising Connections** (для одного модуля обычно `None detected`, ценнее на полном корпусе), **Suggested Questions** с обоснованием через betweenness centrality и cohesion score, **Knowledge Gaps** (изолированные узлы — потенциальные пробелы документации).

**Реальный пример (2026-05-19, `command_module`):**
- Top-3 god-nodes: `CommandManager` (17 edges) > `command_module` (11) > `BaseCommandManager` (8). Соответствует архитектурному пониманию.
- 23 isolated nodes — заголовки секций из STATUS.md/DECISIONS.md без явных edges в код. Не баг, а отражение слабой связи рефлексивных документов со структурой кода.
- 16 communities, из них 9 тонких (<3 узлов) — нормально для одного модуля.

### 7.4. Решение

Зафиксировать в [`logs/graphify-pilot.md`](../../plans/graphify-pilot.md#10-следующий-шаг) (создать, если ещё нет):

- Время индексации одного модуля.
- Качество ответов R1/R2/R3 (1–5).
- Что нашёл, чего не нашёл бы `grep + Read`.

**Если qualitatively зашло** — переходить к [§4 Этап 1 плана](../../plans/graphify-pilot.md#этап-1--первичная-индексация-1-час) (индексация всего корпуса).
**Если не зашло** — переходить к §11 (удаление).

## 8. Полная индексация проекта

Делать **только после успешного quick-try**.

```bash
# Из корня проекта. Корпус ~854 файла .py, время ожидаемо 1-5 мин на M-серии Mac.
# update индексирует ТОЛЬКО изменённые файлы — для первого запуска получим
# полный проход AST.
cd /Users/twokrai/Project_code/Inspector_bottles
graphify update .
```

**Артефакты появятся в `./graphify-out/`** (в корне проекта, не во вложенных папках).

**Если граф >5000 узлов и HTML тормозит браузер:** перегенерировать без визуализации:

```bash
graphify cluster-only . --no-viz
# Применяется к существующему graph.json — перекластеризует и НЕ генерирует HTML
```

**Полезные флаги команды `cluster-only`:**

- `--no-viz` — пропустить HTML.
- `--resolution 1.5` — более гранулярные communities (дефолт ~1.0).
- `--exclude-hubs 99` — подавить узлы-утилиты из god-nodes ранжирования (для проектов с большим количеством хелперов).

**Содержимое `graphify-out/` после полной индексации:**

```bash
ls -lah graphify-out/
# graph.json          — основные данные (для 854 .py ожидаемо ~3-8 МБ)
# graph.html          — интерактив (если не cluster-only --no-viz)
# GRAPH_REPORT.md     — отчёт (god nodes, communities, suggested questions)
# cache/              — кэш AST между запусками
# .graphify_root      — маркер корня графа
# .graphify_labels.json — кастомные метки узлов
```

## 9. Повседневная работа

### 9.1. Инкрементальное обновление

После правок:

```bash
# Из корня проекта (где graphify-out/):
graphify update .
```

Для **кода** — секунды, без API. Используется `graph.json` + AST-кэш в `graphify-out/cache/`.

### 9.2. Полная пересборка

После рефакторинга с переименованиями или удалениями файлов:

```bash
# update с --force — обходит безопасность «не уменьшать граф»:
graphify update . --force

# или через env var:
GRAPHIFY_FORCE=1 graphify update .
```

`--force` чистит ghost-узлы от удалённых файлов. Делать **только** если уверен, что граф должен ужаться (а то можно затереть нормальный граф плохим запуском).

### 9.3. Типичные запросы

**ВАЖНО:** все запросы (`path`/`explain`/`query`) читают `./graphify-out/graph.json` относительно CWD. Запускать **из директории с графом** или передавать `--graph <path>`.

```bash
# Кратчайший путь между символами/файлами:
graphify path "ChannelRoutingModule" "RouterManager"
graphify path "CommandManager" "BaseCommandManager"
# С явным графом:
graphify path "A" "B" --graph /Users/twokrai/Project_code/Inspector_bottles/graphify-out/graph.json

# Объяснение узла и его 17 соседей с типизированными edges:
graphify explain "CommandManager"
graphify explain "RouterAdapter"

# BFS-traversal с natural language вопросом:
graphify query "what depends on CommandManager"
graphify query "shortest dependency chain from Plugins to ProcessManagerProcess"
graphify query "..." --dfs --budget 1500   # DFS, лимит токенов вывода

# Перекластеризация существующего графа без переиндексации:
graphify cluster-only . --resolution 1.5
graphify cluster-only . --exclude-hubs 99
```

### 9.4. Авто-rebuild на commit (опционально, **не на старте**)

Если пилот пройдёт go-критерии:

```bash
graphify hook install
# Установит post-commit и post-checkout git hooks.
# AST-only, без API-вызовов, секунды на обычный commit.
```

Удаление: `graphify hook uninstall`.

## 10. MCP-сервер — отложено

Graphify может работать как MCP-сервер (флаг `--mcp` или `python -m graphify.serve`). У тебя уже работают **три MCP**: `qex`, `qex_inspector`, `sentrux`, `context7`. Добавлять четвёртый структурный MCP **на пилоте не нужно** — это создаст в промптах агентов конфликт «какой звать первым».

К вопросу о MCP вернуться **только если** [§5 плана](../../plans/graphify-pilot.md#5-интеграция-в-dev-pipeline-только-если-go) покажет, что dev-агент зовёт `graphify` через `Bash` чаще раза в день. Тогда — регистрировать как **локальный** MCP через project-scoped `.mcp.json` (НЕ глобально):

```bash
# (не делать сейчас)
uv tool install "graphifyy[mcp]"
# затем добавить в .mcp.json проекта
```

## 11. Удаление, если не зашло

```bash
# Снести инструмент с PATH
uv tool uninstall graphifyy

# Удалить артефакты пилота
rm -rf graphify-out/
rm -f .graphify.toml .graphifyignore

# Если был зарегистрирован skill (НЕ должен быть, но на всякий случай):
graphify uninstall --purge   # уже без uv-tool, можно пропустить
```

Обновить статью [`graphify-mcp.md` в KnowledgeOS](file:///Users/twokrai/Project_code/obsidian/knowledge/wiki/tools/graphify-mcp.md) пометкой «не оправдалось на Inspector_bottles, корпус ~854 .py, кейс R1/R2/R3 покрывается qex+sentrux+pydeps».

## 12. Troubleshooting

### 12.1. macOS Apple Silicon

Tree-sitter пакеты ставятся как arm64 wheels с PyPI — компиляции не должно быть. Если есть — нужны Xcode Command Line Tools: `xcode-select --install`.

### 12.2. `graphify: command not found` после установки

```bash
# 1. uv добавляет в PATH через ~/.local/bin или $UV_TOOL_BIN_DIR
echo $PATH | tr ':' '\n' | grep -E "\.local/bin|uv"

# 2. Если нет — обновить PATH:
uv tool update-shell

# 3. Перезапустить терминал. Или:
exec $SHELL
```

### 12.3. Граф меньше, чем был

```
Graph has fewer nodes than expected
```

После рефакторинга/удалений Graphify по умолчанию **отказывается** уменьшать граф (безопасность от случайной потери). Лечится:

```bash
graphify extract . --force
# или
GRAPHIFY_FORCE=1 graphify .
```

### 12.4. HTML тормозит браузер

```bash
graphify . --no-viz
# далее работать только через query/path/explain через CLI
```

### 12.5. Дубликаты узлов (ghost duplicates)

Возникают, когда AST и semantic extraction разошлись в ID. Лечится полной пересборкой:

```bash
graphify extract . --force
```

### 12.6. Конфликт версий skill

```
Skill version mismatch warning
```

```bash
uv tool upgrade graphifyy
# graphify install — НЕ выполнять, мы skill не регистрировали
```

### 12.7. Leiden недоступен (Python 3.13+)

У нас Python 3.12, проблемы быть не должно. Если будет — упасть на дефолтный Louvain через флаг `--cluster-algo louvain` (если поддерживается) или установить без leiden extra.

## 13. Сводка команд (cheatsheet)

```bash
# === Установка ===
uv tool install graphifyy
graphify --version

# === Quick-try на одном модуле (без API, секунды) ===
graphify update multiprocess_framework/modules/command_module
open multiprocess_framework/modules/command_module/graphify-out/GRAPH_REPORT.md

# === Полный корпус (только после успешного quick-try) ===
cd /Users/twokrai/Project_code/Inspector_bottles
graphify update .

# === HTML тормозит → перегенерация без визуализации ===
graphify cluster-only . --no-viz

# === Инкремент после правок ===
graphify update .

# === Полная пересборка после рефакторинга с переименованиями ===
graphify update . --force

# === Запросы (из директории с graph.json) ===
graphify path "A" "B"
graphify explain "X"
graphify query "..."

# === Слияние графов нескольких модулей ===
graphify merge-graphs mod_a/graphify-out/graph.json mod_b/graphify-out/graph.json \
  --out shared-graphify-out/graph.json

# === Удаление ===
uv tool uninstall graphifyy
rm -rf graphify-out/ multiprocess_framework/**/graphify-out/
```

## 14. Связи

- План пилота: [`plans/graphify-pilot.md`](../../plans/graphify-pilot.md) — формальные go/no-go критерии.
- Статья в KnowledgeOS: `~/Project_code/obsidian/knowledge/wiki/tools/graphify-mcp.md` — общий концепт-обзор.
- qex (семантический поиск): [`.claude/mcp/qex/README.md`](../../.claude/mcp/qex/README.md)
- sentrux (архитектурные правила): [`.claude/mcp/sentrux/README.md`](../../.claude/mcp/sentrux/README.md)
- pydeps (граф импортов): [`Makefile`](../../Makefile) → `make diagrams`
