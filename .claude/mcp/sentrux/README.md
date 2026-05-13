# sentrux — архитектурный health-gate

**sentrux** ([github.com/sentrux/sentrux](https://github.com/sentrux/sentrux)) — структурный анализатор кодовой базы. Один Rust-бинарь, без рантайм-зависимостей. Считает граф импортов, метрики связности, циклы — и сводит всё в один **quality_signal** (0–10000), который удобно использовать как gate перед коммитом или мерджем.

В этом проекте sentrux подключён как **MCP-сервер** (Claude Code умеет его звать) + 8 проектных slash-команд `/sentrux-*`.

---

## Что он даёт

| Боль | Как помогает sentrux |
|------|----------------------|
| «У нас всё запутано, но непонятно где именно» | Считает 5 метрик (modularity, acyclicity, depth, equality, redundancy), показывает **bottleneck** — главную причину просадки |
| «Где циклы между модулями?» | `dsm` строит Dependency Structure Matrix и подсвечивает циклы |
| «Рефакторинг не сделал хуже?» | `session_start` фиксирует baseline → правки → `session_end` показывает дельту качества |
| «Какие модули без тестов?» | `test_gaps` находит непокрытые узлы графа — приоритезируя те, у кого много зависимостей |
| «`process_module` не должен импортировать `frontend_module` — как заставить CI это ловить?» | `.sentrux/rules.toml` + `sentrux check` (exit 0/1, CI-friendly) |
| «Куда мы движемся по качеству — вверх или вниз?» | `evolution` показывает тренды по времени |

**sentrux ортогонален qex:**

- **qex** отвечает на «*где* используется X» (семантический поиск).
- **sentrux** отвечает на «*насколько здорова* архитектура».

Они **не дублируют** друг друга. Не используй sentrux для поиска по коду, не используй qex для оценки связности.

---

## Установка

### macOS

```bash
brew install sentrux/tap/sentrux
```

Grammars скачаются при первом запуске автоматически.

### Linux

```bash
curl -fsSL https://raw.githubusercontent.com/sentrux/sentrux/main/install.sh | sh
```

### Windows

**Вариант 1 — curl (рекомендуется, если есть Rust toolchain):**

```powershell
# Скачать бинарь в ~/.cargo/bin/ (уже в PATH если Rust установлен)
curl -L -o "%USERPROFILE%\.cargo\bin\sentrux.exe" ^
  https://github.com/sentrux/sentrux/releases/latest/download/sentrux-windows-x86_64.exe

# Проверить
sentrux --version
```

Grammars (51 языковой парсер) скачаются при первом запуске автоматически (~30 MB).

**Вариант 2 — ручная установка:**

1. Скачать `sentrux-windows-x86_64.exe` из [latest release](https://github.com/sentrux/sentrux/releases/latest)
2. Переименовать в `sentrux.exe`
3. Положить в любую директорию из PATH (например `%USERPROFILE%\.cargo\bin\` или `%USERPROFILE%\bin\`)

**Вариант 3 — bootstrap (автоматическая проверка):**

```bash
python .claude/mcp/bootstrap.py
```

Bootstrap проверит наличие sentrux и подскажет команду установки для текущей ОС.

### Проверка установки

```bash
sentrux --version          # должно показать "sentrux X.Y.Z"
sentrux check              # должно показать "Quality: NNNN" и список правил
```

### MCP-подключение

MCP-биндинг прописан в `.mcp.json` (бинарь запускается через `sentrux mcp`). После установки перезапусти Claude Code и проверь: `/mcp` → sentrux должен быть зелёным.

---

## Метрики и quality_signal

`quality_signal` — **геометрическое среднее** пяти под-метрик, каждая нормирована в 0–10000.

| Метрика | Что меряет | Низкий score = |
|---------|-----------|----------------|
| **modularity** | Насколько модули внутренне связаны и слабо связаны между собой | Размытые границы, утечка деталей |
| **acyclicity** | Отсутствие циклов в графе импортов | Есть циклы → score падает в пол |
| **depth** | Глубина архитектурных слоёв | Всё в одной плоскости / слишком вложено |
| **equality** | Равномерность распределения сложности по модулям | God-module / десятки крошечных |
| **redundancy** | Дубликаты / повторяющийся код | Много копи-пасты |

Шкала `quality_signal`:

| Диапазон | Интерпретация |
|----------|---------------|
| 0–3000 | Архитектура запутана, рефакторинг неизбежен |
| 3000–6000 | Средне. Видны bottleneck'и, точечные улучшения дадут эффект |
| 6000–8000 | Хорошо. Поддерживаемо, регулярная гигиена |
| 8000–10000 | Отлично. Сохранять текущий уровень |

**Главное правило:** не смотри на абсолютное число — смотри на **дельту** до/после изменений и на **bottleneck**.

---

## Slash-команды (`.claude/commands/sentrux-*`)

### Снимки и анализ

| Команда | Что делает | Когда звать |
|---------|------------|-------------|
| `/sentrux-health` | scan + health, общий снимок: quality_signal + bottleneck + 5 метрик | В начале сессии, чтобы понять «откуда стартуем» |
| `/sentrux-dsm` | Dependency Structure Matrix: связи между модулями, циклы | Когда bottleneck = `acyclicity` или нужно понять «кто кого тянет» |
| `/sentrux-gaps` | Список модулей без тестов (с приоритетом по связности) | Перед `/ship`, перед PR |
| `/sentrux-evolution` | Тренды метрик во времени | Ретроспектива после крупного рефакторинга |

### Workflow рефакторинга

| Команда | Что делает | Когда звать |
|---------|------------|-------------|
| `/sentrux-baseline` | Фиксирует quality_signal как точку отсчёта (`session_start`) | **Перед** началом крупного рефакторинга |
| `/sentrux-diff` | Сравнивает текущее состояние с baseline (`session_end`), показывает дельту | **После** правок, перед коммитом |

### Правила и CI

| Команда | Что делает | Когда звать |
|---------|------------|-------------|
| `/sentrux-rules` | Проверка `.sentrux/rules.toml` через MCP, интерактивный разбор нарушений | После изменения границ слоёв / новых импортов |
| `/sentrux-check` | CLI `sentrux check` (exit 0/1, для pre-commit и CI) | В скриптах, в pre-commit, в CI |

---

## Типичные сценарии

### 1. Перед рефакторингом

```
/sentrux-baseline       # фиксируем точку отсчёта
... делаешь правки ...
/sentrux-diff           # видишь signal_before → signal_after
```

Если `signal_after < signal_before` — что-то поломал. Запусти `/sentrux-dsm` чтобы найти, где появились новые связи или циклы.

### 2. Поиск циклов

```
/sentrux-health         # bottleneck = acyclicity, score 2500/10000
/sentrux-dsm            # видим какие модули замкнулись
```

Кандидаты на разрыв цикла:

- вынести общий код в нижний слой;
- инвертировать зависимость через интерфейс / событие;
- разбить «толстый» модуль на два.

### 3. Перед `/ship` (PR)

```
/sentrux-gaps           # что не покрыто тестами — закрываем критичное
/sentrux-check          # правила архитектуры не нарушены
/sentrux-diff           # качество не упало относительно baseline
```

### 4. Настройка инвариантов

Создать `.sentrux/rules.toml` в корне проекта (минимальный шаблон — в `/sentrux-rules`). Пример для этого проекта:

```toml
[constraints]
max_cycles = 0
no_god_files = true

[[layers]]
name = "framework"
paths = ["multiprocess_framework/*"]
order = 0

[[layers]]
name = "prototype"
paths = ["multiprocess_prototype/*"]
order = 1

[[boundaries]]
from = "multiprocess_framework/modules/process_module/*"
to = "multiprocess_framework/modules/frontend_module/*"
reason = "process не зависит от frontend (см. ROUTING_GLOSSARY.md)"
```

Дальше:

```
/sentrux-rules          # проверка через MCP — интерактивно
/sentrux-check          # та же проверка через CLI — для CI
```

---

## MCP-инструменты (девять)

Slash-команды выше — обёртки над этими MCP-tool'ами. Их можно звать и напрямую (если нужна нестандартная комбинация):

| Tool | Назначение |
|------|-----------|
| `mcp__sentrux__scan` | Полный пересчёт метрик (обязателен перед остальными в новой сессии) |
| `mcp__sentrux__rescan` | Быстрое обновление после правок |
| `mcp__sentrux__health` | quality_signal + bottleneck + 5 метрик |
| `mcp__sentrux__dsm` | Dependency Structure Matrix |
| `mcp__sentrux__test_gaps` | Модули без тестов |
| `mcp__sentrux__check_rules` | Валидация `.sentrux/rules.toml` |
| `mcp__sentrux__session_start` | Сохранить baseline |
| `mcp__sentrux__session_end` | Сравнить с baseline (pass/fail + дельта) |
| `mcp__sentrux__evolution` | Историческая динамика |

---

## CLI (без MCP)

Полезно для CI / pre-commit / скриптов. Работает одинаково на macOS, Linux, Windows:

```bash
sentrux                        # GUI с live-treemap (если есть дисплей)
sentrux check                  # валидация rules.toml, exit 0/1
sentrux gate --save            # сохранить baseline
sentrux gate                   # сравнить с baseline (CI-режим)
sentrux mcp                    # запустить MCP-сервер (это и делает .mcp.json)
sentrux plugin list            # языковые плагины
```

> **Примечание:** в v0.5.7+ путь к проекту определяется автоматически (текущая директория). Аргумент `.` не нужен.

---

## Диагностика

**`/mcp` показывает sentrux как failed**

```bash
# macOS / Linux
which sentrux                  # бинарь должен быть в PATH
sentrux mcp --help             # должно быть "Start the MCP server"

# Windows (Git Bash)
where sentrux                  # или: which sentrux
sentrux mcp --help
```

Если бинарь есть, но MCP всё равно падает — перезапусти Claude Code:
- VS Code: `Ctrl+Shift+P` (Windows) / `Cmd+Shift+P` (macOS) → `Developer: Reload Window`
- CLI: перезапустить терминал

**`scan` слишком долгий**

Большой проект → проверь `.gitignore` и `.ignore`. sentrux уважает их (как ripgrep). Уберите из индексации архивы, бинарники, генерёнку.

**`session_end` говорит "no baseline"**

Сначала `/sentrux-baseline`, потом правки, потом `/sentrux-diff`. Baseline хранится в памяти MCP-сервера — пережить рестарт Claude Code не сможет.

**Метрики не меняются после правок**

`mcp__sentrux__rescan` или просто `/sentrux-health` (он зовёт scan заново).

---

## Источники

- Репозиторий: <https://github.com/sentrux/sentrux>
- Установка/релизы: <https://github.com/sentrux/sentrux/releases>
- Pro-версия (продвинутые root-cause диагностики): <https://github.com/sentrux/sentrux> → Upgrade

Полный список slash-команд проекта — в корневом [`CLAUDE.md`](../../../CLAUDE.md), раздел «Проектные команды».
